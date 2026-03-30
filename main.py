import os
import csv
import io
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

import requests
import anthropic
import pytz

# ── 환경변수 ──────────────────────────────────────────
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]

# ── KST 기준 오늘 날짜 ────────────────────────────────
kst        = pytz.timezone("Asia/Seoul")
now_kst    = datetime.now(kst)
TODAY      = now_kst.strftime("%Y. %m. %d")
WEEKDAY_KR = "월화수목금토일"[now_kst.weekday()]
TODAY_FILE = now_kst.strftime("%Y%m%d")
TODAY_KR   = now_kst.strftime("%Y년 %m월 %d일") + f"({WEEKDAY_KR})"

# ── RSS 피드 목록 ──────────────────────────────────────
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

# ── 공통 헤더 ─────────────────────────────────────────
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


# ══════════════════════════════════════════════════════
# stooq CSV 한 줄 파싱 헬퍼
# 반환: 최신 종가(float) or None
# ══════════════════════════════════════════════════════
def _stooq_close(symbol: str) -> float | None:
    """
    stooq.com에서 일봉 CSV를 받아 최신 종가를 반환.
    GitHub Actions 환경에서 IP 차단 없이 동작 확인된 소스.
    """
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    try:
        r = requests.get(url, headers={"User-Agent": BROWSER_UA}, timeout=10)
        r.raise_for_status()
        reader = csv.DictReader(io.StringIO(r.text))
        rows = list(reader)
        if not rows:
            return None
        # 최신 날짜 행 (마지막 행)
        last = rows[-1]
        close = last.get("Close") or last.get("close")
        return float(close) if close and close.strip() not in ("", "null") else None
    except Exception as e:
        print(f"⚠️  stooq [{symbol}] 실패: {e}")
        return None


# ══════════════════════════════════════════════════════
# 1. 시장 지표 수집
#    코스피/코스닥 → stooq.com (^ksp / ^kosdaq)
#    USD/KRW      → open.er-api.com (무료, 키 불필요)
#    금값(XAU)    → stooq.com (xauusd) × USD/KRW
#    휘발유       → 오피넷 메인 HTML 스크래핑 (키 불필요)
# ══════════════════════════════════════════════════════
def fetch_market_data() -> dict:
    data = {
        "kospi":    "-",
        "kosdaq":   "-",
        "usd_krw":  "-",
        "gold_krw": "-",
        "gasoline": "-",
    }

    # ── 코스피 ───────────────────────────────────────
    v = _stooq_close("^ksp")
    if v:
        data["kospi"] = f"{v:,.2f}"

    # ── 코스닥 ───────────────────────────────────────
    v = _stooq_close("^kosdaq")
    if v:
        data["kosdaq"] = f"{v:,.2f}"

    # ── USD/KRW ──────────────────────────────────────
    usd_krw_float = None
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD",
                         timeout=8)
        if r.ok:
            usd_krw_float = r.json().get("rates", {}).get("KRW")
            if usd_krw_float:
                data["usd_krw"] = f"{usd_krw_float:,.0f}"
    except Exception as e:
        print(f"⚠️  USD/KRW 실패: {e}")

    # ── 금값 (XAU/USD → 원화 환산) ───────────────────
    xau_usd = _stooq_close("xauusd")
    if xau_usd and usd_krw_float:
        gold_krw = xau_usd * usd_krw_float
        data["gold_krw"] = f"{gold_krw:,.0f}"
    elif xau_usd:
        # 환율 없으면 달러 기준으로만 표시
        data["gold_krw"] = f"${xau_usd:,.0f}"

    # ── 휘발유: 오피넷 메인 HTML 스크래핑 ─────────────
    # 오피넷 키 있으면 API 우선, 없으면 HTML 파싱
    opinet_key = os.environ.get("OPINET_API_KEY", "")
    if opinet_key:
        try:
            r = requests.get(
                f"http://www.opinet.co.kr/api/avgRecentPrice.do"
                f"?out=json&prodcd=B027&code={opinet_key}",
                timeout=8,
            )
            if r.ok:
                items = r.json().get("RESULT", {}).get("OIL", [])
                if items:
                    data["gasoline"] = f"{float(items[0]['PRICE']):,.0f}"
        except Exception as e:
            print(f"⚠️  오피넷 API 실패: {e}")
    else:
        # 키 없을 때: 오피넷 공시가격 페이지 스크래핑
        try:
            r = requests.get(
                "https://www.opinet.co.kr/user/main/mainView.do",
                headers={"User-Agent": BROWSER_UA},
                timeout=10,
            )
            if r.ok:
                # 전국 평균 휘발유 가격 패턴: 숫자 4자리 앞뒤
                matches = re.findall(r"1[,\.]?\d{3}[\.,]\d", r.text)
                prices = []
                for m in matches:
                    try:
                        prices.append(float(m.replace(",", ".")))
                    except Exception:
                        pass
                if prices:
                    # 1700~2200 범위 값만 필터 (휘발유 합리적 범위)
                    valid = [p for p in prices if 1700 <= p <= 2200]
                    if valid:
                        data["gasoline"] = f"{valid[0]:,.1f}"
        except Exception as e:
            print(f"⚠️  오피넷 스크래핑 실패: {e}")

    print(
        f"📊 코스피:{data['kospi']} 코스닥:{data['kosdaq']} "
        f"USD:{data['usd_krw']} 금:{data['gold_krw']} 유가:{data['gasoline']}"
    )
    return data


# ══════════════════════════════════════════════════════
# 2. RSS 뉴스 수집 (기존 유지)
# ══════════════════════════════════════════════════════
def fetch_rss_news(max_per_feed=8):
    articles = []
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }
    yesterday_kst = (now_kst - timedelta(days=1)).date()

    for feed in RSS_FEEDS:
        try:
            resp = requests.get(feed["url"], headers=headers, timeout=15)
            resp.encoding = "utf-8"
            try:
                root = ET.fromstring(resp.content)
            except ET.ParseError:
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
                if not title:
                    continue
                is_recent = False
                try:
                    from email.utils import parsedate_to_datetime
                    if parsedate_to_datetime(pub_date).astimezone(kst).date() >= yesterday_kst:
                        is_recent = True
                except Exception:
                    is_recent = True
                if is_recent:
                    articles.append({"source": feed["name"], "title": title,
                                     "desc": desc[:500], "date": pub_date})
                    count += 1
            print(f"✅ {feed['name']}: {count}개 수집")
        except Exception as e:
            print(f"⚠️  {feed['name']} 실패: {e}")

    print(f"\n📰 총 {len(articles)}개 기사 수집\n")
    return articles


# ══════════════════════════════════════════════════════
# 3. Claude → HTML 카드 생성 (JPY → 금값으로 교체)
# ══════════════════════════════════════════════════════
def generate_card_html(articles, market):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    articles_text = ""
    for i, a in enumerate(articles, 1):
        articles_text += (
            f"\n[{i}] 출처: {a['source']} | 날짜: {a['date']}\n"
            f"제목: {a['title']}\n내용: {a['desc']}\n---"
        )

    kospi    = market["kospi"]
    kosdaq   = market["kosdaq"]
    usd_krw  = market["usd_krw"]
    gold_krw = market["gold_krw"]
    gasoline = market["gasoline"]

    prompt = f"""
아래는 {TODAY_KR} 최신 한국 경제·금융 뉴스 기사들이야.
이 기사들 중에서 가장 중요한 4개를 골라서 아래 HTML 템플릿을 완성해줘.

【규칙】
- 반드시 아래 제공된 기사 내용만 사용 (없는 내용 절대 만들지 말 것)
- 수치는 기사에 명시된 것만 사용. 없으면 수치 없이 작성
- 육하원칙(누가/언제/어디서/무엇을/어떻게/왜)을 지킬 것
- 투자 시사점은 기사 내용에서 논리적으로 도출 가능한 것만 작성
- 전문 애널리스트가 쓴 것처럼 간결하고 직접적으로
- 완성된 HTML 코드만 반환, 다른 설명 없이

【기사 목록】
{articles_text}

【HTML 템플릿 — [대괄호] 부분만 채워서 반환】
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;900&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Noto Sans KR',sans-serif;background:#e8eaf0;display:flex;justify-content:center;padding:20px}}
.card{{width:640px;background:#f0f2f7;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.15)}}
.header{{background:linear-gradient(135deg,#0a1628 0%,#1a2f52 60%,#0d2144 100%);padding:20px 22px 18px;display:flex;justify-content:space-between;align-items:flex-start;gap:12px}}
.header-left{{display:flex;flex-direction:column;gap:4px}}
.good-morning{{font-size:18px;font-weight:900;color:#fff;letter-spacing:1px;display:flex;align-items:center;gap:6px}}
.brand-name{{font-size:13px;font-weight:700;color:#7eb8f7;letter-spacing:2px;text-transform:uppercase;border:1.5px solid #7eb8f7;padding:2px 8px;border-radius:4px;width:fit-content;margin-top:2px}}
.main-title{{font-size:26px;font-weight:900;color:#fff;line-height:1.2;margin-top:6px}}
.main-title .highlight{{color:#ffd700}}
.index-table{{display:flex;flex-direction:column;gap:7px;min-width:210px}}
.index-row{{display:flex;align-items:center;gap:8px;justify-content:flex-end}}
.index-icon{{font-size:15px;width:22px;text-align:center}}
.index-label{{font-size:12px;color:#a0c4f0;font-weight:500;width:90px;text-align:left}}
.index-value{{font-size:15px;font-weight:900;color:#fff;min-width:85px;text-align:right}}
.index-unit{{font-size:11px;color:#a0c4f0;margin-left:2px}}
.date-bar{{background:#dde1ea;padding:8px 22px}}
.date-text{{font-size:15px;font-weight:900;color:#1a2f52}}
.news-section{{padding:0 16px;margin-top:10px}}
.news-item{{border-bottom:1.5px dashed #c0c8d8;padding:10px 6px;display:flex;gap:12px;align-items:flex-start}}
.news-item:last-child{{border-bottom:none}}
.num-badge{{flex-shrink:0;width:26px;height:26px;background:#1a3a6e;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:900;color:#fff;margin-top:2px}}
.news-tag{{display:inline-block;font-size:10px;letter-spacing:1px;color:#1a4080;background:#cddff5;padding:2px 8px;border-radius:4px;font-weight:700;margin-bottom:5px}}
.news-headline{{font-size:14px;font-weight:900;color:#08183a;margin-bottom:5px;line-height:1.4}}
.news-body{{font-size:12px;color:#2c3e60;line-height:1.7}}
.news-body em{{color:#1040a0;font-style:normal;font-weight:700}}
.vocab-section{{background:linear-gradient(135deg,#0a1628 0%,#1a2f52 100%);margin:10px 0 0;padding:14px 18px 16px}}
.vocab-header{{font-size:16px;font-weight:900;color:#ffd700;margin-bottom:8px}}
.vocab-body{{font-size:12px;color:#ccd8ee;line-height:1.75}}
.quote-bar{{background:#0d1e3a;padding:12px 20px;text-align:center}}
.quote-text{{font-size:12px;color:#a0b8d8;font-style:italic;line-height:1.6}}
.quote-source{{font-size:11px;color:#7090b0;margin-top:3px}}
</style>
</head>
<body>
<div class="card">
  <div class="header">
    <div class="header-left">
      <div class="good-morning">☀️ Good Morning</div>
      <div class="brand-name">JW Financial</div>
      <div class="main-title">아침을 깨우는<br><span class="highlight">주요뉴스</span></div>
    </div>
    <div class="index-table">
      <div class="index-row">
        <span class="index-icon">📈</span>
        <span class="index-label">코스피<span style="font-size:10px;color:#7eb8f7">(pt)</span></span>
        <span class="index-value">{kospi} <span class="index-unit">pt</span></span>
      </div>
      <div class="index-row">
        <span class="index-icon">📊</span>
        <span class="index-label">코스닥<span style="font-size:10px;color:#7eb8f7">(pt)</span></span>
        <span class="index-value">{kosdaq} <span class="index-unit">pt</span></span>
      </div>
      <div class="index-row">
        <span class="index-icon">🇺🇸</span>
        <span class="index-label">미국<span style="font-size:10px;color:#7eb8f7">(USD)</span></span>
        <span class="index-value">{usd_krw} <span class="index-unit">원</span></span>
      </div>
      <div class="index-row">
        <span class="index-icon">🥇</span>
        <span class="index-label">금<span style="font-size:10px;color:#7eb8f7">(1온스)</span></span>
        <span class="index-value">{gold_krw} <span class="index-unit">원</span></span>
      </div>
      <div class="index-row">
        <span class="index-icon">⛽</span>
        <span class="index-label">휘발유<span style="font-size:10px;color:#7eb8f7">(리터당)</span></span>
        <span class="index-value">{gasoline} <span class="index-unit">원</span></span>
      </div>
      <div style="text-align:right;margin-top:2px">
        <span style="font-size:9px;color:#7eb8f7">※상기 지수 전일 마감 기준</span>
      </div>
    </div>
  </div>

  <div class="date-bar">
    <div class="date-text">{TODAY_KR}</div>
  </div>

  <div class="news-section">
    <div class="news-item">
      <div class="num-badge">01</div>
      <div>
        <div class="news-tag">[섹터]</div>
        <div class="news-headline">[헤드라인]</div>
        <div class="news-body">[본문 2~3문장. 핵심 수치는 &lt;em&gt;태그로]</div>
      </div>
    </div>
    <div class="news-item">
      <div class="num-badge">02</div>
      <div>
        <div class="news-tag">[섹터]</div>
        <div class="news-headline">[헤드라인]</div>
        <div class="news-body">[본문]</div>
      </div>
    </div>
    <div class="news-item">
      <div class="num-badge">03</div>
      <div>
        <div class="news-tag">[섹터]</div>
        <div class="news-headline">[헤드라인]</div>
        <div class="news-body">[본문]</div>
      </div>
    </div>
    <div class="news-item">
      <div class="num-badge">04</div>
      <div>
        <div class="news-tag">[섹터]</div>
        <div class="news-headline">[헤드라인]</div>
        <div class="news-body">[본문]</div>
      </div>
    </div>
  </div>

  <div class="vocab-section">
    <div class="vocab-header">📌 오늘의 시사&amp;경제용어 : [용어명]</div>
    <div class="vocab-body">[용어 설명 3~4문장]</div>
  </div>

  <div class="quote-bar">
    <div class="quote-text">"[명언]"</div>
    <div class="quote-source">– [출처]</div>
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


# ══════════════════════════════════════════════════════
# 4. HTML → PNG 변환
# ══════════════════════════════════════════════════════
def html_to_png(html_content, output_path):
    with open("temp_card.html", "w", encoding="utf-8") as f:
        f.write(html_content)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 680, "height": 1200})
        page.goto(f"file://{os.path.abspath('temp_card.html')}")
        page.wait_for_timeout(2000)
        page.locator(".card").screenshot(path=output_path)
        browser.close()

    os.remove("temp_card.html")
    print(f"✅ PNG 생성 완료: {output_path}")


# ══════════════════════════════════════════════════════
# 5. 텔레그램 발송
# ══════════════════════════════════════════════════════
def send_to_telegram(image_path, market):
    caption = (
        f"📊 <b>JW Financial 아침 브리핑</b>\n"
        f"{TODAY_KR}\n\n"
        f"코스피 {market['kospi']} | 코스닥 {market['kosdaq']} | "
        f"USD {market['usd_krw']}원 | 금 {market['gold_krw']}원"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    with open(image_path, "rb") as img:
        response = requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"},
            files={"photo": img},
        )
    if response.status_code == 200:
        print("✅ 텔레그램 발송 완료")
    else:
        print(f"❌ 텔레그램 발송 실패: {response.text}")
        raise Exception(f"Telegram error: {response.text}")


# ══════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════
if __name__ == "__main__":
    output_png = f"news_card_{TODAY_FILE}.png"
    print(f"📅 기준 날짜: {TODAY_KR}\n")

    print("📊 시장 지표 수집 중...")
    market = fetch_market_data()

    print("\n📰 RSS 뉴스 수집 중...")
    articles = fetch_rss_news(max_per_feed=8)
    if not articles:
        raise Exception("수집된 기사가 없습니다.")

    print("🎨 카드 HTML 생성 중...")
    html = generate_card_html(articles, market)

    print("🖼️  PNG 변환 중...")
    html_to_png(html, output_png)

    print("📨 텔레그램 발송 중...")
    send_to_telegram(output_png, market)

    print("\n🎉 완료!")
