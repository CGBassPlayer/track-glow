from track_glow.models import Flag

Rgb = tuple[int, int, int]

WHITE: Rgb = (0xFF, 0xFF, 0xFF)
OFF: Rgb = (0, 0, 0)
OFFLINE: Rgb = (0x40, 0x18, 0x00)

LED_COLORS: dict[Flag, Rgb] = {
    Flag.GREEN: (0x00, 0xFF, 0x00),
    Flag.YELLOW: (0xFF, 0xC8, 0x00),
    Flag.RED: (0xFF, 0x00, 0x00),
    Flag.WHITE: WHITE,
    Flag.CHECKERED: WHITE,
    Flag.HOT_TRACK: (0x00, 0x00, 0xFF),
    Flag.COLD_TRACK: (0x28, 0x28, 0x28),
}

BLOCK = 6
FLASH_STEP = 0.25
FLASH_SECONDS = 1.5
CHECKERED_SECONDS = 5.0


def blocks(n: int, a: Rgb, b: Rgb, phase: int, block: int = BLOCK) -> bytes:
    pa, pb = bytes(a), bytes(b)
    return b"".join(pa if (i // block + phase) % 2 == 0 else pb for i in range(n))


def solid(n: int, c: Rgb) -> bytes:
    return bytes(c) * n


def flag_frame(flag: Flag, n: int, elapsed: float) -> bytes:
    phase = int(elapsed / FLASH_STEP) % 2
    if flag is Flag.CHECKERED:
        return blocks(n, WHITE, OFF, phase if elapsed < CHECKERED_SECONDS else 0)
    color = LED_COLORS[flag]
    if elapsed < FLASH_SECONDS:
        return blocks(n, color, OFF, phase)
    return solid(n, color)
