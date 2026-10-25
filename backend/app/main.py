import os
from datetime import date

import psycopg2
from psycopg2.extras import RealDictCursor

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware


# --------------------------------------------------
# FastAPI application
# --------------------------------------------------

app = FastAPI(
    title="Weather Intelligence API",
    description="Weather data for districts across India",
    version="1.0.0",
)


# --------------------------------------------------
# CORS configuration
# --------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://weather-intelligence-platform.paras07sharma07.workers.dev",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------
# Database connection
# --------------------------------------------------

def get_db_connection():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise HTTPException(
            status_code=500,
            detail="DATABASE_URL environment variable is not configured",
        )

    try:
        return psycopg2.connect(
            database_url,
            cursor_factory=RealDictCursor,
            connect_timeout=10,
            sslmode="require",
        )
    except psycopg2.Error as exc:
        print(f"Database connection error: {exc}")
        raise HTTPException(
            status_code=503,
            detail="Could not connect to the database",
        ) from exc


# --------------------------------------------------
# Root and health endpoints
# --------------------------------------------------

@app.get("/")
def root():
    return {
        "message": "Weather Intelligence API is running",
        "status": "success",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "Weather Intelligence API",
    }


# --------------------------------------------------
# Districts endpoint
# --------------------------------------------------

@app.get("/districts")
def get_districts():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        district_id,
                        district_name,
                        state_name,
                        latitude,
                        longitude
                    FROM districts
                    ORDER BY state_name, district_name
                    """
                )
                districts = cursor.fetchall()

        return {
            "count": len(districts),
            "districts": districts,
        }

    except HTTPException:
        raise
    except Exception as exc:
        print(f"District retrieval error: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Could not retrieve districts",
        ) from exc


# --------------------------------------------------
# Current weather endpoint
# --------------------------------------------------

@app.get("/weather/current")
def get_current_weather(state: str | None = None):
    try:
        query = """
            SELECT
                d.district_id,
                d.district_name,
                d.state_name,
                d.latitude,
                d.longitude,
                c.temperature_c,
                c.feels_like_c,
                c.humidity_pct,
                c.precipitation_mm,
                c.wind_speed_kmh,
                c.weather_code,
                c.observed_at
            FROM districts d
            JOIN current_weather c
                ON d.district_id = c.district_id
        """

        params = []

        if state:
            query += " WHERE LOWER(d.state_name) = LOWER(%s)"
            params.append(state)

        query += " ORDER BY d.state_name, d.district_name"

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                weather = cursor.fetchall()

        return {
            "count": len(weather),
            "weather": weather,
        }

    except HTTPException:
        raise
    except Exception as exc:
        print(f"Current weather retrieval error: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Could not retrieve current weather",
        ) from exc


# --------------------------------------------------
# Weather forecast endpoint
# --------------------------------------------------

@app.get("/weather/forecast/{district_id}")
def get_weather_forecast(district_id: str):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        d.district_id,
                        d.district_name,
                        d.state_name,
                        f.forecast_date,
                        f.temperature_max_c,
                        f.temperature_min_c,
                        f.precipitation_sum_mm,
                        f.weather_code
                    FROM weather_forecast f
                    JOIN districts d
                        ON d.district_id = f.district_id
                    WHERE d.district_id::text = %s
                    ORDER BY f.forecast_date
                    """,
                    (district_id,),
                )
                rows = cursor.fetchall()

        if not rows:
            return {
                "district_id": district_id,
                "district_name": None,
                "state_name": None,
                "count": 0,
                "forecast": [],
            }

        forecast = []

        for row in rows:
            item = dict(row)

            # Convert date values to JSON-compatible strings.
            if isinstance(item.get("forecast_date"), date):
                item["forecast_date"] = item["forecast_date"].isoformat()

            forecast.append(item)

        first = rows[0]

        return {
            "district_id": first["district_id"],
            "district_name": first["district_name"],
            "state_name": first["state_name"],
            "count": len(forecast),
            "forecast": forecast,
        }

    except HTTPException:
        raise
    except Exception as exc:
        print(f"Forecast retrieval error: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Could not retrieve weather forecast",
        ) from exc