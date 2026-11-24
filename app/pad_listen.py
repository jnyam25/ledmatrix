"""Read a USB number pad. On the Pi this uses the input device directly, so no monitor is required."""

from __future__ import annotations

import asyncio
import logging
import os
import select
import sys
import threading
import time

log = logging.getLogger("ledmatrix.pad")

_WINDOWS_VK = {
    96: "0",
    97: "1",
    98: "2",
    99: "3",
    100: "4",
    101: "5",
    102: "6",
    103: "7",
    104: "8",
    105: "9",
    106: "*",
    107: "+",
    109: "-",
    110: ".",
    111: "/",
}


def listen_usb_pad(loop: asyncio.AbstractEventLoop, hub, stopper: threading.Event) -> None:
    if sys.platform == "linux":
        _listen_evdev(loop, hub, stopper)
        return
    _listen_pynput(loop, hub, stopper)


def _emit(loop: asyncio.AbstractEventLoop, hub, key: str, recent: dict[str, float]) -> None:
    now = time.monotonic()
    if now - recent.get(key, 0) < 0.25:
        return
    recent[key] = now
    asyncio.run_coroutine_threadsafe(hub.press_key(key), loop)


def _listen_pynput(loop: asyncio.AbstractEventLoop, hub, stopper: threading.Event) -> None:
    try:
        from pynput import keyboard
    except ImportError:
        log.warning("USB number pad listener is unavailable. Install pynput on Windows.")
        hub.pad_name = ""
        return

    recent: dict[str, float] = {}

    def win32_event_filter(msg, data):
        if msg not in (0x0100, 0x0104):
            return True
        extended_enter = data.vkCode == 13 and bool(data.flags & 0x01)
        key = "enter" if extended_enter else _WINDOWS_VK.get(data.vkCode)
        if key is None:
            return True
        hub.pad_name = "USB number pad"
        _emit(loop, hub, key, recent)
        listener.suppress_event()
        return True

    listener = keyboard.Listener(win32_event_filter=win32_event_filter)
    try:
        listener.start()
    except Exception:
        log.warning("USB number pad listener did not start", exc_info=True)
        hub.pad_name = ""
        return
    log.info("listening for a USB number pad")
    stopper.wait()
    listener.stop()
    hub.pad_name = ""


def _open_pads():
    from evdev import InputDevice, ecodes, list_devices

    forced = os.environ.get("LEDMATRIX_KEYPAD", "").strip()
    if forced:
        return [InputDevice(forced)], True

    preferred = []
    others = []
    for path in list_devices():
        device = InputDevice(path)
        try:
            keys = set(device.capabilities().get(ecodes.EV_KEY, []))
        except OSError:
            device.close()
            continue
        if ecodes.KEY_KP0 not in keys and ecodes.KEY_KP1 not in keys:
            device.close()
            continue
        name = (device.name or "").lower()
        if any(word in name for word in ("numpad", "keypad", "number pad", "num pad")):
            preferred.append(device)
        else:
            others.append(device)
    if preferred:
        for device in others:
            device.close()
        return preferred, True
    return others, False


def _listen_evdev(loop: asyncio.AbstractEventLoop, hub, stopper: threading.Event) -> None:
    try:
        from evdev import ecodes
    except ImportError:
        log.warning("USB number pad listener is unavailable. Install evdev on the Pi.")
        hub.pad_name = ""
        return

    codes = {
        ecodes.KEY_KP0: "0",
        ecodes.KEY_KP1: "1",
        ecodes.KEY_KP2: "2",
        ecodes.KEY_KP3: "3",
        ecodes.KEY_KP4: "4",
        ecodes.KEY_KP5: "5",
        ecodes.KEY_KP6: "6",
        ecodes.KEY_KP7: "7",
        ecodes.KEY_KP8: "8",
        ecodes.KEY_KP9: "9",
        ecodes.KEY_KPPLUS: "+",
        ecodes.KEY_KPMINUS: "-",
        ecodes.KEY_KPASTERISK: "*",
        ecodes.KEY_KPSLASH: "/",
        ecodes.KEY_KPDOT: ".",
        ecodes.KEY_KPENTER: "enter",
    }
    recent: dict[str, float] = {}
    while not stopper.is_set():
        try:
            devices, grab = _open_pads()
        except Exception:
            log.warning("number pad scan failed", exc_info=True)
            hub.pad_name = ""
            stopper.wait(2)
            continue
        if not devices:
            hub.pad_name = ""
            stopper.wait(2)
            continue
        for device in devices:
            if not grab:
                continue
            try:
                device.grab()
            except OSError:
                log.info("could not reserve %s", device.path)
        hub.pad_name = devices[0].name or "USB number pad"
        log.info("USB number pad ready: %s", hub.pad_name)
        fds = {device.fd: device for device in devices}
        try:
            while not stopper.is_set():
                ready, _, _ = select.select(list(fds), [], [], 0.5)
                for fd in ready:
                    for event in fds[fd].read():
                        if event.type != ecodes.EV_KEY or event.value != 1:
                            continue
                        key = codes.get(event.code)
                        if key:
                            _emit(loop, hub, key, recent)
        except OSError:
            log.info("USB number pad unplugged")
        finally:
            for device in devices:
                try:
                    device.close()
                except OSError:
                    pass
            hub.pad_name = ""
