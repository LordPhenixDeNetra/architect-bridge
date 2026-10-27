"""Couche liaison ASTM E1381 : sessions ENQ...EOT, trames, checksum."""
import logging
import time
from typing import Callable, Protocol

log = logging.getLogger(__name__)

ENQ, ACK, NAK, STX, ETX, ETB, EOT, CR, LF = (bytes([c]) for c in (5, 6, 21, 2, 3, 23, 4, 13, 10))
ENCODING = "cp850"
MAX_TEXT = 240
MAX_ATTEMPTS = 6


class Transport(Protocol):
    def read(self, n: int, timeout: float) -> bytes: ...  # b"" si timeout
    def write(self, data: bytes) -> None: ...


def checksum(body: bytes) -> bytes:
    """Somme modulo 256 de FN a ETB/ETX inclus, en 2 caracteres hexa majuscules."""
    return f"{sum(body) % 256:02X}".encode()


def build_frames(message: str) -> list[bytes]:
    """Un enregistrement par trame (ETX), decoupe en morceaux de 240 caracteres (ETB)."""
    frames, fn = [], 1
    for record in (r for r in message.split("\r") if r):
        text = (record + "\r").encode(ENCODING)
        chunks = [text[i:i + MAX_TEXT] for i in range(0, len(text), MAX_TEXT)]
        for k, chunk in enumerate(chunks):
            body = str(fn).encode() + chunk + (ETX if k == len(chunks) - 1 else ETB)
            frames.append(STX + body + checksum(body) + CR + LF)
            fn = (fn + 1) % 8
    return frames


def _read_frame(t: Transport, timeout: float) -> bytes | None:
    """Lit apres STX jusqu'a LF inclus ; None si timeout."""
    buf = bytearray()
    while not buf.endswith(LF):
        c = t.read(1, timeout)
        if not c:
            return None
        buf += c
    return bytes(buf)


def receive_session(t: Transport, on_message: Callable[[str], None], frame_timeout: float = 30.0) -> int:
    """Traite une session ENQ...EOT ; renvoie le nombre de messages remis a on_message.

    on_message est appele a la fin de l'enregistrement L, avant l'ACK de cette trame ;
    s'il leve, la trame recoit NAK et l'automate la renverra.
    """
    while True:
        c = t.read(1, frame_timeout)
        if not c:
            return 0
        if c == ENQ:
            break
    t.write(ACK)

    def flush(records: list[str]) -> int:
        """Remet un message deja acquitte mais sans terminateur L (EOT ou ENQ inattendu)."""
        if not records:
            return 0
        try:
            on_message("".join(records))
            return 1
        except Exception:
            log.exception("[ERREUR] Echec d'enregistrement d'un message sans terminateur")
            return 0

    expected, last = 1, None
    partial, records, delivered = b"", [], 0
    last_reply = time.monotonic()
    while True:
        c = t.read(1, frame_timeout)
        # Timer E1381 : relance a chaque reponse ; le bruit sur la ligne ne le prolonge pas.
        if not c or time.monotonic() - last_reply > frame_timeout:
            log.warning("[WARN] Timeout en cours de session, message partiel abandonne")
            return delivered
        if c == EOT:
            return delivered + flush(records)
        if c == ENQ:
            log.warning("[WARN] ENQ recu en cours de session : nouvelle session")
            delivered += flush(records)
            expected, last, partial, records = 1, None, b"", []
            t.write(ACK)
            last_reply = time.monotonic()
            continue
        if c != STX:
            continue

        buf = _read_frame(t, frame_timeout)
        if buf is None:
            log.warning("[WARN] Timeout au milieu d'une trame")
            return delivered
        end, body = buf[-5:-4], buf[:-4]
        valid = (len(buf) >= 6 and buf[-2:-1] == CR and end in (ETX, ETB)
                 and buf[:1].isdigit() and checksum(body) == buf[-4:-2].upper())
        if not valid:
            log.warning("[WARN] Trame invalide (checksum ou format) -> NAK")
            t.write(NAK)
            last_reply = time.monotonic()
            continue
        fn = int(buf[:1])
        if fn == last:
            t.write(ACK)  # trame dupliquee : deja prise en compte
            last_reply = time.monotonic()
            continue
        if fn != expected:
            log.warning("[WARN] Numero de trame %s inattendu (attendu %s) -> NAK", fn, expected)
            t.write(NAK)
            last_reply = time.monotonic()
            continue

        new_partial, new_records = partial + buf[1:-5], records
        if end == ETX:
            new_records = records + [new_partial.decode(ENCODING, errors="replace")]
            new_partial = b""
            if new_records[-1][:1] in ("L", "l"):
                try:
                    on_message("".join(new_records))
                except Exception:
                    log.exception("[ERREUR] Echec d'enregistrement du message -> NAK")
                    t.write(NAK)
                    last_reply = time.monotonic()
                    continue
                delivered += 1
                new_records = []
        partial, records, last, expected = new_partial, new_records, fn, (fn + 1) % 8
        t.write(ACK)
        last_reply = time.monotonic()


def send_message(t: Transport, message: str, timeout: float = 15.0) -> bool:
    """Emet un message complet (ENQ, trames, EOT). Utilise par le simulateur."""
    t.write(ENQ)
    if t.read(1, timeout) != ACK:
        return False
    for f in build_frames(message):
        for _ in range(MAX_ATTEMPTS):
            t.write(f)
            if t.read(1, timeout) == ACK:
                break
        else:
            t.write(EOT)
            return False
    t.write(EOT)
    return True
