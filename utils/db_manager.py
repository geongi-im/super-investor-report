import pymysql
import os
from dotenv import load_dotenv
from utils.logger_util import LoggerUtil

# 로거 설정
logger = LoggerUtil().get_logger()

# .env 파일에서 환경 변수 로드
load_dotenv()

DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")
DB_PORT = int(os.getenv("DB_PORT", 3306))

def get_db_connection():
    """DB 연결을 생성하고 반환합니다."""
    try:
        conn = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            db=DB_NAME,
            port=DB_PORT,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        logger.info("DB에 성공적으로 연결되었습니다.")
        return conn
    except pymysql.MySQLError as e:
        logger.error(f"DB 연결 오류: {e}")
        return None

CREATE_INVESTOR_PORTFOLIO_TABLE = """
CREATE TABLE IF NOT EXISTS investor_portfolio (
    idx INT AUTO_INCREMENT PRIMARY KEY COMMENT '포트폴리오 메타 고유 ID (PK)',
    investor_code VARCHAR(50) NOT NULL COMMENT '투자자 코드 (예: AKO)',
    investor_name VARCHAR(255) NOT NULL COMMENT '투자자 이름 (예: AKO Capital)',
    portfolio_date DATE NOT NULL COMMENT '포트폴리오 기준 날짜 (예: 2025-03-31)',
    portfolio_period VARCHAR(20) COMMENT '포트폴리오 기준 분기 (예: Q1 2025)',
    portfolio_value BIGINT COMMENT '총 포트폴리오 가치 (달러 단위)',
    number_of_stocks INT COMMENT '보유 종목 수',
    record_created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '레코드 생성 시각',
    UNIQUE KEY uk_investor_date (investor_code, portfolio_date)
) COMMENT = '투자자별 포트폴리오 메타 정보 테이블';
"""

CREATE_INVESTOR_PORTFOLIO_DETAIL_TABLE = """
CREATE TABLE IF NOT EXISTS investor_portfolio_detail (
    idx INT AUTO_INCREMENT PRIMARY KEY COMMENT '포트폴리오 상세 항목 고유 ID (PK)',
    p_idx INT NOT NULL COMMENT '참조되는 포트폴리오 메타 ID (FK)',
    ticker VARCHAR(50) NOT NULL COMMENT '종목 코드 (예: AAPL, MSFT)',
    stk_name VARCHAR(255) NOT NULL COMMENT '회사명 (예: Apple Inc.)',
    portfolio_rate DECIMAL(5,2) COMMENT '해당 종목이 차지하는 포트폴리오 내 비중 (%)',
    recent_activity_type VARCHAR(20) COMMENT '최근 활동 유형 (예: buy, reduce, add, New, Sold Out)',
    recent_activity_value DECIMAL(10,2) COMMENT '최근 활동 값(%) (예: 15, 2.86)',
    shares BIGINT COMMENT '보유 주식 수량',
    reported_price DECIMAL(16,4) COMMENT '보고된 평균 매입 단가',
    reported_value_amount BIGINT COMMENT '보고된 종목 가치 (shares × price)',
    current_price DECIMAL(16,4) COMMENT '현재 주가',
    reported_price_rate DECIMAL(8,4) COMMENT '보고가 대비 현재 변화율 (%)',
    low_52_week DECIMAL(16,4) COMMENT '52주 최저가',
    high_52_week DECIMAL(16,4) COMMENT '52주 최고가',
    record_created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '레코드 생성 시각',
    CONSTRAINT fk_detail_to_meta FOREIGN KEY (p_idx)
        REFERENCES investor_portfolio (idx)
        ON DELETE CASCADE ON UPDATE CASCADE
) COMMENT = '포트폴리오 상세 종목 정보 테이블';
"""

def create_tables_if_not_exists(conn):
    """필요한 테이블이 없으면 생성합니다."""
    with conn.cursor() as cursor:
        try:
            cursor.execute(CREATE_INVESTOR_PORTFOLIO_TABLE)
            logger.info("'investor_portfolio' 테이블이 준비되었습니다.")
            cursor.execute(CREATE_INVESTOR_PORTFOLIO_DETAIL_TABLE)
            logger.info("'investor_portfolio_detail' 테이블이 준비되었습니다.")
            conn.commit()
        except pymysql.MySQLError as e:
            logger.error(f"테이블 생성 오류: {e}")
            conn.rollback()
            raise

def check_portfolio_exists(conn, investor_code, portfolio_date):
    """주어진 investor_code와 portfolio_date 데이터가 이미 investor_portfolio 테이블에 존재하는지 확인합니다."""
    with conn.cursor() as cursor:
        sql = "SELECT idx FROM investor_portfolio WHERE investor_code = %s AND portfolio_date = %s"
        cursor.execute(sql, (investor_code, portfolio_date))
        result = cursor.fetchone()
        return result is not None

def insert_investor_portfolio(conn, investor_code, investor_name, portfolio_date, portfolio_period, portfolio_value, number_of_stocks):
    """investor_portfolio 테이블에 데이터를 삽입하고, 생성된 p_idx를 반환합니다."""
    with conn.cursor() as cursor:
        sql = """
        INSERT INTO investor_portfolio 
        (investor_code, investor_name, portfolio_date, portfolio_period, portfolio_value, number_of_stocks)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        try:
            # 타입 변환 및 유효성 검사 추가
            portfolio_value = int(portfolio_value)
            number_of_stocks = int(number_of_stocks)
            cursor.execute(sql, (investor_code, investor_name, portfolio_date, portfolio_period, portfolio_value, number_of_stocks))
            # conn.commit() # 트랜잭션은 main에서 관리
            return cursor.lastrowid
        except ValueError as ve:
            logger.error(f"Data type error for investor_portfolio insert: {ve} (inv_code: {investor_code})")
            raise
        except pymysql.MySQLError as e:
            logger.error(f"investor_portfolio 삽입 오류: {e} (inv_code: {investor_code})")
            raise

def insert_portfolio_details(conn, p_idx, details):
    """investor_portfolio_detail 테이블에 여러 상세 데이터를 삽입합니다."""
    if not details: # 상세 정보가 없으면 아무것도 안함
        logger.info(f"No details to insert for p_idx: {p_idx}")
        return

    with conn.cursor() as cursor:
        sql = """
        INSERT INTO investor_portfolio_detail
        (p_idx, ticker, stk_name, portfolio_rate, recent_activity_type, recent_activity_value, 
        shares, reported_price, reported_value_amount, current_price, reported_price_rate, low_52_week, high_52_week)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        values_to_insert = []
        for detail in details:
            try:
                values_to_insert.append((
                    p_idx,
                    detail.get('ticker'),
                    detail.get('name'), # crawler에서 'name' 키로 회사명 반환 가정
                    detail.get('portfolio_rate'),
                    detail.get('recent_activity_type'),
                    detail.get('recent_activity_value'),
                    detail.get('shares'),
                    detail.get('reported_price'),
                    detail.get('reported_value_amount'),
                    detail.get('current_price'),
                    detail.get('reported_price_rate'),
                    detail.get('low_52_week'),
                    detail.get('high_52_week')
                ))
            except KeyError as ke:
                logger.error(f"Missing key in detail item for p_idx {p_idx}: {ke}. Item: {detail}")
                # 선택: 이 아이템을 건너뛰거나, None으로 채우거나, 오류를 발생시킬 수 있음
                continue # 일단 건너뛰기
        
        if not values_to_insert: # 유효한 데이터가 하나도 없으면
            logger.warning(f"No valid detail items to insert for p_idx: {p_idx} after filtering.")
            return

        try:
            cursor.executemany(sql, values_to_insert)
            # conn.commit() # 트랜잭션은 main에서 관리
            logger.info(f"{len(values_to_insert)}개의 포트폴리오 상세 정보가 성공적으로 준비되었습니다 (p_idx: {p_idx}).")
        except pymysql.MySQLError as e:
            logger.error(f"portfolio_details 삽입 오류 (p_idx: {p_idx}): {e}")
            raise

# 이 파일이 직접 실행될 때 테이블 생성 로직을 실행 (테스트용)
if __name__ == '__main__':
    db_conn = get_db_connection()
    if db_conn:
        try:
            # 모듈 테스트
            print("DB 환경변수:")
            print(f"- DB_HOST: {DB_HOST}")
            print(f"- DB_PORT: {DB_PORT}")
            print(f"- DB_USER: {DB_USER}")
            print(f"- DB_NAME: {DB_NAME}")
        finally:
            db_conn.close()
            print("DB 연결이 종료되었습니다.")
    else:
        print("DB 연결에 실패하여 테이블 생성 및 테스트를 진행할 수 없습니다.") 