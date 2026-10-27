from dataclasses import dataclass


@dataclass
class LinkState:
    """Etat de la liaison automate, partage entre le thread connecteur et l'API."""
    connected: bool = False
    transport: str = ""
    last_frame_at: str | None = None
    last_message_at: str | None = None
    error: str | None = None
