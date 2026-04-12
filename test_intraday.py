import pandas as pd
import numpy as np
import FinanceDataReader as fdr
import os

def run_intraday_backtest():
    print("1. 밸류킹 로그 데이터 로딩 및 가속도 계산 중...")
    
    file_name = 'total_value_log.csv'
    if not os.path.exists(file_name):
        print(f"❌ 오류: '{file_name}' 파일을 찾을 수 없습니다.")
        return

    df = pd.read_csv(file_name)
    df.columns = ['Time','Code','Name','Price','Volume','Trade_Amt','Rate','PG_Amt','Market_Cap','Date']
    
    # 숫자형 변환
    num_cols = ['Price', 'Volume', 'Trade_Amt', 'Rate', 'PG_Amt', 'Market_Cap']
    for c in num_cols:
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(',', ''), errors='coerce')
        
    df['Date'] = df['Date'].astype(str)
    df['Datetime'] = pd.to_datetime(df['Date'] + ' ' + df['Time'])
    df = df.sort_values(['Code', 'Datetime'])
    
    # =======================================================
    # ⚡ 봇 로직 복원: 수급 가속도(분당 유입 속도) 계산
    # =======================================================
    df['prev_time'] = df.groupby('Code')['Datetime'].shift(1)
    df['prev_trade'] = df.groupby('Code')['Trade_Amt'].shift(1)
    df['prev_pg'] = df.groupby('Code')['PG_Amt'].shift(1)
    
    df['time_diff_min'] = (df['Datetime'] - df['prev_time']).dt.total_seconds() / 60.0
    same_day = df['Datetime'].dt.date == df['prev_time'].dt.date
    
    df['trade_speed'] = np.where(same_day & (df['time_diff_min'] > 0), 
                                 (df['Trade_Amt'] - df['prev_trade']) / df['time_diff_min'], 0)
    df['pg_speed'] = np.where(same_day & (df['time_diff_min'] > 0), 
                              (df['PG_Amt'] - df['prev_pg']) / df['time_diff_min'], 0)

    # =======================================================
    # 🚧 봇 진입 필터 적용
    # =======================================================
    # 1. 제외 키워드 필터 (ETF/ETN/스팩 등)
    excluded = ["스팩", "ETN", "ETF", "리츠", "우B", "우\\(", "인버스", "레버리지", "선물", "채권", "KODEX", "TIGER", "HANARO", "SOL", "PLUS", "RISE", "KOSEF", "ACE", "히어로즈", "WOORI"]
    df = df[~df['Name'].str.contains('|'.join(excluded))]
    
    # 2. 기본 가격, 상승률, 시총, 애매한 프로그램(0~3억) 컷
    cond_price = (df['Price'] >= 1000) & (df['Price'] <= 500000)
    cond_rate = (df['Rate'] >= 5.0) & (df['Rate'] <= 11.0)
    cond_mcap = (df['Market_Cap'] >= 2000)
    cond_pg = (df['PG_Amt'] < 0) | (df['PG_Amt'] >= 3)
    
    # 3. 속도 필터 (분당 거래대금 10억 이상, 프로그램 순매도세 아닐 것)
    cond_speed = (df['trade_speed'] >= 10) & (df['pg_speed'] >= 0)
    
    # 4. 시간대별 투-트랙 모드
    time_str = df['Time']
    cond_morning = (time_str >= '09:06:00') & (time_str <= '10:00:00') & (df['Trade_Amt'] >= 50) & (df['Trade_Amt'] <= 200)
    cond_afternoon = (time_str >= '12:00:00') & (time_str <= '14:30:00') & (df['Trade_Amt'] >= 1000)
    cond_time_trade = cond_morning | cond_afternoon

    # 시그널 포착 및 하루 1회 진입 제한 (가장 먼저 포착된 시점)
    signals = df[cond_price & cond_rate & cond_mcap & cond_pg & cond_speed & cond_time_trade].copy()
    signals = signals.drop_duplicates(subset=['Date', 'Code'], keep='first')
    
    print(f"✅ 총 {len(signals)}건의 밸류킹 매수 시그널 포착! FDR을 통한 장중 성과 검증 시작...")
    
    # =======================================================
    # 🎯 FDR 당일 봉 데이터를 활용한 가상 청산 시뮬레이션
    # =======================================================
    results = []
    for idx, row in signals.iterrows():
        date_str = row['Date']
        code = str(row['Code']).zfill(6)
        buy_price = row['Price']
        
        try:
            fdr_df = fdr.DataReader(code, date_str, date_str)
            if fdr_df.empty: continue
            
            daily_open = fdr_df['Open'].iloc[0]
            daily_high = fdr_df['High'].iloc[0]
            daily_low = fdr_df['Low'].iloc[0]
            daily_close = fdr_df['Close'].iloc[0]
            
            # 음봉 진입 차단 로직 (봇의 info['price'] < info['open'] continue 동일 적용)
            if buy_price < daily_open:
                continue

            # 수익률 계산
            max_profit = (daily_high - buy_price) / buy_price * 100
            max_loss = (daily_low - buy_price) / buy_price * 100
            close_profit = (daily_close - buy_price) / buy_price * 100
            
            # 봇 청산 룰 적용 (+2.5% 익절 / -3.0% 손절)
            if max_profit >= 2.5 and max_loss <= -3.0:
                outcome = "⚠️ 롤러코스터 (익/손절 동시 터치)"
                final_profit = close_profit 
            elif max_profit >= 2.5:
                outcome = "💰 익절 (+2.5% 도달)"
                final_profit = 2.5
            elif max_loss <= -3.0:
                outcome = "💔 기계적 손절 (-3.0% 이탈)"
                final_profit = -3.0
            else:
                outcome = "⏳ 타임아웃/종가청산"
                final_profit = close_profit

            results.append({
                'Date': date_str, 'Time': row['Time'], 'Code': code, 'Name': row['Name'],
                'Track': '오전장' if row['Time'] < '12' else '오후장',
                'Buy_Price': buy_price, 'Daily_High_Rate': max_profit, 'Daily_Low_Rate': max_loss,
                'Trade_Speed': round(row['trade_speed'], 1), 'PG_Speed': round(row['pg_speed'], 1),
                'Outcome': outcome, 'Final_Profit(%)': final_profit
            })
        except:
            pass

    res_df = pd.DataFrame(results)
    if res_df.empty:
        print("조건을 만족하는 매매 내역이 없습니다.")
        return
        
    print("\n==================================================")
    print("🚀 [밸류킹 장중 단타 봇] 백테스트 결과 요약")
    print("==================================================")
    print(f"총 진입 횟수: {len(res_df)}건")
    print(f"익절(+2.5%) 도달 확률: {(res_df['Outcome'] == '💰 익절 (+2.5% 도달)').mean()*100:.1f}%")
    print(f"손절(-3.0%) 타격 확률: {(res_df['Outcome'] == '💔 기계적 손절 (-3.0% 이탈)').mean()*100:.1f}%")
    print(f"평균 확정 수익률(추정): {res_df['Final_Profit(%)'].mean():.2f}%\n")
    
    print("📊 [트랙별 성과 분석]")
    for track in ['오전장', '오후장']:
        subset = res_df[res_df['Track'] == track]
        if not subset.empty:
            print(f"[{track}] 진입: {len(subset)}건 | 평균수익: {subset['Final_Profit(%)'].mean():.2f}% | 익절률: {(subset['Outcome'] == '💰 익절 (+2.5% 도달)').mean()*100:.1f}%")

    res_df.to_csv('valueking_backtest_result.csv', index=False, encoding='utf-8-sig')
    print("\n✅ 분석 완료! 상세 내역이 'valueking_backtest_result.csv'로 저장되었습니다.")

if __name__ == "__main__":
    run_intraday_backtest()
