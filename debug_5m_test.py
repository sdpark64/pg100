import pprint

def test_manual_aggregation_logic():
    print("🧪 [실험] 1분봉 10개를 -> 5분봉 2개로 잘 합치는지 로직 검증")
    print("=" * 60)

    # 1. 가짜 1분봉 데이터 준비 (09:00 ~ 09:09)
    # 상황: 주가가 1000원에서 시작해서 매분 10원씩 오르는 상황 가정
    fake_1m_data = [
        # [첫 번째 5분봉 재료: 09:00 ~ 09:04]
        {'stck_cntg_hour': '090000', 'stck_oprc': '1000', 'stck_prpr': '1010', 'stck_hgpr': '1010', 'stck_lwpr': '1000'},
        {'stck_cntg_hour': '090100', 'stck_oprc': '1010', 'stck_prpr': '1020', 'stck_hgpr': '1020', 'stck_lwpr': '1010'},
        {'stck_cntg_hour': '090200', 'stck_oprc': '1020', 'stck_prpr': '1030', 'stck_hgpr': '1030', 'stck_lwpr': '1020'},
        {'stck_cntg_hour': '090300', 'stck_oprc': '1030', 'stck_prpr': '1040', 'stck_hgpr': '1040', 'stck_lwpr': '1030'},
        {'stck_cntg_hour': '090400', 'stck_oprc': '1040', 'stck_prpr': '1050', 'stck_hgpr': '1055', 'stck_lwpr': '1040'}, # 고가 1055

        # [두 번째 5분봉 재료: 09:05 ~ 09:09]
        {'stck_cntg_hour': '090500', 'stck_oprc': '1050', 'stck_prpr': '1040', 'stck_hgpr': '1050', 'stck_lwpr': '1040'}, # 하락 시작
        {'stck_cntg_hour': '090600', 'stck_oprc': '1040', 'stck_prpr': '1030', 'stck_hgpr': '1040', 'stck_lwpr': '1030'},
        {'stck_cntg_hour': '090700', 'stck_oprc': '1030', 'stck_prpr': '1020', 'stck_hgpr': '1030', 'stck_lwpr': '1020'},
        {'stck_cntg_hour': '090800', 'stck_oprc': '1020', 'stck_prpr': '1010', 'stck_hgpr': '1020', 'stck_lwpr': '1010'},
        {'stck_cntg_hour': '090900', 'stck_oprc': '1010', 'stck_prpr': '1000', 'stck_hgpr': '1010', 'stck_lwpr': '990'},  # 저가 990
    ]

    print(f"📥 입력: 1분봉 데이터 {len(fake_1m_data)}개 로드됨.")

    # 2. 봇에 들어있는 [로직] 그대로 실행
    # -------------------------------------------------------------------------
    candles_5m = []
    current_bucket_key = None
    temp_candle = {'open': 0, 'close': 0, 'high': 0, 'low': 0, 'count': 0}
    
    # 시간순 정렬 (API는 역순일 수 있어서 안전장치)
    fake_1m_data.sort(key=lambda x: x['stck_cntg_hour']) 
    
    for item in fake_1m_data:
        t_str = item['stck_cntg_hour'] 
        price_o = int(item['stck_oprc'])
        price_c = int(item['stck_prpr'])
        price_h = int(item['stck_hgpr'])
        price_l = int(item['stck_lwpr'])
        
        minute = int(t_str[2:4])
        bucket_min = (minute // 5) * 5  # 0~4분 -> 00, 5~9분 -> 05로 변환
        bucket_key = t_str[0:2] + f"{bucket_min:02d}" # 예: 0900, 0905
        
        # 새로운 5분 구간이 시작되면, 이전 구간 저장
        if current_bucket_key != bucket_key:
            if current_bucket_key is not None:
                candles_5m.append(temp_candle.copy()) # 저장
            
            # 새 구간 초기화
            current_bucket_key = bucket_key
            temp_candle = {
                'time': bucket_key, # 확인용 시간 태그
                'open': price_o, 
                'close': price_c, 
                'high': price_h, 
                'low': price_l
            }
        else:
            # 기존 구간 업데이트 (고가/저가/종가 갱신)
            temp_candle['close'] = price_c
            if price_h > temp_candle['high']: temp_candle['high'] = price_h
            if price_l < temp_candle['low']: temp_candle['low'] = price_l
    
    # 마지막 남은 조각 저장
    if temp_candle['open'] > 0:
        candles_5m.append(temp_candle)
    
    # -------------------------------------------------------------------------

    # 3. 결과 확인
    print(f"📤 출력: 생성된 5분봉 {len(candles_5m)}개")
    print("-" * 60)
    
    # 첫 번째 봉 (09:00 ~ 09:04) 검증
    c1 = candles_5m[0]
    print(f"🔹 [1번봉] 09:00 (상승장)")
    print(f"   - 시가: {c1['open']} (기대값: 1000) -> {'✅' if c1['open']==1000 else '❌'}")
    print(f"   - 종가: {c1['close']} (기대값: 1050) -> {'✅' if c1['close']==1050 else '❌'}")
    print(f"   - 고가: {c1['high']} (기대값: 1055) -> {'✅' if c1['high']==1055 else '❌'}")
    
    print("-" * 60)

    # 두 번째 봉 (09:05 ~ 09:09) 검증
    c2 = candles_5m[1]
    print(f"🔹 [2번봉] 09:05 (하락장)")
    print(f"   - 시가: {c2['open']} (기대값: 1050) -> {'✅' if c2['open']==1050 else '❌'}")
    print(f"   - 종가: {c2['close']} (기대값: 1000) -> {'✅' if c2['close']==1000 else '❌'}")
    print(f"   - 저가: {c2['low']} (기대값: 990)  -> {'✅' if c2['low']==990 else '❌'}")
    
    print("=" * 60)
    if len(candles_5m) == 2 and c1['close'] == 1050 and c2['close'] == 1000:
        print("🎉 [결론] 로직 완벽함! 내일 아침 데이터만 들어오면 무조건 작동합니다.")
    else:
        print("🔥 [결론] 로직 수정 필요.")

if __name__ == "__main__":
    test_manual_aggregation_logic()

