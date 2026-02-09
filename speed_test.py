import time
import sys
# 기존 봇 파일에서 API 기능만 빌려옵니다
from trading_bot import KisApi, BotConfig, MODE

def run_speed_test():
    print(f"🚀 [속도 측정 시작] 현재 모드: {MODE}")
    print(f"   (설정된 딜레이: REAL={BotConfig.DELAY_REAL}초 / MOCK={BotConfig.DELAY_MOCK}초)")
    print("=" * 60)

    # 1. API 객체 생성
    try:
        api = KisApi()
    except Exception as e:
        print(f"❌ API 초기화 실패: {e}")
        return

    # 2. 테스트할 종목 10개 (대형주 위주)
    # 실제 pg100 리스트를 가져오는 과정도 시간이 걸리므로, 
    # API 통신 속도 자체만 보기 위해 종목은 고정합니다.
    test_list = [
        {'code': '005930', 'name': '삼성전자'},
        {'code': '000660', 'name': 'SK하이닉스'},
        {'code': '005380', 'name': '현대차'},
        {'code': '207940', 'name': '삼성바이오로직스'},
        {'code': '000270', 'name': '기아'},
        {'code': '005490', 'name': 'POSCO홀딩스'},
        {'code': '035420', 'name': 'NAVER'},
        {'code': '068270', 'name': '셀트리온'},
        {'code': '003550', 'name': 'LG'},
        {'code': '051910', 'name': 'LG화학'}
    ]

    print(f"📋 테스트 대상: {len(test_list)}개 종목 조회 시작...")
    print("-" * 60)

    total_start_time = time.time()
    slow_count = 0

    # 3. 순차 조회 및 시간 측정
    for i, stock in enumerate(test_list):
        start_time = time.time()
        
        # 봇이 사용하는 것과 똑같은 함수 호출
        info = api.fetch_price_detail(stock['code'], stock['name'])
        
        end_time = time.time()
        duration = end_time - start_time
        
        status = "✅ 쾌적"
        if duration > 1.0: 
            status = "⚠️ 느림"
            slow_count += 1
        if duration > 3.0: 
            status = "❌ 타임아웃 의심"
            slow_count += 1

        if info:
            print(f"[{i+1:>2}/{len(test_list)}] {stock['name']:<8} : {duration:.4f}초 | {status}")
        else:
            print(f"[{i+1:>2}/{len(test_list)}] {stock['name']:<8} : {duration:.4f}초 | ❌ 데이터 수신 실패")

    total_end_time = time.time()
    total_duration = total_end_time - total_start_time
    avg_duration = total_duration / len(test_list)

    print("=" * 60)
    print(f"🏁 [진단 결과]")
    print(f"   - 총 소요 시간 : {total_duration:.4f}초")
    print(f"   - 종목당 평균  : {avg_duration:.4f}초")
    
    print("-" * 60)
    if avg_duration < 0.3:
        print("🎉 [판정] 속도 아주 빠름! (실전 매매 최적 상태)")
    elif avg_duration < 0.8:
        print("😐 [판정] 보통 (모의투자 환경이거나 약간의 지연 있음)")
        if MODE == "MOCK":
            print("   -> 모의투자는 원래 0.6초 딜레이가 있어서 정상입니다.")
    else:
        print("🚨 [판정] 매우 느림! (네트워크 문제 또는 로직 비효율)")
        print("   -> fetch_price_detail 함수 내부에서 API를 2번 호출하는지 확인 필요.")

if __name__ == "__main__":
    run_speed_test()

