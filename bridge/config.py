"""Lecture de config.toml."""
import tomllib
from dataclasses import dataclass


@dataclass
class Config:
    transport: str
    port: str
    baudrate: int
    bytesize: int
    parity: str
    stopbits: int
    tcp_host: str
    tcp_port: int
    tcp_allowed_peer: str
    db_path: str
    retention_days: int
    api_host: str
    api_port: int
    api_key: str
    log_path: str


def load_config(path: str) -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    link, store, api, logcfg = (raw.get(k, {}) for k in ("link", "store", "api", "log"))
    cfg = Config(
        transport=link.get("transport", "serial"),
        port=link.get("port", "COM5"),
        baudrate=link.get("baudrate", 9600),
        bytesize=link.get("bytesize", 8),
        parity=link.get("parity", "N"),
        stopbits=link.get("stopbits", 1),
        tcp_host=link.get("tcp_host", "0.0.0.0"),
        tcp_port=link.get("tcp_port", 5100),
        tcp_allowed_peer=link.get("tcp_allowed_peer", ""),
        db_path=store.get("path", "architect-bridge.db"),
        retention_days=store.get("retention_days", 90),
        api_host=api.get("host", "127.0.0.1"),
        api_port=api.get("port", 8085),
        api_key=api.get("api_key", ""),
        log_path=logcfg.get("path", "logs/bridge.log"),
    )
    if not cfg.api_key:
        raise ValueError("[api] api_key est obligatoire dans la configuration")
    if cfg.transport not in ("serial", "tcp"):
        raise ValueError("[link] transport doit valoir 'serial' ou 'tcp'")
    return cfg
