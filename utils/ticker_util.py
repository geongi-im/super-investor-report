"""CUSIP -> 티커 변환 (OpenFIGI API)

13F 원본에는 티커가 없고 CUSIP 만 있으므로 OpenFIGI 로 변환한다.
변환 결과는 cache/cusip_ticker.json 에 저장해서 다음 실행부터는 API 를 다시 부르지 않는다.
찾지 못한 CUSIP(상장폐지, CUSIP 변경 전 번호 등)은 조회한 날짜를 남겨 30일 동안은 다시 조회하지 않는다.

OPENFIGI_API_KEY 가 없어도 동작하지만 요청 한 번에 10건, 분당 25회로 제한되어 느리다.
키가 있으면 요청 한 번에 100건, 6초당 25회까지 가능하다.
"""
import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

from utils.logger_util import LoggerUtil

load_dotenv()
logger = LoggerUtil().get_logger()

OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
CACHE_FILE = Path(__file__).resolve().parent.parent / "cache" / "cusip_ticker.json"
MAX_ATTEMPTS = 3
MISS_RETRY_DAYS = 30


class TickerResolver:
    def __init__(self):
        self.api_key = os.getenv("OPENFIGI_API_KEY")
        if self.api_key:
            self.batch_size = 100
            self.request_interval = 0.25
        else:
            self.batch_size = 10
            self.request_interval = 2.5
            logger.info("OPENFIGI_API_KEY 가 없어 키 없는 속도 제한(10건/요청, 분당 25회)으로 티커를 조회합니다.")
        cache = self._load_cache()
        # tickers: {cusip: ticker}, misses: {cusip: 마지막으로 못 찾은 날짜(YYYY-MM-DD)}
        self.tickers = cache.get("tickers", {})
        self.misses = cache.get("misses", {})
        self._last_request_at = 0.0

    @staticmethod
    def _load_cache():
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            logger.warning(f"티커 캐시를 읽지 못해 새로 만듭니다: {e}")
            return {}

    def _save_cache(self):
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = CACHE_FILE.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump({"tickers": self.tickers, "misses": self.misses}, f, ensure_ascii=False, indent=0, sort_keys=True)
        os.replace(tmp_file, CACHE_FILE)

    def _needs_lookup(self, cusip):
        if cusip in self.tickers:
            return False
        missed_on = self.misses.get(cusip)
        if missed_on is None:
            return True
        return missed_on < (date.today() - timedelta(days=MISS_RETRY_DAYS)).isoformat()

    @staticmethod
    def _build_job(cusip):
        # 앞자리가 영문인 해외 발행 증권은 CINS 번호라서 ID_CUSIP 으로는 찾지 못한다
        id_type = "ID_CINS" if cusip[:1].isalpha() else "ID_CUSIP"
        return {"idType": id_type, "idValue": cusip, "exchCode": "US"}

    @staticmethod
    def _pick_ticker(data):
        """OpenFIGI 결과 중 티커를 고른다. BRK/B 같은 클래스 표기는 BRK.B 로 바꾼다"""
        for item in data:
            ticker = item.get("ticker")
            if ticker:
                return ticker.replace("/", ".")
        return None

    def _post(self, jobs):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-OPENFIGI-APIKEY"] = self.api_key

        for attempt in range(1, MAX_ATTEMPTS + 1):
            wait = self.request_interval - (time.time() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            self._last_request_at = time.time()
            try:
                response = requests.post(OPENFIGI_URL, json=jobs, headers=headers, timeout=30)
            except requests.RequestException as e:
                logger.warning(f"OpenFIGI 요청 오류({attempt}/{MAX_ATTEMPTS}): {e}")
                time.sleep(5 * attempt)
                continue

            if response.status_code == 200:
                return response.json()
            if response.status_code == 429 or response.status_code >= 500:
                reset = response.headers.get("ratelimit-reset")
                sleep_seconds = int(reset) + 1 if reset and reset.isdigit() else 10 * attempt
                logger.warning(f"OpenFIGI 응답 {response.status_code}({attempt}/{MAX_ATTEMPTS}), {sleep_seconds}초 후 재시도합니다.")
                time.sleep(min(sleep_seconds, 70))
                continue
            logger.error(f"OpenFIGI 요청 실패: status={response.status_code} {response.text[:300]}")
            return None
        return None

    def resolve(self, cusips):
        """CUSIP 목록을 받아 {cusip: ticker} 를 돌려준다. 찾지 못한 CUSIP 은 결과에 없다"""
        unique = list(dict.fromkeys(c for c in cusips if c))
        missing = [c for c in unique if self._needs_lookup(c)]
        if missing:
            logger.info(f"티커 조회: 전체 {len(unique)}건 중 캐시에 없는 {len(missing)}건을 OpenFIGI 로 조회합니다.")
            found = 0
            today = date.today().isoformat()
            for start in range(0, len(missing), self.batch_size):
                chunk = missing[start:start + self.batch_size]
                result = self._post([self._build_job(c) for c in chunk])
                # 요청 자체가 실패한 묶음은 못 찾은 것으로 기록하지 않는다 (다음 실행 때 다시 조회)
                if result is None:
                    continue
                for cusip, item in zip(chunk, result):
                    ticker = self._pick_ticker(item.get("data") or [])
                    if ticker:
                        self.tickers[cusip] = ticker
                        self.misses.pop(cusip, None)
                        found += 1
                    elif "error" not in item:
                        self.misses[cusip] = today
                # 중간에 멈춰도 그때까지 찾은 결과는 남도록 묶음마다 저장한다
                self._save_cache()
            logger.info(f"티커 조회 완료: {found}/{len(missing)}건 찾음")
        return {c: self.tickers[c] for c in unique if c in self.tickers}
