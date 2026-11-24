"""Read a DHT11 on the Pi. Windows keeps using the forecast until the sensor is there."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from app.comfort import comfort

log = logging.getLogger("ledmatrix.sensor")

_device = None
_pin: int | None = None
_library_missing = False


def sensor_pin(configured: int | None = 4) -> int | None:
    raw = os.environ.get("LEDMATRIX_DHT_PIN", "").strip()
    if raw:
        configured = int(raw)
    if configured is None:
        return 4
    pin = int(configured)
    if pin < 0:
        return None
    return pin


def read_local_air(pin: int | None, units: str, timezone: str) -> dict | None:
    """Temperature and humidity, plus the icon those two numbers select."""
    chosen = sensor_pin(pin)
    if chosen is None:
        return None
    sample = _read_dht11(chosen)
    if sample is None:
        return None
    celsius, humidity = sample
    fahrenheit = celsius * 9 / 5 + 32
    shown = fahrenheit if units != "celsius" else celsius
    kind, feel = comfort(fahrenheit, humidity)
    return {
        "temperature": shown,
        "humidity": humidity,
        "kind": kind,
        "feel": feel,
        "units": "celsius" if units == "celsius" else "fahrenheit",
        "clock": _clock(timezone),
        "source": "dht11",
        "code": 0,
    }


def _clock(timezone: str) -> str:
    zone = None
    if timezone and timezone != "auto":
        try:
            zone = ZoneInfo(timezone)
        except Exception:
            zone = None
    moment = datetime.now(zone) if zone else datetime.now()
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment.minute:02d}"


def _read_dht11(pin: int) -> tuple[float, float] | None:
    global _library_missing
    if _library_missing:
        return None
    try:
        device = _open(pin)
    except ImportError:
        _library_missing = True
        log.info("DHT11 library is not installed. The forecast is used until the Pi has the sensor.")
        return None
    except Exception:
        log.warning("DHT11 on GPIO %s did not open", pin, exc_info=True)
        return None
    for attempt in range(3):
        try:
            celsius = device.temperature
            humidity = device.humidity
            if celsius is not None and humidity is not None:
                return float(celsius), float(humidity)
        except RuntimeError:
            log.info("DHT11 reading %s failed its checksum", attempt + 1)
        if attempt < 2:
            time.sleep(1.2)
    return None


def _open(pin: int):
    global _device, _pin
    import adafruit_dht
    import board

    if _device is not None and _pin == pin:
        return _device
    if _device is not None:
        try:
            _device.exit()
        except Exception:
            log.debug("closing the previous DHT11 failed", exc_info=True)
    _device = adafruit_dht.DHT11(getattr(board, f"D{pin}"))
    _pin = pin
    return _device
