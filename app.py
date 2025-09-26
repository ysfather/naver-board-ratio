from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uuid, asyncio, time
from datetime import datetime
import pandas as pd
from io import BytesIO

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")

JOBS = {}
RESULTS = {}

@app.get("/")
def root():
    return FileResponse("static/index.html")

@app.post("/api/run")
async def api_run(payload: dict):
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"status": "queued", "started_at": time.time(), "progress": 0, "message": ""}
    asyncio.create_task(worker(job_id, payload))
    return {"id": job_id}

async def worker(job_id: str, payload: dict):
    try:
        JOBS[job_id]["status"] = "running"
        await asyncio.sleep(0.1)
        # TODO: 여기서 실제 크롤러를 호출하도록 연결하세요.
        df = pd.DataFrame([
            {"code":"005930","name":"삼성전자","today":10,"yday":5,"ratio":2.0,"todayreturn":1.23},
            {"code":"000660","name":"SK하이닉스","today":9,"yday":3,"ratio":3.0,"todayreturn":-0.45},
        ])
        RESULTS[job_id] = {"rows": df.to_dict(orient="records"), "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        JOBS[job_id]["progress"] = 100
        JOBS[job_id]["status"] = "finished"
        JOBS[job_id]["message"] = "ok"
    except Exception as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["message"] = str(e)

@app.get("/api/status")
def api_status(id: str):
    job = JOBS.get(id)
    if not job:
        raise HTTPException(status_code=404, detail="unknown job id")
    return job

@app.get("/api/result")
def api_result(id: str):
    data = RESULTS.get(id)
    if not data:
        raise HTTPException(status_code=404, detail="result not ready")
    return data

@app.get("/api/excel")
def api_excel(id: str):
    data = RESULTS.get(id)
    if not data:
        raise HTTPException(status_code=404, detail="result not ready")
    df = pd.DataFrame(data["rows"])
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="all")
    bio.seek(0)
    return StreamingResponse(bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="board_ratio_log.xlsx"'})