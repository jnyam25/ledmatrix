"""Sign state: preview, weather refresh, and pushes to the two panels."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
from io import BytesIO
from pathlib import Path

from PIL import Image

from app.fleet import PanelLink, normalize_address, scan_panels
from app.keypad import Keypad, library_slots, previous_index
from app.library import Library, build_rotation, dwell_seconds, normalize_runs
from app.render import (
    PANEL_H,
    SIGN_W,
    blank,
    fit_frames,
    frames_png,
    image_strip,
    layout_runs,
    parse_color,
    render_weather,
    split_sign,
    welcome_frame,
)
from app.sensor import read_local_air
from app.weather import current_weather

log = logging.getLogger("ledmatrix.hub")

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "data" / "config.json"

DEFAULT_CONFIG = {
    "left": None,
    "right": None,
    "brightness": 48,
    "weather": {
        "query": "San Antonio",
        "label": "San Antonio",
        "latitude": 29.4241,
        "longitude": -98.4936,
        "timezone": "America/Chicago",
        "units": "fahrenheit",
        "live": False,
        "refresh_seconds": 60,
        "dht11_pin": 4,
    },
}


class Hub:
    def __init__(self) -> None:
        self.config = _load_config()
        self.left = _link_from(self.config.get("left"))
        self.right = _link_from(self.config.get("right"))
        if self.left and self.right and self.left.address == self.right.address:
            self.right = None
            self.config["right"] = None
            _save_config(self.config)
        self.mode = "text"
        self.target = "span"
        self.delay_ms = 120
        self.frames = [welcome_frame()]
        self.message = ""
        self.busy = False
        self.observation: dict | None = None
        self.library = Library()
        self.keypad = Keypad()
        self.now_playing = "Starting the library"
        self.playlist_on = True
        self.pad_name = ""
        self.paused = False
        self._index = 0
        self._jump: tuple[str, dict | None] | None = None
        self._rewind = False
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._advance = asyncio.Event()

    async def close(self) -> None:
        self._stop.set()
        await self._drop(self.left)
        await self._drop(self.right)

    async def live_loop(self) -> None:
        while not self._stop.is_set():
            seconds = int(self.config["weather"].get("refresh_seconds") or 60)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=max(30, seconds))
            except TimeoutError:
                pass
            if self._stop.is_set():
                return
            weather = self.config["weather"]
            if self.playlist_on:
                continue
            if self.mode != "weather" or not weather.get("live"):
                continue
            if weather.get("latitude") is None:
                continue
            try:
                await self.refresh_weather(push=True)
            except Exception as exc:
                log.warning("weather refresh failed: %s", exc)
                self.message = str(exc)

    async def activate(self) -> dict:
        """Log in the saved panels and set brightness. The library keeps the sign moving."""
        notes: list[str] = []
        level = int(self.config.get("brightness") or 48)
        async with self._lock:
            self.busy = True
            try:
                for side, link in (("left", self.left), ("right", self.right)):
                    if link is None:
                        notes.append(f"{side} is not linked")
                        continue
                    try:
                        await link.connect()
                        await link.set_brightness(level)
                        notes.append(f"{side} is on")
                    except Exception as exc:
                        log.warning("activate %s failed", side, exc_info=True)
                        notes.append(f"{side} failed: {exc}")
            finally:
                self.busy = False
        self.message = f"System on. {' '.join(notes)} The library is playing.".strip()
        return self.preview_payload()

    async def playlist_loop(self) -> None:
        """Play text, then a picture, then weather, and keep going."""
        while not self._stop.is_set():
            if self.paused:
                await self._wait(None)
                continue
            jump = self._jump
            self._jump = None
            if jump is not None:
                kind, item = jump
            else:
                rotation = self._rotation()
                if not rotation:
                    self._rewind = False
                    self.now_playing = "Add text or a picture to the library"
                    await self._wait(2)
                    continue
                if self._rewind:
                    self._index = previous_index(self._index, len(rotation))
                    self._rewind = False
                kind, item = rotation[self._index % len(rotation)]
                self._index = (self._index + 1) % len(rotation)
            if self._stop.is_set():
                return
            try:
                dwell = await self._play_library_item(kind, item)
            except Exception as exc:
                log.warning("playlist %s failed", kind, exc_info=True)
                self.message = str(exc.args[0] if exc.args and isinstance(exc.args[0], str) else exc)
                dwell = 5
            await self._wait(dwell)

    async def _wait(self, timeout: float | None) -> None:
        stop_task = asyncio.create_task(self._stop.wait())
        advance_task = asyncio.create_task(self._advance.wait())
        try:
            await asyncio.wait({stop_task, advance_task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stop_task.cancel()
            advance_task.cancel()
            self._advance.clear()

    async def press_key(self, raw: str) -> dict:
        """Run the command saved for one USB number-pad key."""
        binding = self.keypad.binding(raw)
        if binding is None:
            self.message = "That number-pad key has no command."
            return self.status()
        action = binding["action"]
        if action == "brighter":
            level = int(self.config.get("brightness") or 48) + 24
            result = await self.set_brightness(level)
            result["message"] = binding["label"]
            self.message = result["message"]
            return result
        if action == "dimmer":
            level = int(self.config.get("brightness") or 48) - 24
            result = await self.set_brightness(level)
            result["message"] = binding["label"]
            self.message = result["message"]
            return result
        if action == "pause":
            self.paused = not self.paused
            self._advance.set()
            self.message = "Paused." if self.paused else "Playing."
            return self.status()
        if action == "item":
            timezone = (self.config.get("weather") or {}).get("timezone") or "auto"
            slots = library_slots(self.library.snapshot(timezone))
            slot = int(binding.get("slot") or 0)
            if slot < 1 or slot > len(slots):
                self.message = f"Library slot {slot} is empty."
                return self.status()
        self.paused = False
        if action == "previous":
            self._jump = None
            self._rewind = True
        elif action == "weather":
            self._rewind = False
            self._jump = ("weather", None)
        elif action == "item":
            self._rewind = False
            self._jump = slots[slot - 1]
        else:
            self._jump = None
            self._rewind = False
        self._advance.set()
        self.message = binding["label"]
        return self.status()

    def _rotation(self) -> list[tuple[str, dict | None]]:
        timezone = (self.config.get("weather") or {}).get("timezone") or "auto"
        saved = self.library.snapshot(timezone)
        weather = self.config.get("weather") or {}
        return build_rotation(saved["texts"], saved["images"], weather.get("latitude") is not None)

    async def _play_library_item(self, kind: str, item: dict | None) -> float:
        timezone = (self.config.get("weather") or {}).get("timezone") or "auto"
        hold = self.library.snapshot(timezone)["hold_seconds"]
        if kind == "text" and item is not None:
            await self.show_text(
                item["text"], item["color"], item["background"], item["speed"], "span", item.get("runs")
            )
            label = item["text"]
        elif kind == "image" and item is not None:
            raw, mode = self.library.image_bytes(item["id"])
            await self.show_image(raw, mode, "span")
            label = item["name"]
        else:
            await self.refresh_weather(push=True)
            label = (self.observation or {}).get("place") or "Weather"
        self.now_playing = label
        self.message = f"{label} · offline" if "failed" in self.message.lower() else label
        return dwell_seconds(kind, len(self.frames), int(self.delay_ms), hold)

    async def scan(self) -> list[dict]:
        async with self._lock:
            self.busy = True
            try:
                await self._drop(self.left)
                await self._drop(self.right)
                devices = await scan_panels()
                matrices = [item for item in devices if item["likely"]]
                if len(matrices) == 1:
                    self.message = (
                        "Found 1 matrix. Link it to one side, power on the other board, "
                        "and scan again. The same board cannot fill both sides."
                    )
                elif len(matrices) > 1:
                    self.message = f"Found {len(matrices)} matrices. Assign each address to a different side."
                else:
                    self.message = f"Found {len(devices)} named Bluetooth device(s), and no matrix yet."
                return devices
            finally:
                self.busy = False

    async def assign(self, side: str, address: str, name: str) -> dict:
        if side not in {"left", "right"}:
            raise ValueError("Choose the left or right panel")
        address = normalize_address(address)
        if not address:
            raise ValueError("That panel has no Bluetooth address")
        async with self._lock:
            self.busy = True
            try:
                other_side = "right" if side == "left" else "left"
                other = self.right if side == "left" else self.left
                cleared = False
                if other and other.address == address:
                    await self._drop(other)
                    if other_side == "left":
                        self.left = None
                    else:
                        self.right = None
                    self.config[other_side] = None
                    cleared = True
                current = self.left if side == "left" else self.right
                await self._drop(current)
                link = PanelLink(address, name.strip())
                try:
                    await link.connect()
                    note = "Connected"
                except Exception as exc:
                    note = f"Saved, but Bluetooth login failed: {exc}"
                if cleared:
                    note += ". That address was also on the other side, so the other side was cleared"
                if side == "left":
                    self.left = link
                else:
                    self.right = link
                self.config[side] = {"address": link.address, "name": link.name}
                _save_config(self.config)
                level = int(self.config.get("brightness") or 48)
                if link.connected:
                    try:
                        await link.set_brightness(level)
                    except Exception:
                        log.debug("brightness after assign failed", exc_info=True)
                self.message = f"{side.capitalize()} panel {note.lower()}."
                return self.status()
            finally:
                self.busy = False

    async def set_brightness(self, level: int) -> dict:
        level = max(5, min(255, int(level)))
        async with self._lock:
            self.config["brightness"] = level
            _save_config(self.config)
            errors = []
            for side, link in (("left", self.left), ("right", self.right)):
                if link is None:
                    continue
                try:
                    await link.set_brightness(level)
                except Exception as exc:
                    errors.append(f"{side}: {exc}")
            self.message = "Brightness updated." if not errors else "; ".join(errors)
            return self.status()

    async def show_text(
        self,
        text: str,
        color: str,
        background: str,
        speed: int,
        target: str,
        runs: list | None = None,
    ) -> dict:
        message, _ink, cleaned = normalize_runs(text, color, runs)
        target = "span"
        speed = max(1, min(10, int(speed)))
        bg = parse_color(background, (0, 0, 0))
        scale = 2 if len(message) <= 24 else 1
        pairs = [(run["text"], parse_color(run["color"])) for run in cleaned]
        content = layout_runs(pairs, bg, scale=scale)
        delay = int(140 - (speed - 1) * 10)
        step = 1 if speed < 4 else 2 if speed < 8 else 3
        frames = fit_frames(content, SIGN_W, bg, step=step, travel=True)
        async with self._lock:
            self.mode = "text"
            self.target = target
            self.delay_ms = delay
            self.frames = frames
            self.busy = True
            try:
                pushed = await self._push(frames, self.delay_ms, target)
            finally:
                self.busy = False
            self.message = pushed
            return self.preview_payload()

    async def show_image(self, raw: bytes, mode: str, target: str) -> dict:
        if len(raw) > 8_000_000:
            raise ValueError("Image is larger than 8 MB")
        target = "span"
        try:
            source = Image.open(BytesIO(raw))
            frames = _traveling_image(source, mode)
        except Exception as exc:
            raise ValueError("That file is not an image this app can read") from exc
        async with self._lock:
            self.mode = "image"
            self.target = target
            self.delay_ms = 80
            self.frames = frames
            self.busy = True
            try:
                pushed = await self._push(frames, self.delay_ms, target)
            finally:
                self.busy = False
            self.message = pushed
            return self.preview_payload()

    async def start_weather(self, place: dict, units: str, live: bool, refresh_seconds: int) -> dict:
        units = "fahrenheit" if units != "celsius" else "celsius"
        refresh_seconds = max(30, min(3600, int(refresh_seconds)))
        weather = self.config["weather"]
        weather.update(
            {
                "query": place.get("name") or place.get("label") or "",
                "label": place.get("name") or place.get("label") or "",
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "timezone": place.get("timezone") or "auto",
                "units": units,
                "live": bool(live),
                "refresh_seconds": refresh_seconds,
            }
        )
        _save_config(self.config)
        return await self.refresh_weather(push=True)

    async def refresh_weather(self, push: bool) -> dict:
        weather = self.config["weather"]
        units = weather.get("units") or "fahrenheit"
        timezone = weather.get("timezone") or "America/Chicago"
        obs = await asyncio.to_thread(read_local_air, weather.get("dht11_pin", 4), units, timezone)
        if obs is None:
            if weather.get("latitude") is None:
                raise ValueError("Choose a city first")
            obs = await asyncio.to_thread(
                current_weather,
                weather["latitude"],
                weather["longitude"],
                units,
                timezone,
            )
        obs["place"] = weather.get("label") or weather.get("query") or "San Antonio"
        image = render_weather(obs)
        async with self._lock:
            self.mode = "weather"
            self.target = "span"
            self.delay_ms = 1000
            self.frames = [image]
            self.observation = obs
            if not push:
                self.message = "Weather preview updated."
                return self.preview_payload()
            self.busy = True
            try:
                pushed = await self._push([image], 1000, "span")
            finally:
                self.busy = False
            self.message = pushed
            return self.preview_payload()

    async def _push(self, frames: list[Image.Image], delay_ms: int | list[int], target: str) -> str:
        jobs: list[tuple[str, PanelLink, list[Image.Image]]] = []
        if target == "span":
            left_frames = []
            right_frames = []
            for frame in frames:
                left, right = split_sign(frame)
                left_frames.append(left)
                right_frames.append(right)
            if self.left:
                jobs.append(("left", self.left, left_frames))
            if self.right:
                jobs.append(("right", self.right, right_frames))
        elif target == "left" and self.left:
            jobs.append(("left", self.left, frames))
        elif target == "right" and self.right:
            jobs.append(("right", self.right, frames))

        if not jobs:
            return "Preview updated. No panel is linked yet, so nothing was sent."

        notes = []
        armed = []
        for side, link, panel_frames in jobs:
            try:
                notes.append(f"{side}: {await link.upload(panel_frames, delay_ms)}")
                armed.append(link)
            except Exception as exc:
                log.warning("push to %s failed", side, exc_info=True)
                detail = exc.args[0] if exc.args and isinstance(exc.args[0], str) else exc
                notes.append(f"{side} failed: {detail}")
        if len(armed) > 1 and len(frames) > 1:
            await asyncio.gather(*(link.kick() for link in armed), return_exceptions=True)
        return " ".join(notes)

    def status(self) -> dict:
        weather = self.config["weather"]
        return {
            "left": _side_status(self.left),
            "right": _side_status(self.right),
            "brightness": self.config.get("brightness", 48),
            "mode": self.mode,
            "busy": self.busy,
            "message": self.message,
            "playlist": {
                "now": self.now_playing,
                "hold_seconds": self.library.snapshot(weather.get("timezone") or "auto")["hold_seconds"],
                "paused": self.paused,
            },
            "keypad": {
                "device": self.pad_name,
            },
            "weather": {
                "label": weather.get("label") or "",
                "units": weather.get("units") or "fahrenheit",
                "live": bool(weather.get("live")),
                "refresh_seconds": weather.get("refresh_seconds") or 60,
                "latitude": weather.get("latitude"),
                "longitude": weather.get("longitude"),
                "timezone": weather.get("timezone") or "auto",
                "observation": self.observation,
            },
        }

    def preview_payload(self) -> dict:
        encoded = []
        for frame in self.frames[:48]:
            encoded.append(base64.b64encode(frames_png(frame)).decode("ascii"))
        body = self.status()
        body["preview"] = {
            "width": SIGN_W,
            "height": PANEL_H,
            "delay_ms": self.delay_ms,
            "frames": encoded,
        }
        return body

    async def _drop(self, link: PanelLink | None) -> None:
        if link is not None:
            await link.disconnect()


def _traveling_image(source: Image.Image, mode: str) -> list[Image.Image]:
    count = min(getattr(source, "n_frames", 1) or 1, 12)
    strips: list[Image.Image] = []
    for index in range(count):
        source.seek(index)
        frame = source.copy()
        if mode == "stretch":
            frame = frame.resize((SIGN_W, PANEL_H), Image.Resampling.LANCZOS)
            strips.append(frame.convert("RGB"))
        else:
            strips.append(image_strip(frame))
    if not strips:
        raise ValueError("The image has no frames")
    width = strips[0].width
    strips = [strip.resize((width, PANEL_H), Image.Resampling.NEAREST) for strip in strips]
    span = width + SIGN_W
    step = max(1, math.ceil(span / 48))
    frames: list[Image.Image] = []
    for index, pos in enumerate(range(0, span + 1, step)):
        frame = blank(SIGN_W, PANEL_H, (0, 0, 0))
        frame.paste(strips[index % len(strips)], (pos - width, 0))
        frames.append(frame)
        if len(frames) >= 48:
            break
    return frames


def _side_status(link: PanelLink | None) -> dict | None:
    if link is None:
        return None
    return {"address": link.address, "name": link.name, "connected": link.connected}


def _link_from(saved) -> PanelLink | None:
    if not saved or not saved.get("address"):
        return None
    return PanelLink(normalize_address(saved["address"]), saved.get("name") or "")


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return json.loads(json.dumps(DEFAULT_CONFIG))
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    config.update({key: loaded.get(key, config[key]) for key in ("left", "right", "brightness")})
    if isinstance(loaded.get("weather"), dict):
        config["weather"].update(loaded["weather"])
    return config


def _save_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
