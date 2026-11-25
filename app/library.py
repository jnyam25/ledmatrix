"""Saved texts and pictures. The sign walks this list on its own."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

ROOT = Path(__file__).resolve().parent.parent
LIBRARY_DIR = ROOT / "data" / "library"
LIBRARY_FILE = LIBRARY_DIR / "library.json"
DEFAULT_SLIDES = ROOT / "defaults" / "slides"
DEFAULT_IMAGES = (
    ("jagwire", "Jagwire", "jagwire.png", "letterbox"),
    ("tamusa-dome", "A&M San Antonio", "tamusa-dome.png", "letterbox"),
    ("tamusa-banner", "A&M San Antonio banner", "tamusa-banner.jpg", "letterbox"),
    ("tamusa-banner-offset", "A&M San Antonio banner offset", "tamusa-banner-offset.jpg", "letterbox"),
)

HOLD_SECONDS = 12


def greeting_for(hour: int) -> tuple[str, list[dict]]:
    """Good morning from 5, good afternoon from noon, good evening from 5 pm."""
    if 5 <= hour < 12:
        part = "MORNING"
    elif 12 <= hour < 17:
        part = "AFTERNOON"
    else:
        part = "EVENING"
    runs = [
        {"text": "GOOD ", "color": "#d6ff4a"},
        {"text": part, "color": "#ffb020"},
    ]
    return f"GOOD {part}", runs


def with_live_greeting(texts: list[dict], hour: int | None = None, timezone: str | None = None) -> list[dict]:
    if hour is not None:
        clock_hour = hour
    else:
        zone = None
        if timezone and timezone != "auto":
            try:
                zone = ZoneInfo(timezone)
            except Exception:
                zone = None
        clock_hour = datetime.now(zone).hour
    message, runs = greeting_for(clock_hour)
    live: list[dict] = []
    for item in texts:
        if item.get("kind") == "greeting" or item.get("id") == "greeting":
            shown = dict(item)
            shown["text"] = message
            shown["color"] = runs[0]["color"]
            shown["runs"] = runs
            shown["kind"] = "greeting"
            live.append(shown)
        else:
            live.append(item)
    return live


def hex_color(value: str, fallback: str = "#d6ff4a") -> str:
    text = str(value or "").strip()
    return text if _HEX.match(text) else fallback


def normalize_runs(text: str, color: str, runs: list | None) -> tuple[str, str, list[dict]]:
    """Keep each colored piece. A plain message becomes one run."""
    ink = hex_color(color)
    cleaned: list[dict] = []
    if isinstance(runs, list):
        for run in runs[:48]:
            if not isinstance(run, dict):
                continue
            piece = str(run.get("text") or "")
            if piece == "":
                continue
            cleaned.append({"text": piece, "color": hex_color(run.get("color"), ink)})
    visible = "".join(item["text"] for item in cleaned)
    if not visible.strip():
        message = " ".join((text or "").split())
        if not message:
            raise ValueError("Type a message first")
        cleaned = [{"text": message, "color": ink}]
        visible = message
    if len(visible) > 180:
        raise ValueError("Keep the message under 180 characters")
    return " ".join(visible.split()), cleaned[0]["color"], cleaned


def build_rotation(texts: list[dict], images: list[dict], include_weather: bool) -> list[tuple[str, dict | None]]:
    """Text, then a picture, then weather, repeated across the library."""
    count = max(len(texts), len(images), 1 if include_weather else 0)
    items: list[tuple[str, dict | None]] = []
    for index in range(count):
        if texts:
            items.append(("text", texts[index % len(texts)]))
        if images:
            items.append(("image", images[index % len(images)]))
        if include_weather:
            items.append(("weather", None))
    return items


def dwell_seconds(kind: str, frame_count: int, delay_ms: int, hold: float) -> float:
    """Keep a scrolling item up for at least one full pass across both panels."""
    if kind == "weather":
        return float(hold)
    return max(float(hold), frame_count * delay_ms / 1000)


class Library:
    def __init__(self, directory: Path = LIBRARY_DIR, path: Path = LIBRARY_FILE) -> None:
        self.directory = directory
        self.path = path
        self.directory.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"texts": [], "images": [], "hold_seconds": HOLD_SECONDS})
        self.ensure_default_slides()
        self.ensure_default_greeting()

    def ensure_default_slides(self) -> None:
        """Add the bundled logos once. Removing one later leaves it removed."""
        data = self._read()
        if data.get("defaults_seeded"):
            return
        known = {item["id"] for item in data["images"]}
        for item_id, name, filename, mode in DEFAULT_IMAGES:
            source = DEFAULT_SLIDES / filename
            if item_id in known or not source.exists():
                continue
            stored = f"{item_id}{source.suffix.lower()}"
            (self.directory / stored).write_bytes(source.read_bytes())
            data["images"].append({"id": item_id, "name": name, "file": stored, "mode": mode})
        data["defaults_seeded"] = True
        self._write(data)

    def ensure_default_greeting(self) -> None:
        """Add one clock greeting. Removing it later leaves it removed."""
        data = self._read()
        if data.get("greeting_seeded"):
            return
        if not any(item.get("id") == "greeting" or item.get("kind") == "greeting" for item in data["texts"]):
            message, runs = greeting_for(datetime.now().hour)
            data["texts"].insert(
                0,
                {
                    "id": "greeting",
                    "kind": "greeting",
                    "text": message,
                    "color": runs[0]["color"],
                    "background": "#000000",
                    "speed": 4,
                    "runs": runs,
                },
            )
        data["greeting_seeded"] = True
        self._write(data)

    def snapshot(self, timezone: str | None = None) -> dict:
        data = self._read()
        return {
            "texts": with_live_greeting(list(data["texts"]), timezone=timezone),
            "images": [
                {"id": item["id"], "name": item["name"], "mode": item.get("mode") or "letterbox"}
                for item in data["images"]
            ],
            "hold_seconds": int(data.get("hold_seconds") or HOLD_SECONDS),
        }

    def add_text(self, text: str, color: str, background: str, speed: int, runs: list | None = None) -> dict:
        message, ink, cleaned = normalize_runs(text, color, runs)
        item = {
            "id": uuid.uuid4().hex[:8],
            "text": message,
            "color": ink,
            "background": hex_color(background, "#000000"),
            "speed": max(1, min(10, int(speed))),
            "runs": cleaned,
        }
        data = self._read()
        data["texts"].append(item)
        self._write(data)
        return item

    def add_image(self, name: str, raw: bytes, mode: str) -> dict:
        if len(raw) > 8_000_000:
            raise ValueError("Image is larger than 8 MB")
        suffix = Path(name or "image.png").suffix.lower()
        if suffix not in {".png", ".gif", ".jpg", ".jpeg", ".webp"}:
            suffix = ".png"
        item_id = uuid.uuid4().hex[:8]
        filename = f"{item_id}{suffix}"
        (self.directory / filename).write_bytes(raw)
        item = {
            "id": item_id,
            "name": Path(name or filename).name,
            "file": filename,
            "mode": mode if mode in {"letterbox", "cover", "stretch"} else "letterbox",
        }
        data = self._read()
        data["images"].append(item)
        self._write(data)
        return {"id": item["id"], "name": item["name"], "mode": item["mode"]}

    def remove(self, kind: str, item_id: str) -> None:
        data = self._read()
        key = "texts" if kind == "text" else "images"
        kept = []
        for item in data[key]:
            if item["id"] == item_id and kind == "image":
                file_path = self.directory / item["file"]
                if file_path.exists():
                    file_path.unlink()
            if item["id"] != item_id:
                kept.append(item)
        data[key] = kept
        self._write(data)

    def image_bytes(self, item_id: str) -> tuple[bytes, str]:
        for item in self._read()["images"]:
            if item["id"] == item_id:
                return (self.directory / item["file"]).read_bytes(), item.get("mode") or "letterbox"
        raise ValueError("That picture is not in the library")

    def _read(self) -> dict:
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        return {
            "texts": list(loaded.get("texts") or []),
            "images": list(loaded.get("images") or []),
            "hold_seconds": int(loaded.get("hold_seconds") or HOLD_SECONDS),
            "defaults_seeded": bool(loaded.get("defaults_seeded")),
            "greeting_seeded": bool(loaded.get("greeting_seeded")),
        }

    def _write(self, data: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
