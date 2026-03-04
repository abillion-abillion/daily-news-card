# 📊 Heomoney Daily News Card

매일 오전 8시, 경제 핵심 뉴스를 자동으로 카드 이미지로 만들어 텔레그램으로 발송합니다.

## 동작 방식

```
GitHub Actions (매일 08:00 KST)
  → Claude AI로 뉴스 수집 + 카드 HTML 생성
  → Playwright로 PNG 변환
  → 텔레그램 봇으로 자동 발송
```

## 설정 방법

### 1. Secrets 등록
GitHub 저장소 → Settings → Secrets and variables → Actions

| 이름 | 내용 |
|------|------|
| `ANTHROPIC_API_KEY` | Anthropic API 키 |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 텔레그램 채팅 ID |

### 2. 수동 테스트
Actions 탭 → Daily News Card → Run workflow

## 파일 구조

```
daily-news-card/
├── main.py                          # 메인 실행 스크립트
├── .github/
│   └── workflows/
│       └── daily_news.yml           # GitHub Actions 설정
└── README.md
```
