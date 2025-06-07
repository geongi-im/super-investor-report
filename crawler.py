import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime
from fake_useragent import UserAgent
from utils.logger_util import LoggerUtil
import time # 페이지 간 요청 딜레이를 위해 추가 (필요시)
import random # 페이지 간 요청 딜레이를 위해 추가 (필요시)

logger = LoggerUtil().get_logger()

def crawl_top_investors(top_count=5):
    ua = UserAgent()
    url = "https://dataroma.com/m/managers.php"
    headers = {"User-Agent": ua.random}
    logger.info(f"Crawling {url}...")
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", {"id": "grid"})
    if not table:
        logger.error("Error: 투자자 테이블을 찾을 수 없습니다.")
        raise Exception("투자자 테이블을 찾을 수 없습니다.")
    
    tbody = table.find("tbody")
    rows = tbody.find_all("tr") if tbody else table.find_all("tr")
    if tbody:
        logger.info(f"Found {len(rows)} rows in tbody.")
    else:
        logger.info(f"Found {len(rows)} rows in table (no tbody).")
        if rows and rows[0].find_all("th"):
             logger.info("Header row (th elements) found in table, skipping first row.")
             rows = rows[1:]
        elif rows and rows[0].find_all("td") and not rows[0].find("a", href=re.compile(r"/m/holdings\.php\?m=\w+")):
            logger.info("Possible header row (td elements without investor link) found, skipping first row.")
            rows = rows[1:]

    if not rows:
        logger.error("Error: No data rows found in table.")
        return []
            
    investors = []
    for i, row in enumerate(rows):
        cols = row.find_all("td")
        if len(cols) < 3:
            logger.warning(f"Skipping row {i+1} due to insufficient columns: {len(cols)}")
            continue
        
        link_tag = cols[0].find("a")
        if not link_tag or not link_tag.has_attr("href"):
            logger.warning(f"Skipping row {i+1} due to missing link or href in first column. First col content: {cols[0].text.strip()}")
            continue
            
        m_code_match = re.search(r"m=(\w+)", link_tag["href"])
        if not m_code_match:
            logger.warning(f"Skipping row {i+1} due to m_code pattern not found in href: {link_tag['href']}")
            continue
            
        code = m_code_match.group(1)
        name = link_tag.text.strip()
        value_text = cols[1].text.strip().upper().replace("$", "")
        value = 0
        try:
            if "B" in value_text:
                value = float(value_text.replace("B", "").strip()) * 1_000_000_000
            elif "M" in value_text:
                value = float(value_text.replace("M", "").strip()) * 1_000_000
            else:
                value = float(value_text.replace(",", "").strip())
            value = int(value)
        except ValueError:
            logger.error(f"ValueError for row {i+1}, value_text: '{value_text}'. Defaulting value to 0.")
            value = 0
            
        investors.append({"code": code, "name": name, "value": value})
    
    logger.info(f"Total investors extracted before sorting: {len(investors)}")
    if not investors:
        logger.warning("No investors data extracted. Returning empty list.")
        return []
    
    # 가져올 상위 투자자 수 제한
    top_count = max(1, min(top_count, len(investors)))  # 최소 1명, 최대 전체 수
    top_investors = sorted(investors, key=lambda x: x["value"], reverse=True)[:top_count]
    logger.info(f"Top {top_count} investors after sorting: {top_investors}")
    return top_investors

def _parse_portfolio_summary(soup):
    try:
        p2_tag = soup.find("p", id="p2")
        if not p2_tag:
            logger.warning("Summary p#p2 tag not found.")
            return None
        
        spans = p2_tag.find_all('span')
        if len(spans) < 4:
            logger.warning(f"Expected at least 4 spans in p#p2, found {len(spans)}")
            return None

        portfolio_period = spans[0].text.strip()
        portfolio_date_str = spans[1].text.strip()
        number_of_stocks_str = spans[2].text.strip()
        portfolio_value_str = spans[3].text.strip()

        parsed_dt = datetime.strptime(portfolio_date_str, "%d %b %Y")
        portfolio_date = parsed_dt.strftime("%Y-%m-%d")
        number_of_stocks = int(number_of_stocks_str)
        portfolio_value = int(portfolio_value_str.replace("$", "").replace(",", ""))

        return {
            "portfolio_period": portfolio_period,
            "portfolio_date": portfolio_date,
            "number_of_stocks": number_of_stocks,
            "portfolio_value": portfolio_value
        }
    except Exception as e:
        logger.error(f"Error parsing portfolio summary: {e}", exc_info=True)
        return None

def _parse_portfolio_details(soup):
    details = []
    try:
        stock_table = soup.find("table", {"id": "grid"})
        if not stock_table:
            logger.warning("Details table #grid not found.")
            return details
        
        tbody = stock_table.find("tbody")
        if not tbody:
            logger.warning("Details tbody in #grid not found.")
            return details

        stock_rows = tbody.find_all("tr")
        logger.debug(f"Found {len(stock_rows)} stock rows for details on current page.")

        for i, row in enumerate(stock_rows):
            cols = row.find_all("td")
            if len(cols) < 12: 
                logger.warning(f"Skipping stock row {i+1} due to insufficient columns: {len(cols)}")
                continue
            
            try:
                col1_text_content = cols[1].text.strip()
                stock_col_1_link = cols[1].find("a")
                raw_ticker_text = stock_col_1_link.text.strip() if stock_col_1_link else ""
                ticker = raw_ticker_text 
                name = ""

                if " - " in raw_ticker_text:
                    parts = raw_ticker_text.split(" - ", 1)
                    ticker = parts[0].strip()
                    name = parts[1].strip() if len(parts) > 1 else ""
                
                stock_col_1_span = cols[1].find("span")
                if stock_col_1_span:
                    span_name_text = stock_col_1_span.text.strip().lstrip(" -").strip()
                    if span_name_text: name = span_name_text
                
                if not name and ticker and " - " not in raw_ticker_text: 
                    potential_name_from_col_text = col1_text_content.replace(ticker, "").strip().lstrip(" -").strip()
                    if potential_name_from_col_text: name = potential_name_from_col_text
                
                if not name and ticker: name = ticker
                
                if not ticker:
                    logger.warning(f"Skipping row {i+1} as ticker could not be parsed from: {col1_text_content}")
                    continue
                
                if name == ticker and " - " in ticker:
                     parts = ticker.split(" - ", 1)
                     ticker = parts[0].strip()
                     name = parts[1].strip() if len(parts) > 1 else name
                
                if len(ticker) > 50: 
                    logger.warning(f"Parsed ticker for row {i+1} is too long: '{ticker}' (length {len(ticker)}). Original text: {col1_text_content}")
                    ticker = ticker[:50] # 티커 길이 제한

                detail_item = {
                    "ticker": ticker, "name": name,
                    "portfolio_rate": float(cols[2].text.strip().replace("%", "")),
                    "shares": int(cols[4].text.strip().replace(",", "")),
                    "reported_price": float(cols[5].text.strip().replace("$", "").replace(",", "")),
                    "reported_value_amount": int(cols[6].text.strip().replace("$", "").replace(",", "")),
                    "current_price": float(cols[8].text.strip().replace("$", "").replace(",", "")),
                    "reported_price_rate": float(cols[9].text.strip().replace("%", "")),
                    "low_52_week": float(cols[10].text.strip().replace("$", "").replace(",", "")),
                    "high_52_week": float(cols[11].text.strip().replace("$", "").replace(",", "")),
                    "recent_activity_type": None, "recent_activity_value": None
                }
                
                activity_col_text = cols[3].text.strip()
                if activity_col_text and activity_col_text != "-":
                    activity_parts = activity_col_text.split(" ")
                    detail_item["recent_activity_type"] = activity_parts[0].strip().lower()
                    if len(activity_parts) > 1 and "%" in activity_parts[-1]:
                        try:
                            detail_item["recent_activity_value"] = float(activity_parts[-1].replace("%", "").strip())
                        except ValueError:
                            logger.warning(f"Could not parse recent_activity_value from {activity_parts[-1]} for row {i+1}")
                
                details.append(detail_item)
            except Exception as e_row:
                logger.error(f"Error processing stock row {i+1}. Content: {row.text[:100]}. Error: {e_row}", exc_info=True)
                continue
        return details
    except Exception as e_table:
        logger.error(f"Error parsing portfolio details table: {e_table}", exc_info=True)
        return details

def crawl_dataroma_portfolio_page(m_code):
    ua = UserAgent()
    base_url = "https://dataroma.com"
    initial_page_url = f"{base_url}/m/holdings.php?m={m_code}&L=1" 
    headers = {"User-Agent": ua.random}
    
    all_details_list = []
    summary_data = None
    
    logger.info(f"Crawling initial page data for m_code: {m_code} from {initial_page_url}...")
    try:
        resp = requests.get(initial_page_url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        summary_data = _parse_portfolio_summary(soup)
        if summary_data is None:
            logger.error(f"Failed to parse summary for {m_code} on initial page ({initial_page_url}). Aborting.")
            return None

        current_page_details = _parse_portfolio_details(soup)
        if current_page_details:
            all_details_list.extend(current_page_details)
        logger.info(f"Collected {len(current_page_details) if current_page_details else 0} items from initial page {initial_page_url}")

        pages_div = soup.find("div", id="pages")
        if pages_div:
            logger.info(f"Pagination detected for m_code {m_code}.")
            page_links_tags = pages_div.find_all("a", href=True)
            urls_to_crawl_subsequent = set()
            
            for link_tag in page_links_tags:
                href = link_tag['href']
                link_text = link_tag.text.strip()
                
                if link_text.isdigit():
                    page_num_in_link = int(link_text)
                    if page_num_in_link == 1: 
                        continue

                    match = re.search(r"/m/holdings\.php\?m=" + re.escape(m_code) + r"&L=(\d+)", href)
                    if match:
                        actual_page_num_in_href = int(match.group(1))
                        if page_num_in_link == actual_page_num_in_href:
                             urls_to_crawl_subsequent.add(f"{base_url}{href}")
            
            sorted_urls_to_crawl = sorted(list(urls_to_crawl_subsequent))

            for page_url in sorted_urls_to_crawl:
                logger.info(f"Crawling paginated page: {page_url} for m_code {m_code}")
                try:
                    # time.sleep(random.uniform(0.3, 0.8)) # 필요시 주석 해제
                    page_resp = requests.get(page_url, headers=headers, timeout=15)
                    page_resp.raise_for_status()
                    page_soup = BeautifulSoup(page_resp.text, "html.parser")
                    
                    paginated_details = _parse_portfolio_details(page_soup)
                    if paginated_details:
                        all_details_list.extend(paginated_details)
                        logger.info(f"Added {len(paginated_details)} stock items from {page_url}")
                except requests.exceptions.RequestException as e_page_req:
                    logger.error(f"Request failed for paginated page {page_url}: {e_page_req}")
                except Exception as e_page_parse:
                    logger.error(f"Error parsing paginated page {page_url}: {e_page_parse}", exc_info=True)
        else:
            logger.info(f"No pagination detected for m_code {m_code} or first page already contains all items.")

        return {"summary": summary_data, "details": all_details_list}

    except requests.exceptions.RequestException as e_req:
        logger.error(f"Request failed for initial page {initial_page_url}: {e_req}")
        return None
    except Exception as e_general:
        logger.error(f"General error crawling page data for {m_code} on initial page {initial_page_url}: {e_general}", exc_info=True)
        return None
