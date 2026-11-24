"""Bluetooth sessions for one or two Juntong panels."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakDeviceNotFoundError
from PIL import Image

from app.protocol import (
    CHAR_UUID,
    LOGIN,
    brightness_packet,
    build_program,
    chunk_packet,
    iter_chunks,
    largest_chunk,
    lzss_compress,
    start_packet,
    unwrap,
    wrap,
)

log = logging.getLogger("ledmatrix.fleet")

LIKELY = ("jt_", "2121", "16x96", "coolled", "led")
_SEEN: dict[str, BLEDevice] = {}


def normalize_address(address: str) -> str:
    return address.strip().upper().replace("-", ":")


def _likely(name: str) -> bool:
    folded = name.lower()
    return any(token in folded for token in LIKELY)


@dataclass
class PanelLink:
    address: str
    name: str = ""
    client: BleakClient | None = None
    _acks: asyncio.Queue = field(default_factory=asyncio.Queue)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def connected(self) -> bool:
        return bool(self.client and self.client.is_connected)

    def _on_notify(self, _sender, data: bytearray) -> None:
        payload = unwrap(bytes(data))
        loop = getattr(self, "_loop", None)
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._acks.put_nowait, payload)

    async def _wait(self, command: int, timeout: float) -> bytes:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError(f"Panel {self.name or self.address} did not answer command {command:#04x}")
            payload = await asyncio.wait_for(self._acks.get(), timeout=remaining)
            if payload and payload[0] == command:
                return payload

    async def connect(self) -> None:
        async with self._lock:
            if self.connected:
                return
            while not self._acks.empty():
                self._acks.get_nowait()
            self._loop = asyncio.get_running_loop()
            self.address = normalize_address(self.address)
            client = await self._open_client()
            try:
                await client.start_notify(CHAR_UUID, self._on_notify)
                await asyncio.sleep(0.2)
                await client.write_gatt_char(CHAR_UUID, wrap(LOGIN), response=False)
                await self._wait(0x0D, 8)
            except Exception:
                await client.disconnect()
                raise
            self.client = client
            log.info("logged in %s %s", self.name, self.address)

    async def _open_client(self) -> BleakClient:
        """Connect from the last scan. Windows can open that address without a second search."""
        remembered = _SEEN.get(self.address) or BLEDevice(self.address, self.name or None, None)
        try:
            client = BleakClient(remembered, timeout=20.0)
            await client.connect()
            return client
        except BleakDeviceNotFoundError:
            log.info("address cache miss for %s, scanning once", self.address)
        fresh = await BleakScanner.find_device_by_address(self.address, timeout=8.0)
        if fresh is None:
            raise RuntimeError(
                f"{self.name or 'Panel'} {self.address} is not in range. "
                "Power it on, close the phone app, and scan again."
            )
        _SEEN[self.address] = fresh
        client = BleakClient(fresh, timeout=20.0)
        await client.connect()
        return client

    async def disconnect(self) -> None:
        client = self.client
        self.client = None
        if client and client.is_connected:
            try:
                await client.disconnect()
            except Exception:
                log.debug("disconnect failed", exc_info=True)

    async def set_brightness(self, level: int) -> None:
        await self.connect()
        assert self.client is not None
        async with self._lock:
            await self.client.write_gatt_char(CHAR_UUID, brightness_packet(level), response=False)
            await self._wait(0x04, 8)

    async def upload(self, frames: list[Image.Image], delay_ms: int | list[int]) -> str:
        await self.connect()
        assert self.client is not None
        delays = delay_ms if isinstance(delay_ms, list) else [delay_ms] * len(frames)
        program = build_program(frames, delays, frames[0].width, frames[0].height)
        compressed = lzss_compress(program)
        char = self.client.services.get_characteristic(CHAR_UUID)
        if char is None:
            raise RuntimeError("This panel does not expose the CoolLEDUX data characteristic")
        for _ in range(6):
            if char.max_write_without_response_size > 20:
                break
            await asyncio.sleep(0.25)
        pieces = list(iter_chunks(compressed, largest_chunk(char.max_write_without_response_size)))
        self._program = program
        async with self._lock:
            await self._send_program(program, compressed, pieces)
        return f"sent {len(frames)} frame(s) in {len(pieces)} chunks"

    async def _send_program(self, program: bytes, compressed: bytes, pieces: list[bytes]) -> None:
        assert self.client is not None
        await self.client.write_gatt_char(CHAR_UUID, start_packet(program), response=False)
        start = await self._wait(0x02, 8)
        if len(start) >= 2 and start[1] == 1:
            return
        if len(start) >= 2 and start[1] not in (0, 3):
            raise RuntimeError(f"Panel rejected the program (status {start[1]:#04x})")
        for index, piece in enumerate(pieces):
            packet = chunk_packet(compressed, index, piece)
            await self.client.write_gatt_char(CHAR_UUID, packet, response=False)
            await self._wait(0x03, 8)
            await asyncio.sleep(0.02)

    async def kick(self) -> None:
        """Restart the loaded program so both panels begin on the same frame."""
        program = getattr(self, "_program", None)
        if program is None:
            return
        await self.connect()
        assert self.client is not None
        async with self._lock:
            await self.client.write_gatt_char(CHAR_UUID, start_packet(program), response=False)
            await self._wait(0x02, 8)


async def scan_panels(timeout: float = 8.0) -> list[dict]:
    discovered = await BleakScanner.discover(timeout=timeout, return_adv=True)
    found: list[dict] = []
    for address, (device, adv) in discovered.items():
        name = (adv.local_name or device.name or "").strip()
        if not name:
            continue
        seen_address = normalize_address(device.address or address)
        _SEEN[seen_address] = device
        found.append(
            {
                "address": seen_address,
                "name": name,
                "rssi": adv.rssi,
                "likely": _likely(name),
            }
        )
    found.sort(key=lambda item: (not item["likely"], -(item["rssi"] or -200)))
    return found
