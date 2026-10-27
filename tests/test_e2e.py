import threading

import pytest
from fastapi.testclient import TestClient

from bridge.api import create_app
from bridge.config import load_config
from bridge.link import LinkState
from bridge.main import run_connector
from bridge.store import Store
from bridge.transport.tcp import TcpServerTransport
from simulator.architect_sim import send_sample
from tests.fakes import free_port, wait_until
from tests.samples import BHCG, EXCEPTION


def test_simulator_to_api(tmp_path):
    store, link, stop = Store(str(tmp_path / "b.db")), LinkState(), threading.Event()
    port = free_port()
    th = threading.Thread(target=run_connector,
                          args=(lambda: TcpServerTransport("127.0.0.1", port), store, link, stop),
                          kwargs={"frame_timeout": 0.2}, daemon=True)
    th.start()
    wait_until(lambda: link.transport == "tcp")  # serveur en ecoute
    assert send_sample(("127.0.0.1", port), BHCG)
    assert send_sample(("127.0.0.1", port), EXCEPTION)  # reconnexion apres deconnexion
    wait_until(lambda: store.stats()["unackedResults"] == 4)
    assert link.last_message_at is not None and link.last_frame_at is not None
    c = TestClient(create_app(store, link, "k", "test"))
    items = c.get("/results", headers={"X-API-Key": "k"}).json()["items"]
    assert [i["resultType"] for i in items] == ["F", "I", "P", "X"]
    stop.set()
    th.join(timeout=5)
    assert not th.is_alive()


def test_connector_retries_when_transport_fails(tmp_path):
    store, link, stop = Store(str(tmp_path / "b.db")), LinkState(), threading.Event()
    calls = []

    def factory():
        calls.append(1)
        raise OSError("COM5 introuvable")

    th = threading.Thread(target=run_connector, args=(factory, store, link, stop),
                          kwargs={"retry_delay": 0.01}, daemon=True)
    th.start()
    wait_until(lambda: len(calls) >= 3)
    assert link.connected is False and "COM5" in link.error
    stop.set()
    th.join(timeout=5)


def test_config_requires_api_key(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[link]\ntransport="tcp"\n[store]\npath="b.db"\n[api]\napi_key=""\n')
    with pytest.raises(ValueError):
        load_config(str(p))


def test_config_defaults(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[link]\ntransport="serial"\nport="COM5"\n[store]\npath="b.db"\n[api]\napi_key="s3cret"\n')
    c = load_config(str(p))
    assert (c.baudrate, c.bytesize, c.parity, c.stopbits) == (9600, 8, "N", 1)
    assert (c.api_host, c.api_port, c.retention_days) == ("127.0.0.1", 8085, 90)
