import sys
import datetime
import time

# 📂 사용자님의 기존 파일들을 불러옵니다 (수정 X)
try:
    import config
    import trading_bot      # 여기에 있는 로직을 검증합니다.
    import token_manager    # 토큰 매니저 사용
except ImportError as e:
    print(f"❌ 필수 파일이 없습니다: {e}")
    sys.exit()

def verify_program_strategy():
    print("🧪 [검증] 프로그램 자이언트(PROGRAM) 전략 대상 추출 테스트")
    print(f"📅 현재 시간: {datetime.datetime.now().strftime('%H:%M:%S')}")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. 봇의 API 객체 빌려오기 (trading_bot.py 활용)
    # ------------------------------------------------------------------
    # 검증을 위해 강제로 REAL 모드 설정
    trading_bot.MODE = "REAL"
    
    try:
        # trading_bot.py에 있는 KisApi 클래스 생성
        api = trading_bot.KisApi()
        
        # 토큰 주입 (token_manager 사용)
        token = token_manager.get_access_token("REAL")
        if not token:
            print("❌ 실전 토큰을 가져올 수 없습니다.")
            return

        # 헤더에 사용할 토큰 포맷팅
        if not token.startswith("Bearer"):
            token = f"Bearer {token}"
            
        # API 객체에 토큰 강제 주입 (봇이 하는 것과 동일하게)
        api.base_headers_real["authorization"] = token
        # get_headers 함수가 token_manager를 내부적으로 쓰더라도 문제 없도록 준비
        
        print("✅ API 초기화 완료 (Session 장착됨)")
        
    except Exception as e:
        print(f"❌ API 객체 생성 실패: {e}")
        return

    # ------------------------------------------------------------------
    # 2. 종목 리스트 가져오기 (PG100 조건검색)
    # ------------------------------------------------------------------
    print("\n📡 [1단계] 'pg100' 조건검색 종목 수집 중...")
    
    # 봇에 있는 함수 그대로 사용
    pg_list = api.fetch_condition_stocks("pg100")
    
    if not pg_list:
        print("⚠️ 'pg100' 검색 결과가 없습니다. (조건식이 없거나, 포착된 종목이 없음)")
        print("👉 'top100'(거래대금상위)으로 대체하여 로직을 검증합니다.")
        pg_list = api.fetch_condition_stocks("top100")
    
    if not pg_list:
        print("❌ [오류] 종목 리스트를 아예 가져오지 못했습니다. API 키 권한이나 HTS 설정을 확인하세요.")
        return

    print(f"🔍 스캔 대상: {len(pg_list)}개 종목")
    print("-" * 60)

    # ------------------------------------------------------------------
    # 3. 자이언트 전략 로직 검증 (봇 설정 그대로 적용)
    # ------------------------------------------------------------------
    # 봇 설정값 로드
    conf = trading_bot.BotConfig
    
    # 시간대별 수급 필터 기준 계산
    now = datetime.datetime.now()
    if (now.hour == 9 and now.minute < 30):
        time_filter = conf.PG_TIME_FILTER_0
        time_msg = "09:00~09:30 (50억)"
    elif (now.hour == 9 and now.minute >= 30) or (now.hour < 10):
        time_filter = conf.PG_TIME_FILTER_1
        time_msg = "09:30~10:00 (100억)"
    elif (now.hour == 10) or (now.hour == 11 and now.minute < 30):
        time_filter = conf.PG_TIME_FILTER_2
        time_msg = "10:00~11:30 (200억)"
    elif (now.hour == 11 and now.minute >= 30) or (now.hour == 12):
        time_filter = conf.PG_TIME_FILTER_3
        time_msg = "11:30~13:00 (250억)"
    else:
        time_filter = conf.PG_TIME_FILTER_4
        time_msg = "13:00~ (300억)"

    print(f"🎯 현재 시간 수급 커트라인: {time_filter // 100000000}억 원 ({time_msg})")
    
    detected = []
    
    for i, item in enumerate(pg_list):
        code = item['stck_shrn_iscd']
        name = item['hts_kor_isnm']
        
        # [봇 로직 1] 이름 필터
        if any(x in name for x in ["스팩", "ETN", "ETF", "리츠", "우B", "우(", "인버스", "레버리지", "선물", "채권"]) or name.endswith("우"):
            continue

        # [봇 로직 2] 예상 거래대금 필터
        est_total_amt = item['price'] * item['vol']
        if est_total_amt < (conf.PG_LEVEL_0_AMT * 0.9): 
            continue 

        print(f"\r🚀 분석 중... [{i+1}/{len(pg_list)}] {name}", end="")
        
        # --------------------------------------------------------------
        # [핵심] fetch_price_detail 호출 (봇 코드 사용)
        # --------------------------------------------------------------
        info = api.fetch_price_detail(code, name)
        
        if not info: continue
        
        # 데이터 추출
        pg_amt = info['program_buy'] * info['price']
        rate = info['rate']
        wick_ratio = info['wick_ratio']
        is_yangbong = info['price'] >= info['open']
        
        # --------------------------------------------------------------
        # [봇 로직 3] 자이언트 판별 (조건문 그대로 재현)
        # --------------------------------------------------------------
        reasons = []
        is_pass = True
        
        # 1. 시간대별 수급 금액 체크
        if pg_amt < time_filter:
            is_pass = False
            reasons.append(f"수급부족({pg_amt//100000000}억 < {time_filter//100000000}억)")
        
        # 2. 등락률 체크
        if not (conf.GIANT_RATE_MIN <= rate <= conf.GIANT_RATE_MAX):
            is_pass = False
            reasons.append(f"등락률벗어남({rate}%)")
            
        # 3. 양봉 체크
        if not is_yangbong:
            is_pass = False
            reasons.append("음봉")
            
        # 4. 윗꼬리 체크
        if wick_ratio >= conf.MAX_WICK_RATIO:
            is_pass = False
            reasons.append(f"윗꼬리과다({wick_ratio:.2f})")

        # 결과 저장
        if is_pass:
            detected.append({
                'name': name,
                'pg_amt': pg_amt,
                'rate': rate,
                'status': 'PASS'
            })
        else:
            # 수급은 만족했는데 다른 조건에서 탈락한 경우만 로그로 확인 (너무 많으니)
            if pg_amt >= time_filter: 
                 detected.append({
                    'name': name,
                    'pg_amt': pg_amt,
                    'rate': rate,
                    'status': f"FAIL: {', '.join(reasons)}"
                })

    print("\n" + "=" * 60)
    
    # ------------------------------------------------------------------
    # 4. 최종 리포트
    # ------------------------------------------------------------------
    if detected:
        # 수급 금액순 정렬
        detected.sort(key=lambda x: x['pg_amt'], reverse=True)
        
        print(f"[📢 검증 결과 리포트]")
        for d in detected:
            amt_uk = d['pg_amt'] // 100000000
            icon = "✅" if d['status'] == 'PASS' else "❌"
            print(f"{icon} {d['name']:<8} | 수급: {amt_uk:>4}억 | 등락: {d['rate']:>5.2f}% | 결과: {d['status']}")
            
        pass_count = len([x for x in detected if x['status'] == 'PASS'])
        print("-" * 60)
        print(f"👉 총 {len(detected)}개 후보 중 [{pass_count}개] 종목이 매수 대상입니다.")
    else:
        print("💨 조건(수급/차트)을 만족하는 종목이 하나도 없습니다.")

if __name__ == "__main__":
    verify_program_strategy()