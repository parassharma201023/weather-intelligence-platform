
import os
import pandas as pd
import psycopg
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)

CURRENT_CSV = os.path.join(BASE_DIR, "data", "current_weather.csv")
FORECAST_CSV = os.path.join(BASE_DIR, "data", "weather_forecast.csv")

CURRENT_COLUMNS = [
    "district_id",
    "observation_time",
    "temperature_c",
    "humidity_pct",
    "feels_like_c",
    "precipitation_mm",
    "wind_speed_kmh",
]

FORECAST_COLUMNS = [
    "district_id",
    "forecast_date",
    "temperature_max_c",
    "temperature_min_c",
    "precipitation_sum_mm",
    "weather_code",
]



def connect_db():
    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        sslmode="require",
        connect_timeout=15,
    )



def clean_value(value):
    if pd.isna(value):
        return None
    return value


def sync_current_weather(conn):
    df = pd.read_csv(CURRENT_CSV)

    # Keep only columns that exist in the PostgreSQL table.
    df = df[CURRENT_COLUMNS]
    df = df.map(clean_value)

    with conn.cursor() as cur:
        # Replace current readings for imported districts only.
        district_ids = df["district_id"].tolist()

        cur.execute(
            """
            DELETE FROM current_weather
            WHERE district_id = ANY(%s)
            """,
            (district_ids,),
        )

        cur.executemany(
            """
            INSERT INTO current_weather (
                district_id, observation_time, temperature_c,
                humidity_pct, feels_like_c, precipitation_mm,
                wind_speed_kmh, fetched_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, NOW()
            )
            """,
            list(df.itertuples(index=False, name=None)),
        )

    print(f"Current weather synced: {len(df)} rows")


def sync_forecast(conn):
    df = pd.read_csv(FORECAST_CSV)

    # Keep only columns that exist in the PostgreSQL table.
    df = df[FORECAST_COLUMNS]
    df = df.map(clean_value)

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO weather_forecast (
                district_id, forecast_date, temperature_max_c,
                temperature_min_c, precipitation_sum_mm,
                weather_code, fetched_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (district_id, forecast_date)
            DO UPDATE SET
                temperature_max_c = EXCLUDED.temperature_max_c,
                temperature_min_c = EXCLUDED.temperature_min_c,
                precipitation_sum_mm = EXCLUDED.precipitation_sum_mm,
                weather_code = EXCLUDED.weather_code,
                fetched_at = NOW()
            """,
            list(df.itertuples(index=False, name=None)),
        )

    print(f"Forecast synced: {len(df)} rows")


def main():
    with connect_db() as conn:
        sync_current_weather(conn)
        sync_forecast(conn)

    print("PostgreSQL sync completed successfully!")


if __name__ == "__main__":
    main()
