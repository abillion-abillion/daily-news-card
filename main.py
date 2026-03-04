import os
import json
import requests
import anthropic
from datetime import datetime
from playwright.sync_api import sync_playwright

# ── 환경변수 ──────────────────────────────────────────
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]

# ── 1. Anthropic으로 뉴스 수집 + 카드 HTML 생성 ───────
def generate_news_card_html() -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    today = datetime.now().strftime("%Y. %m. %d")
    weekday = ["MON","TUE","WED","THU","FRI","SAT","SUN"][datetime.now().weekday()]

    prompt = f"""
오늘({today})의 한국 경제·금융 핵심 뉴스 5가지와 주식시장 동향을 조사해서,
아래 HTML 템플릿의 [PLACEHOLDER] 부분을 실제 내용으로 채워서 완성된 HTML 전체를 반환해줘.

규칙:
- 육하원칙(누가/언제/어디서/무엇을/어떻게/왜)을 지킬 것
- 향후 투자 시사점을 자연스럽게 이어서 작성할 것
- AI가 쓴 느낌 없이 전문 애널리스트가 쓴 것처럼 간결하고 직접적으로
- 숫자와 팩트 중심으로
- 핵심 수치는 <em> 태그로 강조
- 웹 검색을 통해 실제 오늘 뉴스를 반영할 것
- HTML 코드만 반환, 다른 설명 없이

[TODAY] = {today}
[WEEKDAY] = {weekday}

HTML 템플릿:
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>오늘의 경제 브리핑</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;600;700&family=Noto+Sans+KR:wght@300;400;500;700&display=swap" rel="stylesheet">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ width: 800px; background: #f0f4f9; font-family: 'Noto Sans KR', sans-serif; color: #1a2540; }}
  .card {{ width: 800px; background: #f0f4f9; position: relative; overflow: hidden; }}
  .header-block {{
    background: linear-gradient(135deg, #1a3a6e 0%, #1e4d8c 60%, #2563a8 100%);
    padding: 40px 52px 36px; position: relative; overflow: hidden;
  }}
  .header-block::before {{
    content: ''; position: absolute; top: -60px; right: -60px;
    width: 280px; height: 280px;
    background: radial-gradient(circle, rgba(255,255,255,0.06) 0%, transparent 70%);
  }}
  .header-block::after {{
    content: ''; position: absolute; bottom: 0; left: 0; right: 0; height: 3px;
    background: linear-gradient(90deg, #4a9fe8, #7bc4f5, #4a9fe8);
  }}
  .header-top {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; }}
  .brand {{ font-size: 10px; letter-spacing: 3.5px; color: rgba(180,210,255,0.7); text-transform: uppercase; font-weight: 500; }}
  .date-badge {{
    background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.15);
    border-radius: 20px; padding: 4px 14px; font-size: 11px;
    color: rgba(200,225,255,0.8); letter-spacing: 0.5px;
  }}
  .header-title {{
    font-family: 'Noto Serif KR', serif; font-size: 28px; font-weight: 700;
    color: #ffffff; line-height: 1.25; margin-bottom: 14px; letter-spacing: -0.5px;
  }}
  .alert-strip {{
    display: flex; align-items: center; gap: 10px;
    background: rgba(255,80,80,0.15); border: 1px solid rgba(255,120,120,0.25);
    border-radius: 6px; padding: 9px 15px;
  }}
  .alert-dot {{
    width: 6px; height: 6px; background: #ff6b6b; border-radius: 50%;
    flex-shrink: 0; box-shadow: 0 0 8px rgba(255,100,100,0.7);
  }}
  .alert-text {{ font-size: 12px; color: rgba(255,180,180,0.95); font-weight: 400; letter-spacing: 0.2px; }}
  .body {{ padding: 32px 52px 36px; }}
  .news-item {{ display: flex; gap: 20px; padding: 20px 0; border-bottom: 1px solid #dce6f0; }}
  .news-item:last-child {{ border-bottom: none; }}
  .num-col {{ flex-shrink: 0; width: 36px; padding-top: 2px; }}
  .num-circle {{
    width: 28px; height: 28px; background: #1e4d8c; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 11px; font-weight: 700; color: #fff;
  }}
  .news-tag {{
    display: inline-block; font-size: 9.5px; letter-spacing: 1.5px; color: #2563a8;
    text-transform: uppercase; margin-bottom: 5px; font-weight: 600;
    background: #e3edf9; padding: 2px 8px; border-radius: 3px;
  }}
  .news-headline {{ font-size: 14.5px; font-weight: 700; color: #0f2040; margin-bottom: 7px; line-height: 1.4; letter-spacing: -0.3px; }}
  .news-body {{ font-size: 12.5px; color: #506080; line-height: 1.78; font-weight: 300; }}
  .news-body em {{ color: #1e4d8c; font-style: normal; font-weight: 600; }}
  .special-section {{ background: #1a3a6e; border-radius: 12px; padding: 26px 28px; margin-top: 8px; }}
  .special-badge {{
    display: inline-block; font-size: 9.5px; letter-spacing: 2px; color: #7bc4f5;
    text-transform: uppercase; font-weight: 600;
    background: rgba(120,190,245,0.12); padding: 3px 10px; border-radius: 3px;
    border: 1px solid rgba(120,190,245,0.2); margin-bottom: 14px;
  }}
  .special-title {{ font-size: 14px; font-weight: 700; color: #e8f2ff; margin-bottom: 16px; line-height: 1.45; }}
  .reason-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }}
  .reason-item {{ background: rgba(255,255,255,0.05); border-radius: 8px; padding: 14px 15px; border-left: 3px solid #4a9fe8; }}
  .reason-num {{ font-size: 9px; letter-spacing: 1.5px; color: #4a9fe8; font-weight: 700; margin-bottom: 6px; text-transform: uppercase; }}
  .reason-title {{ font-size: 12.5px; font-weight: 700; color: #c8dff5; margin-bottom: 6px; line-height: 1.3; }}
  .reason-desc {{ font-size: 11px; color: rgba(160,190,220,0.75); line-height: 1.65; font-weight: 300; }}
  .footer {{
    background: #1a2540; padding: 16px 52px;
    display: flex; align-items: center; justify-content: space-between;
  }}
  .footer-keyword {{ font-size: 11.5px; color: rgba(180,200,230,0.6); letter-spacing: 0.3px; }}
  .footer-keyword strong {{ color: #7bc4f5; font-weight: 600; }}
  .footer-brand {{ font-size: 10px; color: rgba(180,200,230,0.35); letter-spacing: 2px; text-transform: uppercase; }}
</style>
</head>
<body>
<div class="card">
  <div class="header-block">
    <div class="header-top">
      <div class="brand">Heomoney · Daily Market Brief</div>
      <div class="date-badge">[TODAY]  [WEEKDAY]</div>
    </div>
    <div class="header-title">오늘의 경제 핵심 뉴스</div>
    <div class="alert-strip">
      <div class="alert-dot"></div>
      <div class="alert-text">[오늘의 핵심 알림 한 줄 — 가장 중요한 이슈 3개를 · 로 구분]</div>
    </div>
  </div>

  <div class="body">
    <div class="news-item">
      <div class="num-col"><div class="num-circle">01</div></div>
      <div class="news-content">
        <div class="news-tag">[섹터태그1]</div>
        <div class="news-headline">[뉴스1 헤드라인]</div>
        <div class="news-body">[뉴스1 본문 — 육하원칙 + 향후 시사점 자연스럽게 이어서, 3~4문장]</div>
      </div>
    </div>
    <div class="news-item">
      <div class="num-col"><div class="num-circle">02</div></div>
      <div class="news-content">
        <div class="news-tag">[섹터태그2]</div>
        <div class="news-headline">[뉴스2 헤드라인]</div>
        <div class="news-body">[뉴스2 본문]</div>
      </div>
    </div>
    <div class="news-item">
      <div class="num-col"><div class="num-circle">03</div></div>
      <div class="news-content">
        <div class="news-tag">[섹터태그3]</div>
        <div class="news-headline">[뉴스3 헤드라인]</div>
        <div class="news-body">[뉴스3 본문]</div>
      </div>
    </div>
    <div class="news-item">
      <div class="num-col"><div class="num-circle">04</div></div>
      <div class="news-content">
        <div class="news-tag">[섹터태그4]</div>
        <div class="news-headline">[뉴스4 헤드라인]</div>
        <div class="news-body">[뉴스4 본문]</div>
      </div>
    </div>
    <div class="news-item">
      <div class="num-col"><div class="num-circle">05</div></div>
      <div class="news-content">
        <div class="news-tag">[섹터태그5]</div>
        <div class="news-headline">[뉴스5 헤드라인]</div>
        <div class="news-body">[뉴스5 본문]</div>
      </div>
    </div>

    <div class="special-section">
      <div class="special-badge">Deep Dive · 심층 분석</div>
      <div class="special-title">[오늘 가장 중요한 이슈에 대한 심층 분석 제목]</div>
      <div class="reason-grid">
        <div class="reason-item">
          <div class="reason-num">Point 01</div>
          <div class="reason-title">[포인트1 제목]</div>
          <div class="reason-desc">[포인트1 설명 2~3문장]</div>
        </div>
        <div class="reason-item">
          <div class="reason-num">Point 02</div>
          <div class="reason-title">[포인트2 제목]</div>
          <div class="reason-desc">[포인트2 설명]</div>
        </div>
        <div class="reason-item">
          <div class="reason-num">Point 03</div>
          <div class="reason-title">[포인트3 제목]</div>
          <div class="reason-desc">[포인트3 설명]</div>
        </div>
      </div>
    </div>
  </div>

  <div class="footer">
    <div class="footer-keyword">
      오늘의 키워드 &nbsp;·&nbsp;
      <strong>[키워드1]</strong> → <strong>[키워드2]</strong> → <strong>[키워드3]</strong>
    </div>
    <div class="footer-brand">Heomoney</div>
  </div>
</div>
</body>
</html>
"""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search"
        }],
        messages=[{"role": "user", "content": prompt}]
    )

    # 응답에서 HTML 추출
    html_content = ""
    for block in message.content:
        if block.type == "text":
            html_content += block.text

    # ```html 코드블록 제거
    if "```html" in html_content:
        html_content = html_content.split("```html")[1].split("```")[0].strip()
    elif "```" in html_content:
        html_content = html_content.split("```")[1].split("```")[0].strip()

    return html_content


# ── 2. HTML → PNG 변환 ────────────────────────────────
def html_to_png(html_content: str, output_path: str):
    with open("temp_card.html", "w", encoding="utf-8") as f:
        f.write(html_content)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 800, "height": 1200})
        page.goto(f"file://{os.path.abspath('temp_card.html')}")
        page.wait_for_timeout(2000)  # 폰트 로딩 대기
        page.screenshot(path=output_path, full_page=True)
        browser.close()

    os.remove("temp_card.html")
    print(f"✅ PNG 생성 완료: {output_path}")


# ── 3. 텔레그램으로 이미지 발송 ──────────────────────
def send_to_telegram(image_path: str):
    today_str = datetime.now().strftime("%Y년 %m월 %d일")
    caption = f"📊 {today_str} 경제 핵심 뉴스\nHeomoney Daily Brief"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    with open(image_path, "rb") as img:
        response = requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": caption
        }, files={"photo": img})

    if response.status_code == 200:
        print("✅ 텔레그램 발송 완료")
    else:
        print(f"❌ 텔레그램 발송 실패: {response.text}")
        raise Exception(f"Telegram error: {response.text}")


# ── 메인 실행 ─────────────────────────────────────────
if __name__ == "__main__":
    today_file = datetime.now().strftime("%Y%m%d")
    output_png = f"news_card_{today_file}.png"

    print("🔍 뉴스 수집 및 카드 생성 중...")
    html = generate_news_card_html()

    print("🖼️  PNG 변환 중...")
    html_to_png(html, output_png)

    print("📨 텔레그램 발송 중...")
    send_to_telegram(output_png)

    print("🎉 완료!")
