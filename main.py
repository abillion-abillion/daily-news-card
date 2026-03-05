import os
import requests
import anthropic
import pytz
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

# ── 환경변수 ──────────────────────────────────────────
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]

# ── KST 기준 오늘 날짜 ────────────────────────────────
kst        = pytz.timezone("Asia/Seoul")
now_kst    = datetime.now(kst)
TODAY      = now_kst.strftime("%Y. %m. %d")
WEEKDAY    = ["MON","TUE","WED","THU","FRI","SAT","SUN"][now_kst.weekday()]
TODAY_FILE = now_kst.strftime("%Y%m%d")
TODAY_KR   = now_kst.strftime("%Y년 %m월 %d일")

# ── RSS 피드 목록 (다양하게 확장) ──────────────────────
RSS_FEEDS = [
    {"name": "한국경제-경제",  "url": "https://www.hankyung.com/feed/economy"},
    {"name": "한국경제-금융",  "url": "https://www.hankyung.com/feed/finance"},
    {"name": "한국경제-증권",  "url": "https://www.hankyung.com/feed/stock"},
    {"name": "연합뉴스-경제",  "url": "https://www.yonhapnews.co.kr/rss/economy.xml"},
    {"name": "연합뉴스-금융",  "url": "https://www.yonhapnews.co.kr/rss/finance.xml"},
    {"name": "매일경제",       "url": "https://www.mk.co.kr/rss/30100041/"},
    {"name": "매일경제-증권",  "url": "https://www.mk.co.kr/rss/30200030/"},
    {"name": "조선비즈",       "url": "https://biz.chosun.com/arc/outboundfeeds/rss/?outputType=xml"},
    {"name": "SBS-경제",       "url": "https://news.sbs.co.kr/news/RSS.jsp?cateId=economy"},
    {"name": "KBS-경제",       "url": "https://news.kbs.co.kr/rss/news/news_economy.xml"},
]

# ── 1. RSS에서 뉴스 수집 ──────────────────────────────
def fetch_rss_news(max_per_feed=8):
    """RSS 피드에서 최신 기사 수집 (날짜 필터 완화)"""
    articles = []
    headers  = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }

    # 오늘 + 어제까지 허용 (pubDate 형식 불일치 대비)
    today_kst     = now_kst.date()
    yesterday_kst = (now_kst - timedelta(days=1)).date()

    for feed in RSS_FEEDS:
        try:
            resp = requests.get(feed["url"], headers=headers, timeout=15)
            resp.encoding = "utf-8"

            # XML 파싱
            try:
                root = ET.fromstring(resp.content)
            except ET.ParseError:
                # 인코딩 문제 시 재시도
                content = resp.content.decode("euc-kr", errors="replace").encode("utf-8")
                root = ET.fromstring(content)

            items = root.findall(".//item")
            count = 0

            for item in items:
                if count >= max_per_feed:
                    break

                title    = item.findtext("title", "").strip()
                pub_date = item.findtext("pubDate", "")
                desc     = re.sub(r"<[^>]+>", "", item.findtext("description", "")).strip()

                # 제목 없으면 스킵
                if not title:
                    continue

                # pubDate 파싱 시도
                is_recent = False
                try:
                    # RFC 2822 형식: "Wed, 05 Mar 2026 08:30:00 +0900"
                    from email.utils import parsedate_to_datetime
                    pub_dt    = parsedate_to_datetime(pub_date)
                    pub_date_kst = pub_dt.astimezone(kst).date()
                    if pub_date_kst >= yesterday_kst:
                        is_recent = True
                except Exception:
                    # 날짜 파싱 실패 시 일단 포함 (제목으로 판단)
                    is_recent = True

                if is_recent:
                    articles.append({
                        "source": feed["name"],
                        "title":  title,
                        "desc":   desc[:300],
                        "date":   pub_date,
                    })
                    count += 1

            print(f"✅ {feed['name']}: {count}개 수집")

        except Exception as e:
            print(f"⚠️  {feed['name']} 실패: {e}")

    print(f"\n📰 총 {len(articles)}개 기사 수집\n")
    return articles


# ── 2. Claude로 카드 HTML 생성 ────────────────────────
def generate_card_html(articles):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    articles_text = ""
    for i, a in enumerate(articles, 1):
        articles_text += f"\n[{i}] 출처: {a['source']} | 날짜: {a['date']}\n제목: {a['title']}\n내용: {a['desc']}\n---"

    prompt = f"""
아래는 {TODAY_KR} 최신 한국 경제·금융 뉴스 기사들이야.
이 기사들 중에서 가장 중요한 5개를 골라서 아래 HTML 템플릿을 완성해줘.

【규칙】
- 반드시 아래 제공된 기사 내용만 사용 (없는 내용 절대 만들지 말 것)
- 육하원칙(누가/언제/어디서/무엇을/어떻게/왜)을 지킬 것
- 향후 투자 시사점을 본문에 자연스럽게 이어서 작성
- 전문 애널리스트가 쓴 것처럼 간결하고 직접적으로. AI가 쓴 느낌 없게
- 핵심 수치는 <em> 태그로 강조
- 완성된 HTML 코드만 반환, 다른 설명 없이

【기사 목록】
{articles_text}

【HTML 템플릿 — [대괄호] 부분만 채워서 반환】
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;600;700&family=Noto+Sans+KR:wght@300;400;500;700&display=swap" rel="stylesheet">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ width: 800px; background: #f0f4f9; font-family: 'Noto Sans KR', sans-serif; color: #1a2540; }}
  .card {{ width: 800px; background: #f0f4f9; }}
  .header-block {{ background: linear-gradient(135deg, #1a3a6e 0%, #1e4d8c 60%, #2563a8 100%); padding: 40px 52px 36px; position: relative; overflow: hidden; }}
  .header-block::before {{ content: ''; position: absolute; top: -60px; right: -60px; width: 280px; height: 280px; background: radial-gradient(circle, rgba(255,255,255,0.06) 0%, transparent 70%); }}
  .header-block::after {{ content: ''; position: absolute; bottom: 0; left: 0; right: 0; height: 3px; background: linear-gradient(90deg, #4a9fe8, #7bc4f5, #4a9fe8); }}
  .header-top {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; }}
  .brand {{ font-size: 10px; letter-spacing: 3.5px; color: rgba(180,210,255,0.7); text-transform: uppercase; font-weight: 500; }}
  .date-badge {{ background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.15); border-radius: 20px; padding: 4px 14px; font-size: 11px; color: rgba(200,225,255,0.8); letter-spacing: 0.5px; }}
  .header-title {{ font-family: 'Noto Serif KR', serif; font-size: 28px; font-weight: 700; color: #ffffff; line-height: 1.25; margin-bottom: 14px; letter-spacing: -0.5px; }}
  .alert-strip {{ display: flex; align-items: center; gap: 10px; background: rgba(255,80,80,0.15); border: 1px solid rgba(255,120,120,0.25); border-radius: 6px; padding: 9px 15px; }}
  .alert-dot {{ width: 6px; height: 6px; background: #ff6b6b; border-radius: 50%; flex-shrink: 0; }}
  .alert-text {{ font-size: 12px; color: rgba(255,180,180,0.95); font-weight: 400; }}
  .body {{ padding: 32px 52px 36px; }}
  .news-item {{ display: flex; gap: 20px; padding: 20px 0; border-bottom: 1px solid #dce6f0; }}
  .news-item:last-child {{ border-bottom: none; }}
  .num-col {{ flex-shrink: 0; width: 36px; padding-top: 2px; }}
  .num-circle {{ width: 28px; height: 28px; background: #1e4d8c; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; color: #fff; }}
  .news-tag {{ display: inline-block; font-size: 9.5px; letter-spacing: 1.5px; color: #2563a8; text-transform: uppercase; margin-bottom: 5px; font-weight: 600; background: #e3edf9; padding: 2px 8px; border-radius: 3px; }}
  .news-headline {{ font-size: 14.5px; font-weight: 700; color: #0f2040; margin-bottom: 7px; line-height: 1.4; letter-spacing: -0.3px; }}
  .news-body {{ font-size: 12.5px; color: #506080; line-height: 1.78; font-weight: 300; }}
  .news-body em {{ color: #1e4d8c; font-style: normal; font-weight: 600; }}
  .special-section {{ background: #1a3a6e; border-radius: 12px; padding: 26px 28px; margin-top: 8px; }}
  .special-badge {{ display: inline-block; font-size: 9.5px; letter-spacing: 2px; color: #7bc4f5; text-transform: uppercase; font-weight: 600; background: rgba(120,190,245,0.12); padding: 3px 10px; border-radius: 3px; border: 1px solid rgba(120,190,245,0.2); margin-bottom: 14px; }}
  .special-title {{ font-size: 14px; font-weight: 700; color: #e8f2ff; margin-bottom: 16px; line-height: 1.45; }}
  .reason-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }}
  .reason-item {{ background: rgba(255,255,255,0.05); border-radius: 8px; padding: 14px 15px; border-left: 3px solid #4a9fe8; }}
  .reason-num {{ font-size: 9px; letter-spacing: 1.5px; color: #4a9fe8; font-weight: 700; margin-bottom: 6px; text-transform: uppercase; }}
  .reason-title {{ font-size: 12.5px; font-weight: 700; color: #c8dff5; margin-bottom: 6px; line-height: 1.3; }}
  .reason-desc {{ font-size: 11px; color: rgba(160,190,220,0.75); line-height: 1.65; font-weight: 300; }}
  .footer {{ background: #1a2540; padding: 16px 52px; display: flex; align-items: center; justify-content: space-between; }}
  .footer-keyword {{ font-size: 11.5px; color: rgba(180,200,230,0.6); }}
  .footer-keyword strong {{ color: #7bc4f5; font-weight: 600; }}
  .footer-brand {{ font-size: 10px; color: rgba(180,200,230,0.35); letter-spacing: 2px; text-transform: uppercase; }}
</style>
</head>
<body>
<div class="card">
  <div class="header-block">
    <div class="header-top">
      <div class="brand">Heomoney · Daily Market Brief</div>
      <div class="date-badge">{TODAY}  {WEEKDAY}</div>
    </div>
    <div class="header-title">오늘의 경제 핵심 뉴스</div>
    <div class="alert-strip">
      <div class="alert-dot"></div>
      <div class="alert-text">[오늘 가장 중요한 이슈 3개를 · 로 구분해서 한 줄로]</div>
    </div>
  </div>
  <div class="body">
    <div class="news-item">
      <div class="num-col"><div class="num-circle">01</div></div>
      <div class="news-content">
        <div class="news-tag">[섹터]</div>
        <div class="news-headline">[헤드라인]</div>
        <div class="news-body">[본문 3~4문장. 육하원칙 + 투자 시사점]</div>
      </div>
    </div>
    <div class="news-item">
      <div class="num-col"><div class="num-circle">02</div></div>
      <div class="news-content">
        <div class="news-tag">[섹터]</div>
        <div class="news-headline">[헤드라인]</div>
        <div class="news-body">[본문]</div>
      </div>
    </div>
    <div class="news-item">
      <div class="num-col"><div class="num-circle">03</div></div>
      <div class="news-content">
        <div class="news-tag">[섹터]</div>
        <div class="news-headline">[헤드라인]</div>
        <div class="news-body">[본문]</div>
      </div>
    </div>
    <div class="news-item">
      <div class="num-col"><div class="num-circle">04</div></div>
      <div class="news-content">
        <div class="news-tag">[섹터]</div>
        <div class="news-headline">[헤드라인]</div>
        <div class="news-body">[본문]</div>
      </div>
    </div>
    <div class="news-item">
      <div class="num-col"><div class="num-circle">05</div></div>
      <div class="news-content">
        <div class="news-tag">[섹터]</div>
        <div class="news-headline">[헤드라인]</div>
        <div class="news-body">[본문]</div>
      </div>
    </div>
    <div class="special-section">
      <div class="special-badge">Deep Dive · 심층 분석</div>
      <div class="special-title">[오늘 가장 중요한 이슈 심층 분석 제목]</div>
      <div class="reason-grid">
        <div class="reason-item">
          <div class="reason-num">Point 01</div>
          <div class="reason-title">[포인트1 제목]</div>
          <div class="reason-desc">[설명 2~3문장]</div>
        </div>
        <div class="reason-item">
          <div class="reason-num">Point 02</div>
          <div class="reason-title">[포인트2 제목]</div>
          <div class="reason-desc">[설명]</div>
        </div>
        <div class="reason-item">
          <div class="reason-num">Point 03</div>
          <div class="reason-title">[포인트3 제목]</div>
          <div class="reason-desc">[설명]</div>
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
        messages=[{"role": "user", "content": prompt}]
    )

    html_content = message.content[0].text
    if "```html" in html_content:
        html_content = html_content.split("```html")[1].split("```")[0].strip()
    elif "```" in html_content:
        html_content = html_content.split("```")[1].split("```")[0].strip()

    return html_content


# ── 3. HTML → PNG 변환 ────────────────────────────────
def html_to_png(html_content, output_path):
    with open("temp_card.html", "w", encoding="utf-8") as f:
        f.write(html_content)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 800, "height": 1200})
        page.goto(f"file://{os.path.abspath('temp_card.html')}")
        page.wait_for_timeout(2000)
        page.screenshot(path=output_path, full_page=True)
        browser.close()

    os.remove("temp_card.html")
    print(f"✅ PNG 생성 완료: {output_path}")


# ── 4. 텔레그램 발송 ──────────────────────────────────
def send_to_telegram(image_path):
    caption  = f"📊 {TODAY_KR} 경제 핵심 뉴스\nHeomoney Daily Brief"
    url      = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"

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
    output_png = f"news_card_{TODAY_FILE}.png"

    print(f"📅 기준 날짜: {TODAY_KR} (KST)\n")

    print("📰 RSS 뉴스 수집 중...")
    articles = fetch_rss_news(max_per_feed=8)

    if not articles:
        raise Exception("수집된 기사가 없습니다. RSS 피드를 확인해주세요.")

    print("🎨 카드 HTML 생성 중...")
    html = generate_card_html(articles)

    print("🖼️  PNG 변환 중...")
    html_to_png(html, output_png)

    print("📨 텔레그램 발송 중...")
    send_to_telegram(output_png)

    print("\n🎉 완료!")
