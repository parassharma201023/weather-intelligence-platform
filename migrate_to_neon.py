
import os
from pathlib import Path

import pandas as pd
import psycopg
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


def read_csv(filename, required_columns):
    path = DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    df = pd.read_csv(path, dtype={"district_id": str})

    missing = set(required_columns) - set(df.columns)
    if missing:
        raise ValueError(f"{filename} missing columns: {missing}")

    if df["district_id"].isna().any():
        raise ValueError(f"{filename} contains empty district_id values")

    return df


def clean(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def records(df, columns):
    return [
        tuple(clean(value) for value in row)
        for row in df[columns].itertuples(index=False, name=None)
    ]


def main():
    districts = read_csv("district_master.csv", [
        "district_id", "district_name", "district_name_local",
        "state_id", "state_name", "latitude", "longitude"
    ])

    current = read_csv("current_weather.csv", [
        "district_id", "observation_time", "temperature_c",
        "humidity_pct", "feels_like_c", "precipitation_mm",
        "wind_speed_kmh"
    ])

    forecast = read_csv("weather_forecast.csv", [
        "district_id", "forecast_date", "temperature_max_c",
        "temperature_min_c", "precipitation_sum_mm", "weather_code"
    ])

    print("CSV validation passed:")
    print(f"Districts: {len(districts)}")
    print(f"Current weather: {len(current)}")
    print(f"Forecast: {len(forecast)}")

    required_env = ["DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    missing_env = [key for key in required_env if not os.getenv(key)]
    if missing_env:
        raise RuntimeError(f"Missing .env settings: {missing_env}")

    with psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        sslmode="require",
        connect_timeout=15,
    ) as conn:
        with conn.cursor() as cur:
            # 1. Load district master first.
            cur.executemany("""
                INSERT INTO public.districts (
                    district_id, district_name, district_name_local,
                    state_id, state_name, latitude, longitude
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (district_id) DO UPDATE SET
                    district_name = EXCLUDED.district_name,
                    district_name_local = EXCLUDED.district_name_local,
                    state_id = EXCLUDED.state_id,
                    state_name = EXCLUDED.state_name,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude
            """, records(districts, [
                "district_id", "district_name", "district_name_local",
                "state_id", "state_name", "latitude", "longitude"
            ]))

            # 2. Current weather is a snapshot: replace its rows.
            cur.execute("DELETE FROM public.current_weather")

            cur.executemany("""
                INSERT INTO public.current_weather (
                    district_id, observation_time, temperature_c,
                    humidity_pct, feels_like_c, precipitation_mm,
                    wind_speed_kmh
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, records(current, [
                "district_id", "observation_time", "temperature_c",
                "humidity_pct", "feels_like_c", "precipitation_mm",
                "wind_speed_kmh"
            ]))

            # 3. Insert/update forecasts without duplicating dates.
            cur.executemany("""
                INSERT INTO public.weather_forecast (
                    district_id, forecast_date, temperature_max_c,
                    temperature_min_c, precipitation_sum_mm, weather_code
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (district_id, forecast_date) DO UPDATE SET
                    temperature_max_c = EXCLUDED.temperature_max_c,
                    temperature_min_c = EXCLUDED.temperature_min_c,
                    precipitation_sum_mm = EXCLUDED.precipitation_sum_mm,
                    weather_code = EXCLUDED.weather_code,
                    fetched_at = CURRENT_TIMESTAMP
            """, records(forecast, [
                "district_id", "forecast_date", "temperature_max_c",
                "temperature_min_c", "precipitation_sum_mm", "weather_code"
            ]))

            # 4. Verify database row counts before transaction commits.
            for table in ("districts", "current_weather", "weather_forecast"):
                cur.execute(f"SELECT COUNT(*) FROM public.{table}")
                print(f"{table}: {cur.fetchone()[0]} rows")

    print("Migration completed successfully.")


if __name__ == "__main__":
    main()
