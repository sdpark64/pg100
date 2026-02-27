import requests
import time
import config
import token_manager

# 시세 및 조건검색 API는 실전(REAL) 엔드포인트를 사용합니다.
URL_REAL = "https://openapi.koreainvestment.com:9443"
APP_KEY = config.REAL_API_KEY
APP_SECRET = config.REAL_API_SECRET
HTS_ID = config.HTS_ID

def get_headers(tr_id):
    # token_manager를 이용해 실전용 토큰 발급/조회
    token = token_manager.get_access_token("REAL")
    return {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appKey": APP_KEY,
        "appSecret": APP_SECRET,
        "custtype": "P",
        "tr_id": tr_id
    }

def check_top20_value():
    print("🔍 ['value' 조건검색] 종목들의 실시간 거래대금 조회를 시작합니다...\n")
    
    # 1. 조건검색식 Seq(일련번호) 조회
    url_title = f"{URL_REAL}/uapi/domestic-stock/v1/quotations/psearch-title"
    headers_title = get_headers("HHKST03900300")
    res_title = requests.get(url_title, headers=headers_title, params={"user_id": HTS_ID}).json()
    
    seq = None
    if res_title['rt_cd'] == '0':
        for item in res_title['output2']:
            if item['grp_nm'] == 'value': # 👈 HTS에 저장된 조건검색식 이름
                seq = item['seq']
                break
                
    if not seq:
        print("❌ 'value' 조건검색식을 찾을 수 없습니다. HTS에서 이름을 확인해주세요.")
        return

    # 2. 조건검색 결과(종목 리스트) 조회
    url_result = f"{URL_REAL}/uapi/domestic-stock/v1/quotations/psearch-result"
    headers_result = get_headers("HHKST03900400")
    res_result = requests.get(url_result, headers=headers_result, params={"user_id": HTS_ID, "seq": seq}).json()
    
    if res_result['rt_cd'] != '0':
        print(f"❌ 조건검색 결과 조회 실패: {res_result.get('msg1')}")
        return
        
    stock_list = res_result['output2']
    print(f"✅ 'value' 조건검색에서 {len(stock_list)}개 종목 포착 완료. 상세 데이터 계산 중...\n")
    
    results = []
    
    # 3. 각 종목별 현재가 및 누적거래량 조회하여 거래대금 계산
    url_price = f"{URL_REAL}/uapi/domestic-stock/v1/quotations/inquire-price"
    headers_price = get_headers("FHKST01010100")
    
    for idx, item in enumerate(stock_list):
        code = item['code']
        name = item['name']
        
        # API 초당 호출 제한(TPS) 방지용 딜레이
        time.sleep(0.1) 
        
        res_price = requests.get(url_price, headers=headers_price, params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}).json()
        
        if res_price['rt_cd'] == '0':
            out = res_price['output']
            price = int(out['stck_prpr'])   # 현재가
            vol = int(out['acml_vol'])      # 누적 거래량
            
            # 💰 거래대금 = 현재가 * 누적거래량
            trade_amt = price * vol 
            
            results.append({
                'name': name,
                'price': price,
                'vol': vol,
                'trade_amt': trade_amt
            })
            print(f"⏳ [{idx+1:02d}/{len(stock_list):02d}] {name} 분석 완료")

    # 4. 결과 출력
    print("\n" + "="*60)
    print("🏆 ['value' 조건식] 실시간 거래대금 랭킹 🏆")
    print("="*60)
    
    # 거래대금이 큰 순서대로 내림차순 정렬
    results.sort(key=lambda x: x['trade_amt'], reverse=True)
    
    for i, res in enumerate(results):
        # 보기 편하게 '억' 단위로 변환
        amt_100m = res['trade_amt'] // 100_000_000
        
        # 간격 맞춰서 출력
        print(f"{i+1:02d}위 | {res['name']:<12} | 거래대금: {amt_100m:>6,}억 원 | 현재가: {res['price']:>8,}원")
        
    print("="*60)
    print("💡 이 데이터를 바탕으로 BotConfig의 VALUE_KING_MIN_VALUE 기준을 설정하세요.")

if __name__ == "__main__":
    check_top20_value()
