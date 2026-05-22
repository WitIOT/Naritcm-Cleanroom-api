# NARIT CM Cleanroom API

FastAPI service for reading temperature and humidity from RS485 Modbus sensors, calculating dew point, and exposing the values through REST API, WebSocket, and an optional static web UI.

## Features

- Read RS485 Modbus RTU sensors through `pymodbus`
- Support holding registers or input registers
- Return humidity, temperature, dew point, and raw register values
- Poll sensors in the background and broadcast realtime values over WebSocket
- Serve `static/index.html` at `/` when the static UI exists
- Run locally with Uvicorn or in Docker Compose with mapped serial devices

## Project Structure

```text
.
|-- main.py              # FastAPI app, Modbus polling, REST API, WebSocket
|-- modbus_client.py     # Small reusable RS485 Modbus helper
|-- static/              # Optional web UI served by FastAPI
|-- Dockerfile           # Python 3.11 image for the API
|-- docker-compose.yml   # Container config and device mapping
`-- requirements.txt     # Python dependencies
```

## API Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | Serve `static/index.html` if available, otherwise return service status |
| `GET` | `/health` | Health check |
| `GET` | `/api/sensor` | Read indoor room sensor and outdoor sensor |
| `GET` | `/api/sensor/{unit_id}` | Read one sensor by Modbus unit ID |
| `WS` | `/ws/sensor` | Realtime sensor updates |
| `GET` | `/docs` | Swagger/OpenAPI documentation |

Example response from `/api/sensor`:

```json
{
  "ok": true,
  "room1": {
    "unit_id": 1,
    "raw": [650, 250],
    "humi": 65.0,
    "temp": 25.0,
    "dewpoint": 17.9
  },
  "outdoor": {
    "unit_id": 2,
    "raw": [700, 280],
    "humi": 70.0,
    "temp": 28.0,
    "dewpoint": 22.0
  }
}
```

## Configuration

The service is configured through environment variables.

| Variable | Default | Description |
| --- | --- | --- |
| `STATIC_DIR` | `static` | Static UI directory |
| `SERIAL_PORT` | `/dev/ttyACM0` | Serial device inside the app/container |
| `BAUDRATE` | `9600` | Modbus baud rate |
| `PARITY` | `N` | Serial parity |
| `BYTESIZE` | `8` | Serial byte size |
| `STOPBITS` | `1` | Serial stop bits |
| `TIMEOUT_S` | `1.0` | Modbus timeout in seconds |
| `READ_TABLE` | `holding` | Register table: `holding` or `input` |
| `REG_START` | `0` | First register address to read |
| `REG_COUNT` | `2` | Number of registers to read |
| `HUMI_INDEX` | `0` | Register index used for humidity |
| `TEMP_INDEX` | `1` | Register index used for temperature |
| `SCALE_DIV` | `10` | Divider for raw sensor values |
| `room1` | `1` | Indoor sensor Modbus unit ID |
| `OUTDOOR_ID` | `2` | Outdoor sensor Modbus unit ID |
| `POLL_MS` | `1000` | WebSocket polling interval in milliseconds |

Note: `main.py` currently reads the indoor unit ID from the lowercase environment variable `room1`.

## Run With Docker Compose

Edit the device mapping in `docker-compose.yml` to match the host machine:

```yaml
devices:
  - "/dev/ttyRS485:/dev/ttyACM0"
```

Then start the service:

```bash
docker compose up -d --build
```

Open:

- Web UI: `http://localhost:8000/`
- API docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

View logs:

```bash
docker compose logs -f naritcm-lidar-api
```

Stop the service:

```bash
docker compose down
```

## Run Locally

Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the API:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

For local testing with a different serial port:

```bash
SERIAL_PORT=/dev/ttyUSB0 uvicorn main:app --host 0.0.0.0 --port 8000
```

## WebSocket Payload

`/ws/sensor` broadcasts JSON payloads similar to:

```json
{
  "ts": 1760000000000,
  "ok": true,
  "room1": {
    "unit_id": 1,
    "temp": 25.0,
    "humi": 65.0,
    "dewpoint": 17.9
  },
  "outdoor": {
    "unit_id": 2,
    "temp": 28.0,
    "humi": 70.0,
    "dewpoint": 22.0
  }
}
```

## Troubleshooting

- `Modbus not connected`: check `SERIAL_PORT`, Docker `devices`, USB/RS485 adapter, and host permissions.
- `Modbus Error`: check unit ID, register address, register table, baud rate, parity, and wiring.
- Empty `/`: make sure `static/index.html` exists or use `/docs` to inspect the API directly.
- No WebSocket updates: check API logs and confirm the sensors can be read through `/api/sensor`.
