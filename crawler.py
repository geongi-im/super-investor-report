"""SEC EDGAR 13F 포트폴리오 수집

투자자 CIK 로 최근 13F 신고서를 받아 Dataroma 크롤러와 같은 형태({"summary", "details"})로 돌려준다.

- 같은 분기에 정정 신고(13F-HR/A)가 있으면 반영한다.
  RESTATEMENT 는 원본을 대체하고, NEW HOLDINGS 는 원본에 종목을 추가한다.
  단 NEW HOLDINGS 로 표시돼 있어도 금액이 원본의 절반 이상이면 전체를 다시 낸 것으로 보고 대체한다.
  (First Eagle 2026 Q2 처럼 전체 정정을 NEW HOLDINGS 로 표시하는 경우가 있다)
- 주식(SH)만 집계하고 옵션(Put/Call)과 채권(PRN)은 뺀다.
- 같은 CUSIP 이 운용 주체별로 여러 줄이면 합친다.
- 최근 활동(buy/add/reduce)은 직전 분기 13F 와 티커별 보유 주식 수를 비교해 계산한다.
  직전 분기 CUSIP 의 티커를 찾지 못하면(재설립으로 CUSIP 이 바뀐 경우 등) 발행사명으로 비교한다.
- 티커는 OpenFIGI, 현재가와 52주 최저/최고가는 yfinance 로 채운다.
"""
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime

import requests
from dotenv import load_dotenv

from utils.logger_util import LoggerUtil

load_dotenv()
logger = LoggerUtil().get_logger()

SEC_DATA_URL = "https://data.sec.gov"
SEC_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data"
FORM_ORIGINAL = "13F-HR"
FORM_AMENDMENT = "13F-HR/A"
# 2023-01-03 이후 접수분부터 value 가 달러 단위다. 그 전에는 천 달러 단위였다.
VALUE_IN_DOLLARS_FROM = "2023-01-03"
# SEC 는 초당 10회까지 허용한다
SEC_REQUEST_INTERVAL = 0.15
MAX_ATTEMPTS = 3
# DB 컬럼 범위: reported_price_rate DECIMAL(8,4), recent_activity_value DECIMAL(10,2)
MAX_PRICE_RATE = 9999.9999
MAX_ACTIVITY_VALUE = 99999999.99
# 발행사명 비교 때 끝에서 떼어 내는 법인 형태 단어
LEGAL_SUFFIXES = {
    "INC", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LIMITED", "PLC", "NEW",
    "HOLDINGS", "HLDGS", "HOLDING", "NV", "SA", "AG", "SE", "LLC", "LP", "THE",
}


class SecClient:
    """SEC EDGAR 요청. SEC 는 User-Agent 에 연락처(이름과 이메일)를 넣도록 요구한다"""

    def __init__(self):
        user_agent = os.getenv("SEC_USER_AGENT")
        if not user_agent:
            logger.warning("SEC_USER_AGENT 가 설정되지 않았습니다. SEC 가 요청을 막을 수 있으니 .env 에 '이름 이메일' 형식으로 설정하세요.")
            user_agent = "super-investor-report"
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
        self._last_request_at = 0.0

    def get(self, url):
        for attempt in range(1, MAX_ATTEMPTS + 1):
            wait = SEC_REQUEST_INTERVAL - (time.time() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            self._last_request_at = time.time()
            try:
                response = self.session.get(url, timeout=30)
            except requests.RequestException as e:
                logger.warning(f"SEC 요청 오류({attempt}/{MAX_ATTEMPTS}) {url}: {e}")
                time.sleep(2 * attempt)
                continue
            if response.status_code == 200:
                return response
            if response.status_code == 429 or response.status_code >= 500:
                logger.warning(f"SEC 응답 {response.status_code}({attempt}/{MAX_ATTEMPTS}) {url}")
                time.sleep(5 * attempt)
                continue
            response.raise_for_status()
        raise RuntimeError(f"SEC 요청 실패: {url}")

    def get_json(self, url):
        return self.get(url).json()


def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


def _child_text(element, name):
    for child in element.iter():
        if _local_name(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _to_int(text):
    try:
        return int(float(text.replace(",", "")))
    except (ValueError, AttributeError):
        return 0


def _period_label(period_date):
    """2026-09-30 -> Q3 2026"""
    dt = datetime.strptime(period_date, "%Y-%m-%d")
    return f"Q{(dt.month - 1) // 3 + 1} {dt.year}"


def _list_13f_filings(sec, cik):
    data = sec.get_json(f"{SEC_DATA_URL}/submissions/CIK{cik:010d}.json")
    recent = data["filings"]["recent"]
    filings = []
    for i, form in enumerate(recent["form"]):
        if form not in (FORM_ORIGINAL, FORM_AMENDMENT):
            continue
        filings.append({
            "form": form,
            "accession": recent["accessionNumber"][i],
            "filing_date": recent["filingDate"][i],
            "period": recent["reportDate"][i],
        })
    return filings


def _filing_base_url(cik, accession):
    return f"{SEC_ARCHIVE_URL}/{cik}/{accession.replace('-', '')}"


def _get_amendment_type(sec, cik, filing):
    root = ET.fromstring(sec.get(f"{_filing_base_url(cik, filing['accession'])}/primary_doc.xml").content)
    return _child_text(root, "amendmentType").upper()


def _get_info_table_rows(sec, cik, filing):
    """신고서의 information table 을 읽어 주식 행 목록을 돌려준다"""
    base_url = _filing_base_url(cik, filing["accession"])
    index = sec.get_json(f"{base_url}/index.json")
    xml_names = [
        item["name"] for item in index["directory"]["item"]
        if item["name"].lower().endswith(".xml") and item["name"].lower() != "primary_doc.xml"
    ]

    root = None
    for name in xml_names:
        candidate = ET.fromstring(sec.get(f"{base_url}/{name}").content)
        if _local_name(candidate.tag) == "informationTable":
            root = candidate
            break
    if root is None:
        logger.warning(f"information table 을 찾지 못했습니다: {base_url}")
        return []

    multiplier = 1 if filing["filing_date"] >= VALUE_IN_DOLLARS_FROM else 1000
    rows = []
    for entry in root:
        if _local_name(entry.tag) != "infoTable":
            continue
        if _child_text(entry, "putCall"):
            continue
        if _child_text(entry, "sshPrnamtType").upper() != "SH":
            continue
        shares = _to_int(_child_text(entry, "sshPrnamt"))
        if shares <= 0:
            continue
        rows.append({
            "cusip": _child_text(entry, "cusip").upper(),
            "name": _child_text(entry, "nameOfIssuer"),
            "value": _to_int(_child_text(entry, "value")) * multiplier,
            "shares": shares,
        })
    return rows


def _get_period_rows(sec, cik, filings, period):
    """한 분기의 원본과 정정 신고를 접수 순서대로 반영한 행 목록"""
    period_filings = sorted(
        (f for f in filings if f["period"] == period),
        key=lambda f: (f["filing_date"], f["accession"]),
    )
    rows = None
    for filing in period_filings:
        filing_rows = _get_info_table_rows(sec, cik, filing)
        if filing["form"] == FORM_ORIGINAL or rows is None:
            rows = filing_rows
            continue

        amendment_type = _get_amendment_type(sec, cik, filing)
        if amendment_type == "RESTATEMENT":
            logger.info(f"정정 신고(RESTATEMENT) 반영: {filing['accession']}")
            rows = filing_rows
        else:
            base_value = sum(r["value"] for r in rows)
            added_value = sum(r["value"] for r in filing_rows)
            if base_value and added_value >= base_value * 0.5:
                logger.info(
                    f"정정 신고({amendment_type or '유형 없음'})의 금액이 원본의 절반 이상이라 전체 정정으로 보고 대체합니다: {filing['accession']}"
                )
                rows = filing_rows
            else:
                logger.info(f"정정 신고({amendment_type or '유형 없음'}) 종목 {len(filing_rows)}건 추가: {filing['accession']}")
                rows = rows + filing_rows
    return rows or []


def _aggregate_by_cusip(rows):
    holdings = {}
    for row in rows:
        holding = holdings.get(row["cusip"])
        if holding is None:
            holdings[row["cusip"]] = dict(row)
        else:
            holding["value"] += row["value"]
            holding["shares"] += row["shares"]
    return holdings


def _shares_by_key(holdings, tickers):
    """보유 주식 수를 티커 기준으로 합친다. 티커를 모르는 CUSIP 은 CUSIP 을 키로 쓴다.
    합병이나 재설립으로 CUSIP 만 바뀐 종목, 한 종목이 여러 CUSIP 으로 보고된 경우도 같은 종목으로 비교하기 위함이다.
    """
    shares = {}
    for cusip, holding in holdings.items():
        key = tickers.get(cusip, cusip)
        shares[key] = shares.get(key, 0) + holding["shares"]
    return shares


def _normalize_name(name):
    """발행사명 비교용. 'EXXON MOBIL CORP' 와 'EXXONMOBIL HOLDINGS CORP' 를 같은 값으로 만든다"""
    words = re.sub(r"[^A-Z0-9 ]", " ", (name or "").upper()).split()
    while words and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    return "".join(words)


def _unmapped_shares_by_name(prev_holdings, holdings, tickers):
    """직전 분기에만 있고 티커도 찾지 못한 CUSIP 의 보유 주식 수를 발행사명 기준으로 합친다.
    재설립/재상장으로 CUSIP 이 바뀐 회사(예: XOM, OKE, CCL)는 옛 CUSIP 이 OpenFIGI 에서 조회되지 않으므로
    발행사명으로 이어 붙이기 위함이다.
    """
    shares = {}
    for cusip, holding in prev_holdings.items():
        if cusip in holdings or cusip in tickers:
            continue
        name = _normalize_name(holding["name"])
        if name:
            shares[name] = shares.get(name, 0) + holding["shares"]
    return shares


def _activity(key, name, current_shares, prev_shares_by_key, prev_unmapped_by_name):
    if prev_shares_by_key is None:
        return None, None
    prev_shares = prev_shares_by_key.get(key) or prev_unmapped_by_name.get(_normalize_name(name))
    if not prev_shares:
        return "buy", None
    shares = current_shares[key]
    if shares > prev_shares:
        return "add", min(round((shares - prev_shares) / prev_shares * 100, 2), MAX_ACTIVITY_VALUE)
    if shares < prev_shares:
        return "reduce", round((prev_shares - shares) / prev_shares * 100, 2)
    return None, None


def crawl_13f_portfolio(investor, sec, ticker_resolver, price_fetcher):
    """투자자의 최근 13F 포트폴리오를 {"summary": {...}, "details": [...]} 로 돌려준다. 실패하면 None"""
    cik = investor["cik"]
    code = investor["code"]
    try:
        filings = _list_13f_filings(sec, cik)
        periods = sorted({f["period"] for f in filings}, reverse=True)
        if not periods:
            logger.warning(f"{code}: 13F 신고서가 없습니다 (CIK {cik}).")
            return None

        latest_period = periods[0]
        holdings = _aggregate_by_cusip(_get_period_rows(sec, cik, filings, latest_period))
        if not holdings:
            logger.warning(f"{code}: {latest_period} 13F 에 주식 보유 내역이 없습니다.")
            return None

        prev_holdings = None
        if len(periods) > 1:
            prev_holdings = _aggregate_by_cusip(_get_period_rows(sec, cik, filings, periods[1]))
        else:
            logger.info(f"{code}: 직전 분기 13F 가 없어 최근 활동을 비워 둡니다.")

        total_value = sum(h["value"] for h in holdings.values())
        summary = {
            "portfolio_period": _period_label(latest_period),
            "portfolio_date": latest_period,
            "number_of_stocks": len(holdings),
            "portfolio_value": total_value,
        }

        ranked = sorted(holdings.values(), key=lambda h: h["value"], reverse=True)
        if investor.get("max_holdings"):
            ranked = ranked[:investor["max_holdings"]]

        # 상세에 넣을 종목 + 직전 분기에만 있는 종목(CUSIP 이 바뀐 경우를 찾기 위해)의 티커를 조회한다
        lookup_cusips = [h["cusip"] for h in ranked]
        if prev_holdings:
            lookup_cusips += [c for c in prev_holdings if c not in holdings]
        tickers = ticker_resolver.resolve(lookup_cusips)
        prices = price_fetcher.get_prices([tickers[h["cusip"]] for h in ranked if h["cusip"] in tickers])

        current_shares = _shares_by_key(holdings, tickers)
        prev_shares = None
        prev_unmapped = {}
        if prev_holdings is not None:
            prev_shares = _shares_by_key(prev_holdings, tickers)
            prev_unmapped = _unmapped_shares_by_name(prev_holdings, holdings, tickers)

        details = []
        for holding in ranked:
            cusip = holding["cusip"]
            ticker = tickers.get(cusip)
            reported_price = round(holding["value"] / holding["shares"], 4)
            price = prices.get(ticker) if ticker else None
            current_price = price["current_price"] if price else None
            reported_price_rate = None
            if current_price is not None and reported_price > 0:
                rate = (current_price - reported_price) / reported_price * 100
                reported_price_rate = round(max(-MAX_PRICE_RATE, min(rate, MAX_PRICE_RATE)), 4)
            activity_type, activity_value = _activity(ticker or cusip, holding["name"], current_shares, prev_shares, prev_unmapped)

            details.append({
                # 티커를 찾지 못하면 CUSIP 을 대신 넣는다 (ticker 컬럼이 NOT NULL)
                "ticker": ticker or cusip,
                "name": holding["name"],
                "portfolio_rate": round(holding["value"] / total_value * 100, 2) if total_value else 0,
                "shares": holding["shares"],
                "reported_price": reported_price,
                "reported_value_amount": holding["value"],
                "current_price": current_price,
                "reported_price_rate": reported_price_rate,
                "low_52_week": price["low_52_week"] if price else None,
                "high_52_week": price["high_52_week"] if price else None,
                "recent_activity_type": activity_type,
                "recent_activity_value": activity_value,
            })

        logger.info(
            f"{code}: {summary['portfolio_period']} 보유 {summary['number_of_stocks']}종목, "
            f"${total_value / 1_000_000_000:.2f}B, 상세 {len(details)}건 "
            f"(티커 없음 {sum(1 for h in ranked if h['cusip'] not in tickers)}건, "
            f"시세 없음 {sum(1 for d in details if d['current_price'] is None)}건)"
        )
        return {"summary": summary, "details": details}

    except Exception as e:
        logger.error(f"{code}: 13F 수집 중 오류 (CIK {cik}): {e}", exc_info=True)
        return None
