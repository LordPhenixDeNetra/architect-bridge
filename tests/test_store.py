from datetime import datetime, timedelta, timezone

import pytest

from bridge.ingest import ingest, replay
from bridge.store import Store
from tests.samples import BHCG


@pytest.fixture
def s(tmp_path):
    return Store(str(tmp_path / "b.db"))


def test_ingest_then_fetch(s):
    assert ingest(s, BHCG) == 3
    items = s.fetch_results(0, 100)
    assert [i["seq"] for i in items] == [1, 2, 3]
    assert items[0]["assay"] == {"number": "0021", "name": "B-hCG", "dilution": "UNDILUTED", "status": "P"}
    assert items[0]["flags"] == ["<"] and items[0]["rawMessageId"] == 1
    assert items[0]["patientIds"] == {"practice": None, "lab": None, "id3": "PIDSID13"}
    assert items[0]["position"] == 5 and items[2]["comments"] == ["Example Result Comment"]
    assert s.fetch_results(3, 100) == []
    assert s.raw_messages("parsed", 10)[0]["id"] == 1


def test_fetch_respects_limit(s):
    ingest(s, BHCG)
    assert [i["seq"] for i in s.fetch_results(1, 1)] == [2]


def test_insert_is_idempotent(s):
    ingest(s, BHCG)
    ingest(s, BHCG)
    assert len(s.fetch_results(0, 100)) == 3


def test_parse_error_keeps_raw(s):
    assert ingest(s, "garbage\r") == 0
    raw = s.raw_messages("parse_error", 10)
    assert raw[0]["text"] == "garbage\r" and raw[0]["error"]
    assert s.stats()["parseErrors"] == 1


def test_save_raw_failure_propagates(s, monkeypatch):
    def boom(text):
        raise OSError("disk full")
    monkeypatch.setattr(s, "save_raw", boom)
    with pytest.raises(OSError):
        ingest(s, BHCG)


def test_replay(s):
    rid = s.save_raw(BHCG)
    assert replay(s, rid) == 3 and replay(s, rid) == 0
    with pytest.raises(KeyError):
        replay(s, 999)


def test_ack_never_goes_back(s):
    ingest(s, BHCG)
    s.ack(3)
    s.ack(1)
    assert s.stats()["unackedResults"] == 0


def test_stats_counts_today(s):
    ingest(s, BHCG)
    assert s.stats() == {"messagesToday": 1, "parseErrors": 0, "unackedResults": 3}


def test_purge_only_acked_and_old(s):
    ingest(s, BHCG)
    s.ack(2)
    s.purge(90, datetime.now(timezone.utc) + timedelta(days=91))
    assert [i["seq"] for i in s.fetch_results(0, 100)] == [3]
    assert s.get_raw(1) is not None  # encore reference par seq 3


def test_purge_keeps_recent(s):
    ingest(s, BHCG)
    s.ack(3)
    s.purge(90, datetime.now(timezone.utc))
    assert len(s.fetch_results(0, 100)) == 3
