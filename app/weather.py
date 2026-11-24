"""Open-Meteo lookup. No API key."""

from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import urlopen

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"


def _get_json(url: str, timeout: float = 12) -> dict:
    with urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def search_places(query: str) -> list[dict]:
    name = query.strip()
    if len(name) < 2:
        return []
    payload = _get_json(f"{GEOCODE}?{urlencode({'name': name, 'count': 5, 'language': 'en', 'format': 'json'})}")
    places = []
    for item in payload.get("results") or []:
        label = ", ".join(
            part
            for part in (item.get("name"), item.get("admin1"), item.get("country_code"))
            if part
        )
        places.append(
            {
                "label": label,
                "name": item.get("name") or name,
                "latitude": item["latitude"],
                "longitude": item["longitude"],
                "timezone": item.get("timezone") or "auto",
            }
        )
    return places


def current_weather(latitude: float, longitude: float, units: str, timezone: str = "auto") -> dict:
    unit = "fahrenheit" if units == "fahrenheit" else "celsius"
    query = urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min",
            "temperature_unit": unit,
            "wind_speed_unit": "mph",
            "timezone": timezone or "auto",
            "forecast_days": 1,
        }
    )
    payload = _get_json(f"{FORECAST}?{query}")
    current = payload.get("current") or {}
    daily = payload.get("daily") or {}
    highs = daily.get("temperature_2m_max") or [current.get("temperature_2m", 0)]
    lows = daily.get("temperature_2m_min") or [current.get("temperature_2m", 0)]
    stamp = current.get("time") or ""
    clock = ""
    if stamp:
        try:
            moment = datetime.fromisoformat(stamp)
            hour = moment.hour % 12 or 12
            clock = f"{hour}:{moment.minute:02d}"
        except ValueError:
            clock = ""
    return {
        "temperature": current.get("temperature_2m", 0),
        "code": int(current.get("weather_code") or 0),
        "wind": current.get("wind_speed_10m", 0),
        "high": highs[0],
        "low": lows[0],
        "units": unit,
        "clock": clock,
        "observed": stamp,
    }
