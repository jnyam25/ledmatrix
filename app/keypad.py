"""USB number-pad commands. Keys are saved locally and played with no screen."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEYPAD_FILE = ROOT / "data" / "keypad.json"

KEY_ORDER = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "+", "-", "*", "/", "enter", "."]

ACTIONS = {
    "item": "Library item",
    "weather": "Weather",
    "next": "Next",
    "previous": "Previous",
    "pause": "Pause or resume",
    "brighter": "Brighter",
    "dimmer": "Dimmer",
}

_ALIASES = {
    "enter": "enter",
    "return": "enter",
    "kp_enter": "enter",
    "+": "+",
    "plus": "+",
    "add": "+",
    "kp_plus": "+",
    "-": "-",
    "minus": "-",
    "subtract": "-",
    "kp_minus": "-",
    "*": "*",
    "multiply": "*",
    "asterisk": "*",
    "kp_multiply": "*",
    "/": "/",
    "divide": "/",
    "slash": "/",
    "kp_divide": "/",
    ".": ".",
    "dot": ".",
    "decimal": ".",
    "period": ".",
    "kp_dot": ".",
}


def normalize_key(raw: str) -> str:
    text = (raw or "").strip().lower()
    if text in _ALIASES:
        return _ALIASES[text]
    if text.startswith("kp") and text[2:].isdigit() and text[2:] in KEY_ORDER:
        return text[2:]
    if text in KEY_ORDER:
        return text
    raise ValueError("Use a number-pad key: 0-9, + - * / . or Enter")


def previous_index(index: int, count: int) -> int:
    """Step back from the item the playlist has already advanced past."""
    if count <= 0:
        return 0
    return (index - 2) % count


def library_slots(snapshot: dict) -> list[tuple[str, dict]]:
    slots = [("text", item) for item in snapshot.get("texts") or []]
    slots.extend(("image", item) for item in snapshot.get("images") or [])
    return slots


def default_bindings() -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for digit in range(1, 10):
        key = str(digit)
        rows[key] = {"key": key, "action": "item", "slot": digit, "label": f"Library item {digit}"}
    rows["0"] = {"key": "0", "action": "weather", "label": "Weather"}
    rows["+"] = {"key": "+", "action": "brighter", "label": "Brighter"}
    rows["-"] = {"key": "-", "action": "dimmer", "label": "Dimmer"}
    rows["*"] = {"key": "*", "action": "pause", "label": "Pause or resume"}
    rows["/"] = {"key": "/", "action": "previous", "label": "Previous"}
    rows["enter"] = {"key": "enter", "action": "next", "label": "Next"}
    rows["."] = {"key": ".", "action": "next", "label": "Next"}
    return rows


class Keypad:
    def __init__(self, path: Path = KEYPAD_FILE) -> None:
        self.path = path
        self.bindings = self._load()

    def rows(self) -> list[dict]:
        ordered = [self.bindings[key] for key in KEY_ORDER if key in self.bindings]
        extras = [item for key, item in self.bindings.items() if key not in KEY_ORDER]
        return [dict(item) for item in ordered + extras]

    def binding(self, raw: str) -> dict | None:
        try:
            key = normalize_key(raw)
        except ValueError:
            return None
        item = self.bindings.get(key)
        return dict(item) if item else None

    def replace(self, rows: list[dict]) -> list[dict]:
        cleaned: dict[str, dict] = {}
        for row in rows:
            key = normalize_key(str(row.get("key", "")))
            action = str(row.get("action", ""))
            if action not in ACTIONS:
                raise ValueError(f"Choose a command for the {key} key")
            label = " ".join(str(row.get("label") or ACTIONS[action]).split())[:80] or ACTIONS[action]
            item = {"key": key, "action": action, "label": label}
            if action == "item":
                slot = int(row.get("slot") or 0)
                if slot < 1 or slot > 99:
                    raise ValueError(f"The {key} key needs a library slot from 1 to 99")
                item["slot"] = slot
            cleaned[key] = item
        if not cleaned:
            raise ValueError("Keep at least one key")
        self.bindings = cleaned
        self._write()
        return self.rows()

    def _load(self) -> dict[str, dict]:
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default_bindings()
        rows = loaded.get("keys") if isinstance(loaded, dict) else None
        if not isinstance(rows, list):
            return default_bindings()
        try:
            cleaned: dict[str, dict] = {}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                key = normalize_key(str(row.get("key", "")))
                action = str(row.get("action", ""))
                if action not in ACTIONS:
                    continue
                item = {
                    "key": key,
                    "action": action,
                    "label": " ".join(str(row.get("label") or ACTIONS[action]).split())[:80] or ACTIONS[action],
                }
                if action == "item":
                    slot = int(row.get("slot") or 0)
                    if slot < 1 or slot > 99:
                        continue
                    item["slot"] = slot
                cleaned[key] = item
            return cleaned or default_bindings()
        except (TypeError, ValueError):
            return default_bindings()

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"keys": self.rows()}, indent=2), encoding="utf-8")
