"""시세 조회 (yfinance)

현재가와 52주 최저/최고가를 조회한다. 52주 값은 최근 1년 일봉의 최저가/최고가다.
한 번 실행하는 동안 조회한 티커는 메모리에 저장해서 여러 투자자가 같은 종목을 갖고 있어도 한 번만 받는다.
"""
import logging
import math

import yfinance as yf

from utils.logger_util import LoggerUtil

logger = LoggerUtil().get_logger()

# yfinance 는 없는 티커마다 ERROR 로그를 찍으므로 조용히 시킨다. 못 찾은 개수는 아래에서 따로 남긴다.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

CHUNK_SIZE = 200


def _to_yahoo_symbol(ticker):
    # BRK.B -> BRK-B
    return ticker.replace(".", "-")


def _clean(value):
    if value is None:
        return None
    value = float(value)
    if math.isnan(value):
        return None
    return round(value, 4)


class PriceFetcher:
    def __init__(self):
        self.cache = {}

    def _download(self, tickers):
        symbols = {_to_yahoo_symbol(t): t for t in tickers}
        try:
            df = yf.download(
                list(symbols.keys()),
                period="1y",
                auto_adjust=False,
                group_by="ticker",
                progress=False,
                threads=True,
            )
        except Exception as e:
            logger.error(f"yfinance 시세 조회 오류: {e}")
            return

        available = set(df.columns.get_level_values(0)) if not df.empty else set()
        for symbol, ticker in symbols.items():
            price = None
            if symbol in available:
                rows = df[symbol].dropna(subset=["Close"])
                if not rows.empty:
                    price = {
                        "current_price": _clean(rows["Close"].iloc[-1]),
                        "low_52_week": _clean(rows["Low"].min()),
                        "high_52_week": _clean(rows["High"].max()),
                    }
            self.cache[ticker] = price

    def get_prices(self, tickers):
        """{ticker: {current_price, low_52_week, high_52_week}} 를 돌려준다. 시세가 없는 티커는 결과에 없다"""
        unique = list(dict.fromkeys(t for t in tickers if t))
        missing = [t for t in unique if t not in self.cache]
        for start in range(0, len(missing), CHUNK_SIZE):
            self._download(missing[start:start + CHUNK_SIZE])

        result = {t: self.cache[t] for t in unique if self.cache.get(t)}
        if missing:
            not_found = [t for t in missing if not self.cache.get(t)]
            logger.info(f"시세 조회 완료: {len(missing) - len(not_found)}/{len(missing)}건")
            if not_found:
                logger.info(f"시세를 찾지 못한 티커 {len(not_found)}건: {', '.join(not_found[:20])}{' ...' if len(not_found) > 20 else ''}")
        return result
