import trading_bot
from trading_bot import KisApi, BotConfig
import datetime

def test_candle_logic():
    print("🧪 5분봉 데이터 및 추세 하락 로직 정밀 점검 시작...")
    print("=" * 70)

    # 1. API 객체 생성 (실전/모의 모드 설정은 trading_bot.py 설정을 따름)
    try:
        api = KisApi()
    except Exception as e:
        print(f"❌ API 초기화 실패: {e}")
        return

    # 테스트할 종목 (거래량 많은 삼성전자 권장)
    target_code = "005930" 
    target_name = "삼성전자"

    print(f"📡 '{target_name}({target_code})' 5분봉 데이터 요청 중...")
    
    # 2. 봇과 똑같은 함수 호출 (최근 12개 = 1시간 분량)
    # fetch_5m_candles 함수가 1분봉을 가져와서 5분봉으로 잘 합치는지 확인
    candles = api.fetch_5m_candles(target_code, target_n=12)

    if not candles:
        print("❌ 데이터 수신 실패 (빈 리스트 반환됨)")
        print("   -> 장 운영 시간이 아니거나, 차트 서버 에러일 수 있습니다.")
        return

    # 3. 데이터 가공 결과 출력
    print(f"✅ 수신 및 가공된 5분봉 개수: {len(candles)}개")
    print("-" * 70)
    print(f"{'Index':<5} | {'Open':<8} | {'Close':<8} | {'High':<8} | {'Low':<8} | {'캔들상태'}")
    print("-" * 70)

    # 4. 봇 내부 로직 시뮬레이션 (계단식 하락 카운트)
    bearish_count = 0
    
    # candles[0]이 가장 최신 데이터입니다.
    for i, candle in enumerate(candles):
        # 양봉/음봉 시각화
        is_bear = candle['open'] > candle['close']
        state = "🟦음봉(하락)" if is_bear else "🟥양봉(상승)"
        if candle['open'] == candle['close']: state = "⬜도지(보합)"
        
        # 아직 미완성된 봉(현재 진행중)인지 표시
        finish_mark = ""
        if 'is_finished' in candle and not candle['is_finished']:
            finish_mark = " (진행중)"

        print(f"{i:<5} | {candle['open']:<8} | {candle['close']:<8} | {candle['high']:<8} | {candle['low']:<8} | {state}{finish_mark}")

    print("-" * 70)

    # 5. [핵심] 봇의 '추세 이탈' 판단 로직 검증
    # monitor_portfolio에 있는 로직을 그대로 가져와서 테스트
    print("\n🧮 [로직 시뮬레이션] 봇이 계산한 '하락 음봉' 개수")
    
    if len(candles) < 2:
        print("⚠️ 비교할 캔들이 부족합니다.")
        return

    for i in range(len(candles) - 1):
        curr = candles[i]     # 현재(더 최근)
        prev = candles[i+1]   # 과거(직전)
        
        # 조건 1: 음봉인가?
        is_bearish = curr['open'] > curr['close']
        
        # 조건 2: 직전 봉 종가보다 더 떨어졌는가? (계단식 하락)
        is_lower_close = curr['close'] < prev['close']
        
        if is_bearish and is_lower_close:
            bearish_count += 1
            print(f"  👉 [검출] Index {i}번 캔들은 '하락 음봉'입니다.")
            print(f"     (현재종가 {curr['close']} < 직전종가 {prev['close']} & 음봉)")

    print(f"\n📊 최종 집계 결과: {bearish_count}개")
    
    # 6. 판단
    threshold = 4 # 예: 오전장 기준
    print("-" * 70)
    if bearish_count >= threshold:
        print(f"🚨 [매도신호] 기준치({threshold}개) 이상이므로 '추세 이탈'로 판단하여 매도했을 것입니다.")
    else:
        print(f"🟢 [보유유지] 기준치({threshold}개) 미만이므로 아직 추세가 살아있다고 판단합니다.")
    print("=" * 70)

if __name__ == "__main__":
    test_candle_logic()

