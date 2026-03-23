import sys
# 봇 코드를 임포트하여 API 인증 및 BotConfig 설정값을 그대로 사용
from stock_bot import TradingBot, BotConfig

def verify_all_filters_comprehensive():
    print("\n=== [ 조건검색식 'value' 전체 필터 전수 검사 시작 ] ===")
    
    # 1. 봇 초기화 (API 인증 수행)
    print("⏳ API 연동 중...")
    bot = TradingBot()
    api = bot.api
    
    # 2. 조건검색식 조회
    print("🔍 'value' 조건검색식 실시간 조회 중...")
    value_list = api.fetch_condition_stocks("value")
    
    if not value_list:
        print("❌ 포착된 종목이 없습니다. (장 운영 시간 확인 요망)")
        return
        
    print(f"✅ 포착된 종목 수: {len(value_list)}개\n")
    print("=" * 60)
    
    def is_excluded_stock(stock_name):
        return any(keyword in stock_name for keyword in BotConfig.EXCLUDE_KEYWORDS)

    passed_stocks = []
    
    # 3. 각 종목별로 '모든' 필터 검사 진행
    for item in value_list:
        code = item['code']
        name = item['name']
        price = item.get('price', 0)
        vol = item.get('vol', 0)
        
        print(f"\n▶ [{code}] {name} (포착가: {price:,}원) 필터별 진단 결과")
        
        # 합격 여부를 추적할 변수
        is_all_passed = True
        results = {}
        
        # [필터 1] 제외 키워드
        if is_excluded_stock(name):
            results['1. 제외종목'] = "❌ (스팩, ETF 등 배제 대상)"
            is_all_passed = False
        else:
            results['1. 제외종목'] = "✅ 통과"
            
        # [필터 2] 최소 가격
        if price < BotConfig.MIN_STOCK_PRICE:
            results['2. 최소주가'] = f"❌ (미달: {price:,}원 < {BotConfig.MIN_STOCK_PRICE:,}원)"
            is_all_passed = False
        else:
            results['2. 최소주가'] = "✅ 통과"
            
        # [필터 3] 초반 거래대금
        est_trade_amt = price * vol
        if est_trade_amt > BotConfig.VALUE_KING_MAX_VALUE:
            results['3. 초반수급'] = f"❌ (초과: {est_trade_amt/100000000:,.1f}억 상한선 돌파)"
            is_all_passed = False
        else:
            results['3. 초반수급'] = "✅ 통과"
            
        # API 상세 정보 조회 (나머지 필터 검사에 필수)
        info = api.fetch_price_detail(code, name)
        
        if not info or info.get('open', 0) == 0:
            results['4. API상세 '] = "❌ (데이터 수신 실패 또는 시가 0원)"
            is_all_passed = False
            # 데이터가 없으면 뒤의 필터를 계산할 수 없으므로 여기까지만 기록
        else:
            current_price = info['price']
            open_price = info['open']
            high_price = info['high']
            current_rate = info.get('rate', 0)
            total_trade_amt = info.get('acml_vol', 0) * current_price
            pg_amt = info.get('program_buy', 0) * current_price
            market_cap = info.get('market_cap', 0)
            max_rate_limit = getattr(BotConfig, 'MAX_RATE_LIMIT', 15.0)

            # [필터 4] 양봉 여부
            if current_price < open_price:
                results['4. 캔들상태'] = "❌ (음봉 - 시가 이탈)"
                is_all_passed = False
            else:
                results['4. 캔들상태'] = "✅ 양봉 유지"

            # [필터 5] 등락률 조건 (MIN ~ MAX)
            if current_rate < BotConfig.MIN_RATE_LIMIT:
                results['5. 등락률  '] = f"❌ (미달: 현재 {current_rate}%)"
                is_all_passed = False
            elif current_rate > max_rate_limit:
                results['5. 등락률  '] = f"❌ (초과: 현재 {current_rate}%)"
                is_all_passed = False
            else:
                results['5. 등락률  '] = f"✅ 적정 ({current_rate}%)"

            # [필터 6] 윗꼬리 및 상한 이력 (설거지 방어)
            if high_price > 0:
                drop_from_high = (high_price - current_price) / high_price * 100
                prev_close = current_price / (1 + (current_rate / 100))
                highest_rate = (high_price - prev_close) / prev_close * 100
                
                tail_errors = []
                if drop_from_high >= 3.0:
                    tail_errors.append(f"윗꼬리 -{drop_from_high:.1f}%")
                if highest_rate > max_rate_limit:
                    tail_errors.append(f"장중최고 +{highest_rate:.1f}% 도달이력")
                    
                if tail_errors:
                    results['6. 윗꼬리  '] = f"❌ ({' / '.join(tail_errors)})"
                    is_all_passed = False
                else:
                    results['6. 윗꼬리  '] = "✅ 안전"
            else:
                results['6. 윗꼬리  '] = "✅ (고가 정보 없음)"

            # [필터 7] 누적 거래대금 (10억 이상)
            if total_trade_amt < BotConfig.VALUE_KING_MIN_VALUE:
                results['7. 누적거래'] = f"❌ (부족: {total_trade_amt/100000000:,.1f}억)"
                is_all_passed = False
            else:
                results['7. 누적거래'] = f"✅ 풍부 ({total_trade_amt/100000000:,.1f}억)"

            # [필터 8] 프로그램 수급 (애매한 구간 제외)
            if BotConfig.PROGRAM_BUY_AMBIGUOUS_MIN <= pg_amt < BotConfig.PROGRAM_BUY_AMBIGUOUS_MAX:
                results['8. PG순매수'] = f"❌ (애매한 수급: {pg_amt/100000000:,.1f}억)"
                is_all_passed = False
            else:
                results['8. PG순매수'] = f"✅ 양호 ({pg_amt/100000000:,.1f}억)"

            # [필터 9] 시가총액
            if market_cap < BotConfig.MIN_MARKET_CAP:
                results['9. 시가총액'] = f"❌ (소형주: {market_cap:,}억)"
                is_all_passed = False
            else:
                results['9. 시가총액'] = f"✅ 우량 ({market_cap:,}억)"

        # 진단 결과 일괄 출력
        for key, value in results.items():
            print(f"   {key} : {value}")
            
        if is_all_passed:
            print("   🟢 [최종결과] : 매수 조건 완벽 충족!")
            passed_stocks.append(name)
        else:
            print("   🔴 [최종결과] : 탈락 (일부 조건 미달)")

    print("\n" + "=" * 60)
    print(f"🎉 조회된 총 {len(value_list)}개 종목 중 {len(passed_stocks)}개 최종 통과")
    if passed_stocks:
        print(f"👉 실시간 매수 대상 종목: {', '.join(passed_stocks)}")
    else:
        print("👉 봇의 까다로운 9가지 조건을 모두 통과한 종목이 없습니다.")
    print("=" * 60)

if __name__ == '__main__':
    verify_all_filters_comprehensive()

