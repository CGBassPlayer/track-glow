import socket
import struct

DDP_PORT = 4048
MAX_DATA = 1440

_VERSION = 0x40
_PUSH = 0x01
_TYPE_RGB8 = 0x0B
_ID_DISPLAY = 0x01


def ddp_packets(pixels: bytes, seq: int) -> list[bytes]:
    packets = []
    for offset in range(0, len(pixels), MAX_DATA):
        chunk = pixels[offset : offset + MAX_DATA]
        last = offset + MAX_DATA >= len(pixels)
        flags = _VERSION | (_PUSH if last else 0)
        header = struct.pack(">BBBBIH", flags, seq, _TYPE_RGB8, _ID_DISPLAY, offset, len(chunk))
        packets.append(header + chunk)
    return packets


class DdpSender:
    def __init__(self, port: int = DDP_PORT) -> None:
        self.port = port
        self.last_error: str | None = None
        self.closed = False
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setblocking(False)

    def send(self, host: str, pixels: bytes, seq: int) -> None:
        try:
            for pkt in ddp_packets(pixels, seq):
                self._sock.sendto(pkt, (host, self.port))
        except OSError as e:
            self.last_error = f"{host}: {e}"
        else:
            self.last_error = None

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self._sock.close()
