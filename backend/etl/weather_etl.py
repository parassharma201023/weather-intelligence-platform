
from pathlib import Path
from datetime import datetime, timezone
import argparse
import time

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"

API_URL = "https://api.open-meteo.com/v1/forecast"
BATCH_SIZE = 50
REQUEST_TIMEOUT = (10, 60)


def make_session():
    """Create a session with retry handling."""
    session = requests.Session()

    retry_policy = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        respect_retry_after_header=True,
    )

    session.mount(
        "https://",
        HTTPAdapter(max_retries=retry_policy),
    )
    return session


def build_api_params(districts):
    """Build a multi-location Open-Meteo request."""
    return {
        "latitude": ",".join(
            str(float(d["latitude"])) for d in districts
        ),
        "longitude": ",".join(
            str(float(d["longitude"])) for d in districts
        ),
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


def convert_weather_result(district, data):
    """Convert one API result into current and forecast records."""
    current = data["current"]
    daily = data["daily"]
    district_id = str(district["district_id"])

    current_row = {
        "district_id": district_id,
        "observation_time": current["time"],
        "temperature_c": current["temperature_2m"],
        "humidity_pct": current["relative_humidity_2m"],
        "feels_like_c": current["apparent_temperature"],
        "precipitation_mm": current["precipitation"],
        "wind_speed_kmh": current["wind_speed_10m"],
    }

    forecast_rows = []

    for i, forecast_date in enumerate(daily["time"]):
        forecast_rows.append({
            "district_id": district_id,
            "forecast_date": forecast_date,
            "temperature_max_c": daily["temperature_2m_max"][i],
            "temperature_min_c": daily["temperature_2m_min"][i],
            "precipitation_sum_mm": daily["precipitation_sum"][i],
            "weather_code": daily["weather_code"][i],
        })

    return current_row, forecast_rows


def fetch_district_batch(district_batch):
    """
    Fetch a batch in one request.
    If the batch fails, split it into smaller batches so one
    bad request does not cause every district to fail.
    """
    try:
        with make_session() as session:
            response = session.get(
                API_URL,
                params=build_api_params(district_batch),
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            results = response.json()

        if isinstance(results, dict):
            results = [results]

        if not isinstance(results, list):
            raise ValueError("Unexpected API response format.")

        if len(results) != len(district_batch):
            raise ValueError(
                f"Expected {len(district_batch)} results, "
                f"received {len(results)}."
            )

        current_records = []
        forecast_records = []
        errors = []

        for district, data in zip(district_batch, results):
            try:
                current_row, forecast_rows = convert_weather_result(
                    district, data
                )
                current_records.append(current_row)
                forecast_records.extend(forecast_rows)

            except (KeyError, ValueError, TypeError, IndexError) as exc:
                errors.append(
                    f"{district['district_name']}: {exc}"
                )

        return current_records, forecast_records, errors

    except (
        requests.RequestException,
        ValueError,
        TypeError,
    ) as exc:
        # If one request for the batch fails, split and retry.
        if len(district_batch) > 1:
            midpoint = len(district_batch) // 2

            left_current, left_forecast, left_errors = (
                fetch_district_batch(district_batch[:midpoint])
            )
            right_current, right_forecast, right_errors = (
                fetch_district_batch(district_batch[midpoint:])
            )

            return (
                left_current + right_current,
                left_forecast + right_forecast,
                left_errors + right_errors,
            )

        district = district_batch[0]
        return [], [], [
            f"{district['district_name']}: {exc}"
        ]


def read_failed_district_names(errors_file):
    """Read district names from weather_errors.csv."""
    if not errors_file.exists():
        return set()

    try:
        errors_df = pd.read_csv(errors_file, dtype=str)
    except (
        pd.errors.ParserError,
        UnicodeDecodeError,
    ):
        errors_df = pd.read_csv(
            errors_file,
            dtype=str,
            header=None,
            on_bad_lines="skip",
        )

    if errors_df.empty:
        return set()

    if "error" in errors_df.columns:
        error_values = errors_df["error"].dropna().astype(str)
    else:
        error_values = errors_df.iloc[:, 0].dropna().astype(str)

    failed_names = set()

    for message in error_values:
        district_name = message.split(":", 1)[0].strip().strip('"')
        if district_name and district_name.lower() != "error":
            failed_names.add(district_name.casefold())

    return failed_names


def read_existing_csv(path):
    """Read an existing CSV, or return an empty DataFrame."""
    if path.exists():
        try:
            df = pd.read_csv(path, dtype={"district_id": str})

            if "district_id" in df.columns:
                df["district_id"] = df["district_id"].astype(str)

            return df

        except (
            pd.errors.EmptyDataError,
            pd.errors.ParserError,
        ):
            pass

    return pd.DataFrame()


def merge_current(existing, fresh):
    """Update successful districts and preserve other districts."""
    if existing.empty:
        return fresh

    if fresh.empty:
        return existing

    combined = pd.concat([existing, fresh], ignore_index=True)
    combined["district_id"] = combined["district_id"].astype(str)

    return combined.drop_duplicates(
        subset=["district_id"],
        keep="last",
    )


def merge_forecast(existing, fresh):
    """Update fetched forecast dates and preserve other rows."""
    if existing.empty:
        return fresh

    if fresh.empty:
        return existing

    combined = pd.concat([existing, fresh], ignore_index=True)
    combined["district_id"] = combined["district_id"].astype(str)

    return combined.drop_duplicates(
        subset=["district_id", "forecast_date"],
        keep="last",
    )


def refresh_weather_data(retry_failed=False):
    start = time.time()

    districts_file = DATA_DIR / "district_master.csv"
    errors_file = DATA_DIR / "weather_errors.csv"
    current_file = DATA_DIR / "current_weather.csv"
    forecast_file = DATA_DIR / "weather_forecast.csv"

    if not districts_file.exists():
        raise FileNotFoundError(
            f"District file not found: {districts_file}"
        )

    districts = pd.read_csv(
        districts_file,
        dtype={"district_id": str},
    )

    # Retry only the districts already listed as failed.
    if retry_failed:
        failed_names = read_failed_district_names(errors_file)

        if not failed_names:
            print("No failed district names found.", flush=True)
            print("No API requests were made.", flush=True)
            return

        districts = districts[
            districts["district_name"]
            .astype(str)
            .str.casefold()
            .isin(failed_names)
        ].copy()

        if districts.empty:
            print(
                "Failed names did not match district_master.csv.",
                flush=True,
            )
            print("No API requests were made.", flush=True)
            return

        print(
            f"Retry mode: {len(districts)} failed districts.",
            flush=True,
        )

    else:
        print(
            f"Full refresh: {len(districts)} districts.",
            flush=True,
        )

    current_records = []
    forecast_records = []
    errors = []

    district_rows = districts.to_dict("records")
    total_districts = len(district_rows)

    total_batches = (
        total_districts + BATCH_SIZE - 1
    ) // BATCH_SIZE

    print(
        f"Fetching weather in batches of {BATCH_SIZE}...",
        flush=True,
    )

    for batch_number, start_index in enumerate(
        range(0, total_districts, BATCH_SIZE),
        start=1,
    ):
        batch = district_rows[
            start_index:start_index + BATCH_SIZE
        ]

        batch_current, batch_forecast, batch_errors = (
            fetch_district_batch(batch)
        )

        current_records.extend(batch_current)
        forecast_records.extend(batch_forecast)
        errors.extend(batch_errors)

        processed = min(
            start_index + len(batch),
            total_districts,
        )

        print(
            f"Batch {batch_number}/{total_batches} | "
            f"Processed: {processed}/{total_districts} | "
            f"Success: {len(current_records)} | "
            f"Errors: {len(errors)}",
            flush=True,
        )

    # Preserve existing CSVs if every request fails.
    if not current_records:
        print("No new weather records fetched.", flush=True)
        print(
            "Existing current and forecast CSVs were preserved.",
            flush=True,
        )
        return

    current_fresh = pd.DataFrame(current_records).merge(
        districts[["district_id", "district_name", "state_name"]],
        on="district_id",
        how="left",
    )

    forecast_fresh = pd.DataFrame(forecast_records).merge(
        districts[["district_id", "district_name", "state_name"]],
        on="district_id",
        how="left",
    )

    current_existing = read_existing_csv(current_file)
    forecast_existing = read_existing_csv(forecast_file)

    current_final = merge_current(
        current_existing, current_fresh
    )
    forecast_final = merge_forecast(
        forecast_existing, forecast_fresh
    )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%d_%H%M%S"
    )

    current_final.to_csv(current_file, index=False)
    forecast_final.to_csv(forecast_file, index=False)

    # Save timestamped history snapshots.
    current_final.to_csv(
        HISTORY_DIR / f"current_weather_{timestamp}.csv",
        index=False,
    )
    forecast_final.to_csv(
        HISTORY_DIR / f"weather_forecast_{timestamp}.csv",
        index=False,
    )

    # In retry mode, retain older errors only for districts
    # that are still failing.
    old_failed = read_failed_district_names(errors_file)
    succeeded_ids = {
        str(record["district_id"]) for record in current_records
    }

    succeeded_names = set(
        districts.loc[
            districts["district_id"].astype(str).isin(succeeded_ids),
            "district_name",
        ].astype(str).str.casefold()
    )

    remaining_old_errors = []

    if retry_failed and errors_file.exists():
        try:
            old_df = pd.read_csv(errors_file, dtype=str)

            if "error" in old_df.columns:
                old_values = old_df["error"].dropna().astype(str)
            else:
                old_values = old_df.iloc[:, 0].dropna().astype(str)

            for message in old_values:
                name = (
                    message.split(":", 1)[0]
                    .strip()
                    .strip('"')
                    .casefold()
                )

                if name in old_failed and name not in succeeded_names:
                    remaining_old_errors.append(message)

        except (
            pd.errors.EmptyDataError,
            pd.errors.ParserError,
        ):
            pass

    all_errors = remaining_old_errors + errors

    pd.DataFrame(
        all_errors,
        columns=["error"],
    ).to_csv(errors_file, index=False)

    print("\nRefresh completed.", flush=True)
    print(
        f"New current records fetched: {len(current_fresh)}",
        flush=True,
    )
    print(
        f"New forecast records fetched: {len(forecast_fresh)}",
        flush=True,
    )
    print(
        f"Failed requests this run: {len(errors)}",
        flush=True,
    )
    print(
        f"Current rows available: {len(current_final)}",
        flush=True,
    )
    print(
        f"Forecast rows available: {len(forecast_final)}",
        flush=True,
    )
    print(
        f"Elapsed time: {time.time() - start:.1f} seconds",
        flush=True,
    )
    print(
        f"Remaining errors: {len(all_errors)}",
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry only districts listed in weather_errors.csv",
    )

    args = parser.parse_args()
    refresh_weather_data(retry_failed=args.retry_failed)
