from bridge.datalink import (ACK, CR, ENQ, EOT, ETB, ETX, LF, NAK, STX, build_frames, checksum,
                             receive_session, send_message)
from tests.fakes import FakeTransport


def frame(fn, text, end=ETX):
    body = str(fn).encode() + text.encode("cp850") + end
    return STX + body + checksum(body) + CR + LF


def test_checksum_manual_example():
    assert checksum(b"1ABCDEFGHI" + ETX) == b"A1"


def test_build_frames_splits_long_record():
    frames = build_frames("H|\\^&\r" + "R|1|" + "X" * 300 + "\rL|1\r")
    assert len(frames) == 4  # H, R partie 1 (ETB), R partie 2 (ETX), L
    assert frames[1][-5:-4] == ETB and frames[2][-5:-4] == ETX
    assert frames[3][1:2] == b"4"


def test_frame_number_wraps_7_to_0():
    frames = build_frames("".join(f"R|{i}\r" for i in range(9)))
    assert [f[1:2] for f in frames] == [b"1", b"2", b"3", b"4", b"5", b"6", b"7", b"0", b"1"]


def test_receive_single_message():
    got = []
    t = FakeTransport(ENQ + frame(1, "H|\\^&\r") + frame(2, "L|1\r") + EOT)
    assert receive_session(t, got.append) == 1
    assert got == ["H|\\^&\rL|1\r"]
    assert bytes(t.out) == ACK * 3


def test_bad_checksum_gets_nak():
    bad = frame(1, "H|\\^&\r")[:-4] + b"00" + CR + LF
    t = FakeTransport(ENQ + bad + frame(1, "H|\\^&\r") + frame(2, "L|1\r") + EOT)
    receive_session(t, lambda m: None)
    assert bytes(t.out) == ACK + NAK + ACK + ACK


def test_unexpected_frame_number_gets_nak():
    t = FakeTransport(ENQ + frame(3, "H|\\^&\r") + EOT)
    receive_session(t, lambda m: None)
    assert bytes(t.out) == ACK + NAK


def test_duplicate_frame_not_appended():
    got = []
    h = frame(1, "H|\\^&\r")
    t = FakeTransport(ENQ + h + h + frame(2, "L|1\r") + EOT)
    receive_session(t, got.append)
    assert got == ["H|\\^&\rL|1\r"]
    assert bytes(t.out) == ACK * 4


def test_nak_when_on_message_raises():
    def boom(m):
        raise OSError("disk full")
    t = FakeTransport(ENQ + frame(1, "H|\\^&\r") + frame(2, "L|1\r") + EOT)
    receive_session(t, boom)
    assert bytes(t.out) == ACK + ACK + NAK


def test_two_messages_in_one_session():
    got = []
    t = FakeTransport(ENQ + frame(1, "H|\\^&\r") + frame(2, "L|1\r")
                      + frame(3, "H|\\^&\r") + frame(4, "L|1\r") + EOT)
    assert receive_session(t, got.append) == 2


def test_eot_without_terminator_still_delivers():
    got = []
    t = FakeTransport(ENQ + frame(1, "H|\\^&\r") + EOT)
    receive_session(t, got.append)
    assert got == ["H|\\^&\r"]


def test_timeout_abandons_partial():
    got = []
    t = FakeTransport(ENQ + frame(1, "H|\\^&\r"))  # puis plus rien
    receive_session(t, got.append, frame_timeout=0.01)
    assert got == []


def test_send_then_receive_roundtrip():
    msg = "H|\\^&\rR|1|" + "Y" * 500 + "\rL|1\r"
    t = FakeTransport(ACK * 10)
    assert send_message(t, msg)
    got = []
    receive_session(FakeTransport(bytes(t.out)), got.append)
    assert got == [msg]


def test_send_fails_without_ack():
    assert send_message(FakeTransport(NAK), "H|\\^&\rL|1\r", timeout=0.01) is False
