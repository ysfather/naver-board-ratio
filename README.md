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
4. Build Command: `pip install --upgrade pip setuptools wheel && pip install -r requirements.txt`
5. Start Command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
6. Create Web Service → 배포 URL 접속

### Troubleshooting (Render build fails with pandas / CPython 3.13)
- 증상: Render 로그에 `cpython-313`/`pandas/_libs/... CYTHON_UNUSED ...` 컴파일 오류
- 원인: Render가 Python 3.13을 선택해 Pandas가 소스 빌드되며 실패
- 해결:
  1) **runtime.txt** → `3.11.9`
  2) **render.yaml** → `PYTHON_VERSION=3.11.9`
  3) Build Command에 `pip/setuptools/wheel` 업그레이드 포함
  4) Render → Deploys → **Clear build cache & deploy**
