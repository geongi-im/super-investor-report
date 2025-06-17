import sys
from crawler import crawl_top_investors, crawl_dataroma_portfolio_page
from utils.db_manager import get_db_connection, create_tables_if_not_exists, check_portfolio_exists, insert_investor_portfolio, insert_portfolio_details, update_portfolio_details, calculate_and_update_portfolio_avg_return
from utils.logger_util import LoggerUtil
from utils.api_util import ApiUtil  # API 유틸 추가
from utils.telegram_util import TelegramUtil  # 텔레그램 유틸 추가

def main():
    # LoggerUtil 클래스를 사용하여 로거 초기화
    logger = LoggerUtil().get_logger()

    db_conn = get_db_connection()
    if not db_conn:
        logger.error("DB 연결에 실패하여 프로그램을 종료합니다.")
        return

    try:
        create_tables_if_not_exists(db_conn) 

        top_count = 10 # 상위 N명의 투자자 정보 가져오기
        top_investors = crawl_top_investors(top_count)
        if not top_investors:
            logger.warning("크롤링된 투자자 정보가 없습니다.")
            return

        # API 유틸 초기화
        api_util = ApiUtil()
        # 텔레그램 유틸 초기화
        telegram_util = TelegramUtil()

        logger.info(f"--- 상위 {len(top_investors)}명 투자자 포트폴리오 DB 저장 시작 ---")
        for investor in top_investors:
            investor_code = investor['code']
            investor_name = investor['name']
            
            logger.info(f"처리 중인 투자자: {investor_name} ({investor_code})")

            page_data = crawl_dataroma_portfolio_page(investor_code)

            if not page_data or not page_data.get("summary"):
                logger.warning(f"{investor_name}의 포트폴리오 페이지 정보를 가져오는데 실패했습니다. 다음 투자자로 넘어갑니다.")
                continue
            
            portfolio_summary = page_data["summary"]
            portfolio_details = page_data.get("details", []) # details가 없을 경우 빈 리스트

            existing_p_idx = check_portfolio_exists(db_conn, investor_code, portfolio_summary['portfolio_date'])
            
            p_idx = None
            if existing_p_idx:
                logger.info(f"{investor_name} ({investor_code})의 {portfolio_summary['portfolio_date']} 데이터가 이미 존재합니다. 업데이트를 진행합니다.")
                p_idx = existing_p_idx
                
                # 기존 데이터 업데이트
                if portfolio_details:
                    update_portfolio_details(db_conn, p_idx, portfolio_details)
                    calculate_and_update_portfolio_avg_return(db_conn, p_idx)
            else:
                logger.info(f"{investor_name} ({investor_code})의 {portfolio_summary['portfolio_date']} 데이터를 새로 DB에 저장합니다.")
                
                # 새 데이터 삽입
                try:
                    p_idx = insert_investor_portfolio(
                        db_conn,
                        str.upper(investor_code),
                        investor_name,
                        portfolio_summary['portfolio_date'],
                        portfolio_summary['portfolio_period'],
                        portfolio_summary['portfolio_value'],
                        portfolio_summary['number_of_stocks']
                    )

                    if p_idx and portfolio_details:
                        insert_portfolio_details(db_conn, p_idx, portfolio_details)
                except Exception as e_db:
                    logger.error(f"DB 저장 중 오류 발생 ({investor_name} - {investor_code}): {e_db}")
                    if db_conn:
                        db_conn.rollback()
                    continue
            
            # API 호출 및 텔레그램 알림 (신규 추가 시에만)
            if p_idx and not existing_p_idx:
                try:
                    title = f"{investor_name} 포트폴리오 ({portfolio_summary['portfolio_date']})"
                    api_response = api_util.create_post(
                        title=title,
                        portfolio_idx=str(p_idx),
                        investor_code=investor_code,
                        writer="admin"
                    )
                    logger.info(f"API 전송 완료 - {investor_name} (p_idx: {p_idx})")
                    
                    # API 전송 완료 후 텔레그램으로 메시지 전송
                    telegram_message = f"[알림] 포트폴리오 신규 저장 완료\n\n투자자: {investor_name} ({investor_code})\n날짜: {portfolio_summary['portfolio_date']}\n보유 종목 수: {portfolio_summary['number_of_stocks']}\n포트폴리오 가치: ${portfolio_summary['portfolio_value'] / 1_000_000_000:.2f}B"
                    telegram_util.send_test_message(telegram_message)
                    logger.info(f"텔레그램 알림 전송 완료 - {investor_name}")
                    
                except Exception as e_api:
                    logger.error(f"API 전송 중 오류 발생 ({investor_name} - {investor_code}): {e_api}")
            elif existing_p_idx:
                logger.info(f"기존 데이터 업데이트 완료 - {investor_name} (p_idx: {p_idx}). API 및 텔레그램 알림은 건너뜁니다.")
            
            try:
                db_conn.commit() 
                action_text = "업데이트" if existing_p_idx else "저장"
                logger.info(f"{investor_name} ({investor_code}) 데이터 DB {action_text} 완료 (p_idx: {p_idx}).")
            except Exception as e_commit:
                logger.error(f"DB 커밋 중 오류 발생 ({investor_name} - {investor_code}): {e_commit}")
                if db_conn:
                    db_conn.rollback()

    except Exception as e_main:
        logger.error(f"메인 로직 처리 중 예외 발생: {e_main}", exc_info=True) # exc_info로 트레이스백 로깅
    finally:
        if db_conn:
            db_conn.close()
            logger.info("DB 연결이 종료되었습니다.")

if __name__ == "__main__":
    main()