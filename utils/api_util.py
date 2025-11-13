import requests
from typing import List, Optional
import os
import io
from utils.logger_util import LoggerUtil
from dotenv import load_dotenv

load_dotenv()
class ApiError(Exception):
    """API 호출 관련 커스텀 예외"""
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"API Error (Status: {status_code}): {message}")

class ApiUtil:
    def __init__(self):
        base_url = os.getenv("BASE_URL")
        if not base_url:
            raise EnvironmentError("환경 변수 'BASE_URL'가 설정되어 있지 않습니다.")

        base_url = base_url.rstrip("/")
        self.api_base_url = f"{base_url}/api"
        self.headers = {
            "Accept": "application/json"
        }
        self.logger = LoggerUtil().get_logger()

    def create_post(self, title: str, portfolio_idx: str, investor_code: str, writer: str):
        """게시글 생성 API 호출"""
        url = f"{self.api_base_url}/board-portfolio"
        
        try:
            self.logger.info(f"게시글 생성 시작 (이미지 없음) - 제목: {title}")
            payload = {
                "title": title,
                "portfolio_idx": portfolio_idx,
                "investor_code": investor_code,
                "writer": writer
            }
            response = requests.post(url, headers=self.headers, json=payload)

            # 응답 확인 및 한글 디코딩
            try:
                response.encoding = 'utf-8'  # 응답 인코딩을 UTF-8로 설정
                response_data = response.json()
                
                # 응답 로깅 (디버깅용)
                self.logger.debug(f"API 응답: {response_data}")
                
                if not response_data.get('success', False):
                    error_msg = f"게시글 생성 실패\n제목: {title}\n응답: {response.text}"
                    self.logger.error(error_msg)
                    raise ApiError(response.status_code, error_msg)

                self.logger.info(f"게시글 생성 성공 - 제목: {title}")
                                
                return response_data
                
            except ValueError as e:
                error_msg = f"JSON 응답 파싱 실패\n제목: {title}\n응답: {response.text}"
                self.logger.error(error_msg)
                raise ApiError(response.status_code, error_msg)

        except requests.RequestException as e:
            error_msg = f"API 요청 중 오류 발생\n제목: {title}\n오류: {str(e)}"
            self.logger.error(error_msg)
            raise ApiError(500, error_msg)

if __name__ == "__main__":
    # API 테스트
    api = ApiUtil()
        
    # 테스트 데이터
    test_data = {
        "title": "API 전송 테스트",
        "portfolio_idx": "1",
        "investor_code": "BRK",
        "writer": "관리자"
    }
    
    try:
        # API 호출 테스트
        result = api.create_post(
            title=test_data["title"],
            portfolio_idx=test_data["portfolio_idx"],
            investor_code=test_data["investor_code"],
            writer=test_data["writer"]
        )
        print("API 호출 결과:", result)
        
    except ApiError as e:
        print(f"API 에러 발생: {e}")
    except Exception as e:
        print(f"예상치 못한 에러 발생: {e}") 