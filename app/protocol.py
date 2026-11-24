"""CoolLEDUX / Juntong program packets for jt_2121 16x96 panels.

Framing, CRC, and LZSS match the firmware format used by the stock app.
The LZSS container (N=512, F=18, threshold 2) follows the layout documented
by Greg Tatham's coolledux-linux-uploader, MIT.
"""

from __future__ import annotations

from PIL import Image

CHAR_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
LOGIN = bytes.fromhex("0d 55 55 55 55 55 55 55 00")

_N = 512
_F = 18
_THRESHOLD = 2
_NIL = _N


def u16(value: int) -> bytes:
    return int(value).to_bytes(2, "big")


def u32(value: int) -> bytes:
    return int(value).to_bytes(4, "big", signed=False)


def wrap(payload: bytes) -> bytes:
    """Frame a payload: 0x01, escaped length+payload, 0x03."""
    raw = u16(len(payload)) + payload
    out = bytearray([0x01])
    for byte in raw:
        if 0x00 < byte < 0x04:
            out.append(0x02)
            out.append(byte ^ 0x04)
        else:
            out.append(byte)
    out.append(0x03)
    return bytes(out)


def unwrap(packet: bytes) -> bytes:
    if packet and packet[0] == 0x01 and packet[-1] == 0x03:
        packet = packet[1:-1]
    out = bytearray()
    index = 0
    while index < len(packet):
        if packet[index] == 0x02 and index + 1 < len(packet):
            out.append(packet[index + 1] ^ 0x04)
            index += 2
        else:
            out.append(packet[index])
            index += 1
    return bytes(out[2:]) if len(out) >= 2 else bytes(out)


def crc32_panel(data: bytes) -> int:
    """CRC-32 as computed by the panel firmware (no final XOR)."""
    poly = 0x04C11DB7
    crc = 0xFFFFFFFF
    for byte in data:
        for _ in range(8):
            crc_high = crc & 0x80000000
            data_high = byte & 0x80
            crc = (crc << 1) & 0xFFFFFFFF
            if crc_high:
                crc ^= poly
            if data_high:
                crc ^= poly
            byte = (byte << 1) & 0xFF
    return crc & 0xFFFFFFFF


def xor_checksum(data: bytes) -> int:
    value = 0
    for byte in data:
        value ^= byte
    return value & 0xFF


def lzss_compress(src: bytes) -> bytes:
    """Okumura-style LZSS with the panel's window size."""
    text_buf = bytearray(_N + _F - 1)
    lson = [_NIL] * (_N + 1)
    rson = [_NIL] * (_N + 257)
    dad = [_NIL] * (_N + 1)
    match_position = 0
    match_length = 0

    def insert_node(node: int) -> None:
        nonlocal match_position, match_length
        parent = text_buf[node] + _N + 1
        lson[node] = _NIL
        rson[node] = _NIL
        match_length = 0
        cmp_val = 1
        while True:
            if cmp_val >= 0:
                if rson[parent] != _NIL:
                    parent = rson[parent]
                else:
                    rson[parent] = node
                    dad[node] = parent
                    return
            else:
                if lson[parent] != _NIL:
                    parent = lson[parent]
                else:
                    lson[parent] = node
                    dad[node] = parent
                    return
            offset = 1
            while offset < _F:
                cmp_val = text_buf[node + offset] - text_buf[parent + offset]
                if cmp_val != 0:
                    break
                offset += 1
            if offset > match_length:
                match_position = parent
                match_length = offset
            if offset >= _F:
                dad[node] = dad[parent]
                lson[node] = lson[parent]
                rson[node] = rson[parent]
                dad[lson[parent]] = node
                dad[rson[parent]] = node
                if rson[dad[parent]] == parent:
                    rson[dad[parent]] = node
                else:
                    lson[dad[parent]] = node
                dad[parent] = _NIL
                return

    def delete_node(node: int) -> None:
        if dad[node] == _NIL:
            return
        if rson[node] == _NIL:
            child = lson[node]
        elif lson[node] == _NIL:
            child = rson[node]
        else:
            child = lson[node]
            if rson[child] != _NIL:
                while rson[child] != _NIL:
                    child = rson[child]
                rson[dad[child]] = lson[child]
                dad[lson[child]] = dad[child]
                lson[child] = lson[node]
                dad[lson[node]] = child
            rson[child] = rson[node]
            dad[rson[node]] = child
        dad[child] = dad[node]
        if rson[dad[node]] == node:
            rson[dad[node]] = child
        else:
            lson[dad[node]] = child
        dad[node] = _NIL

    out = bytearray()
    code_buf = bytearray(17)
    code_ptr = 1
    mask = 1
    cursor = 0
    window = _N - _F
    for index in range(window):
        text_buf[index] = 0x20

    src_i = 0
    length = 0
    while length < _F and src_i < len(src):
        text_buf[window + length] = src[src_i]
        src_i += 1
        length += 1
    if length == 0:
        return b""

    for index in range(1, _F + 1):
        insert_node(window - index)
    insert_node(window)

    while True:
        if match_length > length:
            match_length = length
        if match_length <= _THRESHOLD:
            match_length = 1
            code_buf[0] |= mask
            code_buf[code_ptr] = text_buf[window]
            code_ptr += 1
        else:
            code_buf[code_ptr] = match_position & 0xFF
            code_buf[code_ptr + 1] = ((match_position >> 4) & 0xF0) | (
                match_length - (_THRESHOLD + 1)
            )
            code_ptr += 2
        mask = (mask << 1) & 0xFF
        if mask == 0:
            out += code_buf[:code_ptr]
            code_buf[0] = 0
            code_ptr = 1
            mask = 1

        last_match = match_length
        step = 0
        while step < last_match and src_i < len(src):
            delete_node(cursor)
            text_buf[cursor] = src[src_i]
            if cursor < _F - 1:
                text_buf[cursor + _N] = src[src_i]
            cursor = (cursor + 1) & (_N - 1)
            window = (window + 1) & (_N - 1)
            src_i += 1
            insert_node(window)
            step += 1
        while step < last_match:
            delete_node(cursor)
            cursor = (cursor + 1) & (_N - 1)
            window = (window + 1) & (_N - 1)
            length -= 1
            if length:
                insert_node(window)
            step += 1
        if length <= 0:
            break

    if code_ptr > 1:
        out += code_buf[:code_ptr]
    return bytes(out)


def rgb444(red: int, green: int, blue: int) -> bytes:
    return bytes([red // 16, ((green // 16) << 4) | (blue // 16)])


def frame_bytes(image: Image.Image, width: int, height: int) -> bytes:
    """Column-major RGB444. Transparent pixels become black."""
    fitted = image.convert("RGBA").resize((width, height), Image.Resampling.NEAREST)
    data = bytearray()
    pixels = fitted.load()
    for x in range(width):
        for y in range(height):
            red, green, blue, alpha = pixels[x, y]
            if alpha < 128:
                red = green = blue = 0
            data += rgb444(red, green, blue)
    return bytes(data)


def build_program(frames: list[Image.Image], delays_ms: list[int], width: int, height: int) -> bytes:
    if not frames:
        raise ValueError("A program needs at least one frame")
    if len(frames) != len(delays_ms):
        raise ValueError("Each frame needs a delay")
    inner = bytearray()
    inner += b"\x03\x01"
    inner += b"\x00" * 6
    inner += b"\x00"
    inner += u16(0)
    inner += u16(0)
    inner += u16(width)
    inner += u16(height)
    inner += b"\x00"
    inner += u16(len(frames))
    for delay in delays_ms:
        inner += u16(max(20, min(65535, int(delay))))
    for frame in frames:
        inner += frame_bytes(frame, width, height)
    block = u32(len(inner) + 4) + inner
    program = bytearray()
    program += b"\x00" * 8
    program += b"\x01"
    program += b"\x00"
    program += block
    return bytes(program)


def brightness_packet(level: int) -> bytes:
    level = max(5, min(255, int(level)))
    return wrap(bytes([0x04, level]))


def start_packet(program: bytes, index: int = 0, count: int = 1, show_count: int = 1) -> bytes:
    payload = b"\x02"
    payload += u32(crc32_panel(program))
    payload += u32(len(program))
    payload += bytes([index & 0xFF, count & 0xFF, show_count & 0xFF])
    return wrap(payload)


def chunk_packet(compressed: bytes, chunk_index: int, chunk: bytes) -> bytes:
    body = b"\x00"
    body += u32(len(compressed))
    body += u16(chunk_index)
    body += u16(len(chunk))
    body += chunk
    body += bytes([xor_checksum(body)])
    return wrap(b"\x03" + body)


def iter_chunks(data: bytes, size: int):
    size = max(16, int(size))
    for index in range(0, len(data), size):
        yield data[index : index + size]


def largest_chunk(write_limit: int) -> int:
    """Largest chunk whose escaped packet still fits in one write."""
    limit = max(20, int(write_limit))
    for size in range(min(180, limit), 0, -1):
        sample = bytes([0x01, 0x02, 0x03]) * ((size // 3) + 1)
        packet = chunk_packet(b"\x01" * 8, 0, sample[:size])
        if len(packet) <= limit:
            return size
    return 1
