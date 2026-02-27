import requests
import time
import csv
import os
import config
import token_manager

# ==============================================================================
# ⚙️ 설정 부분
# ==============================================================================
URL_REAL = "https://openapi.koreainvestment.com:9443"
APP_KEY = config.REAL_API_KEY
APP_SECRET = config.REAL_API_SECRET
HTS_ID = config.HTS_ID

# HTS에 저장해둔 거래대금 상위 조건검색식 이름 (예: 'top20' 또는 'value')
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

def analyze_ohlcv():
    print(f"🔍 ['{CONDITION_NAME}'] 조건검색 종목 데이터 수집 및 분석 시작...\n")
    
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
        print(f"❌ '{CONDITION_NAME}' 조건검색식을 찾을 수 없습니다. 이름을 확인해주세요.")
        return

    # 2. 조건검색 결과(종목 리스트) 조회
    url_result = f"{URL_REAL}/uapi/domestic-stock/v1/quotations/psearch-result"
    res_result = requests.get(url_result, headers=get_headers("HHKST03900400"), params={"user_id": HTS_ID, "seq": seq}).json()
    
    if res_result['rt_cd'] != '0':
        print(f"❌ 조건검색 결과 조회 실패: {res_result.get('msg1')}")
        return
        
    stock_list = res_result['output2']
    print(f"✅ {len(stock_list)}개 종목 포착 완료. OHLCV 데이터 추출 중...\n")
    
    results = []
    
    # 3. OHLCV 상세 데이터 조회
    url_price = f"{URL_REAL}/uapi/domestic-stock/v1/quotations/inquire-price"
    headers_price = get_headers("FHKST01010100")
    
    for idx, item in enumerate(stock_list):
        code = item['code']
        name = item['name']
        
        time.sleep(0.1) # 초당 호출 제한 방지
        res_price = requests.get(url_price, headers=headers_price, params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}).json()
        
        if res_price['rt_cd'] == '0':
            out = res_price['output']
            
            # 기본 OHLCV 추출
            c_price = int(out['stck_prpr'])  # 현재가 (종가)
            o_price = int(out['stck_oprc'])  # 시가
            h_price = int(out['stck_hgpr'])  # 고가
            l_price = int(out['stck_lwpr'])  # 저가
            vol = int(out['acml_vol'])       # 누적 거래량
            
            # 파생 데이터 계산
            trade_amt = c_price * vol        # 거래대금
            trade_amt_100m = trade_amt // 100_000_000 # 거래대금(억)
            
            # 전일 종가 추산 (현재가 및 등락률 기반)
            rate = float(out['prdy_ctrt'])
            prev_close = c_price / (1 + rate / 100) if rate != -100 else c_price
            
            # 지표 1: 시가 갭상승률 (%)
            gap_rate = ((o_price - prev_close) / prev_close) * 100 if prev_close > 0 else 0
            
            # 지표 2: 고가 도달률 (%) - 당일 최고 수익 구간
            high_rate = ((h_price - prev_close) / prev_close) * 100 if prev_close > 0 else 0
            
            # 지표 3: 윗꼬리 비율 (%) - (고가 - 시가/종가 중 큰 값) / 전체 캔들 길이
            total_candle = h_price - l_price
            max_body = max(o_price, c_price)
            upper_wick = h_price - max_body
            wick_ratio = (upper_wick / total_candle * 100) if total_candle > 0 else 0
            
            # ETF/ETN 필터링 (선택사항, 분석을 위해 남겨두거나 뺄 수 있음)
            is_etf = any(x in name for x in ["KODEX", "TIGER", "HANARO", "SOL", "RISE", "KBSTAR", "인버스", "레버리지"])
            
            results.append({
                'Name': name,
                'Code': code,
                'Is_ETF': 'O' if is_etf else 'X',
                'Trade_Amt(100M)': trade_amt_100m,
                'Prev_Close': int(prev_close),
                'Open': o_price,
                'High': h_price,
                'Low': l_price,
                'Close': c_price,
                'Gap_Rate(%)': round(gap_rate, 2),
                'High_Rate(%)': round(high_rate, 2),
                'Close_Rate(%)': round(rate, 2),
                'Wick_Ratio(%)': round(wick_ratio, 2)
            })
            print(f"⏳ [{idx+1:02d}/{len(stock_list):02d}] {name} 분석 완료")

    # 4. 분석 결과 CSV 저장 (거래대금 내림차순)
    results.sort(key=lambda x: x['Trade_Amt(100M)'], reverse=True)
    
    filename = "value_ohlcv_analysis.csv"
    with open(filename, mode='w', encoding='utf-8-sig', newline='') as f:
        if results:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
            
    print("\n" + "="*60)
    print(f"✅ 분석 완료! 데이터가 '{filename}' 파일로 저장되었습니다.")
    print("💡 엑셀에서 파일을 열고 필터(Filter) 기능을 활용하여 최적의 파라미터를 찾아보세요.")
    print("="*60)

if __name__ == "__main__":
    analyze_ohlcv()
