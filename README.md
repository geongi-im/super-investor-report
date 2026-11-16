# 슈퍼 투자자 포트폴리오 리포트 (Super Investor Portfolio Report)

주요 투자자들의 포트폴리오 정보를 수집하고 데이터베이스에 저장하여 분석할 수 있는 프로젝트입니다.

## 개요

이 프로젝트는 SEC EDGAR 에 공시된 13F 신고서 원본에서 투자자들의 포트폴리오 데이터를 수집하고, 이를 MySQL 데이터베이스에 저장합니다. 수집된 데이터를 바탕으로 포트폴리오 구성 및 변동 사항을 시각화하여 보고서를 생성할 수 있습니다.

수집 대상 투자자는 `investors.py` 에 투자자 코드, 이름, SEC CIK 로 등록합니다. 13F 를 제출하는 기관이면 CIK 만 추가해서 대상에 넣을 수 있습니다.

## 주요 기능

- SEC EDGAR 13F 신고서 수집 (정정 신고 반영, 옵션/채권 제외, 같은 종목 합산)
- 포트폴리오 상세 정보 수집 (종목, 비중, 변동 사항 등)
  - 티커: OpenFIGI 로 CUSIP 을 변환 (`cache/cusip_ticker.json` 에 캐시)
  - 최근 활동(buy/add/reduce): 직전 분기 13F 와 보유 주식 수 비교
  - 현재가, 52주 최저/최고가: yfinance
- MySQL 데이터베이스에 데이터 저장
- 포트폴리오 시각화 리포트 생성
- 텔레그램 알림 기능
- API 연동 기능
- 로깅 시스템으로 프로그램 실행 추적

## 기술 스택

- **언어**: Python 3.x
- **데이터베이스**: MySQL
- **주요 라이브러리**:
  - `requests`: SEC EDGAR, OpenFIGI API 호출
  - `yfinance`: 현재가 및 52주 최저/최고가 조회
  - `pymysql`: MySQL 데이터베이스 연결
  - `dotenv`: 환경 변수 관리
  - `logging`: 로그 관리
  - `echarts`: 데이터 시각화 (리포트)
  - `python-telegram-bot`: 텔레그램 메시지 발송

## 설치 방법

1. 저장소 클론

```bash
git clone https://github.com/your-username/super-investor-report.git
cd super-investor-report
```

2. 가상환경 생성 및 활성화 (선택사항)

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Mac/Linux
source venv/bin/activate
```

3. 필요한 패키지 설치

```bash
pip install -r requirements.txt
```

4. 환경 변수 설정
   
`.env` 파일을 프로젝트 루트 디렉토리에 생성하고 다음 내용을 추가합니다:

```
DB_HOST=localhost
DB_USER=your_username
DB_PASSWORD=your_password
DB_NAME=investor_portfolio_db
DB_PORT=3306

# 텔레그램 봇 설정 (선택사항)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# BASE URL
BASE_URL=http://example.com

# API 키 설정 (선택사항)
API_KEY=your_api_key

# SEC EDGAR 요청 헤더 (필수 권장, SEC 요구사항: 이름과 연락 이메일)
SEC_USER_AGENT=YourName your_email@example.com

# OpenFIGI API 키 (선택사항, https://www.openfigi.com/api 에서 무료 발급)
OPENFIGI_API_KEY=your_openfigi_api_key
```

OpenFIGI 키가 없어도 동작하지만 티커 조회 속도 제한이 커서, 캐시가 없는 첫 실행은 수 분이 걸립니다. 이후 실행은 캐시를 써서 빨라집니다.

5. 데이터베이스 준비

MySQL에서 `investor_portfolio_db` 데이터베이스를 생성합니다:

```sql
CREATE DATABASE investor_portfolio_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

## 사용 방법

### 데이터 수집 및 저장

```bash
python main.py
```

이 명령어는 `investors.py` 에 등록된 투자자들의 최근 13F 포트폴리오 정보를 수집하고 데이터베이스에 저장합니다.

### 리포트 생성

```bash
python report_generator.py --investor BRK --date 2023-12-31
```

이 명령어는 특정 투자자의 특정 날짜 포트폴리오 데이터를 시각화한 HTML 리포트를 생성합니다.

## 프로젝트 구조

```
super-investor-report/
  main.py                   # 메인 실행 파일
  investors.py              # 수집 대상 투자자 목록 (코드, 이름, SEC CIK)
  crawler.py                # SEC EDGAR 13F 수집 모듈
  report_generator.py       # 리포트 생성 모듈
  report_template.html      # 리포트 템플릿
  requirements.txt          # 의존성 패키지 목록
  .env                      # 환경 변수 파일 (git에서 제외됨)
  cache/                    # CUSIP -> 티커 변환 캐시 (git에서 제외됨)
  logs/                     # 로그 저장 디렉토리
  report/                   # 생성된 리포트 HTML 파일
  utils/
    db_manager.py           # 데이터베이스 관리 모듈
    logger_util.py          # 로깅 유틸리티 모듈
    api_util.py             # API 연동 유틸리티 모듈
    telegram_util.py        # 텔레그램 알림 유틸리티 모듈
    ticker_util.py          # CUSIP -> 티커 변환 (OpenFIGI)
    price_util.py           # 현재가/52주 시세 조회 (yfinance)
```

## 데이터베이스 스키마

### investor_portfolio 테이블

투자자별 포트폴리오 메타 정보를 저장합니다.

| 필드 | 설명 |
|------|------|
| idx | 포트폴리오 메타 고유 ID (PK) |
| investor_code | 투자자 코드 (예: AKO) |
| investor_name | 투자자 이름 (예: AKO Capital) |
| portfolio_date | 포트폴리오 기준 날짜 (예: 2023-03-31) |
| portfolio_period | 포트폴리오 기준 분기 (예: Q1 2023) |
| portfolio_value | 총 포트폴리오 가치 (달러 단위) |
| number_of_stocks | 보유 종목 수 |
| record_created_at | 레코드 생성 시각 |

### investor_portfolio_detail 테이블

포트폴리오의 상세 종목 정보를 저장합니다.

| 필드 | 설명 |
|------|------|
| idx | 포트폴리오 상세 항목 고유 ID (PK) |
| p_idx | 참조되는 포트폴리오 메타 ID (FK) |
| ticker | 종목 코드 (예: AAPL, MSFT) |
| stk_name | 회사명 (예: Apple Inc.) |
| portfolio_rate | 해당 종목이 차지하는 포트폴리오 내 비중 (%) |
| recent_activity_type | 최근 활동 유형 (예: buy, reduce, add) |
| recent_activity_value | 최근 활동 값(%) (예: 15, 2.86) |
| shares | 보유 주식 수량 |
| reported_price | 보고된 평균 매입 단가 |
| reported_value_amount | 보고된 종목 가치 (shares × price) |
| current_price | 현재 주가 |
| reported_price_rate | 보고가 대비 현재 변화율 (%) |
| low_52_week | 52주 최저가 |
| high_52_week | 52주 최고가 |
| record_created_at | 레코드 생성 시각 |

## 리포트 예시

프로젝트에 포함된 `report_template.html` 파일을 사용하여 다음과 같은 포트폴리오 시각화 리포트를 생성할 수 있습니다:

- 포트폴리오 구성 비중 도넛 차트
- 종목별 상세 정보 카드
- 요약 통계 (총 가치, 종목 수, 평균 수익률 등)

## 로깅

프로그램 실행 로그는 `logs` 디렉토리에 날짜별로 저장됩니다. 로그 파일 형식은 `YYYY-MM-DD_log.log`입니다.

## 향후 계획

- 포트폴리오 변동 추적 및 분석 기능 추가
- 다양한 투자자 검색 및 필터링 기능
- 웹 인터페이스 구현
- 투자 성과 분석 및 비교 기능
- 주가 데이터 실시간 업데이트 기능