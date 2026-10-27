"""Ingestion d'un message recu : journal brut d'abord, interpretation ensuite."""
import logging

from bridge.codec import redact_patient_identity
from bridge.drivers.architect import parse_architect
from bridge.store import Store

log = logging.getLogger(__name__)


def _parse_into(store: Store, raw_id: int, text: str) -> int:
    try:
        inserted = store.insert_results(raw_id, parse_architect(text))
    except Exception as e:
        log.exception("[ERREUR] Interpretation impossible du message brut %s", raw_id)
        store.mark_raw(raw_id, "parse_error", f"{type(e).__name__}: {e}")
        return 0
    store.mark_raw(raw_id, "parsed")
    return inserted


def ingest(store: Store, text: str) -> int:
    """Enregistre le message brut (une erreur ici remonte -> NAK), puis l'interprete.

    Le journal est brut sauf l'identite du patient (P.6, P.8, P.9), jamais stockee.
    """
    text = redact_patient_identity(text)
    raw_id = store.save_raw(text)
    inserted = _parse_into(store, raw_id, text)
    log.info("[INFO] Message %s recu : %s resultat(s) nouveau(x)", raw_id, inserted)
    return inserted


def replay(store: Store, raw_id: int) -> int:
    text = store.get_raw(raw_id)
    if text is None:
        raise KeyError(raw_id)
    return _parse_into(store, raw_id, text)
