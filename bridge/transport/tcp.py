"""Transport TCP : le service ecoute, l'automate (ou le simulateur) se connecte."""
import logging
import select
import socket

log = logging.getLogger(__name__)


class SocketTransport:
    """Adapte une socket connectee a l'interface Transport."""

    def __init__(self, sock: socket.socket):
        self.sock = sock

    def read(self, n: int, timeout: float) -> bytes:
        """b"" si timeout ; ConnectionError si le pair a ferme la connexion."""
        self.sock.settimeout(timeout)
        try:
            data = self.sock.recv(n)
        except socket.timeout:
            return b""
        if not data:
            raise ConnectionError("Connexion fermee par le pair")
        return data

    def write(self, data: bytes) -> None:
        self.sock.sendall(data)

    def close(self) -> None:
        self.sock.close()


class TcpServerTransport:
    name = "tcp"

    def __init__(self, host: str, port: int, allowed_peer: str | None = None):
        self._server = socket.create_server((host, port))
        self._allowed = allowed_peer or None
        self._conn: SocketTransport | None = None
        if self._allowed is None:
            log.warning("[WARN] Mode TCP sans tcp_allowed_peer : toute machine du reseau peut envoyer des resultats")

    @property
    def connected(self) -> bool:
        return self._conn is not None

    def _accept(self, timeout: float) -> None:
        self._server.settimeout(timeout)
        try:
            sock, (peer, _) = self._server.accept()
        except socket.timeout:
            return
        if self._allowed and peer != self._allowed:
            log.warning("[WARN] Connexion refusee depuis %s (attendu %s)", peer, self._allowed)
            sock.close()
            return
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self._conn = SocketTransport(sock)

    def read(self, n: int, timeout: float) -> bytes:
        if self._conn is None:
            self._accept(timeout)
            if self._conn is None:
                return b""
        try:
            data = self._conn.read(n, timeout)
        except OSError:  # ConnectionError en fait partie
            self._drop()
            return b""
        if not data and select.select([self._server], [], [], 0)[0]:
            # Silence + nouvelle connexion en attente : l'ancienne est morte (cable, reboot).
            log.warning("[WARN] Nouvelle connexion entrante, abandon de la connexion muette")
            self._drop()
        return data

    def _drop(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def write(self, data: bytes) -> None:
        if self._conn is not None:
            self._conn.write(data)

    def close(self) -> None:
        self._drop()
        self._server.close()
