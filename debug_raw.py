import requests
import json
import datetime
from trading_bot import KisApi, BotConfig

def force_fetch_minute_chart():
    print("🔓 [트릭 시도] '미래 시간'으로 분봉 강제 조회")
    print("-" * 60)
    
    api = KisApi()
    target_code = "005930"
    
    # URL은 분봉(Time) 차트 그대로 사용
    url = f"{BotConfig.URL_REAL}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
    headers = api.get_headers("FHKST03010200", type="DATA")
    
    # 💡 [핵심 트릭] 
    # 현재 시간이 아니라 '153000'(장마감)으로 고정해서 요청합니다.
    # 이렇게 하면 "지금까지 쌓인 가장 최신 데이터"를 줍니다.
    trick_time = "153000"
    
    params = {
        "FID_ETC_CLS_CODE": "",
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": target_code,
        "FID_INPUT_HOUR_1": trick_time, 
        "FID_PW_DIV_CODE": "0" 
    }
    
    print(f"📡 요청 시간 파라미터: {trick_time} (강제 고정)")
    
    try:
        res = requests.get(url, headers=headers, params=params, timeout=5)
        data = res.json()
        
        output2 = data.get('output2', [])
        
        if len(output2) > 0:
            print(f"✅ [성공!] 데이터 뚫렸습니다. ({len(output2)}개 수신)")
            print(f"   - 최신 데이터 시간: {output2[0]['stck_cntg_hour']}")
            print(f"   - 최신 가격: {output2[0]['stck_prpr']}원")
            print("\n👉 해결책: 봇 코드에서 시간을 '153000'으로 고정하면 됩니다.")
        else:
            print("❌ [실패] 여전히 빈 리스트입니다.")
            print(f"   - 응답 코드: {data.get('rt_cd')}")
            print(f"   - 메시지: {data.get('msg1')}")
            
    except Exception as e:
        print(f"❌ 에러: {e}")

if __name__ == "__main__":
    force_fetch_minute_chart()

