"""Turn a DHT11 temperature and humidity reading into a sign icon.

The sensor cannot see the sky. The icon describes the air it measured.
"""

from __future__ import annotations


def comfort(temp_f: float, humidity: float) -> tuple[str, str]:
    """Return an icon name and a short label."""
    humid = max(0.0, min(100.0, float(humidity)))
    temp = float(temp_f)
    if temp <= 40:
        return "snow", "COLD"
    if temp < 55:
        return ("cloud", "COOL") if humid >= 70 else ("fair", "COOL")
    if temp < 75:
        if humid >= 75:
            return "fog", "DAMP"
        if humid >= 55:
            return "cloud", "HUMID"
        return "clear", "MILD"
    if temp < 90:
        if humid >= 70:
            return "rain", "MUGGY"
        if humid >= 45:
            return "fair", "WARM"
        return "clear", "DRY"
    if humid >= 50:
        return "storm", "STEAMY"
    return "clear", "HOT"
