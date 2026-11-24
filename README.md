# Bright Berry

Local console for two 16×96 LED panels, shown as one 16×192 sign. It plays a library of text and pictures, then local weather, and keeps going on its own.

## Run

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m app
```

Open http://127.0.0.1:8765. On Windows, `activate.cmd` connects the saved panels and starts the playlist.

## Layout

- `app/` — sign protocol, playlist, weather, DHT11, and USB number pad
- `static/` — dashboard
- `tests/` — unit tests
- `deploy/` — Raspberry Pi service and kiosk install

Panel addresses, the library, and number-pad commands stay in `data/` and are not part of the repo.
