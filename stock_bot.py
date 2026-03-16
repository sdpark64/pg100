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

# 📂 사용자 파일 임포트
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

original_print = print
def print(*args, **kwargs):
    msg = " ".join(map(str, args))
    logger.info(msg)

# ==============================================================================
# 🕹️ [모드 설정]
# ==============================================================================
MODE = "REAL"   # 실전투자
# MODE = "MOCK"   # 모의투자

if MODE == "REAL":
    config.TELEGRAM_BOT_TOKEN = config.REAL_TELEGRAM_BOT_TOKEN
    config.TELEGRAM_CHAT_ID = config.REAL_TELEGRAM_CHAT_ID
else:
    config.TELEGRAM_BOT_TOKEN = config.MOCK_TELEGRAM_BOT_TOKEN
    config.TELEGRAM_CHAT_ID = config.MOCK_TELEGRAM_CHAT_ID

# ==============================================================================
# 1. 봇 설정 (BotConfig)
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
        
    PROBE_STOCK_CODE = "005930" 
    
    MAX_GLOBAL_SLOTS = 6  
    INVEST_RATIO = 0.15   
    
    EXCLUDE_KEYWORDS = ["스팩", "ETN", "ETF", "리츠", "우B", "우(", "인버스", "레버리지", "선물", "채권", "KODEX", "TIGER", "HANARO", "SOL", "PLUS", "RISE", "KOSEF", "ACE", "히어로즈", "WOORI"]
    MIN_STOCK_PRICE = 5000

    # ⚔️ [밸류 킹 설정] - KST 09:00 기준
    VALUEKING_START_HOUR = 9     
    VALUEKING_END_HOUR = 9       
    VALUEKING_END_MINUTE = 30
    
    VALUE_KING_MAX_VALUE = 30_000_000_000 # 300억 이하

    # 🚨 수익/손실 청산 룰
    PARTIAL_PROFIT_RATE = 0.025  
    PARTIAL_SELL_RATIO = 0.5
    STOP_LOSS_RATE = -0.02       
    TS_TRIGGER_RATE = 0.025      
    TS_STOP_GAP = 0.015          
    
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
        """웹소켓 접속을 위한 실시간 접속키(Approval Key) 발급"""
        url = f"{BotConfig.URL_REAL}/oauth2/Approval"
        body = {
            "grant_type": "client_credentials",
            "appkey": config.REAL_API_KEY if MODE == "REAL" else config.MOCK_API_KEY,
            "secretkey": config.REAL_API_SECRET if MODE == "REAL" else config.MOCK_API_SECRET
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
                'program_buy': int(out1.get('pgtr_ntby_qty', 0)), 'ask_price_1': ask_price_1, 'acml_vol': int(out1.get('acml_vol', 0))
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
    # 🌐 웹소켓 리스너 & 이벤트 처리 (핵심)
    # ----------------------------------------------------------------------
    def start_websocket(self):
        if not self.ws_approval_key:
            print("❌ 웹소켓 Approval Key 발급 실패. REST 모드로 강제 작동합니다.")
            return

        ws_url = BotConfig.WS_URL_REAL if MODE == "REAL" else BotConfig.WS_URL_MOCK
        
        def on_message(ws, message):
            # KIS 웹소켓 수신 포맷 파싱
            if '|' in message:
                parts = message.split('|')
                if len(parts) >= 4 and parts[1] == 'H0STCNT0': # 실시간 주식 체결가
                    data_str = parts[3].split('^')
                    code = data_str[0]
                    current_price = abs(int(data_str[2])) # 현재 체결가
                    
                    if code in self.portfolio:
                        self.evaluate_realtime_exit(code, current_price)
            elif 'PINGPONG' in message:
                ws.send(message) # 서버 Keep-alive 유지

        def on_error(ws, error): print(f"⚠️ 웹소켓 에러: {error}")
        def on_close(ws, close_status_code, close_msg): print("🔌 웹소켓 연결 종료. 재연결 시도합니다.")
        def on_open(ws):
            print("🟢 웹소켓 서버 접속 성공. 보유 종목 감시망 활성화.")
            # 접속 성공 시 기존 포트폴리오 종목들 일괄 구독
            for code in list(self.portfolio.keys()):
                self.ws_subscribe(code, "1")

        self.ws = websocket.WebSocketApp(ws_url, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)
        
        while self.is_running:
            self.ws.run_forever()
            time.sleep(3) # 끊어지면 3초 후 재접속

    def ws_subscribe(self, code, tr_type="1"):
        """tr_type: "1"(구독/등록), "2"(구독해제)"""
        if not self.ws or not self.ws_approval_key: return
        msg = {
            "header": {"approval_key": self.ws_approval_key, "custtype": "P", "tr_type": tr_type, "content-type": "utf-8"},
            "body": {"input": {"tr_id": "H0STCNT0", "tr_key": code}}
        }
        try: self.ws.send(json.dumps(msg))
        except: pass

    def evaluate_realtime_exit(self, code, current_price):
        """웹소켓에서 틱 데이터가 들어올 때마다 빛의 속도로 이탈 조건을 평가합니다."""
        if code not in self.portfolio: return
        
        info = self.portfolio[code]
        buy_price = info['buy_price']
        open_price = info.get('open_price', 0)
        
        if buy_price <= 0: return
        profit_rate = (current_price - buy_price) / buy_price

        # 최고/최저가 실시간 갱신
        if current_price > info.get('stats_max_price', 0): self.portfolio[code]['stats_max_price'] = current_price
        if current_price < info.get('stats_min_price', current_price): self.portfolio[code]['stats_min_price'] = current_price

        # 트레일링 스탑용 최고 수익률 갱신
        if profit_rate > info.get('max_profit_rate', 0.0):
            self.portfolio[code]['max_profit_rate'] = profit_rate
        max_profit = self.portfolio[code]['max_profit_rate']

        reason = None
        
        # 1. 당일 시가 이탈 (즉시 손절)
        if open_price > 0 and current_price < open_price: reason = "📉시가(Open) 지지선 이탈"
        # 2. 손절선 도달
        elif profit_rate <= BotConfig.STOP_LOSS_RATE: reason = f"📉손절선 이탈({profit_rate*100:.2f}%)"
        # 3. 트레일링 스탑 
        elif max_profit >= BotConfig.TS_TRIGGER_RATE and profit_rate <= (max_profit - BotConfig.TS_STOP_GAP):
            reason = f"🎢트레일링스탑(최고{max_profit*100:.1f}%->현재{profit_rate*100:.1f}%)"
        # 4. 본전 이탈 컷 (부분 익절 후 잔량 방어)
        elif info.get('has_partial_sold', False) and profit_rate <= 0.003:
            reason = "📉본전 이탈(익절 후 잔량 0.3% 컷)"
        
        # 조건 달성 시 별도 스레드로 REST 매도 주문 실행 (웹소켓 수신이 블로킹되지 않도록)
        if reason and code not in self.pending_sells:
            self.pending_sells[code] = datetime.datetime.now() # 중복 매도 방지 락(Lock)
            threading.Thread(target=self.sell_stock, args=(code, reason), daemon=True).start()

        # 5. 기계적 부분 익절 (+2.5% 이상) -> 잔량은 보유하므로 완전 매도가 아님
        if not info.get('has_partial_sold', False) and profit_rate >= BotConfig.PARTIAL_PROFIT_RATE:
            self.portfolio[code]['has_partial_sold'] = True # 플래그 먼저 세워서 중복 방지
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
    # 🕵️ REST API 감시망 (웹소켓이 커버 못하는 타임아웃/편출 감지 및 동기화)
    # ----------------------------------------------------------------------
    def monitor_portfolio(self):
        sync_counter = 0
        while self.is_running:
            sync_counter += 1
            # 10초에 한 번씩 잔고 동기화
            if sync_counter >= 10:
                real_holdings = self.api.fetch_my_stock_list()
                if real_holdings is not None:
                    for my_code in list(self.portfolio.keys()):
                        if my_code not in real_holdings:
                            self.missing_counts[my_code] = self.missing_counts.get(my_code, 0) + 1
                            if self.missing_counts[my_code] >= 6: 
                                self.ws_subscribe(my_code, "2") # 웹소켓 구독 해제
                                del self.portfolio[my_code]
                                self.blacklist[my_code] = "SOLD"
                                if my_code in self.missing_counts: del self.missing_counts[my_code]
                        else:
                            self.portfolio[my_code]['qty'] = real_holdings[my_code]['qty']
                            self.portfolio[my_code]['buy_price'] = real_holdings[my_code]['price']
                sync_counter = 0

            # 웹소켓이 가격은 감시하지만, '검색기 이탈'이나 '시간 경과'는 여기서 주기적으로 체크
            codes_to_sell = []
            now_time = datetime.datetime.now()
            
            for my_code in list(self.portfolio.keys()):
                info = self.portfolio[my_code]
                
                # 타임아웃 컷 (10:30 돌파 시 수익 미달)
                if now_time.hour >= 10 and now_time.minute >= 30:
                    my_info = self.api.fetch_price_detail(my_code, info['name'])
                    if my_info and info['buy_price'] > 0:
                        profit_rate = (my_info['price'] - info['buy_price']) / info['buy_price']
                        if profit_rate <= 0.003: codes_to_sell.append((my_code, "⏳타임아웃(10:30 돌파/본전미달)"))
                
                # 검색기 편출 감지 (전역 변수 활용으로 무과부하 달성)
                if self.current_value_codes and (my_code not in self.current_value_codes):
                    codes_to_sell.append((my_code, "🚨조건검색 편출(수급이탈)"))

            for code, reason in codes_to_sell:
                if code not in self.pending_sells:
                    self.pending_sells[code] = datetime.datetime.now()
                    threading.Thread(target=self.sell_stock, args=(code, reason), daemon=True).start()

            time.sleep(1)

    def log_value_list_volumes(self, value_list):
        if not value_list: return
        filename = f"value_volume_log_{datetime.datetime.now().strftime('%Y%m%d')}.csv"
        file_exists = os.path.isfile(filename)
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        try:
            with open(filename, mode='a', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(['Time', 'Code', 'Name', 'Price', 'Volume', 'Trade_Amt(100M)', 'Rate(%)', 'PG_Amt(100M)'])
                for item in value_list:
                    code = item.get('code', '')
                    name = item.get('name', '')
                    price = item.get('price', 0)
                    vol = item.get('vol', 0)
                    trade_amt_100m = (price * vol) // 100000000
                    pg_amt_100m = 0
                    
                    if trade_amt_100m >= 500:
                        info = self.api.fetch_price_detail(code, name)
                        if info: pg_amt_100m = (info.get('program_buy', 0) * info.get('price', 0)) // 100000000
                            
                    writer.writerow([now_str, code, name, price, vol, trade_amt_100m, item.get('rate', 0.0), pg_amt_100m])
            print(f"📝 [데이터 수집] {now_str} 기준 VALUE 후보 로깅 완료.")
        except: pass

    def execute_buy(self, info):
        if not self.is_buy_active: return
        code = info['code']
        total_asset = self.api.fetch_balance()
        invest_amount = int(total_asset * BotConfig.INVEST_RATIO)
        qty = int(invest_amount / info['price']) if info['price'] > 0 else 0

        if qty > 0:
            target_price = info.get('ask_price_1', info['price'])
            if target_price == 0: target_price = info['price']

            res = self.api.send_order(code, qty, price=target_price, is_buy=True)
            if res['rt_cd'] == '0':
                pg_amt_now = info.get('program_buy', 0) * info['price']
                self.portfolio[code] = {
                    'name': info['name'], 'qty': qty, 'buy_price': info['price'], 
                    'strategy': 'VALUEKING', 'max_profit_rate': 0.0, 'has_partial_sold': False, 
                    'buy_time': datetime.datetime.now(), 'open_price': info['open'],
                    'stats_entry_pg': pg_amt_now, 'stats_max_pg': pg_amt_now,        
                    'stats_max_price': info['price'], 'stats_min_price': info['price']
                }
                
                # 📡 [핵심] 매수 성공 즉시 웹소켓 실시간 가격 감시망에 해당 종목 추가
                self.ws_subscribe(code, "1")
                
                trade_amt_str = f"{(info.get('acml_vol', 0) * info['price']) // 100000000:,}억"
                msg = (f"⚡ [{MODE} 밸류킹 진입] {info['name']}\n💰 매수가: {info['price']:,}원\n💵 거래대금: {trade_amt_str}\n📦 수량: {qty}주")
                telegram_notifier.send_telegram_message(msg)
                
                trade_logger.log_buy({
                    'code': code, 'name': info['name'], 'strategy': 'VALUEKING', 'level': 0,
                    'price': info['price'], 'qty': qty, 'pg_amt': pg_amt_now, 'gap': info.get('rate', 0), 'leader': ''
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
                
                msg = (f"👋 [{MODE} 매도] {name}\n사유: {reason}\n매도가: {cur_price:,}원 ({profit_rate:+.2f}%)")
                telegram_notifier.send_telegram_message(msg)
                
                hold_min = int((datetime.datetime.now() - p_data['buy_time']).total_seconds() / 60) if 'buy_time' in p_data else 0
                trade_logger.log_sell({
                    'code': code, 'name': name, 'strategy': p_data['strategy'], 'reason': reason,
                    'buy_price': buy_price, 'sell_price': cur_price, 'qty': qty, 'hold_time_min': hold_min,
                    'max_price': p_data.get('stats_max_price', 0), 'min_price': p_data.get('stats_min_price', 0),
                    'entry_pg': p_data.get('stats_entry_pg', 0), 'max_pg': p_data.get('stats_max_pg', 0), 'exit_pg': exit_pg
                })
                
                self.blacklist[code] = "SOLD" 
                self.ws_subscribe(code, "2") # 📡 [핵심] 판매 완료 후 웹소켓 감시망에서 해제
                del self.portfolio[code]
                self.save_state()

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
                                info = self.api.fetch_price_detail(c, v['name'])
                                if info and v['buy_price'] > 0:
                                    cur_rate = (info['price'] - v['buy_price']) / v['buy_price'] * 100
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

    def run(self):
        # 3-Track 스레드 가동 (REST감시, Telegram감시, 웹소켓감시)
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
                # API 호출 최소화: 여기서만 조건검색 리스트를 받아오고 전역으로 뿌림
                # ==================================================================
                value_list = self.api.fetch_condition_stocks("value")
                if value_list: self.current_value_codes = [item['code'] for item in value_list]
                
                # 30분 단위 로깅
                if now.minute % 5 == 0 and (self.last_value_log_time is None or now.minute != self.last_value_log_time.minute):
                    threading.Thread(target=self.log_value_list_volumes, args=(value_list,), daemon=True).start()
                    self.last_value_log_time = now

                # 밸류 킹 매수 진입 (09:00 ~ 09:30)
                current_slots = sum(1 for _ in self.portfolio)
                is_valid_time = (now.hour == BotConfig.VALUEKING_START_HOUR and now.minute <= BotConfig.VALUEKING_END_MINUTE)
                
                if self.is_buy_active and current_slots < BotConfig.MAX_GLOBAL_SLOTS and is_valid_time:
                    for item in value_list:
                        code = item['code']
                        name = item['name']
                        
                        if code in self.portfolio or code in self.blacklist: continue
                        if item['price'] < BotConfig.MIN_STOCK_PRICE or is_excluded_stock(name): continue

                        est_trade_amt = item['price'] * item['vol']
                        if est_trade_amt > BotConfig.VALUE_KING_MAX_VALUE: continue
                        
                        info = self.api.fetch_price_detail(code, name)
                        if not info or info['open'] == 0: continue
                        if info['price'] < info['open'] * 1.03: continue # 3% 갭 유지

                        self.execute_buy(info)
                        if sum(1 for _ in self.portfolio) >= BotConfig.MAX_GLOBAL_SLOTS: break

                time.sleep(1)
            except Exception as e:
                print(f"Main Loop Error: {e}")
                time.sleep(5)

if __name__ == "__main__":
    bot = TradingBot()
    bot.run()
