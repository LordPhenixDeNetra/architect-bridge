"""Faux ARCHITECT : se connecte en TCP au service et envoie des messages ASTM.

Usage : python -m simulator.architect_sim --port 5100 [--file messages.txt]
Fichier : un enregistrement par ligne, messages separes par une ligne vide.
"""
import argparse
import socket

from bridge.datalink import send_message
from bridge.transport.tcp import SocketTransport
from simulator.samples import BHCG, CONTROL, EXCEPTION


def send_sample(addr: tuple[str, int], text: str, timeout: float = 15.0) -> bool:
    with socket.create_connection(addr, timeout=timeout) as sock:
        return send_message(SocketTransport(sock), text, timeout)


def _load(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        blocks = f.read().strip().split("\n\n")
    return ["".join(line.strip() + "\r" for line in b.splitlines() if line.strip()) for b in blocks]


def main() -> None:
    p = argparse.ArgumentParser(description="Simulateur ARCHITECT (ASTM sur TCP)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5100)
    p.add_argument("--file")
    args = p.parse_args()
    for msg in _load(args.file) if args.file else [BHCG, CONTROL, EXCEPTION]:
        ok = send_sample((args.host, args.port), msg)
        order = next((r for r in msg.split("\r") if r[:1] in "Oo"), msg.split("\r")[0])
        print(("[OK] " if ok else "[ERREUR] ") + order[:70])


if __name__ == "__main__":
    main()
