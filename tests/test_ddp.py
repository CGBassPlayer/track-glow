import socket
import struct

import pytest

from track_glow.ddp import DDP_PORT, MAX_DATA, DdpSender, ddp_packets


def header(pkt: bytes) -> tuple[int, int, int, int, int, int]:
    return struct.unpack(">BBBBIH", pkt[:10])


def test_constants():
    assert DDP_PORT == 4048
    assert MAX_DATA == 1440


def test_single_packet_header():
    pixels = bytes(range(30))
    [pkt] = ddp_packets(pixels, 7)
    assert pkt[0] == 0x41
    assert pkt[1] == 7
    assert pkt[2] == 0x0B
    assert pkt[3] == 0x01
    assert header(pkt)[4:] == (0, 30)
    assert len(pkt) == 40
    assert pkt[10:] == pixels


def test_splits_at_1440_push_only_last():
    pixels = bytes(i % 256 for i in range(1800))
    pkts = ddp_packets(pixels, 3)
    assert len(pkts) == 2
    assert [header(p)[0] for p in pkts] == [0x40, 0x41]
    assert [header(p)[1] for p in pkts] == [3, 3]
    assert [header(p)[4] for p in pkts] == [0, 1440]
    assert [header(p)[5] for p in pkts] == [1440, 360]
    assert b"".join(p[10:] for p in pkts) == pixels


@pytest.fixture
def listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(2)
    yield sock
    sock.close()


def test_sender_delivers_to_udp_listener(listener):
    port = listener.getsockname()[1]
    sender = DdpSender(port=port)
    pixels = bytes([1, 2, 3] * 10)
    sender.send("127.0.0.1", pixels, 5)
    data, _ = listener.recvfrom(2048)
    sender.close()
    assert data == ddp_packets(pixels, 5)[0]
    assert sender.last_error is None


def test_sender_delivers_every_packet_in_order(listener):
    port = listener.getsockname()[1]
    sender = DdpSender(port=port)
    pixels = bytes(i % 256 for i in range(1800))
    sender.send("127.0.0.1", pixels, 2)
    received = [listener.recvfrom(2048)[0] for _ in range(2)]
    sender.close()
    assert received == ddp_packets(pixels, 2)


def test_send_error_recorded_not_raised():
    sender = DdpSender()
    sender.send("256.0.0.1", bytes(30), 1)
    assert sender.last_error
    sender.close()


def test_close_is_idempotent():
    sender = DdpSender()
    assert sender.closed is False
    sender.close()
    sender.close()
    assert sender.closed is True
