import requests
import json
import time
import datetime
import boto3
import threading
import logging
import logging.handlers
import sys

# 📂 사용자 파일 임포트
import config
import token_manager
import telegram_notifier
import trade_logger # 👈 추가

# ==============================================================================
# 📝 [로그 시스템 설정] print를 자동으로 로그 파일에 기록하기
# ==============================================================================
def setup_logging():
    # 1. 로거 생성
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # 포맷 설정 (시간 - 레벨 - 메시지)
    formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    # 2. 파일 핸들러 (output.log에 기록, 10MB마다 새로운 파일 생성, 최대 5개 보관)
    #    -> 이렇게 하면 로그 파일이 무한히 커지는 것을 막아줍니다.
    file_handler = logging.handlers.RotatingFileHandler(
        'output.log', maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 3. 콘솔 핸들러 (화면에도 출력)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    
    return logger

# 로거 실행
logger = setup_logging()

# 🔥 [핵심 마법] 기존 print 함수를 logger.info로 덮어쓰기 (오버라이딩)
# 이제 코드에서 print("안녕") 하면 -> 로그 파일에 시간과 함께 저장됩니다.
original_print = print
def print(*args, **kwargs):
    # print의 내용을 하나의 문자열로 합침
    msg = " ".join(map(str, args))
    # 로그에 기록 (자동으로 파일+화면 출력)
    logger.info(msg)

# ==============================================================================
# 🕹️ [모드 설정]
# ==============================================================================
# MODE = "REAL"   # 실전투자
MODE = "MOCK"   # 모의투자 (기본값)

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
    
    DELAY_REAL = 0.06
    DELAY_MOCK = 0.60 

    if MODE == "MOCK":
        TR_ID = { "balance": "VTTC8434R", "buy": "VTTC0802U", "sell": "VTTC0801U" }
    else: 
        TR_ID = { "balance": "TTTC8434R", "buy": "TTTC0802U", "sell": "TTTC0801U" }
        
    PROBE_STOCK_CODE = "005930" 
    
    # 💰 [자금 및 슬롯 관리]
    MAX_GLOBAL_SLOTS = 6  
    INVEST_RATIO = 0.15   
    
    # 🔢 [일별 매수 종목 수 제한]
    MAX_DAILY_THEME = 0    
    MAX_DAILY_MORNING = 0  
    
    # 🔥 [시간대별 프로그램 수급 필터] (이 금액을 넘어야만 매수 로직 발동)
    # 09:00 ~ 09:30 : 50억
    # 09:30 ~ 10:00 : 100억
    # 10:00 ~ 11:30 : 200억
    # 11:30 ~ 13:00 : 250억
    # 13:00 ~ 장마감 : 300억
    PG_TIME_FILTER_0 = 5_000_000_000
    PG_TIME_FILTER_1 = 20_000_000_000
    PG_TIME_FILTER_2 = 25_000_000_000
    PG_TIME_FILTER_3 = 50_000_000_000
    PG_TIME_FILTER_4 = 100_000_000_000

    # 🔥 [프로그램 자이언트 설정]
    PG_MILESTONES = [
        5_000_000_000,   # 150억
        20_000_000_000,   # 200억
        50_000_000_000,  # 500억
        100_000_000_000,  # 1000억
        150_000_000_000,  # 1500억
        200_000_000_000   # 2000억
    ]
    
    # 기준점 하향 조정 (200억 -> 150억)
    PG_LEVEL_0_AMT = 5_000_000_000 
    
    # 📉 [프로그램 수급 이탈/반등 감지 비율]
    PG_DROP_RATE_TRIGGER = 0.30   # 고점 대비 30% 하락 시 매도
    PG_RISE_RATE_TRIGGER = 0.30   # 저점 대비 30% 반등 시 재매수

    # 🔥 [모닝 급등주 프로그램 수급 기준]
    MORNING_PG_AMT_10MIN = 0
    MORNING_PG_AMT_30MIN = 1_000_000_000
    MORNING_PG_AMT_LATE  = 3_000_000_000

    # 🕒 [재매수 쿨타임 & 타임아웃]
    REBUY_COOLTIME_MINUTES = 480
    THEME_BUY_TIMEOUT = 30    

    # 🚫 [필터]
    MIN_STOCK_PRICE = 1000

    # 🛡️ 안전장치
    MIN_HOGA_AMT = 50_000_000 
    MAX_WICK_RATIO = 0.3  

    # 📊 [모닝 거래대금 기준]
    MORNING_VOL_LEVEL_1 = 3_000_000_000   
    MORNING_VOL_LEVEL_2 = 10_000_000_000  
    MORNING_VOL_LEVEL_3 = 30_000_000_000  
    
    # ⏳ [시간 제한]
    MORNING_MSG_WINDOW = 1200   #모닝전략 09:10 까지  
    THEME_MSG_WINDOW   = 3600  
    
    # ⚔️ [모닝 전략]
    MORNING_GAP_MIN = 1.0     
    MORNING_GAP_MAX = 12.0    
    MORNING_RATE_MIN = 5.0    
    MORNING_RATE_MAX = 15.0   
    
    # ⚔️ [자이언트 전략 등락률 범위]
    GIANT_RATE_MIN = 3.0
    GIANT_RATE_MAX = 30.0

    # ✅ [추가] 프로그램 자이언트용 최소 호가 총잔량 금액 (기본 1억)
    MIN_TOTAL_HOGA_AMT = 200_000_000

    # 🛡️ [매도/청산 조건]
    PARTIAL_PROFIT_RATE = 0.02  # 수익률 2% 부분익절
    PARTIAL_SELL_RATIO = 0.5    # 부분익절, 절반매도
    STOP_LOSS_RATE = -0.02  # 손절 -2%      
    TARGET_PROFIT = 0.29        
    
    TS_TRIGGER_RATE = 0.04  
    TS_STOP_GAP = 0.02      

    MARKET_CLOSE_HOUR = 15
    MARKET_CLOSE_MINUTE = 15

    TIME_STOP_MINUTES = 600      # 매수 후 20분 지나면 체크
    TIME_STOP_PROFIT = 0.0      # 20분 지났는데 수익률이 0% 이하(본전 이하)면 매도

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

    def _throttle(self, type="DATA"):
        if type == "DATA":
            time.sleep(BotConfig.DELAY_REAL)
        else:
            if MODE == "REAL":
                time.sleep(BotConfig.DELAY_REAL)
            else:
                time.sleep(BotConfig.DELAY_MOCK)

    def get_headers(self, tr_id, type="DATA"):
        self._throttle(type)
        if type == "DATA":
            token = token_manager.get_access_token("REAL")
            h = self.base_headers_real.copy()
            h["authorization"] = f"Bearer {token}"
            h["custtype"] = "P"
        else: 
            target = "REAL" if MODE == "REAL" else "MOCK"
            token = token_manager.get_access_token(target)
            h = self.base_headers_trade.copy()
            h["authorization"] = f"Bearer {token}"
        h["tr_id"] = tr_id
        return h

    def fetch_hashkey(self, body_dict):
        try:
            url = f"{BotConfig.URL_REAL}/uapi/hashkey"
            headers = {
                "content-type": "application/json",
                "appKey": config.REAL_API_KEY,
                "appSecret": config.REAL_API_SECRET
            }
            res = requests.post(url, headers=headers, json=body_dict, timeout=5)
            if res.status_code == 200:
                return res.json()['HASH']
            else:
                return None
        except Exception as e:
            print(f"❌ HashKey 에러: {e}")
            return None

    def _safe_int(self, val):
        try:
            if val is None: return 0
            s_val = str(val).strip().replace(',', '')
            if not s_val: return 0
            return int(float(s_val))
        except:
            return 0

    def check_holiday(self, date_str):
        url = f"{BotConfig.URL_REAL}/uapi/domestic-stock/v1/quotations/chk-holiday"
        headers = self.get_headers("CTCA0903R", type="DATA")
        params = {"BASS_DT": date_str, "CTX_AREA_NK": "", "CTX_AREA_FK": ""}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5).json()
            if res['rt_cd'] == '0':
                for day in res['output']:
                    if day['bass_dt'] == date_str:
                        return day['opnd_yn'] == 'N'
            return False
        except: return False

    def fetch_balance(self):
        base_url = BotConfig.URL_REAL if MODE == "REAL" else BotConfig.URL_MOCK
        url = f"{base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        headers = self.get_headers(BotConfig.TR_ID["balance"], type="TRADE")
        acc_no = config.REAL_ACC_NO if MODE == "REAL" else config.MOCK_ACC_NO
        params = {
            "CANO": acc_no[:8], "ACNT_PRDT_CD": acc_no[-2:],
            "AFHR_FLPR_YN": "N", "OFL_YN": "N", "INQR_DVSN": "02", "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
        }
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5).json()
            if res['rt_cd'] == '0':
                return self._safe_int(res['output2'][0]['tot_evlu_amt'])
        except Exception as e:
            print(f"❌ 잔고 조회 실패: {e}")
        return 0

    def fetch_my_stock_list(self):
        base_url = BotConfig.URL_REAL if MODE == "REAL" else BotConfig.URL_MOCK
        url = f"{base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        headers = self.get_headers(BotConfig.TR_ID["balance"], type="TRADE")
        acc_no = config.REAL_ACC_NO if MODE == "REAL" else config.MOCK_ACC_NO
        params = {
            "CANO": acc_no[:8], "ACNT_PRDT_CD": acc_no[-2:],
            "AFHR_FLPR_YN": "N", "OFL_YN": "N", "INQR_DVSN": "02", "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
        }
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5).json()
            if res['rt_cd'] == '0':
                my_stocks = {}
                for stock in res['output1']:
                    code = stock['pdno']
                    qty = int(stock['hldg_qty'])
                    if qty > 0:
                        my_stocks[code] = {
                            'qty': qty,
                            'name': stock['prdt_name'],
                            'price': float(stock['pchs_avg_pric'])
                        }
                return my_stocks
            else:
                return None
        except Exception as e:
            return None

    def get_condition_seq(self, cond_name):
        if cond_name in self.condition_seq_map:
            return self.condition_seq_map[cond_name]
        url = f"{BotConfig.URL_REAL}/uapi/domestic-stock/v1/quotations/psearch-title"
        headers = self.get_headers("HHKST03900300", type="DATA")
        params = { "user_id": config.HTS_ID }
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5).json()
            if res['rt_cd'] == '0':
                for item in res['output2']:
                    if item['grp_nm'] == cond_name:
                        self.condition_seq_map[cond_name] = item['seq']
                        print(f"✅ 조건검색식 '{cond_name}' 매핑 완료 (Seq: {item['seq']})")
                        return item['seq']
        except Exception as e:
            print(f"❌ 조건식 목록 조회 실패: {e}")
        return None

    def fetch_condition_stocks(self, cond_name):
        seq = self.get_condition_seq(cond_name)
        if not seq: return []
        url = f"{BotConfig.URL_REAL}/uapi/domestic-stock/v1/quotations/psearch-result"
        headers = self.get_headers("HHKST03900400", type="DATA")
        params = { "user_id": config.HTS_ID, "seq": seq }
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5).json()
            if res['rt_cd'] == '0':
                raw_list = res['output2']
                mapped_list = []
                for item in raw_list:
                    price_val = item.get('price', item.get('stck_prpr', 0))
                    vol_val = item.get('acml_vol', 0)
                    mapped_list.append({
                        'stck_shrn_iscd': item['code'],
                        'hts_kor_isnm': item['name'],
                        'prdy_ctrt': float(item.get('chgrate', 0.0)),
                        'price': self._safe_int(price_val),
                        'vol': self._safe_int(vol_val)
                    })
                return mapped_list
        except Exception as e:
            print(f"❌ 조건검색 '{cond_name}' 조회 실패: {e}")
        return []

    def fetch_price_detail(self, code, name_from_rank=None, lite=False):
        self._throttle() 
        
        # ------------------------------------------------------------------
        # STEP 1. 기본 시세 & 프로그램 수급 조회 (inquire-price)
        # ------------------------------------------------------------------
        # url_price = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-price"
        base_url = BotConfig.URL_REAL if MODE == "REAL" else BotConfig.URL_MOCK
        headers_price = self.get_headers("FHKST01010100", type="DATA")
        params_price = { "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code }

        try:
            res1 = self.session.get(url_price, headers=headers_price, params=params_price, timeout=2).json()
            if res1['rt_cd'] != '0': return None 
            
            out1 = res1['output']
            final_name = out1.get('rprs_mant_kor_name', out1.get('hts_kor_isnm', name_from_rank))
            if final_name is None: final_name = "이름없음"
            
            program_buy = int(out1.get('pgtr_ntby_qty', 0)) 
            current_price = int(out1.get('stck_prpr', 0))
            
            # ------------------------------------------------------------------
            # STEP 2. 호가 & [총잔량] 상세 조회 (inquire-asking-price-exp-ccn)
            # ------------------------------------------------------------------
            url_hoga = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn"
            headers_hoga = self.get_headers("FHKST01010200", type="DATA")
            params_hoga = { "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code }
            
            res2 = self.session.get(url_hoga, headers=headers_hoga, params=params_hoga, timeout=2).json()
            
            ask_rsqn1 = 0
            bid_rsqn1 = 0
            ask_price_1 = 0  # 👈 추가
            bid_price_1 = 0  # 👈 추가
            total_ask = 0
            total_bid = 0
            
            if res2['rt_cd'] == '0':
                out2 = res2['output1']
                ask_rsqn1 = int(out2.get('askp_rsqn1', 0)) 
                bid_rsqn1 = int(out2.get('bidp_rsqn1', 0)) 
                
                # ✅ [핵심 수정] 변수명에 'p'가 들어가야 합니다! (askp, bidp)
                ask_price_1 = int(out2.get('askp1', 0))
                bid_price_1 = int(out2.get('bidp1', 0))

                total_ask = int(out2.get('total_askp_rsqn', 0)) 
                total_bid = int(out2.get('total_bidp_rsqn', 0))

            # ------------------------------------------------------------------
            # 데이터 병합
            # ------------------------------------------------------------------
            data = {
                'code': code, 
                'name': final_name,
                'price': current_price,
                'open': int(out1.get('stck_oprc', 0)),
                'high': int(out1.get('stck_hgpr', 0)),
                'low': int(out1.get('stck_lwpr', 0)),
                'max_price': int(out1.get('stck_mxpr', 0)),
                'rate': float(out1.get('prdy_ctrt', 0.0)),
                
                'program_buy': program_buy, 
                'ask_price_1': ask_price_1,
                'bid_price_1': bid_price_1,
                'total_ask': total_ask,     # 이제 정상 값 들어감
                'total_bid': total_bid,     # 이제 정상 값 들어감
                'acml_vol': int(out1.get('acml_vol', 0)),
                
                'ask_rsqn1': ask_rsqn1,     
                'bid_rsqn1': bid_rsqn1,
                'bid_ask_ratio': 0.0
            }
            
            # 비율 계산
            if data['total_ask'] > 0:
                data['bid_ask_ratio'] = (data['total_bid'] / data['total_ask']) * 100
            elif data['total_bid'] > 0:
                data['bid_ask_ratio'] = 999.0
            
            # 윗꼬리 계산
            wick_ratio = 0.0
            if data['high'] > data['open']:
                upper_wick = data['high'] - max(data['price'], data['open'])
                total_candle = data['high'] - data['open']
                wick_ratio = upper_wick / total_candle
            data['wick_ratio'] = wick_ratio

            return data
                
        except Exception:
            pass
            
        return None

    # -----------------------------------------------------------
    # [수정됨] 차트 조회 실패 시 현재가로 대체하는 비상 기능 추가
    # -----------------------------------------------------------
    def fetch_5m_candles(self, code, target_n=12, base_time=None):
        # 1분봉 60개를 요청 (최대 1시간치)
        url = f"{BotConfig.URL_REAL}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
        headers = self.get_headers("FHKST03010200", type="DATA")
        
        if base_time:
            now_str = base_time
        else:
            now_str = datetime.datetime.now().strftime("%H%M%S")

        params = {
            "FID_ETC_CLS_CODE": "",
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
            "FID_INPUT_HOUR_1": now_str, 
            "FID_PW_DIV_CODE": "0" 
        }

        try:
            # 1차 호출
            res = requests.get(url, headers=headers, params=params, timeout=2).json()
            
            # 👇 [핵심] 차트 데이터 수신 실패 시 비상 대책 실행
            if res['rt_cd'] != '0' or not res['output2']:
                # print(f"⚠️ [차트누락] {code} 차트 응답 없음 -> 현재가로 임시 봉 생성")
                
                # 현재가 정보 가져오기 (이건 잘 되니까)
                price_info = self.fetch_price_detail(code)
                if price_info:
                    current_price = price_info['price']
                    # 가짜 봉 1개 생성 (시/고/저/종 모두 현재가)
                    dummy_candle = {
                        'open': current_price,
                        'close': current_price,
                        'high': current_price,
                        'low': current_price,
                        'is_finished': False
                    }
                    # 데이터가 1개라도 있으면 로직이 죽지는 않음
                    return [dummy_candle]
                return []
            
            raw_data = res['output2'] 

            # 2차 호출 (필요 시)
            if target_n > 6 and len(raw_data) > 0:
                last_time = raw_data[-1]['stck_cntg_hour']
                params['FID_INPUT_HOUR_1'] = last_time
                time.sleep(0.1) 
                res2 = requests.get(url, headers=headers, params=params, timeout=2).json()
                if res2['rt_cd'] == '0':
                    raw_data.extend(res2['output2']) 

            # [데이터 가공] 1분봉 -> 5분봉 합치기
            candles_5m = []
            current_bucket_key = None
            temp_candle = {'open': 0, 'close': 0, 'high': 0, 'low': 0, 'count': 0}
            
            raw_data.sort(key=lambda x: x['stck_cntg_hour']) 
            
            for item in raw_data:
                t_str = item['stck_cntg_hour'] 
                price_o = int(item['stck_oprc'])
                price_c = int(item['stck_prpr'])
                price_h = int(item['stck_hgpr'])
                price_l = int(item['stck_lwpr'])
                
                minute = int(t_str[2:4])
                bucket_min = (minute // 5) * 5
                bucket_key = t_str[0:2] + f"{bucket_min:02d}"
                
                if current_bucket_key != bucket_key:
                    if current_bucket_key is not None:
                        candles_5m.append(temp_candle.copy())
                    
                    current_bucket_key = bucket_key
                    temp_candle = {'open': price_o, 'close': price_c, 'high': price_h, 'low': price_l, 'is_finished': False}
                else:
                    temp_candle['close'] = price_c
                    if price_h > temp_candle['high']: temp_candle['high'] = price_h
                    if price_l < temp_candle['low']: temp_candle['low'] = price_l
            
            if temp_candle['open'] > 0:
                candles_5m.append(temp_candle)
            
            return list(reversed(candles_5m))

        except Exception as e:
            # print(f"❌ 5분봉 처리 중 오류: {e}")
            return []

    def send_order(self, code, quantity, price=0, is_buy=True):
        base_url = BotConfig.URL_REAL if MODE == "REAL" else BotConfig.URL_MOCK
        acc_no = config.REAL_ACC_NO if MODE == "REAL" else config.MOCK_ACC_NO
        tr_id = BotConfig.TR_ID["buy"] if is_buy else BotConfig.TR_ID["sell"]
        url = f"{base_url}/uapi/domestic-stock/v1/trading/order-cash"
        
        headers = self.get_headers(tr_id, type="TRADE")

        if price > 0:
            ord_dvsn = "03"       # 00: 지정가 (Limit Order) -> 최유리(03)로 수정
            # ord_unpr = str(price) # 입력받은 가격 사용
            ord_unpr = "0"
        else:
            ord_dvsn = "03"       # 가격 0이면 최유리 (예비용)
            ord_unpr = "0"

        body = {
            "CANO": acc_no[:8], "ACNT_PRDT_CD": acc_no[-2:],
            "PDNO": code, 
            "ORD_DVSN": ord_dvsn, 
            "ORD_QTY": str(quantity), 
            "ORD_UNPR": ord_unpr  # 👈 여기가 핵심
        }
        
        if MODE == "REAL":
            hashkey = self.fetch_hashkey(body)
            if hashkey:
                headers["hashkey"] = hashkey
            else:
                return {'rt_cd': '9999', 'msg1': 'HashKey Generation Failed'}

        try:
            res = requests.post(url, headers=headers, json=body, timeout=5).json()
            return res
        except Exception as e:
            print(f"❌ 주문 전송 실패: {e}")
            return {'rt_cd': '9999', 'msg1': 'Timeout/Error'}

# ==============================================================================
# 3. 봇 메인 로직 (TradingBot)
# ==============================================================================
class TradingBot:
    def __init__(self):
        self.api = KisApi()
        self.reverse_theme_map = {} 
        self.portfolio = {}

        self.is_buy_active = True  # 매수 활성화 여부 (기본 True)
        self.last_update_id = 0    # 마지막으로 처리한 텔레그램 메시지 ID
        
        # 🧠 [블랙리스트 구조 변경] Dictionary로 변경하여 수급 추적 데이터 저장
        # Key: Code, Value: {'reason': str, 'min_pg_amt': int, 'sell_time': datetime}
        self.blacklist = {} 
        
        self.is_running = True
        self.market_open_time = None 
        
        # 테마 및 일일 제한 관리
        self.locked_leaders_time = {}      
        self.daily_buy_cnt = {'MORNING': 0, 'THEME': 0, 'PROGRAM': 0}
        self.bought_themes = set()         
        self.missing_counts = {}
        
        self.last_summary_time = 0

    def load_theme_map(self):
        print(f"📥 [{MODE}] 테마 데이터 로딩 중...")
        try:
            dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-2')
            table = dynamodb.Table('StockThemeGroups')
            resp = table.get_item(Key={'date': 'today_map'})
            if 'Item' in resp:
                theme_data = json.loads(resp['Item']['data'])
                self.reverse_theme_map = {}
                count = 0
                for theme, codes in theme_data.items():
                    for code in codes:
                        if code not in self.reverse_theme_map:
                            self.reverse_theme_map[code] = []
                        if theme not in self.reverse_theme_map[code]:
                            self.reverse_theme_map[code].append(theme)
                        count += 1
                telegram_notifier.send_telegram_message(f"✅ [{MODE}] 테마 로드 완료 ({count}개 관계 매핑)")
            else:
                print("⚠️ DB 데이터 없음.")
        except Exception as e:
            telegram_notifier.send_telegram_message(f"❌ 테마 로드 실패: {e}")

    def get_current_slots_used(self):
        total_slots = 0
        for info in self.portfolio.values():
            level = info.get('pyramid_level', 0)
            total_slots += (level + 1)
        return total_slots

    def get_pg_milestone_index(self, amount):
        for i, milestone in enumerate(BotConfig.PG_MILESTONES):
            if amount < milestone:
                return i - 1 
        return len(BotConfig.PG_MILESTONES) - 1

    def monitor_portfolio(self):
        print("🕵️ 시장 개장 감시 시작...")

        # ==============================================================================
        # [1단계] 초기화 & 긴급 복구 (재시작 시 기억 되찾기)
        # ==============================================================================
        try:
            # [수정 1] 함수 이름 변경 (fetch_my_stock -> fetch_my_stock_list)
            # 이 함수는 { '005930': {'name':..., 'qty':...}, ... } 형태의 딕셔너리를 반환합니다.
            my_stocks = self.api.fetch_my_stock_list()
            
            current_codes = []
            
            # [수정 2] 딕셔너리 처리 방식으로 변경
            if my_stocks:
                for code, info in my_stocks.items():
                    name = info['name']
                    qty = info['qty']
                    price = info['price']
                    current_codes.append(code)
                    
                    # 메모리에 없으면 새로 등록
                    if code not in self.portfolio:
                        self.portfolio[code] = {
                            'name': name,
                            'qty': qty,
                            'buy_price': price,
                            'buy_time': datetime.datetime.now(),
                            'strategy': 'UNKNOWN', # 재시작되면 전략은 모름 (상관없음)
                            'stats_max_price': price, # 통계 데이터 초기화
                            'stats_min_price': price,
                            'stats_max_pg': 0,
                            'stats_entry_pg': 0,
                            'candle_memory': { # 👈 필수 추가
                                'history': [],
                                'current': None,
                                'last_bucket': None
                            }
                        }
                        print(f"♻️ [기억복구] {name} 보유 내역 복원 완료")

            # 실제로는 없는데 메모리에만 남은 유령 종목 삭제
            keys_to_delete = [k for k in self.portfolio.keys() if k not in current_codes]
            for k in keys_to_delete:
                del self.portfolio[k]
                
            print(f"✅ [동기화완료] 현재 보유 종목: {len(self.portfolio)}개")
            
        except Exception as e:
            print(f"⚠️ [초기화실패] 잔고 동기화 중 오류: {e}")

        # ==============================================================================
        # [2단계] 메인 루프 시작 (여기서 sync_counter 정의)
        # ==============================================================================
        sync_counter = 0  # 👈 타이머 0으로 맞춤 (필수!)
        while self.is_running:
            sync_counter += 1
            if sync_counter >= 10:
                real_holdings = self.api.fetch_my_stock_list()
                
                if real_holdings is not None:
                    # [A] 봇 -> 계좌 확인
                    for my_code in list(self.portfolio.keys()):
                        buy_time = self.portfolio[my_code].get('buy_time')
                        if buy_time:
                            elapsed = (datetime.datetime.now() - buy_time).total_seconds()
                            if elapsed < 10: continue

                        bot_qty = self.portfolio[my_code]['qty']
                        
                        if my_code not in real_holdings:
                            self.missing_counts[my_code] = self.missing_counts.get(my_code, 0) + 1
                            if self.missing_counts[my_code] >= 3:
                                telegram_notifier.send_telegram_message(f"🗑️ [수동매도 감지] {self.portfolio[my_code]['name']} 포트폴리오 삭제 (최종)")
                                self.blacklist[my_code] = {
                                    'reason': 'MANUAL_SELL', # 사유 명시
                                    'min_pg_amt': 999999999999, # 수동매도는 웬만하면 재진입 안 하게 높은 값 설정 (선택사항)
                                    'sell_time': datetime.datetime.now() # 팔린 시간 기록 (쿨타임 적용용)
                                }
                                del self.portfolio[my_code]
                                del self.missing_counts[my_code]
                            continue
                        else:
                            if my_code in self.missing_counts:
                                del self.missing_counts[my_code]
                        
                        real_qty = real_holdings[my_code]['qty']
                        if real_qty < bot_qty:
                            diff = bot_qty - real_qty
                            self.portfolio[my_code]['qty'] = real_qty
                            telegram_notifier.send_telegram_message(f"📉 [수량감소 감지] {self.portfolio[my_code]['name']} -{diff}주 반영")

                    # [B] 계좌 -> 봇 확인
                    for real_code, info in real_holdings.items():
                        if real_code not in self.portfolio and real_code not in self.blacklist:
                            self.portfolio[real_code] = {
                                'name': info['name'],
                                'qty': info['qty'],
                                'buy_price': info['price'],
                                'leader': None,
                                'leader_name': 'Unknown',
                                'strategy': 'RECOVERED',
                                'leader_was_locked': False,
                                'max_profit_rate': 0.0,
                                'has_partial_sold': False,
                                'buy_time': datetime.datetime.now(),
                                'pyramid_level': 0,
                                'reference_price': info['price'],
                                'max_pg_amt': 0, # 복구 시 수급 기록 초기화
                                'candle_memory': {
                                    'history': [],
                                    'current': None,
                                    'last_bucket': None
                                }
                            }
                            telegram_notifier.send_telegram_message(f"♻️ [보유종목 복구] {info['name']} ({info['qty']}주) 다시 관리 시작합니다.")
                
                sync_counter = 0

            if not self.portfolio:
                time.sleep(0.1)
                continue
            
            codes_to_sell = [] 
            for my_code in list(self.portfolio.keys()):
                info = self.portfolio[my_code]
                strategy = info['strategy']
                ref_price = info.get('reference_price', info['buy_price'])
                
                # [전략별 특수 매도 조건]
                if strategy == 'THEME':
                    leader_code = info['leader']
                    leader_info = self.api.fetch_price_detail(leader_code, info.get('leader_name', "Unknown"))
                    if leader_info and leader_info['max_price'] > 0:
                        if leader_info['price'] < leader_info['max_price']:
                             codes_to_sell.append((my_code, f"🚨대장주({leader_info['name']}) 상풀림/이탈"))
                             continue

                my_info = self.api.fetch_price_detail(my_code, info['name'])
                if my_info:
                    cur_price = my_info['price']
                    pg_amt = my_info['program_buy'] * cur_price

                    # 🛡️ [안전장치 1] 포트폴리오 딕셔너리에 키가 없으면 빈 껍데기 생성
                    if my_code not in self.portfolio:
                        print(f"⚠️ [메모리동기화] {my_info['name']}({my_code}) 봇 메모리에 재등록")
                        self.portfolio[my_code] = {
                            'name': my_info['name'],
                            'qty': 0, # 잔고조회로 업데이트될 예정
                            'buy_price': 0,
                            'buy_time': datetime.datetime.now(),
                            # 필요한 초기값들...
                        }

                    # 🛡️ [안전장치 2] 그 다음 통계 필드 확인 (기존 코드)
                    if 'stats_max_price' not in self.portfolio[my_code]:
                        self.portfolio[my_code]['stats_max_price'] = cur_price
                        self.portfolio[my_code]['stats_min_price'] = cur_price
                        self.portfolio[my_code]['stats_max_pg'] = pg_amt
                        self.portfolio[my_code]['stats_entry_pg'] = pg_amt
                        if 'buy_time_dt' not in self.portfolio[my_code]:
                            self.portfolio[my_code]['buy_time_dt'] = datetime.datetime.now()
                        print(f"🔧 [데이터복구] {info['name']} 통계 필드 초기화 완료")

                    # 👇 [추가] 분석용 데이터 갱신 (High/Low/MaxPG 추적)
                    if cur_price > self.portfolio[my_code]['stats_max_price']:
                        self.portfolio[my_code]['stats_max_price'] = cur_price
                    if cur_price < self.portfolio[my_code]['stats_min_price']:
                        self.portfolio[my_code]['stats_min_price'] = cur_price

                    # 수급 고점 갱신 (기존 로직과 별도로 통계용으로도 관리)
                    if pg_amt > self.portfolio[my_code]['stats_max_pg']:
                        self.portfolio[my_code]['stats_max_pg'] = pg_amt

                    logic_profit_rate = (cur_price - ref_price) / ref_price
                    
                    # 📉 [수급 이탈 감지 매도] - 보유 중 최고 수급 대비 30% 하락 시 매도
                    if strategy == 'PROGRAM':
                        current_max_pg = info.get('max_pg_amt', 0)
                        if pg_amt > current_max_pg:
                            self.portfolio[my_code]['max_pg_amt'] = pg_amt
                            current_max_pg = pg_amt
                    
                        # 최고점 대비 15% 이상 빠지면 이탈로 간주
                        if current_max_pg > 0 and pg_amt < current_max_pg * (1 - BotConfig.PG_DROP_RATE_TRIGGER):
                            codes_to_sell.append((my_code, f"📉수급이탈({pg_amt/100000000:.0f}억 < Max {current_max_pg/100000000:.0f}억)"))
                            continue

                        # ----------------------------------------------------------
                        # 🔥 [추가] 5분봉 추세 하락 손절 로직 (Trend Follow-down)
                        # ----------------------------------------------------------
                        now_time = datetime.datetime.now()
                        check_n = 0       # 확인할 5분봉 개수
                        threshold = 0     # 손절 기준 음봉 개수
                        
                        # [오전장] 09:00 ~ 11:30 (30분 감시 / 음봉 4개)
                        if 9 <= now_time.hour < 11 or (now_time.hour == 11 and now_time.minute < 30):
                            check_n = 6
                            threshold = 4
                        # [오후장] 11:30 ~ 15:20 (60분 감시 / 음봉 8개)
                        elif (now_time.hour == 11 and now_time.minute >= 30) or (12 <= now_time.hour < 15) or (now_time.hour == 15 and now_time.minute <= 20):
                            check_n = 12
                            threshold = 8
                        
                        # ----------------------------------------------------------
                        # 🔥 [수정됨] 5분봉 추세 하락 손절 로직 (메모리 기반)
                        # ----------------------------------------------------------
                        # 1. 실시간 현재가로 메모리 상의 5분봉 업데이트
                        self.update_candle_memory(my_code, cur_price)
                        
                        cand_mem = self.portfolio[my_code]['candle_memory']
                        # 과거 기록 + 현재 만들어지고 있는 봉을 합쳐서 분석
                        history = cand_mem['history'] 
                        
                        # 감시 시간대 및 기준 설정
                        now_time = datetime.datetime.now()
                        check_n = 0       
                        threshold = 0     
                        
                        # [오전장] 09:00 ~ 11:30 (30분 감시 / 음봉 4개)
                        if 9 <= now_time.hour < 11 or (now_time.hour == 11 and now_time.minute < 30):
                            check_n = 6
                            threshold = 4
                        # [오후장] 11:30 ~ 15:20 (60분 감시 / 음봉 8개)
                        elif (now_time.hour == 11 and now_time.minute >= 30) or (12 <= now_time.hour < 15) or (now_time.hour == 15 and now_time.minute <= 20):
                            check_n = 12
                            threshold = 8
                        
                        # 데이터가 충분히 쌓였을 때만 체크
                        if check_n > 0 and len(history) >= check_n:
                            # 최근 N개만 가져오기 (리스트의 뒤쪽이 최신 데이터임에 주의!)
                            target_candles = history[-check_n:]
                            
                            bearish_count = 0
                            
                            # 과거 봉부터 순서대로 비교 
                            # (i가 커질수록 최신 데이터)
                            for i in range(1, len(target_candles)):
                                prev_candle = target_candles[i-1] # 직전 봉 (과거)
                                curr_candle = target_candles[i]   # 현재 봉 (최신)
                                
                                # 조건 1: 음봉인가? (시가 > 종가)
                                is_bearish = curr_candle['open'] > curr_candle['close']
                                
                                # 조건 2: 종가가 직전 봉보다 낮은가? (하락세)
                                is_lower_close = curr_candle['close'] < prev_candle['close']
                                
                                if is_bearish and is_lower_close:
                                    bearish_count += 1
                                    
                            # 추세 하락 확인 (가장 오래된 봉의 시가 vs 현재가 비교)
                            first_open = target_candles[0]['open']
                            last_close = target_candles[-1]['close']
                            
                            if bearish_count >= threshold and last_close < first_open:
                                reason = f"📉추세이탈(메모리봉: {check_n}개중 {bearish_count}개 음봉)"
                                codes_to_sell.append((my_code, reason))
                                continue

                    # 상한가 감지
                    if cur_price >= my_info['max_price']:
                        codes_to_sell.append((my_code, f"🚀상한가 도달(VI) 전량익절"))
                        continue

                    # 트레일링 스탑
                    current_max = info.get('max_profit_rate', 0.0)
                    if logic_profit_rate > current_max:
                        self.portfolio[my_code]['max_profit_rate'] = logic_profit_rate
                        current_max = logic_profit_rate

                    total_ask = my_info['total_ask']
                    total_bid = my_info['total_bid']
                    dynamic_gap = BotConfig.TS_STOP_GAP
                    
                    if total_ask > 0 and total_bid > total_ask * 2.0: 
                        dynamic_gap = 0.01 
                        status_msg = "⚠️호가불안"
                    else:
                        status_msg = "이격정상"
                    
                    if current_max >= BotConfig.TS_TRIGGER_RATE:
                        trailing_stop_line = current_max - dynamic_gap
                        if logic_profit_rate <= trailing_stop_line:
                            reason = (f"🎢트레일링 스탑\n"
                                      f"기준: {ref_price:,.0f}원\n"
                                      f"최고: {current_max*100:.1f}% / 현재: {logic_profit_rate*100:.1f}%\n"
                                      f"{status_msg} (Gap: {dynamic_gap*100:.0f}%)")
                            codes_to_sell.append((my_code, reason))
                            continue 

                    # 본전 이탈
                    if info.get('has_partial_sold', False) and current_max < BotConfig.TS_TRIGGER_RATE and logic_profit_rate <= 0.0:
                        codes_to_sell.append((my_code, "📉본전 이탈(익절 후 반납)"))
                        continue
                    
                    # --- [추가] 시간 손절 로직 ---
                    if 'buy_time' in info:
                        # 현재 시간과 매수 시간 차이 계산 (분 단위)
                        elapsed_min = (datetime.datetime.now() - info['buy_time']).total_seconds() / 60
                        
                        # 설정한 시간이 지났고, 수익률이 본전(0%) 이하일 때
                        if elapsed_min >= BotConfig.TIME_STOP_MINUTES and logic_profit_rate <= BotConfig.TIME_STOP_PROFIT:
                            codes_to_sell.append((my_code, f"⏳시간손절({BotConfig.TIME_STOP_MINUTES}분 경과/본전미달)"))
                            continue

                    # ----------------------------------------------------------
                    # ✅ [수정] 전략별 손절 기준 차등 적용
                    # ----------------------------------------------------------
                    target_stop_loss = BotConfig.STOP_LOSS_RATE # 기본값: -2% (-0.02)
                    
                    # 모닝 전략은 변동성이 크므로 손절을 짧게 -1%로 설정
                    if strategy == 'MORNING':
                        target_stop_loss = -0.01

                    # 손절
                    if logic_profit_rate <= target_stop_loss:
                        codes_to_sell.append((my_code, f"📉손절선 이탈({logic_profit_rate*100:.2f}%)"))
                        continue

                    # 부분 익절
                    if not info.get('has_partial_sold', False) and logic_profit_rate >= BotConfig.PARTIAL_PROFIT_RATE:
                        sell_qty = int(info['qty'] * BotConfig.PARTIAL_SELL_RATIO)

                        # ==============================================================================
                        # ✅ [수정] 1주만 보유하여 반절 매도가 불가능한 경우(0주) -> 전량 익절 처리
                        # ==============================================================================
                        if sell_qty == 0 and info['qty'] > 0:
                            # codes_to_sell 리스트에 담으면 루프 끝에서 sell_stock 함수가 호출되어
                            # 전량 매도, 로그 기록, 블랙리스트 등록까지 깔끔하게 처리됩니다.
                            codes_to_sell.append((my_code, f"💰소액/잔량({info['qty']}주) 2% 목표달성 전량익절"))
                            continue
                        # ==============================================================================
                        
                        if sell_qty > 0:
                            res = self.api.send_order(my_code, sell_qty, is_buy=False)
                            if res['rt_cd'] == '0':
                                self.portfolio[my_code]['qty'] -= sell_qty
                                self.portfolio[my_code]['has_partial_sold'] = True
                                msg = (f"💰 [{MODE} 부분익절] {info['name']}\n"
                                       f"기준가: {ref_price:,.0f}원\n"
                                       f"수익률: {logic_profit_rate*100:.2f}% 돌파\n"
                                       f"매도가: {cur_price:,}원\n"
                                       f"매도량: {sell_qty}주 / 잔여: {self.portfolio[my_code]['qty']}주")
                                telegram_notifier.send_telegram_message(msg)
                                continue 

            for code, reason in codes_to_sell:
                self.sell_stock(code, reason)
            
            # 블랙리스트에 있는 종목들의 '수급 저점' 추적 (반등 감지용)
            for b_code, b_info in list(self.blacklist.items()):
                if b_info.get('reason') == 'PG_DROP': # 수급 이탈로 판 종목만 추적
                    b_market_info = self.api.fetch_price_detail(b_code)
                    if b_market_info:
                        current_pg = b_market_info['program_buy'] * b_market_info['price']
                        # 더 떨어지면 최저점 갱신
                        if current_pg < b_info['min_pg_amt']:
                            self.blacklist[b_code]['min_pg_amt'] = current_pg

            time.sleep(0.1)

    # 🔄 [매수 실행 함수] (수정됨)
    def execute_buy(self, stock, theme, leader_stock, strategy_type, add_on_level=None):
        # 1. [원격 제어] 매수 정지 상태면 즉시 리턴 (변수 필요 없음)
        if not self.is_buy_active:
            print(f"⛔ [매수정지중] 매수 스킵")
            return

        # 2. [정보 추출] 종목 코드와 상세 정보 먼저 확보
        if 'price' in stock:
            info = stock
        else:
            info = self.api.fetch_price_detail(stock['code'], stock['name'])
        
        if not info: return
        
        code = stock.get('code', stock.get('stck_shrn_iscd', None))
        if not code and 'code' in info:
            code = info['code']
            
        if not code: return

        # 3. [변수 정의] 이제 is_add_on을 계산할 수 있음
        is_add_on = (add_on_level is not None) and (code in self.portfolio)

        # 4. [슬롯 체크] is_add_on이 정의된 후에 체크해야 함!
        if not is_add_on and self.get_current_slots_used() >= BotConfig.MAX_GLOBAL_SLOTS:
            print("🚫 [슬롯초과] 신규 매수 거부")
            return

        # ------------------------------------------------------------------
        # 이하 기존 로직 동일 (주문 실행)
        # ------------------------------------------------------------------
        total_asset = self.api.fetch_balance()
        invest_amount = int(total_asset * BotConfig.INVEST_RATIO)
        
        # [추가 수정] 3억 이상 운용 시 한도 제한 (선택사항, 필요 없으면 주석 처리)
        # invest_amount = min(invest_amount, 30_000_000) 
        
        qty = 0
        if info['price'] > 0: qty = int(invest_amount / info['price'])

        action_msg = f"🔥불타기(Lv.{add_on_level})" if is_add_on else "신규매수"
        print(f"🛒 [주문시도] {info['name']} ({strategy_type}/{action_msg})")

        if qty > 0:
            # ✅ 매수 시 '매도 1호가(ask_price_1)'로 지정가 주문
            # (만약 호가 정보가 없으면 현재가(price)를 대신 사용)
            target_price = info.get('ask_price_1', info['price'])

            # 가격이 0이면 현재가 사용
            if target_price == 0: target_price = info['price']

            res = self.api.send_order(code, qty, price=target_price, is_buy=True)

            if res['rt_cd'] == '0':
                
                leader_name = leader_stock['name'] if leader_stock else "없음"
                leader_code = leader_stock['code'] if leader_stock else None
                leader_rate_str = ""
                is_locked = False
                
                if leader_code:
                    l_info = self.api.fetch_price_detail(leader_code, leader_name)
                    if l_info:
                        if l_info['price'] >= l_info['max_price']: is_locked = True
                        leader_current_rate = l_info['rate']
                    else:
                        leader_current_rate = leader_stock['rate']
                    leader_rate_str = f"(👑{leader_name} +{leader_current_rate:.2f}%)"

                buy_rate = info['rate']
                
                if not is_add_on:
                    if strategy_type in self.daily_buy_cnt:
                        self.daily_buy_cnt[strategy_type] += 1
                
                # 패자부활 성공 -> 블랙리스트 해제
                # if code in self.blacklist:
                    # del self.blacklist[code]
                    # print(f"✨ [패자부활] {info['name']} 블랙리스트 해제")

                # 👇 [.get]으로 안전하게 변경
                prog_qty = info.get('program_buy', 0) 
                pg_amt_now = prog_qty * info['price']

                # ✅ [금액 포맷팅] 억 단위로 변환 (예: 15300000000 -> 153억)
                pg_amt_str = f"{pg_amt_now // 100000000}억" if abs(pg_amt_now) >= 100000000 else f"{pg_amt_now // 1000000}백만"

                if is_add_on:
                    old_qty = self.portfolio[code]['qty']
                    old_price = self.portfolio[code]['buy_price']
                    
                    new_total_qty = old_qty + qty
                    new_avg_price = ((old_qty * old_price) + (qty * info['price'])) / new_total_qty
                    
                    # 리셋: 불타기 가격 기준
                    self.portfolio[code]['reference_price'] = info['price'] 
                    self.portfolio[code]['max_profit_rate'] = 0.0 
                    self.portfolio[code]['has_partial_sold'] = False
                    self.portfolio[code]['max_pg_amt'] = pg_amt_now 

                    self.portfolio[code]['qty'] = new_total_qty
                    self.portfolio[code]['buy_price'] = new_avg_price
                    self.portfolio[code]['pyramid_level'] = add_on_level
                    self.portfolio[code]['buy_time'] = datetime.datetime.now()
                    
                    msg = (f"🔥🔥 [{MODE} 불타기 Lv.{add_on_level}] {info['name']}\n"
                           f"➕ 추가: {qty}주 / 총: {new_total_qty}주\n"
                           f"📊 PG수급: {prog_qty:,}주 ({pg_amt_str})\n"  # 👈 [수정됨] 금액 추가
                           f"평단가: {old_price:,.0f}원 → {new_avg_price:,.0f}원\n"
                           f"🛑 리셋기준가: {info['price']:,.0f}원")
                else:
                    strategy_msg_map = {
                        'THEME': f"🔗 테마: {theme}\n👑 대장: {leader_name} {leader_rate_str}",
                        'PROGRAM': f"🤖 프로그램 매수 포착",
                        'MORNING': f"☀️ 모닝 급등 포착"
                    }
                    detail_msg = strategy_msg_map.get(strategy_type, "")

                    msg = (f"⚡ [{MODE} 신규매수] {info['name']}\n"
                           f"{detail_msg}\n"
                           f"💰 매수가: {info['price']:,}원 (+{buy_rate}%)\n"
                           f"📊 PG수급: {prog_qty:,}주 ({pg_amt_str})\n"  # 👈 [수정됨] 금액 추가
                           f"📦 수량: {qty}주\n"
                           f"📊 전략: {strategy_type}")

                    self.portfolio[code] = {
                        'name': info['name'],
                        'qty': qty,
                        'buy_price': info['price'],
                        'reference_price': info['price'], 
                        'leader': leader_code,
                        'leader_name': leader_name,
                        'strategy': strategy_type,
                        'leader_was_locked': is_locked,
                        'max_profit_rate': 0.0,
                        'has_partial_sold': False,
                        'buy_time': datetime.datetime.now(),
                        'pyramid_level': add_on_level if add_on_level is not None else 0,
                        'max_pg_amt': pg_amt_now,
                        
                        # ✅ [추가] 5분봉 직접 만들기용 메모리 공간
                        'candle_memory': {
                            'history': [],       # 완성된 5분봉 저장소
                            'current': None,     # 현재 만들어지고 있는 봉
                            'last_bucket': None  # 현재 봉의 시간대 (예: 10:05)
                        },

                        # 분석용 데이터
                        'stats_entry_pg': pg_amt_now,      
                        'stats_max_pg': pg_amt_now,        
                        'stats_max_price': info['price'],  
                        'stats_min_price': info['price'],  
                        'buy_time_dt': datetime.datetime.now() 
                    }

                    # 매수 로그 기록
                    trade_logger.log_buy({
                        'code': code, 'name': info['name'],
                        'strategy': strategy_type, 'level': add_on_level,
                        'price': info['price'], 'qty': qty,
                        'pg_amt': pg_amt_now, 'gap': info.get('rate', 0),
                        'leader': leader_name
                    })

                    if strategy_type == 'THEME': self.bought_themes.add(theme)

                telegram_notifier.send_telegram_message(msg)
            else:
                print(f"❌ [API오류] 주문 전송 실패: {res}")
        else:
            print(f"❌ [매수실패] {info['name']} 매수 수량 0 (예수금 부족)")

    # def liquidate_all_positions(self):
    #     if not self.portfolio: return
    #     telegram_notifier.send_telegram_message(f"⏰ [{MODE}] 장 마감 전량 청산")
    #     for code in list(self.portfolio.keys()):
    #         self.sell_stock(code, "장 마감(Time-Cut)")

    def liquidate_all_positions(self, reason="장 마감(Time-Cut)"): # 기본값 설정
        if not self.portfolio: 
            return
        
        # 전달받은 사유에 따라 텔레그램 첫 메시지 변경
        msg_header = "🚨 [원격제어] 긴급 전량 매도 실행" if "원격" in reason else f"⏰ [{MODE}] 장 마감 전량 청산"
        telegram_notifier.send_telegram_message(msg_header)
    
        for code in list(self.portfolio.keys()):
            self.sell_stock(code, reason) # 개별 종목 매도 사유로 전달
            
    def wait_until_next_morning(self):
        now = datetime.datetime.now()
        tomorrow = now + datetime.timedelta(days=1)
        next_morning = datetime.datetime(tomorrow.year, tomorrow.month, tomorrow.day, 8, 50, 0)
        
        wait_seconds = (next_morning - now).total_seconds()
        if wait_seconds > 0:
            msg = f"💤 [{MODE}] 장 종료. 내일 08:50 대기."
            telegram_notifier.send_telegram_message(msg)
            self.portfolio = {}
            self.blacklist = {} # Dict 초기화
            self.daily_buy_cnt = {'MORNING': 0, 'THEME': 0, 'PROGRAM': 0}
            
            self.bought_themes = set()
            self.locked_leaders_time = {}
            self.missing_counts = {}
            
            self.market_open_time = None
            time.sleep(wait_seconds)
            telegram_notifier.send_telegram_message(f"☀️ [{MODE}] 봇 기상! 시장 개장 감시 시작.")

    def wait_for_market_open(self):
        print("🕵️ 시장 개장 감시 시작 (삼성전자 거래량 감시)...")
        while True:
            now = datetime.datetime.now()
            if now.weekday() >= 5:
                telegram_notifier.send_telegram_message("⛔ 주말입니다. 대기 모드 진입.")
                self.wait_until_next_morning()
                return False
            if self.api.check_holiday(now.strftime("%Y%m%d")):
                telegram_notifier.send_telegram_message("⛔ 오늘은 휴장일입니다.")
                self.wait_until_next_morning()
                return False
            if now.hour == 8 and now.minute < 45:
                time.sleep(1) 
                continue

            ref_data = self.api.fetch_price_detail(BotConfig.PROBE_STOCK_CODE)
            vol = ref_data.get('acml_vol', 0) if ref_data else 0
            
            if now.hour == 8 and now.minute >= 45:
                if vol == 0:
                    print(f"   [08:{now.minute}] 거래량 0 (지연 개장 가능성 높음)")
                    time.sleep(30)
                else:
                    print(f"   [08:{now.minute}] 장전 거래량 포착({vol:,}). 09:00 정상 개장 대기.")
                    time.sleep(10)
                continue
            if now.hour == 9:
                if vol > 0:
                    self.market_open_time = now
                    telegram_notifier.send_telegram_message(f"🔔 [정상 개장] 09:00 Market Open!\n(Vol: {vol:,})")
                    return True
                else:
                    if now.minute >= 5:
                        telegram_notifier.send_telegram_message("💤 지연 개장 확인 (Vol=0). 10:00까지 대기합니다.")
                        target_time = datetime.datetime(now.year, now.month, now.day, 9, 59, 50)
                        sleep_sec = (target_time - datetime.datetime.now()).total_seconds()
                        if sleep_sec > 0:
                            time.sleep(sleep_sec)
                        continue
                    else:
                        time.sleep(5)
                        continue
            if 10 <= now.hour < 15:
                self.market_open_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
                telegram_notifier.send_telegram_message(f"🔔 [지연/정상] 10:00 Market Active.\n(Vol: {vol:,})")
                return True
            time.sleep(1)
            
    def sell_stock(self, code, reason):
        if code in self.portfolio:
            qty = self.portfolio[code]['qty']
            cur_price = 0
            
            temp_info = self.api.fetch_price_detail(code)

            # 2. 실패 시 1번 더 재시도 (0.2초 대기)
            if not temp_info:
                time.sleep(0.2)
                temp_info = self.api.fetch_price_detail(code)

            pg_amt_at_sell = 0

            current_pg_qty = 0  
            pg_amt_now = 0

            if temp_info: 
                cur_price = temp_info['price']
                pg_amt_at_sell = temp_info['program_buy'] * temp_info['price']
                current_pg_qty = temp_info.get('program_buy', 0) # 수량 가져오기
                pg_amt_now = current_pg_qty * cur_price # 금액 계산
            else:
                # API 실패 시: 현재가는 0으로 두되, 로그에 남김
                cur_price = 0 
                print(f"⚠️ {code} 매도 시세 조회 실패 -> 가격 0원으로 기록됨")

            pg_amt_str = f"{pg_amt_now // 100000000}억" if abs(pg_amt_now) >= 100000000 else f"{pg_amt_now // 1000000}백만"

            res = self.api.send_order(code, qty, is_buy=False)
            if res['rt_cd'] == '0':
                name = self.portfolio[code]['name']
                buy_price = self.portfolio[code]['buy_price']
                profit_rate = 0.0
                if buy_price > 0 and cur_price > 0:
                    profit_rate = (cur_price - buy_price) / buy_price * 100
                msg = (f"👋 [{MODE} 매도] {name}\n"
                       f"사유: {reason}\n"
                       f"매도가: {cur_price:,}원 ({profit_rate:+.2f}%)\n"
                       f"📊 PG수급: {current_pg_qty:,}주 ({pg_amt_str})\n"
                       f"수량: {qty}주")
                telegram_notifier.send_telegram_message(msg)
                print(msg)
                # ... (주문 전송 로직) ...

                # API 주문 후 성공했다고 가정하고 로그 기록 (혹은 res['rt_cd'] == '0' 내부로 이동 가능)

                # 👇 [추가] 통계 데이터 추출
                p_data = self.portfolio[code]
                cur_price = temp_info['price'] if temp_info else 0
                exit_pg = temp_info['program_buy'] * temp_info['price'] if temp_info else 0

                # 보유 시간 계산 (분 단위)
                hold_min = 0
                if 'buy_time_dt' in p_data:
                    hold_min = int((datetime.datetime.now() - p_data['buy_time_dt']).total_seconds() / 60)

                trade_logger.log_sell({
                    'code': code, 'name': p_data['name'],
                    'strategy': p_data['strategy'], 'reason': reason,
                    'buy_price': p_data['buy_price'],
                    'sell_price': cur_price,
                    'qty': p_data['qty'],
                    'hold_time_min': hold_min,
                    # 추적해온 데이터 기록
                    'max_price': p_data.get('stats_max_price', 0),
                    'min_price': p_data.get('stats_min_price', 0),
                    'entry_pg': p_data.get('stats_entry_pg', 0),
                    'max_pg': p_data.get('stats_max_pg', 0),
                    'exit_pg': exit_pg
                })

                # ... (블랙리스트 처리 및 del portfolio 등 기존 로직) ...

                
                # 블랙리스트 등록 (수급 이탈 추적용 데이터 저장)
                bl_reason = 'PG_DROP' if '수급이탈' in reason else 'NORMAL'
                self.blacklist[code] = {
                    'reason': bl_reason,
                    'min_pg_amt': pg_amt_at_sell, # 매도 시점의 수급을 초기 저점으로 설정
                    'sell_time': datetime.datetime.now()
                }
                
                del self.portfolio[code]

    # 📡 [신규] 텔레그램 명령 처리 쓰레드 함수
    def telegram_listener(self):
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates"
        
        while self.is_running:
            try:
                # 롱폴링 (timeout=10초 대기)
                params = {'offset': self.last_update_id + 1, 'timeout': 10}
                res = requests.get(url, params=params, timeout=15)
                
                if res.status_code == 200:
                    data = res.json()
                    if not data['ok']: continue

                    for update in data['result']:
                        self.last_update_id = update['update_id']
                        
                        if 'message' not in update or 'text' not in update['message']:
                            continue
                            
                        text = update['message']['text'].strip()
                        chat_id = str(update['message']['chat']['id'])
                        
                        # 내 채팅방 명령만 허용
                        if str(chat_id) != str(config.TELEGRAM_CHAT_ID):
                            continue

                        # === 명령어 처리 로직 ===
                        if text == '/info' or text == 'info':
                            balance = self.api.fetch_balance()
                            msg = f"📊 [현재 상태]\n💰 잔고: {balance:,}원\n🛑 매수활성: {'ON' if self.is_buy_active else 'OFF'}\n\n[보유 종목]"
                            if not self.portfolio:
                                msg += "\n없음"
                            else:
                                for c, v in self.portfolio.items():
                                    rate = v.get('max_profit_rate', 0) * 100
                                    msg += f"\n- {v['name']}: {v['qty']}주 (최고 {rate:.1f}%)"
                            telegram_notifier.send_telegram_message(msg)

                        elif text == '/stop' or text == 'stop':
                            self.is_buy_active = False
                            telegram_notifier.send_telegram_message("⛔ [원격제어] 매수 정지! (보유종목 관리는 계속됨)")

                        elif text == '/start' or text == 'start':
                            self.is_buy_active = True
                            telegram_notifier.send_telegram_message("🟢 [원격제어] 매수 재개!")

                        # elif text == '/sell' or text == 'sell':
                        #     telegram_notifier.send_telegram_message("🚨 [원격제어] 긴급 전량 매도 실행!")
                        #     self.liquidate_all_positions()

                        elif text == '/sell' or text == 'sell':
                            # 기존: self.liquidate_all_positions()
                            # 수정: 사유를 넘겨주어 메시지가 구분되게 함
                            self.liquidate_all_positions(reason="원격제어 긴급매도")

            except Exception as e:
                print(f"텔레그램 리스너 에러: {e}")
                time.sleep(5)

    # 🆕 [신규 추가] 실시간 현재가로 5분봉 만들기
    def update_candle_memory(self, code, current_price):
        if code not in self.portfolio: return
        
        mem = self.portfolio[code]['candle_memory']
        now = datetime.datetime.now()
        
        # 현재 시간의 5분 단위 버킷 계산 (예: 10시 13분 -> 10시 10분 버킷)
        minute_bucket = (now.minute // 5) * 5
        bucket_key = f"{now.hour:02d}{minute_bucket:02d}" # "1010" 형태
        
        # 1. 현재 봉이 없거나, 시간이 바뀌었으면 -> 새 봉 시작 (기존 봉은 history로 저장)
        if mem['last_bucket'] != bucket_key:
            # 기존에 만들던 봉이 있으면 history에 저장 (완성)
            if mem['current'] is not None:
                mem['history'].append(mem['current'])
                # history가 너무 길어지지 않게 최근 20개만 유지
                if len(mem['history']) > 20: 
                    mem['history'].pop(0)
            
            # 새 봉 초기화
            mem['current'] = {
                'open': current_price,
                'high': current_price,
                'low': current_price,
                'close': current_price,
                'time': bucket_key
            }
            mem['last_bucket'] = bucket_key
            
        # 2. 같은 시간대라면 -> 고가/저가/종가 갱신 (Update)
        else:
            c = mem['current']
            if current_price > c['high']: c['high'] = current_price
            if current_price < c['low']: c['low'] = current_price
            c['close'] = current_price # 종가는 항상 최신가
            # open은 건드리지 않음

    def run(self):

        # 1. 포트폴리오 감시 쓰레드 (기존)
        t_monitor = threading.Thread(target=self.monitor_portfolio)
        t_monitor.daemon = True
        t_monitor.start()
        
        # 2. [추가] 텔레그램 리스너 쓰레드 (신규)
        t_telegram = threading.Thread(target=self.telegram_listener)
        t_telegram.daemon = True
        t_telegram.start()
        
        telegram_notifier.send_telegram_message(f"🚀 Speed Demon [{MODE}] 봇 시작\n(명령어 대기중: info, stop, start, sell)")
        
        self.last_summary_time = 0

        while True:
            try:
                # ------------------------------------------------------
                # 감시 스레드가 죽었는지 확인 (is_alive가 False면 죽은 것)
                if not t_monitor.is_alive():
                    print("💀 [경고] 감시 스레드 사망 감지 -> 재시작(Resurrection) 실행")
                    t_monitor = threading.Thread(target=self.monitor_portfolio)
                    t_monitor.daemon = True
                    t_monitor.start()
                    telegram_notifier.send_telegram_message("♻️ [시스템] 감시 기능이 복구되었습니다.")

                # 텔레그램 스레드도 죽었는지 확인
                if not t_telegram.is_alive():
                    print("💀 [경고] 텔레그램 스레드 사망 감지 -> 재시작 실행")
                    t_telegram = threading.Thread(target=self.telegram_listener)
                    t_telegram.daemon = True
                    t_telegram.start()
                # ------------------------------------------------------
                # 👆👆 [여기까지 추가] 👆👆

                now = datetime.datetime.now()
                
                if now.hour > 15 or (now.hour == 15 and now.minute >= 15):
                    self.liquidate_all_positions()
                    self.wait_until_next_morning()
                    continue

                if self.market_open_time is None:
                    is_open = self.wait_for_market_open()
                    if not is_open: continue 
                    self.load_theme_map()
                
                elapsed = (datetime.datetime.now() - self.market_open_time).total_seconds()
                current_slots = self.get_current_slots_used()

                # 📥 [3-Track 리스트 수집]
                pg_list = self.api.fetch_condition_stocks("pg100")
                theme_list = self.api.fetch_condition_stocks("top100")
                morning_list = self.api.fetch_condition_stocks("hot100")

                if not pg_list and theme_list: pg_list = theme_list
                
                # 생존신고
                if time.time() - self.last_summary_time >= 60:
                    summary_msg = (f"💓 [생존신고] {now.strftime('%H:%M')} | Slots:{current_slots}/6 | "
                                   f"PG:{len(pg_list)} Theme:{len(theme_list)} Gap:{len(morning_list)}")
                    print(summary_msg)
                    self.last_summary_time = time.time()
                
                # ==================================================================
                # 🔥 [전략 3] 프로그램 자이언트
                # ==================================================================
                if current_slots < BotConfig.MAX_GLOBAL_SLOTS:
                    for item in pg_list:
                        code = item['stck_shrn_iscd']
                        name = item['hts_kor_isnm']
                        
                        if any(x in name for x in ["스팩", "ETN", "ETF", "리츠", "우B", "우(", "인버스", "레버리지", "선물", "채권"]) or name.endswith("우"):
                            continue

                        est_total_amt = item['price'] * item['vol']
                        if est_total_amt < (BotConfig.PG_LEVEL_0_AMT * 0.9): continue 
                        
                        # Case 1 & Case 2 공통 정보를 위해 미리 호출
                        info = self.api.fetch_price_detail(code, name)
                        if not info: continue
                        
                        pg_amt = info['program_buy'] * info['price']

                        # ----------------------------------------------------------
                        # ✅ 시간대별 프로그램 수급 필터 적용
                        # ----------------------------------------------------------
                        time_filter = 0
                        if (now.hour == 9 and now.minute < 30):
                            time_filter = BotConfig.PG_TIME_FILTER_0  # 50억
                        elif (now.hour == 9 and now.minute >= 30) or (now.hour < 11):
                            time_filter = BotConfig.PG_TIME_FILTER_1  # 200억
                        elif (now.hour >= 11 and now.hour < 13):
                            continue    # 매수금지
                        elif (now.hour >= 13 and now.hour < 15):
                            time_filter = BotConfig.PG_TIME_FILTER_1  # 200억
                        else: # 15시 이후
                            continue    # 매수금지
                        
                        # 해당 시간대 기준치에 미달하면 아예 매수 불가
                        if pg_amt < time_filter:
                            continue
                        # ----------------------------------------------------------

                        target_level = None
                        
                        # 0. 쿨타임 체크
                        if code in self.blacklist:
                            sell_time = self.blacklist[code].get('sell_time')
                            if sell_time and (now - sell_time).total_seconds() / 60 < BotConfig.REBUY_COOLTIME_MINUTES:
                                continue

                        # Case 1: 불타기
                        if code in self.portfolio:
                            continue
                            # current_level = self.portfolio[code].get('pyramid_level', 0)
                            
                            # info = self.api.fetch_price_detail(code, name)
                            # if not info: continue
                            
                            # pg_amt = info['program_buy'] * info['price']
                            # current_milestone_idx = self.get_pg_milestone_index(pg_amt)
                            
                            # if current_milestone_idx > current_level:
                                # target_level = current_milestone_idx
                            # else:
                                # continue 
                        
                        # Case 2: 신규 진입 or 패자부활
                        else:
                            info = self.api.fetch_price_detail(code, name)
                            if not info: continue
                            
                            pg_amt = info['program_buy'] * info['price']
                            
                            # [패자부활 로직]
                            if code in self.blacklist:
                                continue
                                # 저점 대비 15% 반등했는지 확인
                                # low_pg = self.blacklist[code].get('min_pg_amt', 0)
                                # if low_pg > 0 and pg_amt >= low_pg * (1 + BotConfig.PG_RISE_RATE_TRIGGER):
                                    # 단, 전체 금액이 100억(PG_LEVEL_0_AMT) 이상이어야 함
                                    # if pg_amt >= BotConfig.PG_LEVEL_0_AMT:
                                        # target_level = self.get_pg_milestone_index(pg_amt)
                                    # else:
                                        # continue
                                # else:
                                    # continue
                            # [완전 신규]
                            else:
                                if pg_amt >= BotConfig.PG_LEVEL_0_AMT:
                                    target_level = self.get_pg_milestone_index(pg_amt)
                                else:
                                    continue

                        if info['rate'] < BotConfig.GIANT_RATE_MIN: continue
                        if info['rate'] > BotConfig.GIANT_RATE_MAX: continue
                        if info['price'] < info['open']: continue
                        if info['wick_ratio'] >= BotConfig.MAX_WICK_RATIO: continue

                        # ✅ [추가됨] 호가 잔량 10억 이상 조건
                        # 매도총잔량(total_ask)과 매수총잔량(total_bid) 금액 계산
                        total_ask_val = info['total_ask'] * info['price']
                        total_bid_val = info['total_bid'] * info['price']
                        total_ask_bid = total_ask_val + total_bid_val

                        # 둘 중 하나라도 10억 미만이면 패스
                        # if total_ask_val < BotConfig.MIN_TOTAL_HOGA_AMT or total_bid_val < BotConfig.MIN_TOTAL_HOGA_AMT:
                        # 둘의 합이 10억 미만이면 패스
                        if total_ask_bid < BotConfig.MIN_TOTAL_HOGA_AMT:
                            continue
                        
                        self.execute_buy(info, "PROGRAM", None, 'PROGRAM', add_on_level=target_level)
                        
                        if self.get_current_slots_used() != current_slots: break

                current_slots = self.get_current_slots_used()

                # ==================================================================
                # 🔥 [전략 1] 모닝 급등주
                # ==================================================================
                if current_slots < BotConfig.MAX_GLOBAL_SLOTS:
                    if elapsed <= BotConfig.MORNING_MSG_WINDOW:
                        
                        if self.daily_buy_cnt['MORNING'] >= BotConfig.MAX_DAILY_MORNING:
                            pass 
                        else:
                            min_trade_vol = BotConfig.MORNING_VOL_LEVEL_3 
                            if elapsed <= 600: min_trade_vol = BotConfig.MORNING_VOL_LEVEL_1 
                            elif elapsed <= 1800: min_trade_vol = BotConfig.MORNING_VOL_LEVEL_2 
                            
                            valid_candidates = []
                            for item in morning_list:
                                code = item['stck_shrn_iscd']
                                name = item['hts_kor_isnm']
                                rate = item['prdy_ctrt']
                                
                                if code in self.blacklist or code in self.portfolio: continue 
                                
                                # 쿨타임 체크 (모닝 전략도 매도 후 바로 재진입 방지)
                                if code in self.blacklist:
                                    sell_time = self.blacklist[code].get('sell_time')
                                    if sell_time and (now - sell_time).total_seconds() / 60 < BotConfig.REBUY_COOLTIME_MINUTES: continue

                                if item['price'] < BotConfig.MIN_STOCK_PRICE: continue
                                est_trade_vol = item['price'] * item['vol']
                                if est_trade_vol < min_trade_vol: continue
                                
                                if not (BotConfig.MORNING_RATE_MIN <= rate <= BotConfig.MORNING_RATE_MAX): continue
                                if any(x in name for x in ["스팩", "ETN", "ETF", "리츠", "우B", "우(", "인버스", "레버리지", "선물", "채권"]) or name.endswith("우"): continue

                                valid_candidates.append({'code': code, 'name': name, 'rate': rate})

                            valid_candidates.sort(key=lambda x: x['rate'], reverse=True)
                            
                            for stock in valid_candidates:
                                if stock['code'] in self.blacklist or stock['code'] in self.portfolio: continue
                                
                                info = self.api.fetch_price_detail(stock['code'], stock['name'])
                                if not info or info['open'] == 0: continue
                                if info['wick_ratio'] >= BotConfig.MAX_WICK_RATIO: continue

                                ask_1_amount = info['price'] * info['ask_rsqn1']
                                bid_1_amount = info['price'] * info['bid_rsqn1']
                                if ask_1_amount < BotConfig.MIN_HOGA_AMT or bid_1_amount < BotConfig.MIN_HOGA_AMT: continue

                                prev_close = info['price'] / (1 + info['rate']/100)
                                gap_rate = (info['open'] - prev_close) / prev_close * 100
                                if not (BotConfig.MORNING_GAP_MIN <= gap_rate <= BotConfig.MORNING_GAP_MAX): continue
                                
                                pg_buy_qty = info['program_buy']
                                pg_buy_amt = pg_buy_qty * info['price']
                                
                                min_pg_amt = BotConfig.MORNING_PG_AMT_LATE
                                if elapsed <= 600:     
                                    min_pg_amt = BotConfig.MORNING_PG_AMT_10MIN 
                                elif elapsed <= 1800: 
                                    min_pg_amt = BotConfig.MORNING_PG_AMT_30MIN
                                
                                if elapsed <= 600:
                                    is_pg_good = (pg_buy_amt > 0)
                                else:
                                    is_pg_good = (pg_buy_amt >= min_pg_amt)
                                
                                is_ask_wall_good = 20.0 <= info['bid_ask_ratio'] <= 90.0
                                
                                if is_pg_good and is_ask_wall_good:
                                    self.execute_buy(stock, "모닝급등", None, 'MORNING')
                                    if self.get_current_slots_used() != current_slots: break
                        
                current_slots = self.get_current_slots_used()

                # ==================================================================
                # 🔥 [전략 2] 테마 짝짓기
                # ==================================================================
                if current_slots < BotConfig.MAX_GLOBAL_SLOTS:
                    if elapsed <= BotConfig.THEME_MSG_WINDOW:
                        
                        if self.daily_buy_cnt['THEME'] >= BotConfig.MAX_DAILY_THEME:
                            pass 
                        else:
                            theme_groups = {}
                            
                            for item in theme_list:
                                code = item['stck_shrn_iscd']
                                name = item['hts_kor_isnm']
                                rate = item['prdy_ctrt']
                                
                                if any(x in name for x in ["스팩", "ETN", "ETF", "리츠", "우B", "우(", "인버스", "레버리지", "선물", "채권"]) or name.endswith("우"): continue
                                
                                if code in self.reverse_theme_map:
                                    themes = self.reverse_theme_map[code]
                                    for theme in themes:
                                        if theme not in theme_groups: theme_groups[theme] = []
                                        theme_groups[theme].append({'code': code, 'name': name, 'rate': rate, 'price': item['price']})
                                        
                            for theme, stocks in theme_groups.items():
                                if theme in self.bought_themes: continue
                                    
                                if len(stocks) >= 2:
                                    stocks.sort(key=lambda x: x['rate'], reverse=True)
                                    leader = stocks[0]
                                    follower = stocks[1]
                                    
                                    if leader['price'] < BotConfig.MIN_STOCK_PRICE: continue
                                    if follower['price'] < BotConfig.MIN_STOCK_PRICE: continue
                                    
                                    if follower['code'] in self.blacklist or follower['code'] in self.portfolio: continue
                                    
                                    # 쿨타임 체크
                                    if follower['code'] in self.blacklist:
                                        sell_time = self.blacklist[follower['code']].get('sell_time')
                                        if sell_time and (now - sell_time).total_seconds() / 60 < BotConfig.REBUY_COOLTIME_MINUTES: continue
                                    
                                    leader_info = self.api.fetch_price_detail(leader['code'], leader['name'])
                                    if not leader_info: continue
                                    
                                    is_limit_up = (leader_info['price'] >= leader_info['max_price'])
                                    
                                    if is_limit_up:
                                        if theme not in self.locked_leaders_time:
                                            self.locked_leaders_time[theme] = datetime.datetime.now()
                                        
                                        lock_duration = (datetime.datetime.now() - self.locked_leaders_time[theme]).total_seconds()
                                        
                                        if lock_duration > BotConfig.THEME_BUY_TIMEOUT:
                                            self.bought_themes.add(theme)
                                            continue
                                    else:
                                        if theme in self.locked_leaders_time:
                                            del self.locked_leaders_time[theme]
                                        continue 

                                    follower_info = self.api.fetch_price_detail(follower['code'], follower['name'])
                                    if not follower_info: continue
                                    if follower_info['wick_ratio'] >= BotConfig.MAX_WICK_RATIO: continue

                                    ask_1_amount = follower_info['price'] * follower_info['ask_rsqn1']
                                    bid_1_amount = follower_info['price'] * follower_info['bid_rsqn1']
                                    if ask_1_amount < BotConfig.MIN_HOGA_AMT or bid_1_amount < BotConfig.MIN_HOGA_AMT: continue
                                    
                                    if follower_info['price'] < follower_info['open']: continue

                                    is_ask_wall_good = 20.0 <= follower_info['bid_ask_ratio'] <= 90.0
                                    
                                    if is_ask_wall_good:
                                        self.execute_buy(follower, theme, leader, 'THEME')
                                        if self.get_current_slots_used() != current_slots: break

                time.sleep(config.TIME_SLEEP)
                
            except Exception as e:
                print(f"Loop Error: {e}")
                time.sleep(5)

if __name__ == "__main__":
    bot = TradingBot()
    bot.run()

