import os
import time
import requests

from influxdb_client import InfluxDBClient, Point, WritePrecision


# ===== Sensor API =====
SENSOR_API_URL = os.getenv("SENSOR_API_URL", "http://naritcm-cleanroom-api:8000/api/sensor")
POLL_SEC = float(os.getenv("POLL_SEC", "1.0"))
TIMEOUT_SEC = float(os.getenv("HTTP_TIMEOUT_SEC", "2.5"))

# ===== InfluxDB =====
INFLUX_URL = os.getenv("INFLUX_URL", "http://influxdb:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "")
INFLUX_ORG = os.getenv("INFLUX_ORG", "Narit")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "Cleanroom")
MEASUREMENT = os.getenv("MEASUREMENT", "room1")


def now_ns() -> int:
    return int(time.time() * 1e9)


def fetch_json(url: str, timeout: float) -> dict:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def build_sensor_points(data: dict, ts: int) -> list:
    points = []

    if data.get("ok") is False:
        print(f"sensor api returned ok=false: {data}", flush=True)

    for location in ("room1", "outdoor"):
        sensor = data.get(location)
        if not isinstance(sensor, dict):
            continue

        temp = sensor.get("temp")
        humi = sensor.get("humi")
        dewpoint = sensor.get("dewpoint")
        unit_id = sensor.get("unit_id")

        if not is_number(temp) or not is_number(humi):
            continue

        point = (
            Point(MEASUREMENT)
            .tag("location", location)
            .field("temp", float(temp))
            .field("humi", float(humi))
            .time(ts, WritePrecision.NS)
        )

        if is_number(dewpoint):
            point = point.field("dewpoint", float(dewpoint))

        if isinstance(unit_id, int) and not isinstance(unit_id, bool):
            point = point.field("unit_id", unit_id)

        points.append(point)

    return points


def main():
    if not INFLUX_TOKEN:
        raise SystemExit("INFLUX_TOKEN is empty. Please set it in docker-compose.yml environment.")

    with InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG) as client:
        write_api = client.write_api()
        backoff = 1.0

        while True:
            try:
                sensor_data = fetch_json(SENSOR_API_URL, TIMEOUT_SEC)
                points = build_sensor_points(sensor_data, now_ns())

                if points:
                    write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=points)
                else:
                    print(f"no valid sensor points from {SENSOR_API_URL}: {sensor_data}", flush=True)

                backoff = 1.0
                time.sleep(POLL_SEC)
            except Exception as exc:
                print(f"writer error: {exc}", flush=True)
                time.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)


if __name__ == "__main__":
    main()
