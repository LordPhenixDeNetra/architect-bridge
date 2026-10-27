"""Point d'entree : thread connecteur + API REST dans un seul processus."""
import argparse
import logging
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable

from bridge import __version__
from bridge.datalink import Transport, receive_session
from bridge.ingest import ingest
from bridge.link import LinkState
from bridge.store import Store

log = logging.getLogger("bridge")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _Tracked:
    """Enveloppe un transport pour dater la derniere reception (lastFrameAt)."""

    def __init__(self, t: Transport, link: LinkState):
        self.t, self.link = t, link

    def read(self, n: int, timeout: float) -> bytes:
        data = self.t.read(n, timeout)
        self.link.connected = getattr(self.t, "connected", True)
        if data:
            self.link.last_frame_at = _now()
        return data

    def write(self, data: bytes) -> None:
        self.t.write(data)


def run_connector(transport_factory: Callable[[], Transport], store: Store, link: LinkState,
                  stop: threading.Event, frame_timeout: float = 30.0, retry_delay: float = 5.0,
                  retention_days: int = 90) -> None:
    def on_message(text: str) -> None:
        try:
            ingest(store, text)
        except Exception as e:
            link.error = f"Ecriture du message impossible : {e}"
            raise  # -> NAK, l'automate renverra le message
        link.error = None
        link.last_message_at = _now()

    last_purge = None
    while not stop.is_set():
        try:
            t = transport_factory()
        except Exception as e:
            link.connected, link.error = False, str(e)
            log.warning("[WARN] Ouverture du transport impossible : %s (nouvel essai dans %ss)", e, retry_delay)
            stop.wait(retry_delay)
            continue
        link.transport, link.error = getattr(t, "name", ""), None
        log.info("[INFO] Transport %s ouvert", link.transport)
        try:
            tracked = _Tracked(t, link)
            while not stop.is_set():
                receive_session(tracked, on_message, frame_timeout)
                today = datetime.now(timezone.utc).date()
                if last_purge != today:
                    last_purge = today
                    try:
                        store.purge(retention_days, datetime.now(timezone.utc))
                    except Exception:
                        log.exception("[ERREUR] Purge impossible")
        except Exception as e:
            link.error = str(e)
            log.exception("[ERREUR] Liaison interrompue")
            stop.wait(retry_delay)
        finally:
            link.connected = False
            try:
                t.close()
            except Exception:
                pass


def _setup_logging(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(name)s %(message)s")
    handlers = [RotatingFileHandler(path, maxBytes=5_000_000, backupCount=5, encoding="utf-8"),
                logging.StreamHandler()]
    for h in handlers:
        h.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=handlers)


def main() -> None:
    import uvicorn

    from bridge.api import create_app
    from bridge.config import load_config

    parser = argparse.ArgumentParser(description="Passerelle ASTM ARCHITECT -> API REST")
    parser.add_argument("--config", default="config.toml")
    cfg = load_config(parser.parse_args().config)
    _setup_logging(cfg.log_path)

    if cfg.transport == "serial":
        from bridge.transport.serial_port import SerialTransport

        def factory():
            return SerialTransport(cfg.port, cfg.baudrate, cfg.bytesize, cfg.parity, cfg.stopbits)
    else:
        from bridge.transport.tcp import TcpServerTransport

        def factory():
            return TcpServerTransport(cfg.tcp_host, cfg.tcp_port, cfg.tcp_allowed_peer)

    store, link, stop = Store(cfg.db_path), LinkState(), threading.Event()
    threading.Thread(target=run_connector, args=(factory, store, link, stop),
                     kwargs={"retention_days": cfg.retention_days}, daemon=True, name="connector").start()
    log.info("[INFO] ARCHITECT Bridge %s - API sur http://%s:%s", __version__, cfg.api_host, cfg.api_port)
    try:
        uvicorn.run(create_app(store, link, cfg.api_key, __version__), host=cfg.api_host, port=cfg.api_port)
    finally:
        stop.set()
