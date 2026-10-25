
from pathlib import Path
import time

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
API_URL = "https://api.open-meteo.com/v1/forecast"

TARGET_IDS = {"IN32D006", "IN08D016"}


def make_session():
    session = requests.Session()
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fetch_one(district):
    params = {
        "latitude": float(district["latitude"]),
        "longitude": float(district["longitude"]),
        "current": (
            "temperature_2m,relative_humidity_2m,"
            "apparent_temperature,precipitation,wind_speed_10m"
        ),
        "daily": (
            "temperature_2m_max,temperature_2m_min,"
            "precipitation_sum,weather_code"
        ),
        "forecast_days": 7,
        "timezone": "Asia/Kolkata",
    }

    with make_session() as session:
        response = session.get(API_URL, params=params, timeout=(15, 90))
        response.raise_for_status()
        data = response.json()

    cur = data["current"]
    district_id = str(district["district_id"])

    current = {
        "district_id": district_id,
        "observation_time": cur["time"],
        "temperature_c": cur["temperature_2m"],
        "humidity_pct": cur["relative_humidity_2m"],
        "feels_like_c": cur["apparent_temperature"],
        "precipitation_mm": cur["precipitation"],
        "wind_speed_kmh": cur["wind_speed_10m"],
        "district_name": district["district_name"],
        "state_name": district["state_name"],
    }

    daily = data["daily"]
    forecast = [
        {
            "district_id": district_id,
            "forecast_date": date,
            "temperature_max_c": daily["temperature_2m_max"][i],
            "temperature_min_c": daily["temperature_2m_min"][i],
            "precipitation_sum_mm": daily["precipitation_sum"][i],
            "weather_code": daily["weather_code"][i],
            "district_name": district["district_name"],
            "state_name": district["state_name"],
        }
        for i, date in enumerate(daily["time"])
    ]

    return current, forecast


def merge_csv(path, fresh, keys):
    if path.exists():
        old = pd.read_csv(path, dtype={"district_id": str})
    else:
        old = pd.DataFrame()

    new = pd.DataFrame(fresh)
    if old.empty:
        result = new
    else:
        old["district_id"] = old["district_id"].astype(str)
        new["district_id"] = new["district_id"].astype(str)
        result = pd.concat([old, new], ignore_index=True)
        result = result.drop_duplicates(subset=keys, keep="last")

    result.to_csv(path, index=False)
    return result


def main():
    master = pd.read_csv(
        DATA / "district_master.csv",
        dtype={"district_id": str},
    )
    targets = master[master["district_id"].isin(TARGET_IDS)]

    if len(targets) != len(TARGET_IDS):
        raise RuntimeError("One or more target IDs were not found in district_master.csv")

    current_rows = []
    forecast_rows = []
    failures = []

    for district in targets.to_dict("records"):
        print(f"Fetching {district['district_name']}...")
        success = False

        for attempt in range(1, 4):
            try:
                current, forecast = fetch_one(district)
                current_rows.append(current)
                forecast_rows.extend(forecast)
                print(f"  Success on attempt {attempt}")
                success = True
                break
            except Exception as exc:
                print(f"  Attempt {attempt} failed: {exc}")
                if attempt < 3:
                    time.sleep(5 * attempt)

        if not success:
            failures.append(district["district_name"])

    if current_rows:
        merge_csv(
            DATA / "current_weather.csv",
            current_rows,
            ["district_id"],
        )
        merge_csv(
            DATA / "weather_forecast.csv",
            forecast_rows,
            ["district_id", "forecast_date"],
        )

    print("\nRecovery complete.")
    print(f"Current records added/updated: {len(current_rows)}")
    print(f"Forecast records added/updated: {len(forecast_rows)}")
    print(f"Still failing: {failures or 'None'}")


if __name__ == "__main__":
    main()
