import json
import requests
import boto3
from bs4 import BeautifulSoup
from datetime import datetime
import time

# ==============================================================================
# 1. 네이버 테마/종목 전체 크롤러 (검증 완료된 로직)
# ==============================================================================
def scrape_all_themes_and_stocks():
    """
    네이버 금융의 모든 테마와 해당 테마에 속한 모든 종목 코드를 수집합니다.
    Return: {'테마명': ['005930', '000660', ...], ...}
    """
    all_themes = {}
    
    # 헤더 설정 (차단 방지)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://finance.naver.com/sise/theme.naver'
    }
    
    print("🕵️ 테마 데이터 수집 시작 (Page 1 ~ 9)...")
    
    # 페이지 순회 (검증 결과 9페이지까지 데이터 존재)
    for page in range(1, 10): 
        try:
            # 등락률 순 정렬 URL
            url = f"https://finance.naver.com/sise/theme.naver?field=change_rate&ordering=desc&page={page}"
            res = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(res.content.decode('euc-kr', 'replace'), 'html.parser')
            
            # 테마 리스트 테이블 (type_1)
            rows = soup.select('table.type_1 tr')
            
            count_in_page = 0
            
            for row in rows:
                cols = row.select('td')
                
                # [로직 1] 빈 줄(blank_07) 건너뛰기
                if len(cols) < 2: 
                    continue
                
                # 테마 링크 태그 찾기
                link = cols[0].select_one('a')
                if not link: 
                    continue
                
                theme_name = link.text.strip()
                theme_url = "https://finance.naver.com" + link['href']
                
                # [로직 2] 상세 페이지에서 종목 코드들 긁어오기
                stock_codes = get_stock_codes_from_detail(theme_url, headers)
                
                if stock_codes:
                    all_themes[theme_name] = stock_codes
                    count_in_page += 1
            
            print(f"   ✅ Page {page} 완료 ({count_in_page}개 테마)")
            
            # 페이지 끝 도달 체크 (테마가 없으면 종료)
            if count_in_page == 0:
                break
                
            # 차단 방지용 딜레이
            time.sleep(0.05)
                
        except Exception as e:
            print(f"❌ Page {page} 크롤링 중 에러: {e}")
            
    return all_themes

def get_stock_codes_from_detail(url, headers):
    """
    테마 상세 페이지에서 종목 코드 리스트만 추출
    """
    codes = []
    try:
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.content.decode('euc-kr', 'replace'), 'html.parser')
        
        # 상세 페이지 종목 테이블 (type_5)
        rows = soup.select('table.type_5 tr')
        
        for row in rows:
            # [로직 3] td.name 아래의 a 태그 찾기 (검증됨)
            name_tag = row.select_one('td.name a')
            
            if name_tag and 'href' in name_tag.attrs:
                href = name_tag['href']
                if 'code=' in href:
                    code = href.split('code=')[1]
                    codes.append(code)
    except:
        pass 
        
    return codes

# ==============================================================================
# 2. Lambda 핸들러
# ==============================================================================
def lambda_handler(event, context):
    print("=== 🚀 StockThemeCrawler Lambda 시작 ===")
    
    # 1. 크롤링 수행
    final_data = scrape_all_themes_and_stocks()
    
    theme_count = len(final_data)
    total_stocks = sum(len(codes) for codes in final_data.values())
    
    print(f"=== 수집 결과: 테마 {theme_count}개 / 종목 {total_stocks}개 ===")
    
    if theme_count == 0:
        return {
            "statusCode": 500, 
            "body": json.dumps("수집된 테마가 0개입니다. 로그를 확인하세요.")
        }

    # 2. DynamoDB 저장
    try:
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('StockThemeGroups')
        
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        # 데이터 저장 (JSON 문자열로 변환)
        # 400KB 제한 안전권: 6000종목 * 6바이트 + 키값 해도 약 60~100KB 수준임.
        item = {
            'date': 'today_map',
            'real_date': today_str,
            'data': json.dumps(final_data, ensure_ascii=False),
            'updated_at': str(datetime.now())
        }
        
        table.put_item(Item=item)
        print("✅ DynamoDB 저장 성공 (Key: today_map)")
        
        return {
            "statusCode": 200, 
            "body": json.dumps(f"Success! Themes: {theme_count}, Stocks: {total_stocks}")
        }
        
    except Exception as e:
        print(f"❌ DynamoDB 저장 실패: {e}")
        return {
            "statusCode": 500, 
            "body": json.dumps(f"DB Error: {str(e)}")
        }