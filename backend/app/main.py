
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.app.database import get_db_connection


app = FastAPI(
    title="Weather Intelligence API",
    description="Weather data for districts across India",
    version="1.0.0",
)


# CORS configuration for local development and deployed frontend
frontend_url = os.getenv("FRONTEND_URL", "").rstrip("/")

allowed_origins = [
    "http://127.0.0.1:5500",
    "http://localhost:5500",
]

if frontend_url:
    allowed_origins.append(frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return {
        "message": "Weather Intelligence API is running",
        "status": "success",
    }


@app.get("/health")
def health_check():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()

        return {
            "status": "healthy",
            "database": "connected",
        }

    except Exception as error:
        print(f"Database health check failed: {error}")

        raise HTTPException(
            status_code=503,
            detail="Database connection failed",
        ) from error


@app.get("/districts")
def get_districts():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        district_id,
                        district_name,
                        district_name_local,
                        state_id,
                        state_name,
                        latitude,
                        longitude
                    FROM districts
                    ORDER BY district_name;
                    """
                )

                columns = [desc[0] for desc in cur.description]
                rows = cur.fetchall()

                return [
                    dict(zip(columns, row))
                    for row in rows
                ]

    except Exception as error:
        print(f"District query failed: {error}")

        raise HTTPException(
            status_code=500,
            detail="Unable to fetch districts",
        ) from error


@app.get("/weather/current")
def get_current_weather():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        d.district_id,
                        d.district_name,
                        d.district_name_local,
                        d.state_name,
                        d.latitude,
                        d.longitude,
                        cw.observation_time,
                        cw.temperature_c,
                        cw.humidity_pct,
                        cw.feels_like_c,
                        cw.precipitation_mm,
                        cw.wind_speed_kmh
                    FROM districts AS d
                    LEFT JOIN current_weather AS cw
                        ON d.district_id = cw.district_id
                    ORDER BY d.district_name;
                    """
                )

                columns = [desc[0] for desc in cur.description]
                rows = cur.fetchall()

                return [
                    dict(zip(columns, row))
                    for row in rows
                ]

    except Exception as error:
        print(f"Current weather query failed: {error}")

        raise HTTPException(
            status_code=500,
            detail="Unable to fetch current weather",
        ) from error


@app.get("/weather/forecast/{district_id}")
def get_weather_forecast(district_id: str):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        district_id,
                        forecast_date,
                        temperature_max_c,
                        temperature_min_c,
                        precipitation_sum_mm,
                        weather_code
                    FROM weather_forecast
                    WHERE district_id = %s
                    ORDER BY forecast_date;
                    """,
                    (district_id,),
                )

                columns = [desc[0] for desc in cur.description]
                rows = cur.fetchall()

                if not rows:
                    raise HTTPException(
                        status_code=404,
                        detail="No forecast found for this district",
                    )

                return [
                    dict(zip(columns, row))
                    for row in rows
                ]

    except HTTPException:
        raise

    except Exception as error:
        print(f"Forecast query failed: {error}")

        raise HTTPException(
            status_code=500,
            detail="Unable to fetch weather forecast",
        ) from error
