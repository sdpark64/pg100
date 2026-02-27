import requests
import time
import csv
import config
import token_manager
from datetime import datetime

# ==============================================================================
# ⚙️ 설정 부분
# ==============================================================================
URL_REAL = "https://openapi.koreainvestment.com:9443"
APP_KEY = config.REAL_API_KEY
APP_SECRET = config.REAL_API_SECRET
HTS_ID = config.HTS_ID

# 검색할 조건식 이름 (기존에 사용하신 'value' 조건식 기준)
CONDITION_NAME = "value" 

def get_headers(tr_id):
    token = token_manager.get_access_token("REAL")
    return {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appKey": APP_KEY,
        "appSecret": APP_SECRET,
        "custtype": "P",
        "tr_id": tr_id
    }

def fetch_all_1min_candles(code):
    """특정 종목의 당일 1분봉 데이터를 09:00부터 끝까지 모두 수집합니다."""
    url = f"{URL_REAL}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
    headers = get_headers("FHKST03010200")
    
    all_candles = []
    # 장 마감 시간(15:30:00)부터 역순으로 조회 시작
    target_time = "153000" 
    
    while True:
        params = {
            "FID_ETC_CLS_CODE": "",
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
            "FID_INPUT_HOUR_1": target_time, 
            "FID_PW_DIV_CODE": "0" 
        }
        
        time.sleep(0.1) # 초당 호출 제한 방어
        res = requests.get(url, headers=headers, params=params).json()
        
        if res['rt_cd'] != '0' or not res['output2']:
            break
            
        candles = res['output2']
        all_candles.extend(candles)
        
        # 마지막으로 받은 캔들의 시간을 다음 조회 기준으로 설정
        last_time = candles[-1]['stck_cntg_hour']
        
        # 09시 데이터까지 다 받았거나, 더 이상 이전 데이터가 없으면 중단
        if last_time <= "090000" or last_time == target_time:
            break
            
        target_time = last_time

    # 시간 역순(15:30 -> 09:00)을 정순(09:00 -> 15:30)으로 뒤집기
    return list(reversed(all_candles))

def analyze_time_based_value():
    print(f"🔍 ['{CONDITION_NAME}'] 종목들의 시간대별 거래대금 분석을 시작합니다...\n")
    
    # 1. 조건검색식 Seq 조회
    url_title = f"{URL_REAL}/uapi/domestic-stock/v1/quotations/psearch-title"
    res_title = requests.get(url_title, headers=get_headers("HHKST03900300"), params={"user_id": HTS_ID}).json()
    
    seq = None
    if res_title['rt_cd'] == '0':
        for item in res_title['output2']:
            if item['grp_nm'] == CONDITION_NAME:
                seq = item['seq']
                break
                
    if not seq:
        print(f"❌ '{CONDITION_NAME}' 조건검색식을 찾을 수 없습니다.")
        return

    # 2. 조건검색 결과 조회
    url_result = f"{URL_REAL}/uapi/domestic-stock/v1/quotations/psearch-result"
    res_result = requests.get(url_result, headers=get_headers("HHKST03900400"), params={"user_id": HTS_ID, "seq": seq}).json()
    
    if res_result['rt_cd'] != '0':
        print("❌ 조건검색 조회 실패")
        return
        
    stock_list = res_result['output2']
    print(f"✅ {len(stock_list)}개 종목 포착. 분봉 추적을 시작합니다. (약 1~2분 소요 예상)\n")
    
    results = []
    
    for idx, item in enumerate(stock_list):
        code = item['code']
        name = item['name']
        
        # ETF/ETN 등은 분석에서 제외 (개별 주식만 보기 위함)
        if any(x in name for x in ["KODEX", "TIGER", "HANARO", "SOL", "RISE", "KBSTAR", "인버스", "레버리지"]):
            continue
            
        candles = fetch_all_1min_candles(code)
        
        if not candles:
            continue
            
        # 시간대별 누적 거래대금 기록용 변수
        cum_value = 0
        value_0930 = 0
        value_1000 = 0
        value_1100 = 0
        value_1300 = 0
        value_total = 0
        
        # 1분봉을 09시부터 순회하며 거래대금 누적
        for candle in candles:
            c_time = candle['stck_cntg_hour']
            c_price = int(candle['stck_prpr'])
            c_vol = int(candle['cntg_vol'])
            
            cum_value += (c_price * c_vol)
            
            # 지정된 시간을 지나는 순간의 누적 거래대금을 스냅샷으로 저장
            if c_time <= "093000": value_0930 = cum_value
            if c_time <= "100000": value_1000 = cum_value
            if c_time <= "110000": value_1100 = cum_value
            if c_time <= "130000": value_1300 = cum_value
            value_total = cum_value # 마지막이 최종 거래대금
            
        results.append({
            'Name': name,
            'Code': code,
            'Val_09:30(억)': value_0930 // 100_000_000,
            'Val_10:00(억)': value_1000 // 100_000_000,
            'Val_11:00(억)': value_1100 // 100_000_000,
            'Val_13:00(억)': value_1300 // 100_000_000,
            'Val_Total(억)': value_total // 100_000_000
        })
        print(f"⏳ [{idx+1:02d}/{len(stock_list):02d}] {name} 완료 (종가기준: {value_total // 100_000_000:,}억)")

    # 3. CSV 파일로 저장 (종가 거래대금 순 정렬)
    results.sort(key=lambda x: x['Val_Total(억)'], reverse=True)
    
    filename = "value_time_tracking.csv"
    with open(filename, mode='w', encoding='utf-8-sig', newline='') as f:
        if results:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
            
    print("\n" + "="*60)
    print(f"✅ 분석 완료! 데이터가 '{filename}' 파일로 저장되었습니다.")
    print("💡 이 데이터를 열어보시고, 시간대별(elapsed) 가변 필터 기준을 세밀하게 조율해 보세요.")
    print("="*60)

if __name__ == "__main__":
    analyze_time_based_value()
