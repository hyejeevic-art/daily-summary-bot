import os
import sys
import requests
import re
from bs4 import BeautifulSoup
from datetime import datetime
import feedparser
import urllib.parse
import google.generativeai as genai

# 환경 변수에서 키 불러오기 (GitHub Actions Secrets에서 주입됨)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

def get_stock_data(mode):
    """모드(morning/afternoon)에 따라 주요 주식 지수 변동을 가져옵니다."""
    if mode == "morning":
        tickers = {
            "S&P 500": "^GSPC",
            "NASDAQ 100": "^NDX"
        }
    elif mode == "afternoon":
        tickers = {
            "KOSPI": "^KS11",
            "KOSDAQ": "^KQ11"
        }
    else:
        return ""

    stock_info = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    
    for name, ticker in tickers.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=5d&interval=1d"
            res = requests.get(url, headers=headers)
            res.raise_for_status()
            data = res.json()
            
            close_prices = data['chart']['result'][0]['indicators']['quote'][0]['close']
            valid_closes = [p for p in close_prices if p is not None]
            
            if len(valid_closes) >= 2:
                prev_close = valid_closes[-2]
                current_close = valid_closes[-1]
                change_pct = ((current_close - prev_close) / prev_close) * 100
                
                # 상승/하락 직관적 표시
                trend_emoji = "🔴" if change_pct > 0 else "🔵" if change_pct < 0 else "⚪"
                stock_info.append(f"{trend_emoji} {name}: {current_close:,.2f} ({change_pct:+.2f}%)")
            else:
                stock_info.append(f"⚠️ {name}: 데이터를 충분히 가져오지 못했습니다.")
        except Exception as e:
            stock_info.append(f"❌ {name}: 데이터 불러오기 실패 ({e})")
            
    return "\n".join(stock_info)

def get_surging_stocks():
    """오늘 장에서 20% 이상 상승한 급등주와 그 섹터 정보를 가져옵니다."""
    headers = {'User-Agent': 'Mozilla/5.0'}
    surging_list = []
    
    # 0: KOSPI, 1: KOSDAQ
    for sosok in [0, 1]:
        url = f"https://finance.naver.com/sise/sise_rise.naver?sosok={sosok}"
        try:
            res = requests.get(url, headers=headers)
            soup = BeautifulSoup(res.text, 'html.parser')
            tables = soup.find_all('table', {'class': 'type_2'})
            if not tables:
                continue
                
            for tr in tables[0].find_all('tr'):
                tds = tr.find_all('td')
                if len(tds) >= 7:
                    try:
                        a_tag = tds[1].find('a')
                        if not a_tag:
                            continue
                        name = a_tag.text.strip()
                        code = a_tag['href'].split('code=')[1]
                        
                        rate_text = tds[4].text.strip().replace('%', '').replace('+', '').replace('-', '').replace(',', '')
                        rate = float(rate_text)
                        
                        if '+' in tds[4].text and rate >= 20.0:
                            # 섹터(업종) 정보 가져오기
                            sector = "기타"
                            item_url = f"https://finance.naver.com/item/main.naver?code={code}"
                            item_res = requests.get(item_url, headers=headers)
                            item_soup = BeautifulSoup(item_res.text, 'html.parser')
                            section = item_soup.find('div', {'class': 'section trade_compare'})
                            if section:
                                h4 = section.find('h4', {'class': 'h_sub sub_tit7'})
                                if h4 and h4.find('em'):
                                    sector_text = h4.find('em').text
                                    match = re.search(r"업종명\s*:\s*([^｜\|]+)", sector_text)
                                    if match:
                                        sector = match.group(1).strip()
                            
                            surging_list.append(f"🚀 {name} (+{rate:.2f}%) - {sector}")
                    except Exception:
                        continue
        except Exception as e:
            print(f"Scraping failed for sosok {sosok}: {e}")
            
    if not surging_list:
        return "20% 이상 급등한 종목이 없습니다."
    
    return "\n".join(surging_list)

def get_us_surging_stocks():
    """미국 증시에서 20% 이상 상승한 급등주 목록을 가져옵니다."""
    url = 'https://finance.yahoo.com/gainers'
    headers = {'User-Agent': 'Mozilla/5.0'}
    surging_list = []
    
    try:
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, 'html.parser')
        rows = soup.find_all('tr')
        
        for row in rows[1:15]:
            cols = row.find_all('td')
            if len(cols) > 4:
                symbol = cols[0].text.strip()
                name = cols[1].text.strip()
                change_pct_text = cols[4].text.strip().replace('%', '').replace('+', '').replace(',', '')
                try:
                    change_pct = float(change_pct_text)
                    if change_pct >= 20.0:
                        surging_list.append(f"🚀 {symbol} ({name}): +{change_pct:.2f}%")
                except:
                    pass
    except Exception as e:
        print("US Surging Stocks error:", e)
        
    if not surging_list:
        return "20% 이상 급등한 종목이 없습니다."
    
    return "\n".join(surging_list)

def get_us_economy_news():
    """구글 뉴스 RSS를 통해 미국 경제 최신 뉴스를 가져옵니다."""
    news_list = []
    try:
        query = urllib.parse.quote("미국 경제")
        feed_url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
        feed = feedparser.parse(feed_url)
        if feed.entries:
            for entry in feed.entries[:3]:
                news_list.append(f"📰 {entry.title}\n👉 {entry.link}")
    except Exception as e:
        print("US Economy News error:", e)
        
    if not news_list:
        return "최신 미국 경제 뉴스를 가져오지 못했습니다."
    
    return "\n\n".join(news_list)

def get_twitter_news():
    """주요 인물의 최근 발언/트윗 관련 동향 뉴스를 가져옵니다."""
    accounts = {
        "도널드 트럼프": "도널드 트럼프 트위터 OR 발언 when:1d",
        "일론 머스크": "일론 머스크 X OR 트위터 when:1d",
        "이재명 대통령": "이재명 트위터 OR 발언 when:1d"
    }
    news_text = []
    
    for name, query in accounts.items():
        try:
            encoded_query = urllib.parse.quote(query)
            feed_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
            feed = feedparser.parse(feed_url)
            news_text.append(f"👤 {name}:")
            if feed.entries:
                for entry in feed.entries[:2]: # 최근 2개 주요 기사만 추출
                    news_text.append(f" - {entry.title}")
            else:
                news_text.append(" - 최근 주요 발언/트윗 동향이 없습니다.")
        except Exception:
            news_text.append(f"👤 {name}:\n - 데이터를 불러오지 못했습니다.")
            
    return "\n".join(news_text)

def generate_ai_briefing(stock_text, surging_text, news_text, twitter_text):
    """제공된 데이터를 바탕으로 AI 투자 브리핑을 생성합니다."""
    if not GEMINI_API_KEY:
        return "⚠️ API 키가 설정되지 않아 AI 브리핑을 생성할 수 없습니다."
        
    system_prompt = """
    You are an advanced investment intelligence and trend-following analysis assistant.
    Your role is to:
    - Analyze financial news, macroeconomic data, and market structure
    - Identify trend direction and momentum across major asset classes
    - Combine fundamental news with technical market context (trend-following perspective)
    - Produce structured, actionable investment insights (not direct buy/sell advice)

    Core focus:
    1. Macro-driven market interpretation
    2. Trend-following (momentum, trend strength, regime detection)
    3. Risk awareness and volatility shifts
    4. Sector rotation signals
    5. Institutional sentiment inference

    You should think like a systematic trend-following macro trader.
    지구상의 모든 데이터를 분석해 수익을 내는 투자가 될 수 있도록 해.

    반드시 다음의 출력 구조를 그대로 따르고, 내용을 한국어로 작성해:

    [Daily Investment & Trend Briefing]

    🧭 1. Market Regime (Trend State)
    - Overall market regime: (상승장/하락장/횡보/전환기)
    - Risk sentiment: (Risk-on / Risk-off / Mixed)
    - Trend strength: (Strong / Weak / Shifting)

    📈 2. Trend-Following View (Key Indices)
    - S&P 500: 트렌드 방향 및 모멘텀
    - Nasdaq: 트렌드 방향 및 모멘텀
    - Russell 2000: 리스크 선호도 시그널
    - DXY (Dollar Index): 매크로 압력 시그널
    - US 10Y Yield: 매크로 레짐 인디케이터

    📊 3. Sector Momentum (Rotation Signals)
    - Strongest sectors:
    - Weakest sectors:
    - Emerging momentum sectors:

    📰 4. Key News Impact (Market Drivers)
    - 1.
    - 2.
    - 3.

    ⚠️ 5. Risk Signals
    - Trend breakdown risks:
    - Macro shocks:
    - Volatility expansion signals:

    🚀 6. Opportunities (Trend-Following Lens)
    - Assets in strong uptrend:
    - Breakout candidates (macro-driven):
    - Momentum continuation setups:

    🧠 7. Final Insight (Trader Interpretation)
    - 시장 체제, 트렌드 방향, 리스크 포지션 등을 종합 해석하여 3-5 문장으로 요약.

    주의사항: 마크다운 기호(*, _, # 등)는 텔레그램 파싱 오류를 유발할 수 있으므로 절대 사용하지 말고, 문단을 명확하게 구분해.
    """
    
    user_prompt = f"""
    아래 수집된 데이터를 바탕으로 투자 브리핑을 작성해줘:
    
    [미국 지수 마감]
    {stock_text}
    
    [미국 20% 이상 급등주]
    {surging_text}
    
    [미국 경제 주요 뉴스]
    {news_text}
    
    [주요 인사 최근 발언/트윗]
    {twitter_text}
    """
    
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(
            contents=[
                {"role": "user", "parts": [system_prompt + "\n\n" + user_prompt]}
            ]
        )
        # 텔레그램 전송 에러 방지용 마크다운 기호 필터링
        text = response.text.replace('*', '').replace('#', '').replace('_', '').strip()
        return text
    except Exception as e:
        return f"⚠️ AI 브리핑 생성 중 오류가 발생했습니다: {e}"

def send_telegram_message(message):
    """텔레그램 봇을 통해 메시지를 전송합니다."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram Token 또는 Chat ID가 설정되지 않았습니다.")
        print("생성된 메시지:\n", message)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print("텔레그램 메시지 전송 성공!")
    except Exception as e:
        print(f"텔레그램 메시지 전송 실패: {e}")

def main():
    if len(sys.argv) < 2:
        print("사용법: python main.py [morning|afternoon]")
        sys.exit(1)
        
    mode = sys.argv[1]
    today_str = datetime.now().strftime("%Y년 %m월 %d일")
    
    if mode == "morning":
        print("아침 브리핑 데이터 수집 중...")
        stock_text = get_stock_data("morning")
        us_surging_text = get_us_surging_stocks()
        us_news_text = get_us_economy_news()
        twitter_news_text = get_twitter_news()
        
        print("AI 투자 브리핑 생성 중...")
        ai_briefing = generate_ai_briefing(stock_text, us_surging_text, us_news_text, twitter_news_text)
        
        final_message = f"🌅 {today_str} 전문 투자 브리핑\n\n🧠 [AI Market Insight]\n{ai_briefing}\n\n=========================\n\n📈 [미국 증시 마감 시황]\n{stock_text}\n\n🔥 [미국 20% 이상 급등주]\n{us_surging_text}\n\n📊 [미국 경제 주요 뉴스]\n{us_news_text}\n\n🗣️ [주요 인사 최근 발언/트윗 동향]\n{twitter_news_text}"
        
        # 트위터 원문 링크 추가
        final_message += "\n\n🔗 공식 X(트위터) 원문 링크:\n"
        twitter_links = {
            "도널드 트럼프": "https://x.com/realDonaldTrump",
            "일론 머스크": "https://x.com/elonmusk",
            "이재명 대통령": "https://x.com/Jaemyung_Lee"
        }
        for name, link in twitter_links.items():
            final_message += f"- {name}: {link}\n"
            
    elif mode == "afternoon":
        print("오후 브리핑 데이터 수집 중...")
        stock_text = get_stock_data("afternoon")
        surging_text = get_surging_stocks()
        final_message = f"🌇 {today_str} 오후 브리핑\n\n📊 [국내 증시 마감 시황]\n{stock_text}\n\n🔥 [오늘의 급등주 (20% 이상)]\n{surging_text}"
    else:
        print("잘못된 모드입니다. morning 또는 afternoon을 입력하세요.")
        sys.exit(1)
    
    print("텔레그램으로 전송 중...")
    send_telegram_message(final_message)

if __name__ == "__main__":
    main()
