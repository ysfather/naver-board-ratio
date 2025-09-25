# Naver Board Ratio (FastAPI, GitHub+Render)

FastAPI 백엔드 + 단일 HTML UI. 네이버 종목토론판 `today/yday` 글수 비율과 `todayreturn(%)`을 수집·정렬하고 Excel(3시트)로 내려받습니다.

## 로컬 실행
```bash
pip install -r requirements.txt
uvicorn app:app --reload
# http://127.0.0.1:8000  접속
```

## Render 배포
1. 이 리포를 GitHub에 업로드
2. https://render.com → New + → **Web Service**
3. 리포 선택 → Environment **Python**
4. Build Command: `pip install -r requirements.txt`
5. Start Command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
6. Create Web Service → 배포 URL 접속

### 운영 팁
- **속도**: conc 24~48, delay 10~30ms 권장(과도하면 429 가능성↑)
- **정확도**: minYday=5로 어제 글 0인 종목 제외
- **부하 절감**: topn/pages를 줄이거나 codes에 직접 입력

> 본 도구는 공개 웹페이지 파싱에 기반합니다. 대상 사이트의 구조가 바뀌면 엔드포인트/파싱 로직을 업데이트하세요.
