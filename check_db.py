import boto3
import json
import pprint

def verify_dynamodb_data():
    print("🕵️ DynamoDB 데이터 정밀 점검 시작...")

    # 1. DynamoDB 연결 (서울 리전)
    try:
        dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-2')
        table = dynamodb.Table('StockThemeGroups')
        
        # 2. 데이터 가져오기 (Key: 'today_map')
        response = table.get_item(Key={'date': 'today_map'})
        
        if 'Item' not in response:
            print("❌ [실패] 'today_map' 키를 가진 데이터가 없습니다. Lambda가 실행되지 않았거나 에러가 났습니다.")
            return

        item = response['Item']
        
        # 3. 메타데이터 확인
        print("-" * 60)
        print(f"📅 데이터 기준일 (Real Date): {item.get('real_date', 'Unknown')}")
        print(f"⏰ 마지막 업데이트 (Updated At): {item.get('updated_at', 'Unknown')}")
        print("-" * 60)

        # 4. JSON 데이터 파싱 (실제 알맹이)
        full_data = json.loads(item['data'])
        
        # 5. [핵심] 그룹사와 테마가 섞여 있는지 검증
        total_count = len(full_data)
        
        # 샘플 검사 (삼성 그룹이 있나?)
        samsung_check = "삼성 그룹" in full_data
        # 샘플 검사 (2차전지가 있나?)
        battery_check = "2차전지(생산)" in full_data or "2차전지(장비)" in full_data
        
        print(f"📊 총 수집된 분류 개수: {total_count}개")
        
        if samsung_check:
            print(f"✅ [성공] '삼성 그룹' 데이터가 확인되었습니다! (그룹사 크롤링 성공)")
            print(f"   ㄴ 종목 수: {len(full_data['삼성 그룹'])}개")
        else:
            print(f"❌ [경고] '삼성 그룹'이 안 보입니다. 그룹사 수집 로직을 확인하세요.")

        if battery_check:
            print(f"✅ [성공] '2차전지' 관련 테마가 확인되었습니다! (기존 테마 크롤링 성공)")
        else:
            print(f"❌ [경고] 일반 테마가 안 보입니다.")

        print("-" * 60)
        
        # 6. 데이터 샘플 출력 (3개만)
        print("🔎 데이터 샘플 (랜덤 3개):")
        sample_keys = list(full_data.keys())[:3]
        for key in sample_keys:
            print(f" - {key}: {full_data[key][:5]} ... (총 {len(full_data[key])}종목)")

    except Exception as e:
        print(f"❌ 점검 중 에러 발생: {e}")

if __name__ == "__main__":
    verify_dynamodb_data()