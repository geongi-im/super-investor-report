import os
from datetime import datetime
from jinja2 import Template
import logging
import json
from utils.db_manager import get_db_connection

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_latest_portfolio_data(db_conn):
    """DB에서 가장 최근의 포트폴리오 데이터를 가져옵니다."""
    try:
        with db_conn.cursor() as cursor:
            # 가장 최근 포트폴리오 메타 정보 조회
            cursor.execute("""
                SELECT idx, investor_code, investor_name, portfolio_date, 
                       portfolio_period, portfolio_value, number_of_stocks
                FROM investor_portfolio
                ORDER BY portfolio_date DESC, record_created_at DESC
                LIMIT 1
            """)
            portfolio_meta = cursor.fetchone()
            
            if not portfolio_meta:
                logger.warning("포트폴리오 메타 데이터가 없습니다.")
                return None
            
            # 해당 포트폴리오의 상세 정보 조회
            cursor.execute("""
                SELECT ticker, stk_name, portfolio_rate, recent_activity_type,
                       recent_activity_value, shares, reported_price,
                       reported_value_amount, current_price, reported_price_rate,
                       low_52_week, high_52_week
                FROM investor_portfolio_detail
                WHERE p_idx = %s
                ORDER BY portfolio_rate DESC
            """, (portfolio_meta['idx'],))
            portfolio_details = cursor.fetchall()
            
            return {
                'meta': portfolio_meta,
                'details': portfolio_details
            }
            
    except Exception as e:
        logger.error(f"포트폴리오 데이터 조회 중 오류 발생: {e}")
        return None

def format_portfolio_data(portfolio_data):
    """DB 데이터를 템플릿에 맞는 형식으로 변환합니다."""
    if not portfolio_data:
        return None
    
    meta = portfolio_data['meta']
    details = portfolio_data['details']
    
    # 메타 데이터 포맷팅
    formatted_meta = {
        'total_value': f"${meta['portfolio_value'] / 1_000_000_000:.1f}B",
        'number_of_stocks': meta['number_of_stocks'],
        'portfolio_date': meta['portfolio_date'].strftime('%Y-%m-%d'),
        'investor_name': meta['investor_name'],
        'investor_code': meta['investor_code']
    }
    
    # 상세 데이터 포맷팅
    formatted_stocks = []
    for detail in details:
        # 수익률 계산 (reported_price_rate 사용)
        change = detail['reported_price_rate']
        change_str = f"+{change:.2f}%" if change >= 0 else f"{change:.2f}%"
        
        # 활동 타입과 값 포맷팅
        activity = ""
        activity_type = detail['recent_activity_type']
        if activity_type and detail['recent_activity_value']:
            activity = f"{activity_type.capitalize()} {detail['recent_activity_value']:.2f}%"
        
        stock = {
            'symbol': detail['ticker'],
            'name': detail['stk_name'].replace('"', ''),
            'percentage': float(detail['portfolio_rate']),
            'value': detail['reported_value_amount'],
            'change': change_str,
            'activity': activity,
            'activityType': activity_type.lower() if activity_type else ''
        }
        formatted_stocks.append(stock)
    
    return {
        'meta': formatted_meta,
        'stocks': formatted_stocks
    }

def generate_report(data):
    """HTML 템플릿에 데이터를 적용하여 리포트를 생성합니다."""
    try:
        # 템플릿 파일 읽기
        template_path = os.path.join(os.path.dirname(__file__), 'report_template.html')
        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()
        
        # JSON 문자열로 변환하면서 HTML 이스케이프 처리
        stocks_json = json.dumps(data["stocks"], ensure_ascii=False)
        
        # 템플릿에 데이터 적용
        template_content = template_content.replace(
            'const stocks = []',
            f'const stocks = {stocks_json}'
        )
        
        template_content = template_content.replace(
            'const investor_name = ""',
            f'const investor_name = "{data["meta"]["investor_name"]}"'
        )

        template_content = template_content.replace(
            'const portfolio_date = ""',
            f'const portfolio_date = "{data["meta"]["portfolio_date"]}"'
        )

        report_html = template_content
        
        # 결과 파일 저장 (report 폴더에 저장)
        report_dir = os.path.join(os.path.dirname(__file__), 'report')
        os.makedirs(report_dir, exist_ok=True)  # 폴더가 없으면 생성
        output_path = os.path.join(report_dir, f'{data["meta"]["investor_code"]}_{data["meta"]["portfolio_date"]}_generated_report.html')
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report_html)
            
        logger.info(f"리포트가 성공적으로 생성되었습니다: {output_path}")
        return output_path
        
    except Exception as e:
        logger.error(f"리포트 생성 중 오류 발생: {e}")
        return None

def main():
    """메인 실행 함수"""
    db_conn = get_db_connection()
    if not db_conn:
        logger.error("DB 연결에 실패하여 프로그램을 종료합니다.")
        return
    
    try:
        # 최신 포트폴리오 데이터 조회
        portfolio_data = get_latest_portfolio_data(db_conn)
        if not portfolio_data:
            logger.error("포트폴리오 데이터를 가져오는데 실패했습니다.")
            return
            
        # 데이터 포맷팅
        formatted_data = format_portfolio_data(portfolio_data)
        if not formatted_data:
            logger.error("데이터 포맷팅에 실패했습니다.")
            return
            
        # 리포트 생성
        report_path = generate_report(formatted_data)
        if report_path:
            logger.info(f"리포트가 성공적으로 생성되었습니다: {report_path}")
        else:
            logger.error("리포트 생성에 실패했습니다.")
            
    except Exception as e:
        logger.error(f"리포트 생성 중 예외 발생: {e}")
    finally:
        if db_conn:
            db_conn.close()
            logger.info("DB 연결이 종료되었습니다.")

if __name__ == "__main__":
    main() 