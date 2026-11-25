"""Local control console for two 16x96 panels."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.hub import Hub
from app.pad_listen import listen_usb_pad
from app.render import frames_png
from app.weather import search_places

log = logging.getLogger("ledmatrix")
ASSETS = Path(__file__).resolve().parent.parent / "static"


def _hub(app: FastAPI) -> Hub:
    return app.state.hub


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    app.state.hub = Hub()
    if os.environ.get("LEDMATRIX_ACTIVATE") == "1":
        result = await app.state.hub.activate()
        log.info("%s", result.get("message", "System on."))
    live = asyncio.create_task(app.state.hub.live_loop())
    playlist = asyncio.create_task(app.state.hub.playlist_loop())
    pad_stop = threading.Event()
    pad_thread = threading.Thread(
        target=listen_usb_pad,
        args=(asyncio.get_running_loop(), app.state.hub, pad_stop),
        name="usb-numpad",
        daemon=True,
    )
    pad_thread.start()
    try:
        yield
    finally:
        app.state.hub._stop.set()
        pad_stop.set()
        live.cancel()
        playlist.cancel()
        await app.state.hub.close()


app = FastAPI(title="Bright Berry", lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(ASSETS / "index.html")


@app.get("/api/status")
async def status() -> dict:
    return _hub(app).status()


@app.get("/api/preview")
async def preview() -> dict:
    return _hub(app).preview_payload()


@app.get("/api/preview.png")
async def preview_png() -> Response:
    frame = _hub(app).frames[0]
    return Response(content=frames_png(frame), media_type="image/png")


@app.post("/api/activate")
async def activate() -> dict:
    try:
        return await _hub(app).activate()
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/api/scan")
async def scan() -> dict:
    try:
        devices = await _hub(app).scan()
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"devices": devices, **_hub(app).status()}


@app.post("/api/panels")
async def assign_panel(body: dict = Body(...)) -> dict:
    try:
        return await _hub(app).assign(str(body.get("side", "")), str(body.get("address", "")), str(body.get("name", "")))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/api/brightness")
async def brightness(body: dict = Body(...)) -> dict:
    try:
        return await _hub(app).set_brightness(int(body.get("level", 48)))
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/library")
async def library_list() -> dict:
    hub = _hub(app)
    timezone = (hub.config.get("weather") or {}).get("timezone") or "auto"
    saved = hub.library.snapshot(timezone)
    saved["now"] = _hub(app).now_playing
    return saved


@app.post("/api/library/text")
async def library_text(body: dict = Body(...)) -> dict:
    try:
        _hub(app).library.add_text(
            str(body.get("text", "")),
            str(body.get("color", "#d6ff4a")),
            str(body.get("background", "#000000")),
            int(body.get("speed", 4)),
            body.get("runs") if isinstance(body.get("runs"), list) else None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    hub = _hub(app)
    timezone = (hub.config.get("weather") or {}).get("timezone") or "auto"
    saved = hub.library.snapshot(timezone)
    saved["now"] = _hub(app).now_playing
    return saved


@app.post("/api/library/image")
async def library_image(file: UploadFile = File(...), mode: str = Form("letterbox")) -> dict:
    raw = await file.read()
    try:
        _hub(app).library.add_image(file.filename or "image.png", raw, mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    hub = _hub(app)
    timezone = (hub.config.get("weather") or {}).get("timezone") or "auto"
    saved = hub.library.snapshot(timezone)
    saved["now"] = _hub(app).now_playing
    return saved


@app.delete("/api/library/{kind}/{item_id}")
async def library_remove(kind: str, item_id: str) -> dict:
    if kind not in {"text", "image"}:
        raise HTTPException(400, "Choose a text or a picture")
    _hub(app).library.remove(kind, item_id)
    hub = _hub(app)
    timezone = (hub.config.get("weather") or {}).get("timezone") or "auto"
    saved = hub.library.snapshot(timezone)
    saved["now"] = _hub(app).now_playing
    return saved


@app.get("/api/keypad")
async def keypad_list() -> dict:
    hub = _hub(app)
    return {"keys": hub.keypad.rows(), "device": hub.pad_name}


@app.put("/api/keypad")
async def keypad_save(body: dict = Body(...)) -> dict:
    try:
        keys = _hub(app).keypad.replace(list(body.get("keys") or []))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"keys": keys, "device": _hub(app).pad_name}


@app.post("/api/keypad/press")
async def keypad_press(body: dict = Body(...)) -> dict:
    return await _hub(app).press_key(str(body.get("key", "")))


@app.post("/api/text")
async def show_text(body: dict = Body(...)) -> dict:
    try:
        return await _hub(app).show_text(
            str(body.get("text", "")),
            str(body.get("color", "#d6ff4a")),
            str(body.get("background", "#000000")),
            int(body.get("speed", 4)),
            str(body.get("target", "span")),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/api/image")
async def show_image(
    file: UploadFile = File(...),
    mode: str = Form("letterbox"),
    target: str = Form("span"),
) -> dict:
    raw = await file.read()
    try:
        return await _hub(app).show_image(raw, mode, target)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/places")
async def places(q: str = "") -> dict:
    try:
        found = await asyncio.to_thread(search_places, q)
    except Exception as exc:
        raise HTTPException(502, f"Place search failed: {exc}") from exc
    return {"places": found}


@app.post("/api/weather")
async def weather(body: dict = Body(...)) -> dict:
    place = body.get("place") or {}
    try:
        return await _hub(app).start_weather(
            place,
            str(body.get("units", "fahrenheit")),
            bool(body.get("live", True)),
            int(body.get("refresh_seconds", 60)),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
