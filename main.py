import os
import time
import math
import asyncio
import threading
from typing import Optional, Tuple, List, Dict, Any, Set

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pymodbus.client import ModbusSerialClient

# =========================================================
# App
# =========================================================
app = FastAPI(
    title="NARIT CM Cleanroom API (RS485 Sensor)",
    version="3.1"
)

# =========================================================
# Static (Sensor Web UI – ถ้ามี)
# =========================================================
STATIC_DIR = os.getenv("STATIC_DIR", "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def root():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return {"ok": True, "service": "naritcm-lidar-api", "docs": "/docs"}


# =========================================================
# Health
# =========================================================
@app.get("/health")
def health():
    return {"ok": True, "service": "naritcm-lidar-api", "version": "3.1"}


# =========================================================
# Sensor (RS485 + Dew Point)
# =========================================================
SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/ttyACM0")
BAUDRATE = int(os.getenv("BAUDRATE", "9600"))
PARITY = os.getenv("PARITY", "N")
BYTESIZE = int(os.getenv("BYTESIZE", "8"))
STOPBITS = int(os.getenv("STOPBITS", "1"))
TIMEOUT_S = float(os.getenv("TIMEOUT_S", "1.0"))

READ_TABLE = os.getenv("READ_TABLE", "holding").lower()  # holding | input
REG_START = int(os.getenv("REG_START", "0"))
REG_COUNT = int(os.getenv("REG_COUNT", "2"))

TEMP_INDEX = int(os.getenv("TEMP_INDEX", "1"))
HUMI_INDEX = int(os.getenv("HUMI_INDEX", "0"))
SCALE_DIV = float(os.getenv("SCALE_DIV", "10"))

room1_ID = int(os.getenv("room1", "1"))
OUTDOOR_ID = int(os.getenv("OUTDOOR_ID", "2"))

POLL_MS = int(os.getenv("POLL_MS", "1000"))

modbus = ModbusSerialClient(
    port=SERIAL_PORT,
    baudrate=BAUDRATE,
    bytesize=BYTESIZE,
    parity=PARITY,
    stopbits=STOPBITS,
    timeout=TIMEOUT_S,
)

_modbus_lock = threading.Lock()


def ensure_connected():
    with _modbus_lock:
        if not modbus.connected:
            if not modbus.connect():
                raise RuntimeError("Modbus not connected")


def read_raw_regs(unit_id: int) -> Tuple[int, ...]:
    ensure_connected()
    with _modbus_lock:
        if READ_TABLE == "input":
            rr = modbus.read_input_registers(REG_START, REG_COUNT, slave=unit_id)
        else:
            rr = modbus.read_holding_registers(REG_START, REG_COUNT, slave=unit_id)
    if rr.isError():
        raise RuntimeError(f"Modbus Error: {rr}")
    return tuple(rr.registers)


# def to_humi_temp(regs: Tuple[int, ...]) -> Tuple[float, float]:
#     humi = regs[HUMI_INDEX] / SCALE_DIV
#     temp = regs[TEMP_INDEX] / SCALE_DIV
#     return humi, temp

def to_humi_temp(regs):
    humi = regs[HUMI_INDEX] / SCALE_DIV
    temp = regs[TEMP_INDEX] / SCALE_DIV
    return humi, temp


def calc_dewpoint(temp_c: float, rh: float) -> float:
    """
    Dew point (°C) using Magnus formula
    """
    if rh <= 0:
        return float("nan")
    a = 17.62
    b = 243.12
    gamma = math.log(rh / 100.0) + (a * temp_c) / (b + temp_c)
    return (b * gamma) / (a - gamma)


@app.get("/api/sensor/{unit_id}")
def read_sensor_unit(unit_id: int):
    try:
        regs = read_raw_regs(unit_id)
        humi, temp = to_humi_temp(regs)
        dew = calc_dewpoint(temp, humi)
        name = "room1" if unit_id == room1_ID else (
            "outdoor" if unit_id == OUTDOOR_ID else f"unit_{unit_id}"
        )
        return {
            "ok": True,
            "name": name,
            "unit_id": unit_id,
            "raw_registers": regs,
            "humi": round(humi, 1),
            "temp": round(temp, 1),
            "dewpoint": round(dew, 1),
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "unit_id": unit_id, "error": str(e)}
        )


@app.get("/api/sensor")
def read_sensor_both():
    out: Dict[str, Any] = {"ok": True}

    try:
        r1 = read_raw_regs(room1_ID)
        h1, t1 = to_humi_temp(r1)
        d1 = calc_dewpoint(t1, h1)
        out["room1"] = {
            "unit_id": room1_ID,
            "raw": r1,
            "humi": round(h1, 1),
            "temp": round(t1, 1),
            "dewpoint": round(d1, 1),
        }
    except Exception as e:
        out["room1"] = {"unit_id": room1_ID, "error": str(e)}
        out["ok"] = False

    try:
        r2 = read_raw_regs(OUTDOOR_ID)
        h2, t2 = to_humi_temp(r2)
        d2 = calc_dewpoint(t2, h2)
        out["outdoor"] = {
            "unit_id": OUTDOOR_ID,
            "raw": r2,
            "humi": round(h2, 1),
            "temp": round(t2, 1),
            "dewpoint": round(d2, 1),
        }
    except Exception as e:
        out["outdoor"] = {"unit_id": OUTDOOR_ID, "error": str(e)}
        out["ok"] = False

    return out


# =========================================================
# WebSocket Sensor Realtime
# =========================================================
ws_clients: Set[WebSocket] = set()


@app.websocket("/ws/sensor")
async def ws_sensor(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(ws)


async def sensor_poll_loop():
    while True:
        payload = {"ts": int(time.time() * 1000), "ok": True}

        def pack(unit_id: int):
            regs = read_raw_regs(unit_id)
            h, t = to_humi_temp(regs)
            d = calc_dewpoint(t, h)
            return {
                "unit_id": unit_id,
                "temp": round(t, 1),
                "humi": round(h, 1),
                "dewpoint": round(d, 1),
            }

        try:
            payload["room1"] = pack(room1_ID)
            payload["outdoor"] = pack(OUTDOOR_ID)
        except Exception as e:
            payload["ok"] = False
            payload["error"] = str(e)

        dead = []
        for ws in ws_clients:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)

        for ws in dead:
            ws_clients.discard(ws)

        await asyncio.sleep(POLL_MS / 1000.0)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(sensor_poll_loop())


@app.on_event("shutdown")
async def shutdown_event():
    try:
        modbus.close()
    except Exception:
        pass
