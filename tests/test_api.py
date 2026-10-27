from fastapi.testclient import TestClient

from bridge.api import create_app
from bridge.ingest import ingest
from bridge.link import LinkState
from bridge.store import Store
from tests.samples import BHCG

H = {"X-API-Key": "k"}


def make(tmp_path):
    s = Store(str(tmp_path / "b.db"))
    ingest(s, BHCG)
    return TestClient(create_app(s, LinkState(connected=True, transport="tcp"), "k", "0.1.0")), s


def test_requires_api_key(tmp_path):
    c, _ = make(tmp_path)
    assert c.get("/health").status_code == 401
    assert c.get("/health", headers={"X-API-Key": "bad"}).status_code == 401
    assert c.get("/results", headers={"X-API-Key": "bad"}).status_code == 401


def test_results_cursor(tmp_path):
    c, _ = make(tmp_path)
    r = c.get("/results?after=0&limit=2", headers=H).json()
    assert [i["seq"] for i in r["items"]] == [1, 2] and r["lastSeq"] == 2
    assert c.get("/results?after=3", headers=H).json() == {"items": [], "lastSeq": 3}
    assert c.get("/results?limit=5000", headers=H).status_code == 422


def test_ack_and_health(tmp_path):
    c, _ = make(tmp_path)
    assert c.post("/results/ack", json={"upToSeq": 3}, headers=H).status_code == 204
    h = c.get("/health", headers=H).json()
    assert h["connected"] is True and h["transport"] == "tcp"
    assert h["unackedResults"] == 0 and h["messagesToday"] == 1 and h["version"] == "0.1.0"


def test_raw_and_replay(tmp_path):
    c, _ = make(tmp_path)
    assert c.get("/raw-messages", headers=H).json()[0]["id"] == 1
    assert c.get("/raw-messages?status=parse_error", headers=H).json() == []
    assert c.post("/raw-messages/1/replay", headers=H).json() == {"inserted": 0}
    assert c.post("/raw-messages/99/replay", headers=H).status_code == 404
