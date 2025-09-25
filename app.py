import re, asyncio, time, uuid, io, math
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

KST = timezone(timedelta(hours=9))

app = FastAPI(title="Naver Board Ratio Service", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

# Static UI
app.mount("/", StaticFiles(directory="static", html=True), name="static")

# ---------------- In-memory Job Store ----------------
JOBS: Dict[str, Dict[str, Any]] = {}

def new_job() -> str:
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {
        "status": "pending", "progress": "queued",
        "started_at": None, "finished_at": None,
        "result": None, "error": None,
    }
    return job_id

def set_progress(job_id: str, msg: str):
    job = JOBS.get(job_id)
    if job: job["progress"] = msg

def set_status(job_id: str, status: str):
    job = JOBS.get(job_id)
    if job: job["status"] = status

def set_error(job_id: str, err: str):
    job = JOBS.get(job_id)
    if job:
        job["status"] = "error"
        job["error"] = err
        job["finished_at"] = datetime.now(KST).isoformat()

# ---------------- Scraper Core ----------------
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8"}

DATE_RE = re.compile(r"(20\d{2})\.(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})")
BOARD_URLS = [
    "https://finance.naver.com/item/board.nhn?code={code}&page={page}",
    "https://finance.naver.com/item/board.naver?code={code}&page={page}",
]
MKT_URLS = [
    "https://finance.naver.com/sise/sise_market_sum.nhn?sosok={sosok}&page={page}",
    "https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}",
]
ITEM_URL = "https://finance.naver.com/item/main.nhn?code={code}"

def now_kst() -> datetime: return datetime.now(KST)
def ymd(dt: datetime) -> str: return dt.strftime("%Y-%m-%d")

async def request_text(client: httpx.AsyncClient, url: str) -> str:
    r = await client.get(url, headers=HEADERS, timeout=30); r.raise_for_status(); return r.text

async def request_json(client: httpx.AsyncClient, url: str) -> Any:
    r = await client.get(url, headers=HEADERS, timeout=30); r.raise_for_status(); return r.json()

def parse_board_dates(html: str) -> List[datetime]:
    out = []
    for m in DATE_RE.finditer(html):
        y, mo, d, hh, mm = map(int, m.groups())
        dt = datetime(y, mo, d, hh, mm, tzinfo=KST)
        out.append(dt)
    return out

async def fetch_board_page(client: httpx.AsyncClient, code: str, page: int) -> str:
    for tmpl in BOARD_URLS:
        url = tmpl.format(code=code, page=page)
        try:
            return await request_text(client, url)
        except Exception:
            continue
    return ""

async def count_board(client: httpx.AsyncClient, code: str, pages: int, delay_ms: int) -> Dict[str, int]:
    today, yday, scanned = 0, 0, 0
    today_s = ymd(now_kst()); yday_s = ymd(now_kst() - timedelta(days=1))
    for p in range(1, pages + 1):
        html = await fetch_board_page(client, code, p)
        scanned += 1
        if not html: continue
        dts = parse_board_dates(html)
        if not dts: continue
        for dt in dts:
            s = ymd(dt)
            if s == today_s: today += 1
            elif s == yday_s: yday += 1
        if ymd(min(dts)) < yday_s: break
        if delay_ms > 0: await asyncio.sleep(delay_ms / 1000)
    return {"today": today, "yday": yday, "scanned": scanned}

async def extract_codes(client: httpx.AsyncClient, market_pages: int, topn: int, delay_ms: int) -> List[str]:
    codes: List[str] = []
    for sosok in (0, 1):
        for p in range(1, market_pages + 1):
            ok = False
            for tmpl in MKT_URLS:
                url = tmpl.format(sosok=sosok, page=p)
                try:
                    html = await request_text(client, url)
                    found = re.findall(r"item\/main\.(?:nhn|naver)\?code=(\d{6})", html)
                    if found: codes.extend(found)
                    ok = True; break
                except Exception:
                    continue
            if not ok: continue
            d = max(delay_ms, 80)
            await asyncio.sleep(d / 1000)
    uniq = list(dict.fromkeys(codes))
    return uniq[:topn]

async def fetch_name(client: httpx.AsyncClient, code: str) -> str:
    try:
        d = await request_json(client, f"https://api.finance.naver.com/service/itemSummary.nhn?itemcode={code}")
        if isinstance(d, dict) and d.get("stockName"): return str(d["stockName"])
    except Exception: pass
    try:
        html = await request_text(client, ITEM_URL.format(code=code))
        m = re.search(r'<div\s+class="wrap_company"[^>]*>[\s\S]*?<h2[^>]*>(.*?)</h2>', html, re.I)
        if m:
            name = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            if name: return name
        t = re.search(r"<title>\s*(.*?)\s*:\s*네이버\s*금융\s*</title>", html)
        if t: return t.group(1).strip()
    except Exception: pass
    return code

def _deep_find_number(obj: Any, keys: List[str]) -> Optional[float]:
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if v is not None and not isinstance(v, (dict, list)) and str(k) in keys:
                    try: return float(str(v).replace(",", ""))
                    except Exception: pass
                if isinstance(v, (dict, list)): stack.append(v)
        elif isinstance(cur, list): stack.extend(cur)
    return None

async def fetch_today_return(client: httpx.AsyncClient, code: str) -> Optional[float]:
    try:
        d1 = await request_json(client, f"https://api.finance.naver.com/service/itemSummary.nhn?itemcode={code}")
        if isinstance(d1, dict):
            fr = d1.get("fluctuationRate", d1.get("fluctuation"))
            if fr is not None: return float(str(fr).replace(",", ""))
            got = _deep_find_number(d1, ["fluctuationRate","fluctuationsRatio","compareToPreviousCloseRatio","rate"])
            if got is not None: return got
            close = d1.get("closePrice") or d1.get("close") or d1.get("now")
            prev  = d1.get("prevClose") or d1.get("prev") or d1.get("yesterday")
            if close is not None and prev is not None:
                cp, pp = float(str(close).replace(",","")), float(str(prev).replace(",",""))
                if pp: return (cp/pp - 1) * 100
    except Exception: pass
    try:
        d2 = await request_json(client, f"https://m.stock.naver.com/api/stock/{code}/basic")
        if isinstance(d2, dict):
            for k in ["fluctuationsRatio","compareToPreviousCloseRatio","rate"]:
                if d2.get(k) is not None: return float(str(d2[k]).replace(",", ""))
            got = _deep_find_number(d2, ["fluctuationsRatio","compareToPreviousCloseRatio","rate"])
            if got is not None: return got
            cp, pp = d2.get("closePrice"), d2.get("prevClosePrice") or d2.get("previousClosePrice")
            if cp is not None and pp is not None:
                cp, pp = float(str(cp).replace(",","")), float(str(pp).replace(",",""))
                if pp: return (cp/pp - 1) * 100
    except Exception: pass
    try:
        d3 = await request_json(client, f"https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:{code}")
        infos = d3.get("realtimeStockInfos") or d3.get("result") or d3.get("datas") or []
        if isinstance(infos, list) and infos:
            got = _deep_find_number(infos[0], ["fluctuationsRatio","fluctuationRate","rate"])
            if got is not None: return got
        elif isinstance(infos, dict):
            got = _deep_find_number(infos, ["fluctuationsRatio","fluctuationRate","rate"])
            if got is not None: return got
    except Exception: pass
    return None

def is_nan(x) -> bool:
    try: return math.isnan(float(x))
    except Exception: return False

async def core_run(params: Dict[str, Any]):
    market_pages = int(params.get("marketPages", 3))
    topn = int(params.get("topn", 200))
    pages = int(params.get("pages", 10))
    topk = int(params.get("topk", 50))
    minYday = int(params.get("minYday", 5))
    conc = max(1, min(96, int(params.get("conc", 24))))
    delay = max(0, min(500, int(params.get("delay", 20))))
    codes_raw = str(params.get("codes", "") or "").strip()

    limits = httpx.Limits(max_keepalive_connections=conc, max_connections=conc)
    async with httpx.AsyncClient(headers=HEADERS, timeout=30, limits=limits) as client:
        set_progress(params["job_id"], f"코드 수집 중… (동시성={conc}, 대기={delay}ms)")
        if codes_raw:
            codes = [c.strip() for c in re.split(r"[,\s]+", codes_raw) if c.strip()]
        else:
            codes = await extract_codes(client, market_pages, topn, delay)
        set_progress(params["job_id"], f"코드 {len(codes)}개 수집 완료 → 종목명 매핑 중…")

        sem = asyncio.Semaphore(conc)
        async def _name(c):
            async with sem:
                try: return c, await fetch_name(client, c)
                except Exception: return c, c
        names_pairs = await asyncio.gather(*[_name(c) for c in codes])
        name_map = dict(names_pairs)

        set_progress(params["job_id"], f"종목명 매핑 완료 → 게시판 집계 중…")
        async def _board(c):
            async with sem:
                r = await count_board(client, c, pages, delay)
                ratio = (r["today"] / r["yday"]) if r["yday"] > 0 else float("nan")
                return {
                    "code": c, "name": name_map.get(c, c),
                    "today": r["today"], "yday": r["yday"], "ratio": ratio,
                    "todayreturn": float("nan"), "scanned_pages": r["scanned"],
                    "note": "" if r["yday"] > 0 else ("excluded: yday=0" if r["today"] > 0 else "no data; excluded")
                }
        board_res: List[Dict[str, Any]] = await asyncio.gather(*[_board(c) for c in codes])

        usable = [r for r in board_res if (r["yday"] or 0) >= minYday]
        def sort_key(r):
            rr = -1e18 if is_nan(r["ratio"]) else -float(r["ratio"])
            return (rr, -int(r["today"]))
        rank = sorted(usable, key=sort_key)
        rankTop = rank[:topk]

        set_progress(params["job_id"], f"todayreturn 수집 중… (TOPK {len(rankTop)}개)")
        async def _ret(r):
            async with sem:
                v = await fetch_today_return(client, r["code"])
                if v is not None: r["todayreturn"] = float(v)
                return r
        rankTop = await asyncio.gather(*[_ret(dict(r)) for r in rankTop])

        set_progress(params["job_id"], f"todayreturn 수집 중… (전체 {len(board_res)}개)")
        board_res = await asyncio.gather(*[_ret(r) for r in board_res])

    def fmt_ratio(v):
        try: return round(float(v), 4)
        except Exception: return None
    def fmt_ret(v):
        try: return round(float(v), 2)
        except Exception: return None

    # Sort again for export
    rankTop_sorted = sorted(rankTop, key=sort_key)
    up10 = [r for r in rankTop_sorted if not is_nan(r.get("todayreturn", float("nan")))]
    up10 = sorted(up10, key=lambda r: -float(r["todayreturn"]))[:10]
    dn10 = [r for r in rankTop_sorted if not is_nan(r.get("todayreturn", float("nan")))]
    dn10 = sorted(dn10, key=lambda r: float(r["todayreturn"]))[:10]
    all_sorted = sorted(board_res, key=sort_key)

    ts = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "ts": ts,
        "params": {
            "marketPages": market_pages, "topn": topn, "pages": pages,
            "topk": topk, "minYday": minYday, "conc": conc, "delay": delay
        },
        "rankTop": [{
            "code": r["code"], "name": r["name"],
            "today": int(r["today"]), "yday": int(r["yday"]),
            "ratio": (None if is_nan(r["ratio"]) else round(float(r["ratio"]), 2)),
            "todayreturn": (None if is_nan(r["todayreturn"]) else round(float(r["todayreturn"]), 2)),
            "note": r.get("note") or ""
        } for r in rankTop_sorted],
        "top10_up": [{
            "ts": ts, "code": r["code"], "name": r["name"],
            "today": int(r["today"]), "yday": int(r["yday"]),
            "ratio": fmt_ratio(r["ratio"]),
            "todayreturn": fmt_ret(r["todayreturn"]),
        } for r in up10],
        "top10_down": [{
            "ts": ts, "code": r["code"], "name": r["name"],
            "today": int(r["today"]), "yday": int(r["yday"]),
            "ratio": fmt_ratio(r["ratio"]),
            "todayreturn": fmt_ret(r["todayreturn"]),
        } for r in dn10],
        "all_export": [{
            "ts": ts, "code": r["code"], "name": r["name"],
            "today": int(r["today"]), "yday": int(r["yday"]),
            "ratio": fmt_ratio(r["ratio"]),
            "todayreturn": fmt_ret(r["todayreturn"]),
            "note": r.get("note") or ""
        } for r in all_sorted],
    }

import pandas as pd

@app.get("/api/excel")
async def api_excel(id: str):
    if id not in JOBS: raise HTTPException(404, "result not ready")
    j = JOBS[id]
    if j["status"] != "done" or not j["result"]: raise HTTPException(404, "result not ready")
    res = j["result"]
    all_df = pd.DataFrame(res["all_export"])
    up_df = pd.DataFrame(res["top10_up"])
    dn_df = pd.DataFrame(res["top10_down"])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        all_df.to_excel(xw, index=False, sheet_name="all")
        up_df.to_excel(xw, index=False, sheet_name="top10_up")
        dn_df.to_excel(xw, index=False, sheet_name="top10_down")
    buf.seek(0)
    filename = f"board_ratio_log_{res['ts'].replace(':','').replace(' ','_')}.xlsx"
    return Response(
        content=buf.read(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename=\"{filename}\"'}
    )

@app.post("/api/run")
async def api_run(payload: Dict[str, Any]):
    job_id = new_job()
    t0 = time.perf_counter()
    try:
        set_status(job_id, "running")
        JOBS[job_id]["started_at"] = datetime.now(KST).isoformat()
        payload = payload or {}
        payload["job_id"] = job_id
        result = await core_run(payload)
        dur_s = time.perf_counter() - t0
        if dur_s >= 3600: dur = f"{int(dur_s//3600)}시간 {int(dur_s%3600//60)}분 {int(dur_s%60)}초"
        elif dur_s >= 60: dur = f"{int(dur_s//60)}분 {int(dur_s%60)}초"
        else: dur = f"{int(dur_s)}초"
        result["duration"] = dur
        JOBS[job_id]["result"] = result
        JOBS[job_id]["finished_at"] = datetime.now(KST).isoformat()
        set_status(job_id, "done")
        set_progress(job_id, f"완료")
    except Exception as e:
        set_error(job_id, f"{type(e).__name__}: {e}")
    return {"job_id": job_id}

@app.get("/api/status")
async def api_status(id: str):
    if id not in JOBS: raise HTTPException(404, "job not found")
    j = JOBS[id]
    return {
        "status": j["status"], "progress": j["progress"],
        "started_at": j["started_at"], "finished_at": j["finished_at"],
        "has_result": j["result"] is not None, "error": j["error"],
    }

@app.get("/api/result")
async def api_result(id: str):
    if id not in JOBS: raise HTTPException(404, "result not ready")
    j = JOBS[id]
    if j["status"] != "done" or not j["result"]: raise HTTPException(404, "result not ready")
    return j["result"]
