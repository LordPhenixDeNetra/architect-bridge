import socket
import time


class FakeTransport:
    """Transport en memoire : lit `inbox` octet par octet, accumule les ecritures dans `out`."""

    def __init__(self, inbox: bytes):
        self.inbox = bytearray(inbox)
        self.out = bytearray()

    def read(self, n: int, timeout: float) -> bytes:
        chunk = bytes(self.inbox[:n])
        del self.inbox[:n]
        return chunk

    def write(self, data: bytes) -> None:
        self.out += data


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_until(cond, timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError("condition non atteinte")
