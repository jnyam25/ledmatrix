"""Run the console. `python -m app activate` turns the saved panels on."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

import uvicorn

CONSOLE = "http://127.0.0.1:8765"


def _console_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{CONSOLE}/api/status", timeout=1.5) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def _activate_running_console() -> None:
    request = urllib.request.Request(
        f"{CONSOLE}/api/activate",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Activate failed ({exc.code}): {detail}") from exc
    print(body.get("message") or "System on.")
    print(CONSOLE)


def main() -> None:
    activate = len(sys.argv) > 1 and sys.argv[1] == "activate"
    if activate and _console_is_up():
        _activate_running_console()
        return
    if activate:
        os.environ["LEDMATRIX_ACTIVATE"] = "1"
        print(f"Starting Bright Berry at {CONSOLE}")
    uvicorn.run("app.main:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    main()
