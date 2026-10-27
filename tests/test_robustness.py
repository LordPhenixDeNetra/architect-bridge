"""Cas de robustesse issus de la revue finale."""
import socket
import threading
import time

import pytest

from bridge.datalink import ACK, ENQ, EOT, receive_session
from bridge.drivers.architect import parse_architect
from bridge.ingest import ingest
from bridge.link import LinkState
from bridge.main import run_connector
from bridge.store import Store
from bridge.transport.tcp import TcpServerTransport
from tests.fakes import FakeTransport, free_port, wait_until
from tests.samples import BHCG, H
from tests.test_datalink import frame


def _read_until(t, want: bytes, tries: int = 10) -> bool:
    return any(t.read(1, 0.05) == want for _ in range(tries))


def test_tcp_new_connection_replaces_stale_one():
    port = free_port()
    srv = TcpServerTransport("127.0.0.1", port)
    stale = socket.create_connection(("127.0.0.1", port))
    assert srv.read(1, 0.05) == b""  # accepte la connexion muette
    fresh = socket.create_connection(("127.0.0.1", port))
    fresh.sendall(ENQ)
    assert _read_until(srv, ENQ)
    stale.close(); fresh.close(); srv.close()


def test_tcp_rejects_unallowed_peer():
    port = free_port()
    srv = TcpServerTransport("127.0.0.1", port, allowed_peer="10.9.9.9")
    c = socket.create_connection(("127.0.0.1", port))
    c.sendall(ENQ)
    assert not _read_until(srv, ENQ)
    assert srv.connected is False
    c.close(); srv.close()


def test_raw_journal_has_no_patient_identity(tmp_path):
    s = Store(str(tmp_path / "b.db"))
    ingest(s, BHCG)
    raw = s.get_raw(1)
    assert "PATIENT" not in raw and "19320122" not in raw
    assert "PIDSID13" in raw and "SID13" in raw


class _CursorSpy:
    def __init__(self, cur, lock):
        self._cur, self._lock = cur, lock

    def fetchall(self):
        assert self._lock.locked(), "lecture hors verrou"
        return self._cur.fetchall()

    def fetchone(self):
        assert self._lock.locked(), "lecture hors verrou"
        return self._cur.fetchone()

    def __getattr__(self, name):
        return getattr(self._cur, name)


class _DbSpy:
    def __init__(self, db, lock):
        self._db, self._lock = db, lock

    def execute(self, *a):
        return _CursorSpy(self._db.execute(*a), self._lock)

    def __getattr__(self, name):
        return getattr(self._db, name)


def test_reads_happen_under_lock(tmp_path):
    s = Store(str(tmp_path / "b.db"))
    ingest(s, BHCG)
    s._db = _DbSpy(s._db, s._lock)
    s.fetch_results(0, 10)
    s.stats()
    s.raw_messages(None, 10)
    s.get_raw(1)


def _run(factory, store, link, **kw):
    stop = threading.Event()
    th = threading.Thread(target=run_connector, args=(factory, store, link, stop),
                          kwargs={"frame_timeout": 0.05, "retry_delay": 0.01, **kw}, daemon=True)
    th.start()
    return stop, th


def test_store_failure_is_reported_in_health(tmp_path, monkeypatch):
    store, link = Store(str(tmp_path / "b.db")), LinkState()

    def boom(text):
        raise OSError("disk full")
    monkeypatch.setattr(store, "save_raw", boom)
    t = FakeTransport(ENQ + frame(1, "H|\\^&\r") + frame(2, "L|1\r") + EOT)
    stop, th = _run(lambda: t, store, link)
    wait_until(lambda: link.error is not None)
    assert "disk full" in link.error
    stop.set(); th.join(timeout=5)


def test_purge_failure_does_not_reopen_link(tmp_path, monkeypatch):
    store, link, calls = Store(str(tmp_path / "b.db")), LinkState(), []

    def boom(*a):
        raise OSError("purge KO")
    monkeypatch.setattr(store, "purge", boom)

    def factory():
        calls.append(1)
        return FakeTransport(b"")
    stop, th = _run(factory, store, link)
    time.sleep(0.3)
    stop.set(); th.join(timeout=5)
    assert len(calls) == 1


def test_enq_mid_session_restarts_session():
    got = []
    h = frame(1, "H|\\^&\r")
    t = FakeTransport(ENQ + h + ENQ + h + frame(2, "L|1\r") + EOT)
    receive_session(t, got.append)
    assert got == ["H|\\^&\r", "H|\\^&\rL|1\r"]
    assert bytes(t.out) == ACK * 5


class _NoiseTransport:
    """Envoie ENQ + une trame H, puis du bruit sans fin."""

    def __init__(self):
        self.inbox = bytearray(ENQ + frame(1, "H|\\^&\r"))

    def read(self, n, timeout):
        if self.inbox:
            c = bytes(self.inbox[:1]); del self.inbox[:1]; return c
        time.sleep(0.005)
        return b"\x00"

    def write(self, data):
        pass


def test_noise_does_not_keep_session_alive():
    got = []
    start = time.monotonic()
    receive_session(_NoiseTransport(), got.append, frame_timeout=0.1)
    assert time.monotonic() - start < 1.0
    assert got == []


def test_replicate_exceptions_have_distinct_uids():
    o = "O|{n}|SID9|SID9^A1^1|^^^0241^TSH^UNDILUTED^P|R||||||||||||||||||||X\rC|1|I|Sample short|I\r"
    rs = parse_architect(H + "P|1\r" + o.format(n=1) + o.format(n=2) + "L|1\r")
    assert len({r.uid for r in rs}) == 2


def test_serial_timeout_not_reconfigured_every_byte(monkeypatch):
    import bridge.transport.serial_port as sp

    class FakeSerial:
        sets = 0

        def __init__(self, **kw):
            self._timeout = kw.get("timeout")

        @property
        def timeout(self):
            return self._timeout

        @timeout.setter
        def timeout(self, v):
            FakeSerial.sets += 1
            self._timeout = v

        def read(self, n):
            return b""

    monkeypatch.setattr(sp.serial, "Serial", FakeSerial)
    t = sp.SerialTransport("COM5", 9600, 8, "N", 1)
    for _ in range(5):
        t.read(1, 30.0)
    assert FakeSerial.sets == 1
