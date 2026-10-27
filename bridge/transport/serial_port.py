"""Transport RS-232 (port COM5 / connecteur P3 de l'ARCHITECT par defaut)."""
import serial


class SerialTransport:
    name = "serial"
    connected = True  # port ouvert ; une deconnexion leve SerialException

    def __init__(self, port: str, baudrate: int, bytesize: int, parity: str, stopbits: int):
        self._s = serial.Serial(port=port, baudrate=baudrate, bytesize=bytesize,
                                parity=parity, stopbits=stopbits, timeout=1)

    def read(self, n: int, timeout: float) -> bytes:
        if self._s.timeout != timeout:  # sous Windows, chaque affectation reconfigure le port
            self._s.timeout = timeout
        return self._s.read(n)

    def write(self, data: bytes) -> None:
        self._s.write(data)
        self._s.flush()

    def close(self) -> None:
        self._s.close()
