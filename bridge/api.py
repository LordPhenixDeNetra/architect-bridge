"""API REST consommee par Hopitalia (Spring Boot)."""
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from pydantic import BaseModel

from bridge.ingest import replay
from bridge.link import LinkState
from bridge.store import Store


class AckRequest(BaseModel):
    upToSeq: int


def create_app(store: Store, link: LinkState, api_key: str, version: str) -> FastAPI:
    def check_key(x_api_key: str | None = Header(default=None)) -> None:
        if not x_api_key or not secrets.compare_digest(x_api_key, api_key):
            raise HTTPException(status_code=401, detail="Cle API invalide")

    app = FastAPI(title="ARCHITECT Bridge", version=version, dependencies=[Depends(check_key)])

    @app.get("/results")
    def get_results(after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
        items = store.fetch_results(after, limit)
        return {"items": items, "lastSeq": items[-1]["seq"] if items else after}

    @app.post("/results/ack", status_code=204)
    def ack_results(body: AckRequest):
        store.ack(body.upToSeq)
        return Response(status_code=204)

    @app.get("/health")
    def health():
        return {
            "connected": link.connected,
            "transport": link.transport,
            "lastFrameAt": link.last_frame_at,
            "lastMessageAt": link.last_message_at,
            "error": link.error,
            **store.stats(),
            "version": version,
        }

    @app.get("/raw-messages")
    def get_raw_messages(status: str | None = None, limit: int = Query(50, ge=1, le=1000)):
        return store.raw_messages(status, limit)

    @app.post("/raw-messages/{raw_id}/replay")
    def replay_raw(raw_id: int):
        try:
            return {"inserted": replay(store, raw_id)}
        except KeyError:
            raise HTTPException(status_code=404, detail="Message brut introuvable")

    return app
