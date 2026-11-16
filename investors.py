"""수집 대상 투자자 목록

SEC EDGAR 13F 를 기준으로 수집하므로 투자자마다 CIK(SEC 등록 번호)가 필요하다.
CIK 는 https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany 에서 회사명으로 찾을 수 있다.

- code: DB 와 API 에 저장되는 투자자 코드. 기존 Dataroma 코드와 같게 유지해야 이전 데이터와 이어진다.
- name: DB 에 저장되는 투자자 이름
- cik: SEC CIK
- max_holdings: 상세 테이블에 저장할 최대 종목 수(비중 순). None 이면 전체 저장.
  보유 종목 수, 포트폴리오 총액, 비중은 항상 전체 보유 종목 기준으로 계산한다.
"""

INVESTORS = [
    {"code": "BRK", "name": "Warren Buffett - Berkshire Hathaway", "cik": 1067983, "max_holdings": None},
    {"code": "DAC", "name": "Dodge & Cox Funds", "cik": 200217, "max_holdings": None},
    {"code": "HA", "name": "Bill Nygren - Oakmark Funds", "cik": 813917, "max_holdings": None},
    {"code": "FE", "name": "First Eagle Investment Management", "cik": 1325447, "max_holdings": None},
    {"code": "tci", "name": "Chris Hohn - TCI Fund Management", "cik": 1647251, "max_holdings": None},
    {"code": "vg", "name": "Viking Global Investors", "cik": 1103804, "max_holdings": None},
    {"code": "GFT", "name": "Bill & Melinda Gates Foundation Trust", "cik": 1166559, "max_holdings": None},
    {"code": "PIM", "name": "Richard Pzena - Pzena Investment Management", "cik": 1027796, "max_holdings": None},
    {"code": "TGM", "name": "Chase Coleman - Tiger Global Management", "cik": 1167483, "max_holdings": None},
    {"code": "DAV", "name": "Christopher Davis - Davis Advisors", "cik": 1036325, "max_holdings": None},
    # 보유 종목이 3천 개가 넘어 비중 상위 100개만 상세 저장한다
    {"code": "RENTEC", "name": "Renaissance Technologies", "cik": 1037389, "max_holdings": 100},
]
