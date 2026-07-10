"""Open-Meteo weather at first pitch (free, no key).
Wind direction is compared to the park's center-field bearing (config) to
decide blowing-out vs blowing-in at HR-wind-sensitive parks (Wrigley, GABP,
Yankee Stadium per config). Missing weather -> None fields -> the model
uses a neutral multiplier and the board shows `—`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from core.http import fetch_json
from core.manifest import Manifest

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


@dataclass
class Weather:
    temp_f: float | None
    wind_mph: float | None
    wind_dir_deg: float | None
    fetched_for_hour_utc: str


def fetch_weather(lat: float, lon: float, first_pitch_utc: str,
                  manifest: Manifest, name: str = "weather") -> Weather | None:
    """Hourly forecast; picks the hour containing first pitch."""
    try:
        dt = datetime.fromisoformat(first_pitch_utc.replace("Z", "+00:00"))
    except ValueError:
        return None
    dt = dt.astimezone(timezone.utc)
    day = dt.strftime("%Y-%m-%d")
    params = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "start_date": day,
        "end_date": day,
        "timezone": "UTC",
    }
    data, rec = fetch_json(name, FORECAST_URL, params=params,
                           row_counter=lambda d: len(d.get("hourly", {}).get("time", [])))
    manifest.add(rec)
    if data is None:
        return None
    try:
        hourly = data["hourly"]
        target = dt.strftime("%Y-%m-%dT%H:00")
        idx = hourly["time"].index(target)
        return Weather(
            temp_f=float(hourly["temperature_2m"][idx]),
            wind_mph=float(hourly["wind_speed_10m"][idx]),
            wind_dir_deg=float(hourly["wind_direction_10m"][idx]),
            fetched_for_hour_utc=target,
        )
    except (KeyError, ValueError, IndexError, TypeError):
        rec.note = (rec.note + "; first-pitch hour not in payload").strip("; ")
        return None


def wind_blowing_out(wind_dir_deg: float | None,
                     cf_bearing_deg: float | None) -> bool | None:
    """True if the wind blows from home plate toward center field.
    Open-Meteo reports the direction the wind comes FROM, so wind blowing
    out means it comes from ~opposite the CF bearing (±60°)."""
    if wind_dir_deg is None or cf_bearing_deg is None:
        return None
    from_home_toward_cf = (wind_dir_deg + 180.0) % 360.0
    diff = abs((from_home_toward_cf - cf_bearing_deg + 180.0) % 360.0 - 180.0)
    if diff <= 60.0:
        return True
    if diff >= 120.0:
        return False
    return None  # crosswind — neither out nor in
