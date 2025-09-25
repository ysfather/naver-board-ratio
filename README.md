# Naver Board Ratio (FastAPI) — Python 3.11 + pandas
- Render에서 Python 3.11.9로 고정 (runtime.txt + render.yaml)
- pandas 2.2.2 wheel 사용

## Render 설정
- Build: pip install --upgrade pip setuptools wheel && pip install -r requirements.txt
- Start: uvicorn app:app --host 0.0.0.0 --port $PORT
- Env: PYTHON_VERSION=3.11.9
