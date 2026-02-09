import sys
import trading_bot
import token_manager

def check_total_residuals():
    print("🧪 [검증] 삼성전자 총 매수/매도 잔량 데이터 확인")
    print("=" * 50)

    # 1. 봇 설정 (실전 모드)
    trading_bot.MODE = "REAL"
    
    try:
        api = trading_bot.KisApi()
        token = token_manager.get_access_token("REAL")
        
        if not token:
            print("❌ 토큰 발급 실패")
            return

        if not token.startswith("Bearer"):
            token = f"Bearer {token}"
        api.access_token = token
        
    except Exception as e:
        print(f"❌ 설정 오류: {e}")
        return

    # 2. 데이터 조회 (삼성전자)
    code = "005930"
    print(f"📡 삼성전자({code}) 데이터 조회 중...")
    
    data = api.fetch_price_detail(code, "삼성전자")

    if data:
        # 3. 핵심 데이터 추출
        total_ask = data.get('total_ask', -1) # 없으면 -1
        total_bid = data.get('total_bid', -1)
        
        print("-" * 50)
        print(f"📉 총 매도 잔량 (total_ask): {total_ask:,} 주")
        print(f"📈 총 매수 잔량 (total_bid): {total_bid:,} 주")
        print("-" * 50)

        # 4. 검증 결과 판정
        # (장 종료 후엔 0일 수 있으나, 키 자체가 없으면 -1이 나옴)
        if total_ask != -1 and total_bid != -1:
            print("✅ [검증 성공] 필드가 정상적으로 존재하며 데이터를 가져왔습니다.")
            
            # 비율 계산 검증
            if total_ask > 0:
                ratio = (total_bid / total_ask) * 100
                print(f"📊 매수/매도 비율 (bid_ask_ratio): {ratio:.2f}%")
            else:
                print("📊 매수/매도 비율: 계산 불가 (매도잔량 0)")
        else:
            print("❌ [검증 실패] 총 잔량 데이터가 누락되었습니다.")
    else:
        print("❌ API 조회 실패 (None 반환)")

if __name__ == "__main__":
    check_total_residuals()