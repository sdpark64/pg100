import time
from trading_bot import KisApi, BotConfig

def check_program_buy_amounts():
    print("🕵️‍♂️ [pg100] 종목별 프로그램 순매수 금액 현황 (내림차순 정렬)")
    print("=" * 80)
    print(f"{'순위':<4} {'종목명':<10} | {'현재가':>9} | {'총거래(억)':>8} | {'프로그램(억)':>11} | {'판정'}")
    print("-" * 80)

    api = KisApi()
    
    # 1. Hot100 목록 가져오기
    hot_list = api.fetch_condition_stocks("pg100")
    if not hot_list:
        print("❌ pg100 목록을 가져오지 못했습니다. (조건식 이름 확인 필요)")
        return

    data_list = []

    # 2. 데이터 수집
    print(f"📡 {len(hot_list)}개 종목 상세 데이터 조회 중...")
    for stock in hot_list:
        code = stock['stck_shrn_iscd']
        name = stock['hts_kor_isnm']
        
        # 상세 정보 조회 (프로그램 수량 확인)
        info = api.fetch_price_detail(code, name)
        if not info: continue
            
        # 금액 계산
        current_price = info['price']
        total_trade_amt_eok = (current_price * info['acml_vol']) / 100_000_000 # 억 단위
        
        pg_qty = info['program_buy']
        pg_amt = pg_qty * current_price
        pg_amt_eok = pg_amt / 100_000_000 # 억 단위
        
        data_list.append({
            'name': name,
            'price': current_price,
            'total_amt': total_trade_amt_eok,
            'pg_amt': pg_amt,
            'pg_amt_eok': pg_amt_eok
        })
        time.sleep(0.05) # API 부하 방지

    # 3. 프로그램 매수금액 큰 순서로 정렬
    data_list.sort(key=lambda x: x['pg_amt'], reverse=True)

    # 4. 출력
    for idx, item in enumerate(data_list, 1):
        # 봇 설정 기준과 비교 (300억, 500억, 1000억 구간 표시)
        status = ""
        amt = item['pg_amt']
        
        if amt >= 100_000_000_000:
            status = "🔥초대형(1000억↑)"
        elif amt >= 50_000_000_000:
            status = "✅대형(500억↑)"
        elif amt >= 20_000_000_000:
            status = "🙂중형(300억↑)"
        elif amt < 0:
            status = "💧순매도"
        else:
            status = "  미달"

        print(f"{idx:<4} {item['name']:<10} | {item['price']:>10,} | {item['total_amt']:>11.1f} | {item['pg_amt_eok']:>14.1f} | {status}")

    print("=" * 80)

if __name__ == "__main__":
    check_program_buy_amounts()

