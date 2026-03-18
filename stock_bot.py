import time
import datetime
import threading
import logging
import logging.handlers
import sys
import os
import signal
import copy
import csv
import requests
import json
import websocket # pip install websocket-client

# 📂 사용자 파일 임포트 (기존 로깅 모듈 유지)
import config
import token_manager
import telegram_notifier
import trade_logger

# ==============================================================================
# 📝 [로그 시스템 설정]
# ==============================================================================
def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    file_handler = logging.handlers.RotatingFileHandler(
        'output.log', maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger

logger = setup_logging()

# original_print = print
# def print(*args, **kwargs):
    # msg = " ".join(map(str, args))
    # logger.info(msg)

# ==============================================================================
# 📝 [시스템 표준 입출력 로거 리다이렉션]
# ==============================================================================
class StreamToLogger:
    def __init__(self, logger, log_level=logging.INFO):
        self.logger = logger
        self.log_level = log_level

    def write(self, buf):
        # 개행 문자를 기준으로 나누어 로그로 기록 (빈 줄 무시)
        for line in buf.rstrip().splitlines():
            if line.strip():
                self.logger.log(self.log_level, line.strip())

    def flush(self):
        pass

# 1. 모든 일반 print 출력과 표준 출력을 INFO 레벨로 가로채기
sys.stdout = StreamToLogger(logger, logging.INFO)

# 2. 모든 파이썬 에러 메시지(Traceback)를 ERROR 레벨로 가로채기
sys.stderr = StreamToLogger(logger, logging.ERROR)

# ==============================================================================
# 🕹️ [모드 설정]
# ==============================================================================
# MODE = "REAL"   # 실전투자
MODE = "MOCK"   # 모의투자

if MODE == "REAL":
    config.TELEGRAM_BOT_TOKEN = config.REAL_TELEGRAM_BOT_TOKEN
    config.TELEGRAM_CHAT_ID = config.REAL_TELEGRAM_CHAT_ID
else:
    config.TELEGRAM_BOT_TOKEN = config.MOCK_TELEGRAM_BOT_TOKEN
    config.TELEGRAM_CHAT_ID = config.MOCK_TELEGRAM_CHAT_ID

# ==============================================================================
# 1. 봇 설정 (BotConfig) - 최초 분석 지침 100% 반영
# ==============================================================================
class BotConfig:
    URL_REAL = "https://openapi.koreainvestment.com:9443"
    URL_MOCK = "https://openapivts.koreainvestment.com:29443"
    
    # 🌐 웹소켓 URL
    WS_URL_REAL = "ws://ops.koreainvestment.com:21000/tryitout/H0STCNT0"
    WS_URL_MOCK = "ws://ops.koreainvestment.com:31000/tryitout/H0STCNT0"

    DELAY_REAL = 0.06
    DELAY_MOCK = 0.60 

    if MODE == "MOCK":
        TR_ID = { "balance": "VTTC8434R", "buy": "VTTC0802U", "sell": "VTTC0801U" }
    else: 
        TR_ID = { "balance": "TTTC8434R", "buy": "TTTC0802U", "sell": "TTTC0801U" }

    MAX_GLOBAL_SLOTS = 6  
    INVEST_RATIO = 0.15   

    EXCLUDE_KEYWORDS = ["스팩", "ETN", "ETF", "리츠", "우B", "우(", "인버스", "레버리지", "선물", "채권", "KODEX", "TIGER", "HANARO", "SOL", "PLUS", "RISE", "KOSEF", "ACE", "히어로즈", "WOORI"]
    MIN_STOCK_PRICE = 5000

    # ⚔️ 1. 진입 (매수) 조건: 초기 수급 포착 (09:00 ~ 09:30)
    VALUEKING_START_HOUR = 9     
    VALUEKING_END_HOUR = 9       
    VALUEKING_END_MINUTE = 30
    VALUE_KING_MIN_VALUE = 1_000_000_000
    VALUE_KING_MAX_VALUE = 30_000_000_000 # 누적 거래대금 300억 이하 공략
    MAX_RATE_LIMIT = 15.0  # 👈 [추가] 너무 높은 고점(+15% 초과) 추격 매수 금지 상한선

    # 🛡️ 2. 청산 (손절/익절) 절대 방어선
    PARTIAL_PROFIT_RATE = 0.025  # +2.5% 도달 시 50% 절반 익절
    PARTIAL_SELL_RATIO = 0.5
    TS_TRIGGER_RATE = 0.025      # 트레일링 스탑 발동 기준
    TS_STOP_GAP = 0.015          # 최고점 대비 -1.5% 하락 시 익절/손절

    # ⏳ 타임아웃 컷 (10:30)
    TIMEOUT_HOUR = 10            
    TIMEOUT_MINUTE = 30
    TIMEOUT_PROFIT = 0.003       # 10시 30분 기준 수익률이 0.3%(수수료 수준) 이하면 무조건 컷

    MARKET_CLOSE_HOUR = 15
    MARKET_CLOSE_MINUTE = 15

def is_excluded_stock(name):
    if name.endswith("우"): return True
    return any(keyword in name for keyword in BotConfig.EXCLUDE_KEYWORDS)

# ==============================================================================
# 2. KIS API 래퍼
# ==============================================================================
class KisApi:
    def __init__(self):
        self.base_headers_real = {
            "content-type": "application/json",
            "appKey": config.REAL_API_KEY,
            "appSecret": config.REAL_API_SECRET
        }
        if MODE == "REAL":
            self.base_headers_trade = self.base_headers_real.copy()
        else:
            self.base_headers_trade = {
                "content-type": "application/json",
                "appKey": config.MOCK_API_KEY,
                "appSecret": config.MOCK_API_SECRET
            }
        self.condition_seq_map = {}
        self.session = requests.Session()
        self.session.mount('https://', requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10))

    def get_approval_key(self):
        url = f"{BotConfig.URL_REAL}/oauth2/Approval"
        body = {
            "grant_type": "client_credentials",
            "appkey": config.REAL_API_KEY,       # 강제 고정
            "secretkey": config.REAL_API_SECRET  # 강제 고정
        }
        res = requests.post(url, headers={"content-type": "application/json"}, json=body)
        if res.status_code == 200:
            return res.json().get('approval_key')
        return None

    def _throttle(self, type="DATA"):
        time.sleep(BotConfig.DELAY_REAL if type == "DATA" or MODE == "REAL" else BotConfig.DELAY_MOCK)

    def get_headers(self, tr_id, type="DATA"):
        self._throttle(type)
        token = token_manager.get_access_token("REAL" if type == "DATA" or MODE == "REAL" else "MOCK")
        h = self.base_headers_real.copy() if type == "DATA" or MODE == "REAL" else self.base_headers_trade.copy()
        h["authorization"] = f"Bearer {token}"
        if type == "DATA": h["custtype"] = "P"
        h["tr_id"] = tr_id
        return h

    def fetch_hashkey(self, body_dict):
        try:
            url = f"{BotConfig.URL_REAL}/uapi/hashkey"
            res = requests.post(url, headers=self.base_headers_real, json=body_dict, timeout=5)
            if res.status_code == 200: return res.json()['HASH']
        except: pass
        return None

    def _safe_int(self, val):
        try:
            if val is None: return 0
            return int(float(str(val).strip().replace(',', '')))
        except: return 0

    def check_holiday(self, date_str):
        url = f"{BotConfig.URL_REAL}/uapi/domestic-stock/v1/quotations/chk-holiday"
        try:
            res = requests.get(url, headers=self.get_headers("CTCA0903R", "DATA"), params={"BASS_DT": date_str, "CTX_AREA_NK": "", "CTX_AREA_FK": ""}, timeout=5).json()
            if res['rt_cd'] == '0':
                for day in res['output']:
                    if day['bass_dt'] == date_str: return day['opnd_yn'] == 'N'
        except: pass
        return False

    def fetch_balance(self):
        base_url = BotConfig.URL_REAL if MODE == "REAL" else BotConfig.URL_MOCK
        acc_no = config.REAL_ACC_NO if MODE == "REAL" else config.MOCK_ACC_NO
        url = f"{base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        params = {
            "CANO": acc_no[:8], "ACNT_PRDT_CD": acc_no[-2:], "AFHR_FLPR_YN": "N", "OFL_YN": "N", "INQR_DVSN": "02", 
            "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
        }
        try:
            res = requests.get(url, headers=self.get_headers(BotConfig.TR_ID["balance"], "TRADE"), params=params, timeout=5).json()
            if res['rt_cd'] == '0': return self._safe_int(res['output2'][0]['tot_evlu_amt'])
        except: pass
        return 0

    def fetch_my_stock_list(self):
        base_url = BotConfig.URL_REAL if MODE == "REAL" else BotConfig.URL_MOCK
        acc_no = config.REAL_ACC_NO if MODE == "REAL" else config.MOCK_ACC_NO
        url = f"{base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        params = {
            "CANO": acc_no[:8], "ACNT_PRDT_CD": acc_no[-2:], "AFHR_FLPR_YN": "N", "OFL_YN": "N", "INQR_DVSN": "02", 
            "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
        }
        try:
            res = requests.get(url, headers=self.get_headers(BotConfig.TR_ID["balance"], "TRADE"), params=params, timeout=5).json()
            if res['rt_cd'] == '0':
                my_stocks = {}
                for stock in res['output1']:
                    qty = int(stock['hldg_qty'])
                    if qty > 0: my_stocks[stock['pdno']] = {'qty': qty, 'name': stock['prdt_name'], 'price': float(stock['pchs_avg_pric'])}
                return my_stocks
        except: pass
        return None

    def get_condition_seq(self, cond_name):
        if cond_name in self.condition_seq_map: return self.condition_seq_map[cond_name]
        url = f"{BotConfig.URL_REAL}/uapi/domestic-stock/v1/quotations/psearch-title"
        try:
            res = requests.get(url, headers=self.get_headers("HHKST03900300", "DATA"), params={"user_id": config.HTS_ID}, timeout=5).json()
            if res['rt_cd'] == '0':
                for item in res['output2']:
                    if item['grp_nm'] == cond_name:
                        self.condition_seq_map[cond_name] = item['seq']
                        return item['seq']
        except: pass
        return None

    def fetch_condition_stocks(self, cond_name):
        seq = self.get_condition_seq(cond_name)
        if not seq: return []
        url = f"{BotConfig.URL_REAL}/uapi/domestic-stock/v1/quotations/psearch-result"
        try:
            res = requests.get(url, headers=self.get_headers("HHKST03900400", "DATA"), params={"user_id": config.HTS_ID, "seq": seq}, timeout=5).json()
            if res['rt_cd'] == '0':
                return [{'code': item['code'], 'name': item['name'], 'rate': float(item.get('chgrate', 0.0)), 
                         'price': self._safe_int(item.get('price', item.get('stck_prpr', 0))), 'vol': self._safe_int(item.get('acml_vol', 0))} 
                        for item in res['output2']]
        except: pass
        return []

    def fetch_price_detail(self, code, name_from_rank=None):
        self._throttle() 
        url_price = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-price"
        try:
            res1 = self.session.get(url_price, headers=self.get_headers("FHKST01010100", "DATA"), params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}, timeout=2).json()
            if res1['rt_cd'] != '0': return None 
            
            out1 = res1['output']
            final_name = out1.get('rprs_mant_kor_name', out1.get('hts_kor_isnm', name_from_rank)) or "이름없음"
            
            url_hoga = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn"
            res2 = self.session.get(url_hoga, headers=self.get_headers("FHKST01010200", "DATA"), params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}, timeout=2).json()
            ask_price_1 = int(res2['output1'].get('askp1', 0)) if res2.get('rt_cd') == '0' else 0

            return {
                'code': code, 'name': final_name, 'price': int(out1.get('stck_prpr', 0)), 'open': int(out1.get('stck_oprc', 0)),
                'high': int(out1.get('stck_hgpr', 0)), 'rate': float(out1.get('prdy_ctrt', 0.0)), 
                'program_buy': int(out1.get('pgtr_ntby_qty', 0)), 'ask_price_1': ask_price_1, 'acml_vol': int(out1.get('acml_vol', 0)),
                # 👇 [여기에 1줄 추가] API 응답에서 시가총액(억 단위) 추출
                'market_cap': int(out1.get('hts_avls', 0))
            }
        except: return None

    def send_order(self, code, quantity, price=0, is_buy=True):
        base_url = BotConfig.URL_REAL if MODE == "REAL" else BotConfig.URL_MOCK
        acc_no = config.REAL_ACC_NO if MODE == "REAL" else config.MOCK_ACC_NO
        url = f"{base_url}/uapi/domestic-stock/v1/trading/order-cash"
        
        headers = self.get_headers(BotConfig.TR_ID["buy"] if is_buy else BotConfig.TR_ID["sell"], "TRADE")
        body = {"CANO": acc_no[:8], "ACNT_PRDT_CD": acc_no[-2:], "PDNO": code, "ORD_DVSN": "01", "ORD_QTY": str(quantity), "ORD_UNPR": "0"}
        
        if MODE == "REAL":
            hashkey = self.fetch_hashkey(body)
            if hashkey: headers["hashkey"] = hashkey
            else: return {'rt_cd': '9999', 'msg1': 'HashKey Failed'}
        try: return requests.post(url, headers=headers, json=body, timeout=5).json()
        except: return {'rt_cd': '9999', 'msg1': 'Error'}

# ==============================================================================
# 3. 봇 메인 로직 (TradingBot - Event Driven WebSockets)
# ==============================================================================
class TradingBot:
    def __init__(self):
        self.api = KisApi()
        self.portfolio = {}
        self.blacklist = {}
        self.is_buy_active = True
        self.last_update_id = 0    
        
        self.current_value_codes = [] 
        self.last_value_log_time = None 
        
        self.ws = None
        self.ws_approval_key = self.api.get_approval_key()
        
        self.load_state()
        signal.signal(signal.SIGINT, self.handle_exit)
        signal.signal(signal.SIGTERM, self.handle_exit)
        
        self.is_running = True
        self.market_open_time = None 
        self.missing_counts = {}
        self.pending_sells = {}

    def load_state(self):
        if os.path.exists('bot_state.json'):
            try:
                with open('bot_state.json', 'r', encoding='utf-8') as f: data = json.load(f)
                if data.get("date") == datetime.datetime.now().strftime("%Y-%m-%d"):
                    self.blacklist = data.get("blacklist", {})
                    self.portfolio = data.get("portfolio", {})
                    for code in self.portfolio:
                        if 'buy_time' in self.portfolio[code]:
                            self.portfolio[code]['buy_time'] = datetime.datetime.fromisoformat(self.portfolio[code]['buy_time'])
                    print(f"📥 [상태복원] 포트폴리오 {len(self.portfolio)}개 복원 완료.")
                    return 
            except: pass
        self.portfolio = {}
        self.blacklist = {}

    def save_state(self):
        try:
            pf_copy = copy.deepcopy(self.portfolio)
            for code in pf_copy:
                if isinstance(pf_copy[code].get('buy_time'), datetime.datetime):
                    pf_copy[code]['buy_time'] = pf_copy[code]['buy_time'].isoformat()
            data = {"date": datetime.datetime.now().strftime("%Y-%m-%d"), "blacklist": self.blacklist, "portfolio": pf_copy}
            with open('bot_state.json', 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=4)
        except: pass

    def handle_exit(self, signum, frame):
        print(f"\n🛑 종료 신호 감지! 상태 저장 중...")
        self.save_state()
        if self.ws: self.ws.close()
        sys.exit(0)

    # ----------------------------------------------------------------------
    # 🌐 웹소켓 리스너 (시가 이탈, 트레일링 스탑, 수익 실현 담당)
    # ----------------------------------------------------------------------
    def start_websocket(self):
        if not self.ws_approval_key:
            print("❌ 웹소켓 Approval Key 발급 실패. REST 모드로 강제 작동합니다.")
            return

        ws_url = BotConfig.WS_URL_REAL  # 무조건 실전 서버로 접속
        
        def on_message(ws, message):
            if '|' in message:
                parts = message.split('|')
                if len(parts) >= 4 and parts[1] == 'H0STCNT0': 
                    data_str = parts[3].split('^')
                    code = data_str[0]
                    current_price = abs(int(data_str[2])) 
                    
                    if code in self.portfolio:
                        self.evaluate_realtime_exit(code, current_price)
            elif 'PINGPONG' in message:
                ws.send(message) 

        def on_error(ws, error): print(f"⚠️ 웹소켓 에러: {error}")
        def on_close(ws, close_status_code, close_msg): print("🔌 웹소켓 연결 종료. 재연결 시도합니다.")
        def on_open(ws):
            print("🟢 웹소켓 서버 접속 성공. 실시간 틱 수신 시작.")
            for code in list(self.portfolio.keys()):
                self.ws_subscribe(code, "1")

        self.ws = websocket.WebSocketApp(ws_url, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)
        
        while self.is_running:
            self.ws.run_forever()
            time.sleep(3) 

    def ws_subscribe(self, code, tr_type="1"):
        if not self.ws or not self.ws_approval_key: return
        msg = {
            "header": {"approval_key": self.ws_approval_key, "custtype": "P", "tr_type": tr_type, "content-type": "utf-8"},
            "body": {"input": {"tr_id": "H0STCNT0", "tr_key": code}}
        }
        try: self.ws.send(json.dumps(msg))
        except: pass

    def evaluate_realtime_exit(self, code, current_price):
        if code not in self.portfolio: return
        
        info = self.portfolio[code]
        info['current_price'] = current_price  # REST 감시망(10:30 타임아웃)과 가격 공유
        
        buy_price = info['buy_price']
        open_price = info.get('open_price', 0)
        
        if buy_price <= 0: return
        profit_rate = (current_price - buy_price) / buy_price

        # 실시간 통계 갱신 (매도 로그용)
        if current_price > info.get('stats_max_price', 0): self.portfolio[code]['stats_max_price'] = current_price
        if current_price < info.get('stats_min_price', current_price): self.portfolio[code]['stats_min_price'] = current_price

        if profit_rate > info.get('max_profit_rate', 0.0):
            self.portfolio[code]['max_profit_rate'] = profit_rate
        max_profit = self.portfolio[code]['max_profit_rate']

        reason = None
        
        # 🚨 최우선 방어선 (웹소켓 틱 단위 감시)
        if open_price > 0 and current_price < open_price: 
            reason = "📉시가(Open) 지지선 이탈 즉시 손절"
        elif max_profit >= BotConfig.TS_TRIGGER_RATE and profit_rate <= (max_profit - BotConfig.TS_STOP_GAP):
            reason = f"🎢트레일링스탑(최고{max_profit*100:.1f}%->현재{profit_rate*100:.1f}%)"
        # 익절 후 흘러내림 방어
        elif info.get('has_partial_sold', False) and profit_rate <= BotConfig.TIMEOUT_PROFIT:
            reason = f"📉본전 이탈(익절 후 잔량 방어 컷)"
        
        if reason and code not in self.pending_sells:
            self.pending_sells[code] = datetime.datetime.now()
            threading.Thread(target=self.sell_stock, args=(code, reason), daemon=True).start()

        # 💰 절반 기계적 익절 (+2.5% 이상)
        if not info.get('has_partial_sold', False) and profit_rate >= BotConfig.PARTIAL_PROFIT_RATE:
            self.portfolio[code]['has_partial_sold'] = True 
            sell_qty = int(info['qty'] * BotConfig.PARTIAL_SELL_RATIO)
            
            if sell_qty == 0 and info['qty'] > 0:
                threading.Thread(target=self.sell_stock, args=(code, f"💰소액 잔량 전량익절({profit_rate*100:.2f}%)"), daemon=True).start()
            elif sell_qty > 0:
                def partial_sell():
                    res = self.api.send_order(code, sell_qty, is_buy=False)
                    if res['rt_cd'] == '0':
                        self.portfolio[code]['qty'] -= sell_qty
                        telegram_notifier.send_telegram_message(f"💰 [절반익절] {info['name']} {profit_rate*100:.2f}% 돌파")
                threading.Thread(target=partial_sell, daemon=True).start()

    # ----------------------------------------------------------------------
    # 🕵️ REST API 감시망 (조건 편출 및 10:30 타임아웃 담당)
    # ----------------------------------------------------------------------
    def monitor_portfolio(self):
        sync_counter = 0
        while self.is_running:
            sync_counter += 1
            if sync_counter >= 10:
                real_holdings = self.api.fetch_my_stock_list()
                if real_holdings is not None:
                    for my_code in list(self.portfolio.keys()):
                        if my_code not in real_holdings:
                            self.missing_counts[my_code] = self.missing_counts.get(my_code, 0) + 1
                            if self.missing_counts[my_code] >= 6: 
                                self.ws_subscribe(my_code, "2") 
                                del self.portfolio[my_code]
                                self.blacklist[my_code] = "SOLD"
                                if my_code in self.missing_counts: del self.missing_counts[my_code]
                        else:
                            self.portfolio[my_code]['qty'] = real_holdings[my_code]['qty']
                            self.portfolio[my_code]['buy_price'] = real_holdings[my_code]['price']
                sync_counter = 0

            codes_to_sell = []
            now_time = datetime.datetime.now()
            
            for my_code in list(self.portfolio.keys()):
                info = self.portfolio[my_code]
                
                # ⏳ 1. 타임아웃 컷 (10:30 돌파 시 수익 미달) - 절대 방어선
                is_timeout = False
                if now_time.hour > BotConfig.TIMEOUT_HOUR:
                    is_timeout = True
                elif now_time.hour == BotConfig.TIMEOUT_HOUR and now_time.minute >= BotConfig.TIMEOUT_MINUTE:
                    is_timeout = True
                    
                if is_timeout:
                    # 웹소켓이 최신화한 메모리 상의 가격을 활용하여 API 호출 낭비 없음
                    current_price = info.get('current_price', info['buy_price'])
                    if info['buy_price'] > 0:
                        profit_rate = (current_price - info['buy_price']) / info['buy_price']
                        if profit_rate <= BotConfig.TIMEOUT_PROFIT:
                            codes_to_sell.append((my_code, f"⏳타임아웃(10:30 도달/수익미달 컷)"))
                
                # 🚨 2. 조건검색 편출 즉시 매도 (수급 이탈)
                if self.current_value_codes and (my_code not in self.current_value_codes):
                    codes_to_sell.append((my_code, "🚨조건검색 편출 즉시 손절(수급이탈)"))

            for code, reason in codes_to_sell:
                if code not in self.pending_sells:
                    self.pending_sells[code] = datetime.datetime.now()
                    threading.Thread(target=self.sell_stock, args=(code, reason), daemon=True).start()

            time.sleep(1)

    # ----------------------------------------------------------------------
    # 📝 조건검색식 데이터 전수 로깅 (5분 주기)
    # ----------------------------------------------------------------------
    def log_value_list_volumes(self, value_list):
        if not value_list: return
        filename = f"value_volume_log_{datetime.datetime.now().strftime('%Y%m%d')}.csv"
        file_exists = os.path.isfile(filename)
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        try:
            with open(filename, mode='a', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                if not file_exists:
                    # 👇 [헤더 수정] 마지막에 'Market_Cap(100M)' 추가
                    writer.writerow(['Time', 'Code', 'Name', 'Price', 'Volume', 'Trade_Amt(100M)', 'Rate(%)', 'PG_Amt(100M)', 'Market_Cap(100M)'])
                
                for item in value_list:
                    code = item.get('code', '')
                    name = item.get('name', '')
                    price = item.get('price', 0)
                    vol = item.get('vol', 0)
                    trade_amt_100m = (price * vol) // 100000000
                    
                    pg_amt_100m = 0
                    market_cap_100m = 0  # 👈 [추가] 시가총액 변수 초기화

                    info = self.api.fetch_price_detail(code, name)
                    if info: 
                        pg_amt_100m = (info.get('program_buy', 0) * info.get('price', 0)) // 100000000
                        market_cap_100m = info.get('market_cap', 0)  # 👈 [추가] 상세 정보에서 시가총액 가져오기

                        # 👇 [기록 수정] 마지막 열에 market_cap_100m을 추가하여 기록
                    writer.writerow([now_str, code, name, price, vol, trade_amt_100m, item.get('rate', 0.0), pg_amt_100m, market_cap_100m])

            print(f"📝 [데이터 수집] {now_str} 기준 검색기 포착 {len(value_list)}종목 전수 로깅 완료.")
        except: pass

    # ----------------------------------------------------------------------
    # 🛒 매수 및 매도 실행 함수 (매매 로그 유지)
    # ----------------------------------------------------------------------
    def execute_buy(self, info):
        if not self.is_buy_active: return
        code = info['code']
        total_asset = self.api.fetch_balance()
        invest_amount = int(total_asset * BotConfig.INVEST_RATIO)
        
        # 💡 [수정] 수량 계산은 진입 직전가 기준
        expected_price = info['price'] 
        qty = int(invest_amount / expected_price) if expected_price > 0 else 0

        if qty > 0:
            res = self.api.send_order(code, qty, price=0, is_buy=True) # 시장가(0) 주문
            if res['rt_cd'] == '0':
                
                # 🛡️ [핵심 수정] 매수 직후 0.5초 대기 후 잔고를 즉시 조회하여 '진짜 체결 평단가'를 가져옴
                time.sleep(0.5) 
                real_holdings = self.api.fetch_my_stock_list()
                
                # 실제 체결가가 확인되면 적용, 혹시 조회가 실패하면 임시가 적용
                actual_buy_price = expected_price
                if real_holdings and code in real_holdings:
                    actual_buy_price = real_holdings[code]['price']

                pg_amt_now = info.get('program_buy', 0) * expected_price
                
                self.portfolio[code] = {
                    'name': info['name'], 'qty': qty, 
                    'buy_price': actual_buy_price,  # 👈 진짜 체결가로 완벽하게 기록
                    'strategy': 'VALUEKING', 'max_profit_rate': 0.0, 'has_partial_sold': False, 
                    'buy_time': datetime.datetime.now(), 'open_price': info['open'],
                    'current_price': actual_buy_price, 
                    
                    'stats_entry_pg': pg_amt_now, 'stats_max_pg': pg_amt_now,        
                    'stats_max_price': actual_buy_price, 'stats_min_price': actual_buy_price
                }
                
                self.ws_subscribe(code, "1")
                
                trade_amt_str = f"{(info.get('acml_vol', 0) * expected_price) // 100000000:,}억"
                # 텔레그램 알림에도 실제 체결가를 반영
                msg = (f"⚡ [{MODE} 수급 포착 진입] {info['name']}\n"
                       f"🎯 예상가: {expected_price:,}원\n"
                       f"💰 체결가: {actual_buy_price:,}원\n"
                       f"💵 거래대금: {trade_amt_str}\n"
                       f"📦 수량: {qty}주")
                telegram_notifier.send_telegram_message(msg)
                
                trade_logger.log_buy({
                    'code': code, 'name': info['name'], 'strategy': 'VALUEKING', 'level': 0,
                    'price': actual_buy_price, 'qty': qty, 'pg_amt': pg_amt_now, 'gap': info.get('rate', 0), 'leader': ''
                })
                
                self.save_state()
                self.blacklist[code] = "BOUGHT_TODAY" 

    def liquidate_all_positions(self, reason="장 마감(Time-Cut)"): 
        if not self.portfolio: return
        telegram_notifier.send_telegram_message(f"🚨 전량 매도 실행: {reason}")
        for code in list(self.portfolio.keys()):
            if code not in self.pending_sells:
                self.pending_sells[code] = datetime.datetime.now()
                threading.Thread(target=self.sell_stock, args=(code, reason), daemon=True).start()
            
    def wait_until_next_morning(self):
        now = datetime.datetime.now()
        next_morning = datetime.datetime((now + datetime.timedelta(days=1)).year, (now + datetime.timedelta(days=1)).month, (now + datetime.timedelta(days=1)).day, 8, 50, 0)
        telegram_notifier.send_telegram_message(f"💤 장 종료. 내일 대기.")
        self.portfolio = {}
        self.blacklist = {}
        self.save_state()
        self.market_open_time = None
        while datetime.datetime.now() < next_morning: time.sleep(10)

    def wait_for_market_open(self):
        while True:
            now = datetime.datetime.now()
            if now.weekday() >= 5 or self.api.check_holiday(now.strftime("%Y%m%d")):
                self.wait_until_next_morning()
                return False
            if now.hour == 8 and now.minute >= 45: time.sleep(10); continue
            if now.hour == 9 and now.minute >= 0:
                self.market_open_time = now
                telegram_notifier.send_telegram_message(f"🔔 Market Open! 밸류킹 가동.")
                return True
            time.sleep(1)
            
    def sell_stock(self, code, reason):
        if code in self.portfolio:
            qty = self.portfolio[code]['qty']
            res = self.api.send_order(code, qty, is_buy=False)
            
            if res['rt_cd'] == '0':
                p_data = self.portfolio[code]
                name = p_data['name']
                buy_price = p_data['buy_price']
                
                temp_info = self.api.fetch_price_detail(code)
                cur_price = temp_info['price'] if temp_info else 0
                exit_pg = (temp_info['program_buy'] * temp_info['price']) if temp_info else 0
                profit_rate = ((cur_price - buy_price) / buy_price * 100) if buy_price > 0 else 0
                
                msg = (f"👋 [{MODE} 절대 방어선 청산] {name}\n사유: {reason}\n매도가: {cur_price:,}원 ({profit_rate:+.2f}%)")
                telegram_notifier.send_telegram_message(msg)
                
                hold_min = int((datetime.datetime.now() - p_data['buy_time']).total_seconds() / 60) if 'buy_time' in p_data else 0
                
                # 원본 코드의 매도 로그 및 통계 기록 유지
                trade_logger.log_sell({
                    'code': code, 'name': name, 'strategy': p_data['strategy'], 'reason': reason,
                    'buy_price': buy_price, 'sell_price': cur_price, 'qty': qty, 'hold_time_min': hold_min,
                    'max_price': p_data.get('stats_max_price', 0), 'min_price': p_data.get('stats_min_price', 0),
                    'entry_pg': p_data.get('stats_entry_pg', 0), 'max_pg': p_data.get('stats_max_pg', 0), 'exit_pg': exit_pg
                })
                
                self.blacklist[code] = "SOLD" 
                self.ws_subscribe(code, "2") # 📡 웹소켓 구독 즉시 해제

                # 👇 [수정] 강제 삭제(del) 대신 안전한 pop 사용 (에러 방지)
                self.portfolio.pop(code, None)
                self.pending_sells.pop(code, None) 

                self.save_state()
            else:
                # 👇 [핵심 추가] API 주문 거절/실패 시 잠금 해제하여 다음 틱에서 재시도할 수 있게 복구
                self.pending_sells.pop(code, None)
                print(f"⚠️ 매도 주문 실패 [{code}]: {res.get('msg1')} - 다음 루프에서 재시도합니다.")

    # ----------------------------------------------------------------------
    # 📱 텔레그램 리스너 (실시간 수익률 표출 적용)
    # ----------------------------------------------------------------------
    def telegram_listener(self):
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates"
        while self.is_running:
            try:
                res = requests.get(url, params={'offset': self.last_update_id + 1, 'timeout': 10}, timeout=15)
                if res.status_code == 200 and res.json()['ok']:
                    for update in res.json()['result']:
                        self.last_update_id = update['update_id']
                        if 'message' not in update or 'text' not in update['message']: continue
                        if str(update['message']['chat']['id']) != str(config.TELEGRAM_CHAT_ID): continue

                        cmd = update['message']['text'].strip().split()[0].lower()
                        if cmd in ['/info', 'info']:
                            msg = f"📊 [상태]\n잔고: {self.api.fetch_balance():,}원\n\n[보유 종목]"
                            if not self.portfolio: msg += "\n없음"
                            for c, v in self.portfolio.items():
                                cur_price = v.get('current_price', v['buy_price'])
                                if cur_price > 0 and v['buy_price'] > 0:
                                    cur_rate = (cur_price - v['buy_price']) / v['buy_price'] * 100
                                    msg += f"\n- {v['name']}: {v['qty']}주 (현재 {cur_rate:+.2f}%)"
                            telegram_notifier.send_telegram_message(msg)
                        elif cmd in ['/stop', 'stop']: self.is_buy_active = False; telegram_notifier.send_telegram_message("⛔ 매수 정지")
                        elif cmd in ['/start', 'start']: self.is_buy_active = True; telegram_notifier.send_telegram_message("🟢 매수 재개")
                        elif cmd in ['/sell', 'sell']:
                            if len(update['message']['text'].split()) > 1:
                                target = update['message']['text'].split()[1]
                                target_code = next((c for c, v in self.portfolio.items() if v['name'] == target or c == target), None)
                                if target_code: self.sell_stock(target_code, "원격 지정 매도")
                            else: self.liquidate_all_positions(reason="원격 긴급매도")
            except: time.sleep(5)

    # ----------------------------------------------------------------------
    # ⚙️ 메인 루프
    # ----------------------------------------------------------------------
    def run(self):
        threading.Thread(target=self.monitor_portfolio, daemon=True).start()
        threading.Thread(target=self.telegram_listener, daemon=True).start()
        threading.Thread(target=self.start_websocket, daemon=True).start()
        
        telegram_notifier.send_telegram_message(f"🚀 Value-King [{MODE}] 하이브리드(WS+REST) 봇 시작")

        while True:
            try:
                now = datetime.datetime.now()
                if now.hour >= 15 and now.minute >= 15:
                    self.liquidate_all_positions(); self.wait_until_next_morning(); continue

                if self.market_open_time is None:
                    if not self.wait_for_market_open(): continue 
                
                # ==================================================================
                # API 호출 최적화: 조건검색 1회 조회 후 전역 변수로 공유
                # ==================================================================
                value_list = self.api.fetch_condition_stocks("value")
                if value_list: self.current_value_codes = [item['code'] for item in value_list]
                
                # 5분 단위 데이터 전수 로깅
                if now.minute % 5 == 0 and (self.last_value_log_time is None or now.minute != self.last_value_log_time.minute):
                    threading.Thread(target=self.log_value_list_volumes, args=(value_list,), daemon=True).start()
                    self.last_value_log_time = now

                # ==================================================================
                # 밸류 킹 매수 진입 (09:00 ~ 09:30 데이터 검증 최적화)
                # ==================================================================
                current_slots = sum(1 for _ in self.portfolio)
                is_valid_time = (now.hour == BotConfig.VALUEKING_START_HOUR and now.minute <= BotConfig.VALUEKING_END_MINUTE)
                
                if self.is_buy_active and current_slots < BotConfig.MAX_GLOBAL_SLOTS and is_valid_time:
                    for item in value_list:
                        code = item['code']
                        name = item['name']
                        
                        # 1. 중복 진입 금지 및 잡주 필터
                        if code in self.portfolio or code in self.blacklist: continue
                        if item['price'] < BotConfig.MIN_STOCK_PRICE or is_excluded_stock(name): continue

                        # 2. 수급 필터 (누적 거래대금 300억 이하 막 진입하는 종목 공략)
                        est_trade_amt = item['price'] * item['vol']
                        if est_trade_amt > BotConfig.VALUE_KING_MAX_VALUE: continue
                        
                        # 3. 상세 조회
                        info = self.api.fetch_price_detail(code, name)
                        if not info or info['open'] == 0: continue

                        # 👇 [반드시 추가해야 할 2줄] 윗꼬리 추격 매수 및 음봉 회피
                        if info['price'] < info['open']: continue                # 양봉(시가 위) 필수 조건
                        if info['rate'] > BotConfig.MAX_RATE_LIMIT: continue

                        # =========================================================================
                        # 👇 [신규 추가] 09:01 이후 & 누적 거래대금 10억 이상 하한선 필터
                        # =========================================================================
                        current_time = datetime.datetime.now().time()
                        market_open_1min = datetime.time(9, 1, 0)
                        
                        # 1. 시간 필터: 09:01:00 이전 매수 진입 차단 (초반 호가 공백/노이즈 회피)
                        if current_time < market_open_1min:
                            continue
                            
                        # 2. 거래대금 필터: 당일 누적 거래대금 10억 원 미만 종목 차단
                        total_trade_amt = info.get('acml_vol', 0) * info['price']
                        if total_trade_amt < BotConfig.VALUE_KING_MIN_VALUE:  # 10억 원
                            continue
                        # =========================================================================

                        '''# 👇 [여기에 추가] 프로그램 대량 매도 폭탄 회피 필터
                        pg_amt = info.get('program_buy', 0) * info['price']
                        total_trade_amt = info.get('acml_vol', 0) * info['price']
                        # 프로그램 순매도 금액이 당일 누적 거래대금의 5%를 초과할 정도로 거세면 매수 포기
                        if pg_amt < 0 and abs(pg_amt) > (total_trade_amt * 0.05): 
                            continue'''

                        # 진입 실행
                        self.execute_buy(info)
                        if sum(1 for _ in self.portfolio) >= BotConfig.MAX_GLOBAL_SLOTS: break

                time.sleep(1)
            except Exception as e:
                print(f"Main Loop Error: {e}")
                time.sleep(5)

if __name__ == "__main__":
    bot = TradingBot()
    bot.run()
