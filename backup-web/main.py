import os
import httpx
from datetime import datetime
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Cleanroom Backup")

INFLUX_URL    = os.getenv("INFLUX_URL",    "http://influxdb:8086")
INFLUX_ORG    = os.getenv("INFLUX_ORG",    "Narit")
INFLUX_TOKEN  = os.getenv("INFLUX_TOKEN",  "")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "Cleanroom")
MEASUREMENT   = os.getenv("MEASUREMENT",   "room2")


@app.get("/api/health")
async def health():
    return {"status": "ok", "influx_url": INFLUX_URL, "org": INFLUX_ORG, "bucket": INFLUX_BUCKET}


@app.get("/api/buckets")
async def list_buckets():
    url = f"{INFLUX_URL}/api/v2/buckets?org={INFLUX_ORG}"
    headers = {"Authorization": f"Token {INFLUX_TOKEN}"}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        data = resp.json()
        buckets = [b["name"] for b in data.get("buckets", []) if not b["name"].startswith("_")]
        return {"buckets": buckets}


@app.get("/api/stats")
async def get_stats(
    bucket: str = Query(None),
    months: int = Query(3, description="จำนวนเดือนย้อนหลัง"),
):
    selected_bucket = bucket or INFLUX_BUCKET
    flux = f"""from(bucket:"{selected_bucket}")
  |> range(start: -{months * 31}d, stop: now())
  |> filter(fn: (r) => r._field != "")
  |> aggregateWindow(every: 1d, fn: count, createEmpty: false)
  |> group(columns: ["_time"])
  |> sum()
  |> map(fn: (r) => ({{ r with day: string(v: r._time) }}))"""

    url = f"{INFLUX_URL}/api/v2/query?org={INFLUX_ORG}"
    headers = {
        "Authorization": f"Token {INFLUX_TOKEN}",
        "Content-Type":  "application/vnd.flux",
        "Accept":        "application/csv",
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, headers=headers, content=flux)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)

        lines = resp.text.strip().split("\n")
        days = {}
        for line in lines:
            if not line or line.startswith("#") or line.startswith(",result"):
                continue
            parts = line.split(",")
            if len(parts) < 6:
                continue
            try:
                time_str = parts[5]
                count    = int(float(parts[6])) if len(parts) > 6 else 0
                day = time_str[:10]
                if day:
                    days[day] = days.get(day, 0) + count
            except (ValueError, IndexError):
                continue

        return {"days": days, "bucket": selected_bucket}


@app.get("/api/export")
async def export_csv(
    start:  str = Query(...),
    stop:   str = Query(...),
    bucket: str = Query(None),
):
    selected_bucket = bucket or INFLUX_BUCKET
    flux = f"""from(bucket:"{selected_bucket}")
  |> range(start: {start}, stop: {stop})"""

    url = f"{INFLUX_URL}/api/v2/query?org={INFLUX_ORG}"
    headers = {
        "Authorization": f"Token {INFLUX_TOKEN}",
        "Content-Type":  "application/vnd.flux",
        "Accept":        "application/csv",
    }

    async def stream_csv():
        async with httpx.AsyncClient(timeout=600) as client:
            async with client.stream("POST", url, headers=headers, content=flux) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise HTTPException(status_code=resp.status_code, detail=body.decode())
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    yield chunk

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{selected_bucket}_{ts}.csv"

    return StreamingResponse(
        stream_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


app.mount("/", StaticFiles(directory="static", html=True), name="static")
