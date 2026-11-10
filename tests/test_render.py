from track_glow.models import Flag
from track_glow.render import (
    LED_COLORS,
    OFF,
    blocks,
    flag_frame,
    solid,
)

A = (1, 2, 3)
B = (4, 5, 6)
GREEN = (0x00, 0xFF, 0x00)
WHITE = (0xFF, 0xFF, 0xFF)
BLACK = (0, 0, 0)


def led(frame: bytes, i: int) -> tuple[int, int, int]:
    return tuple(frame[i * 3 : i * 3 + 3])


def test_blocks_alternate_every_6():
    frame = blocks(14, A, B, 0)
    assert [led(frame, i) for i in range(14)] == [A] * 6 + [B] * 6 + [A] * 2


def test_phase_1_swaps():
    frame = blocks(14, A, B, 1)
    assert [led(frame, i) for i in range(14)] == [B] * 6 + [A] * 6 + [B] * 2


def test_flash_then_hold_green():
    assert led(flag_frame(Flag.GREEN, 12, 0), 0) == GREEN
    assert led(flag_frame(Flag.GREEN, 12, 0), 6) == OFF
    assert led(flag_frame(Flag.GREEN, 12, 0.3), 0) == OFF
    assert flag_frame(Flag.GREEN, 12, 1.6) == solid(12, GREEN)


def test_checkered_flashes_5s_then_holds_pattern():
    held = blocks(12, WHITE, BLACK, 0)
    assert flag_frame(Flag.CHECKERED, 12, 4.9) == blocks(12, WHITE, BLACK, 1)
    assert flag_frame(Flag.CHECKERED, 12, 5.1) == held
    assert flag_frame(Flag.CHECKERED, 12, 9.9) == held


def test_frame_length_is_3n():
    for flag in Flag:
        for elapsed in (0, 0.3, 2.0, 6.0):
            assert len(flag_frame(flag, 37, elapsed)) == 3 * 37
    assert len(solid(5, A)) == 15
    assert len(blocks(0, A, B, 0)) == 0


def test_every_flag_has_led_color():
    assert set(LED_COLORS) == set(Flag)
