# ARCHITECT Bridge (sous-projet A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Service Python qui recoit les resultats ASTM de l'ARCHITECT, les stocke sans perte dans SQLite et les expose a Spring via une API REST.

**Architecture:** Un processus : un thread connecteur (transport -> datalink -> ingestion) ecrit dans SQLite ; FastAPI lit SQLite et l'etat de liaison en memoire. Codec et driver sont des fonctions pures.

**Tech Stack:** Python >= 3.11, pyserial, FastAPI, uvicorn, sqlite3, pytest, httpx (TestClient).

**Spec:** `docs/superpowers/specs/2026-10-27-architect-bridge-a-design.md`

## Global Constraints

- Python >= 3.11 ; dependances runtime : `fastapi`, `uvicorn`, `pyserial` uniquement.
- Encodage des octets ASTM : `cp850`.
- Logs avec prefixes `[INFO]`, `[WARN]`, `[ERREUR]` ; aucun emoji dans le code ni les logs.
- Adresse d'ecoute API par defaut `127.0.0.1`, jamais `0.0.0.0` par defaut.
- Toute requete API sans `X-API-Key` valide -> `401`.
- Le nom, la date de naissance et le sexe du patient ne sont jamais stockes.
- Checksum : somme modulo 256 de FN a ETB/ETX inclus, 2 hexa majuscules.
- Timeout reception entre trames : 30 s.

## Review Focus

1. Trame dupliquee (meme FN que la derniere acceptee, ACK perdu cote automate) -> ACK, contenu non ajoute deux fois. Test : Task 2 `test_duplicate_frame_not_appended`.
2. Echec d'ecriture du message brut -> NAK sur la trame L, rien d'autre ne casse. Test : Task 2 `test_nak_when_on_message_raises`.
3. Valeur non numerique (`<1.20`, `NEGATIVE`, `>500`) -> conservee telle quelle. Test : Task 3 `test_bhcg_f_i_p`.
4. Meme message recu deux fois / rejoue -> pas de doublon dans `results`. Test : Task 4 `test_insert_is_idempotent`.
5. Composants absents (champ `R.3` court, champs finaux manquants) -> pas d'IndexError, valeurs `None`. Test : Task 3 `test_short_fields_do_not_crash`.

---

### Task 1: Squelette du projet + codec E1394

**Files:**
- Create: `pyproject.toml`, `bridge/__init__.py`, `bridge/codec.py`, `tests/test_codec.py`

**Interfaces:**
- Produces:
  - `parse_message(text: str) -> list[list[str]]` : enregistrements (separes par `\r`, vides ignores) -> liste de champs bruts (split sur le delimiteur de champ lu en `H[1]`). Defaut `|` si le premier enregistrement n'est pas un H.
  - `comp(field: str, i: int) -> str | None` : i-eme composant (split `^`), `None` si absent ou vide.
  - `field(record: list[str], i: int) -> str` : champ i (numerotation ASTM : `record[0]` = type = champ 1), `""` si absent.

- [ ] **Step 1: `pyproject.toml`** : projet `architect-bridge`, `requires-python = ">=3.11"`, deps `fastapi`, `uvicorn`, `pyserial` ; extra `dev` = `pytest`, `httpx`. Puis `python -m venv .venv` et `.venv\Scripts\pip install -e .[dev]`.

- [ ] **Step 2: Tests qui echouent** (`tests/test_codec.py`)

```python
MSG = "H|\\^&|||ARCHITECT^1.00^123456789^H1P1O1R1C1Q1L1|||||||P|1|19930330133346\rP|1|||PIDSID13\rL|1\r"

def test_parse_splits_records_and_fields():
    recs = parse_message(MSG)
    assert [r[0] for r in recs] == ["H", "P", "L"]
    assert field(recs[1], 5) == "PIDSID13"

def test_field_missing_returns_empty():
    assert field(["L", "1"], 9) == ""

def test_comp():
    assert comp("ARCHITECT^1.00^123456789", 3) == "123456789"
    assert comp("^^^0241^TSH", 4) == "0241"
    assert comp("^^^0241", 7) is None
    assert comp("a^^b", 2) is None
```

- [ ] **Step 3:** `pytest tests/test_codec.py -v` -> FAIL (module absent).
- [ ] **Step 4:** Implementer `bridge/codec.py` (indices `comp` a partir de 1, comme ASTM).
- [ ] **Step 5:** `pytest tests/test_codec.py -v` -> PASS.
- [ ] **Step 6: Commit** `git add pyproject.toml bridge tests && git commit -m "feat: codec ASTM E1394"`

---

### Task 2: Couche liaison E1381 (reception + emission pour le simulateur)

**Files:**
- Create: `bridge/datalink.py`, `tests/fakes.py`, `tests/test_datalink.py`

**Interfaces:**
- Consumes: rien.
- Produces:
  - `class Transport(Protocol)`: `read(n: int, timeout: float) -> bytes` (`b""` si timeout), `write(data: bytes) -> None`.
  - Constantes `ENQ ACK NAK STX ETX ETB EOT CR LF` (bytes).
  - `checksum(body: bytes) -> bytes`
  - `build_frames(message: str) -> list[bytes]` : un enregistrement par trame, decoupe a 240 caracteres (ETB intermediaire, ETX final), FN 1..7,0,...
  - `receive_session(t: Transport, on_message: Callable[[str], None], frame_timeout: float = 30.0) -> int` : attend ENQ, traite la session jusqu'a EOT, renvoie le nombre de messages remis. Appelle `on_message(text)` a la fin de chaque enregistrement `L` AVANT d'envoyer l'ACK de cette trame ; si `on_message` leve -> NAK. A EOT avec un message commence sans L -> `on_message` quand meme (exception ignoree, deja ACK). Timeout -> abandon, retour sans `on_message`.
  - `send_message(t: Transport, message: str, timeout: float = 15.0) -> bool` : ENQ, attend ACK, envoie les trames (6 tentatives max par trame sur NAK), EOT.
- `tests/fakes.py` : `class FakeTransport` avec `inbox: bytes` lu sequentiellement et `out: bytearray` des ecritures ; `read` renvoie `b""` quand `inbox` est vide.

- [ ] **Step 1: Tests qui echouent**

```python
def frame(fn, text, end=ETX):
    body = str(fn).encode() + text.encode("cp850") + end
    return STX + body + checksum(body) + CR + LF

def test_checksum_manual_example():
    assert checksum(b"1ABCDEFGHI" + ETX) == b"A1"

def test_build_frames_splits_long_record():
    frames = build_frames("H|\\^&\r" + "R|1|" + "X" * 300 + "\rL|1\r")
    assert len(frames) == 4            # H, R part 1 (ETB), R part 2 (ETX), L
    assert frames[1][-5:-4] == ETB and frames[2][-5:-4] == ETX
    assert frames[3][1:2] == b"4"

def test_receive_single_message():
    got = []
    t = FakeTransport(ENQ + frame(1, "H|\\^&\r") + frame(2, "L|1\r") + EOT)
    assert receive_session(t, got.append) == 1
    assert got == ["H|\\^&\rL|1\r"]
    assert bytes(t.out) == ACK * 3

def test_bad_checksum_gets_nak():
    bad = frame(1, "H|\\^&\r")[:-4] + b"00" + CR + LF
    t = FakeTransport(ENQ + bad + frame(1, "H|\\^&\r") + frame(2, "L|1\r") + EOT)
    receive_session(t, lambda m: None)
    assert bytes(t.out) == ACK + NAK + ACK + ACK

def test_duplicate_frame_not_appended():
    got = []
    h = frame(1, "H|\\^&\r")
    t = FakeTransport(ENQ + h + h + frame(2, "L|1\r") + EOT)
    receive_session(t, got.append)
    assert got == ["H|\\^&\rL|1\r"]

def test_nak_when_on_message_raises():
    def boom(m): raise OSError("disk full")
    t = FakeTransport(ENQ + frame(1, "H|\\^&\r") + frame(2, "L|1\r") + EOT)
    receive_session(t, boom)
    assert bytes(t.out) == ACK + ACK + NAK

def test_eot_without_terminator_still_delivers():
    got = []
    t = FakeTransport(ENQ + frame(1, "H|\\^&\r") + EOT)
    receive_session(t, got.append)
    assert got == ["H|\\^&\r"]

def test_timeout_abandons_partial():
    got = []
    t = FakeTransport(ENQ + frame(1, "H|\\^&\r"))   # puis plus rien
    receive_session(t, got.append, frame_timeout=0.01)
    assert got == []

def test_send_then_receive_roundtrip():
    # FakeTransport pre-rempli de ACK pour l'emetteur
    msg = "H|\\^&\rR|1|" + "Y" * 500 + "\rL|1\r"
    t = FakeTransport(ACK * 10)
    assert send_message(t, msg)
    got = []
    receive_session(FakeTransport(bytes(t.out)), got.append)
    assert got == [msg]
```

- [ ] **Step 2:** `pytest tests/test_datalink.py -v` -> FAIL.
- [ ] **Step 3:** Implementer `bridge/datalink.py`. Reception : lire octet par octet ; une trame = de STX jusqu'a LF ; verifier checksum puis FN attendu (`(last+1) % 8`, depart 1) ; FN == last accepte -> ACK sans ajouter ; autre FN -> NAK. Concatener le texte des trames ETB jusqu'a ETX = un enregistrement ; si l'enregistrement commence par `L`, appeler `on_message`. Le `frame_timeout` s'applique a chaque `read`.
- [ ] **Step 4:** `pytest tests/test_datalink.py -v` -> PASS.
- [ ] **Step 5: Commit** `git commit -m "feat: couche liaison ASTM E1381"`

---

### Task 3: Driver ARCHITECT

**Files:**
- Create: `bridge/drivers/__init__.py`, `bridge/drivers/architect.py`, `tests/test_architect.py`

**Interfaces:**
- Consumes: `parse_message`, `field`, `comp` (Task 1).
- Produces:
  - `@dataclass Result` avec exactement les colonnes de `results` de la spec (section 5) sauf `seq` et `raw_message_id` : `uid, kind, specimen_id, instrument_specimen_id, carrier_id, position, patient_id_practice, patient_id_lab, patient_id_3, assay_number, assay_name, dilution, assay_status, reagent_lot, reagent_serial, control_lot, result_type, value, units, reference_range, flags: list[str], result_status, operator_order, operator_release, completed_at, instrument_serial, priority, comments: list[str]`. Tous `str | None` sauf `position: int | None` et les listes.
  - `parse_architect(text: str) -> list[Result]` ; leve `ValueError` si le message ne commence pas par H.
- Regles :
  - Dates `YYYYMMDDHHMMSS` -> `YYYY-MM-DDTHH:MM:SS` ; `uid = f"{instrument_serial}|{specimen_id}|{assay_number}|{result_type}|{completed_at}"`.
  - `kind` : `exception` si O.26 == `X` ; sinon `control` si O.12 == `Q` ; sinon `patient`.
  - R.3 composants : 4 numero, 5 nom, 6 dilution, 7 statut, 8 lot reactif, 9 serie reactif, 10 lot controle, 11 type.
  - Flags R.7 : split sur le delimiteur de repetition `\`, vides retires.
  - Commentaires C.4 rattaches au dernier R (ou au O pour une exception).
  - Exception : un Result par O avec `result_type = "X"`, `completed_at` = H.14, `instrument_serial` = H.5 composant 3, champs R a `None`.
  - P.6, P.8, P.9 ignores.

- [ ] **Step 1: Tests qui echouent** (messages construits depuis les exemples du manuel section 4)

```python
H = "H|\\^&|||ARCHITECT^1.00^123456789^H1P1O1R1C1Q1L1|||||||P|1|19990715081500\r"
BHCG = (H + "P|1|||PIDSID13|PATIENT^IM^A||19320122|F\r"
  "O|1|SID13|SID13^A123^5|^^^0021^B-hCG^UNDILUTED^P|R||||||||||||||||||||F\r"
  "R|1|^^^0021^B-hCG^UNDILUTED^P^47331M100^00788^^F|<1.20|mIU/mL|0.35 TO 4.94|<||F||||19990715081030|I20100\r"
  "R|2|^^^0021^B-hCG^UNDILUTED^P^47331M100^00788^^I|NEGATIVE|||||F||||19990715081030|I20100\r"
  "R|3|^^^0021^B-hCG^UNDILUTED^P^47331M100^00788^^P|9245|RLU||||F||||19990715081030|I20100\r"
  "C|1|I|Example Result Comment|G\r"
  "L|1\r")

def test_bhcg_f_i_p():
    rs = parse_architect(BHCG)
    assert [r.result_type for r in rs] == ["F", "I", "P"]
    f = rs[0]
    assert (f.value, f.units, f.reference_range, f.flags) == ("<1.20", "mIU/mL", "0.35 TO 4.94", ["<"])
    assert (f.specimen_id, f.carrier_id, f.position) == ("SID13", "A123", 5)
    assert (f.assay_number, f.assay_name, f.reagent_lot) == ("0021", "B-hCG", "47331M100")
    assert f.uid == "I20100|SID13|0021|F|1999-07-15T08:10:30"
    assert f.kind == "patient" and f.patient_id_3 == "PIDSID13"
    assert rs[1].value == "NEGATIVE"
    assert rs[2].comments == ["Example Result Comment"]

def test_no_patient_name_stored():
    assert not any("PATIENT" in str(v) for v in vars(parse_architect(BHCG)[0]).values())

def test_control_result():
    msg = H + "P|1\rO|1|TSHBIORAD 2|TSHBIORAD 2^A123^2|^^^0241^TSH^UNDILUTED^P|R||||||Q||||||||||||||F\r" \
          "R|1|^^^0241^TSH^UNDILUTED^P^0607M200^01824^40080^F|4.6011|mIU/mL|4.292500 TO 5.397300|||F||ECB^RY||19990715081030|I20100\rL|1\r"
    r = parse_architect(msg)[0]
    assert r.kind == "control" and r.control_lot == "40080"
    assert (r.operator_order, r.operator_release) == ("ECB", "RY")

def test_exception_record():
    msg = H + "P|1\rO|1|SID9|SID9^A1^1|^^^0241^TSH^UNDILUTED^P|R||||||||||||||||||||X\rC|1|I|Sample short|I\rL|1\r"
    r = parse_architect(msg)[0]
    assert (r.kind, r.result_type, r.value) == ("exception", "X", None)
    assert r.comments == ["Sample short"] and r.instrument_serial == "123456789"
    assert r.completed_at == "1999-07-15T08:15:00"

def test_short_fields_do_not_crash():
    rs = parse_architect(H + "P|1\rO|1|S1\rR|1|^^^0241\rL|1\r")
    assert rs[0].assay_number == "0241" and rs[0].value is None

def test_rejects_non_header():
    with pytest.raises(ValueError):
        parse_architect("P|1\rL|1\r")
```

- [ ] **Step 2:** `pytest tests/test_architect.py -v` -> FAIL.
- [ ] **Step 3:** Implementer `bridge/drivers/architect.py` (parcours lineaire des enregistrements, etat courant P/O/dernier R).
- [ ] **Step 4:** `pytest tests/test_architect.py -v` -> PASS.
- [ ] **Step 5: Commit** `git commit -m "feat: driver ARCHITECT (resultats, CQ, exceptions)"`

---

### Task 4: Store SQLite + ingestion

**Files:**
- Create: `bridge/store.py`, `bridge/ingest.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: `Result`, `parse_architect` (Task 3).
- Produces:
  - `class Store(path: str)` (cree le schema, `PRAGMA journal_mode=WAL`, `check_same_thread=False` + `threading.Lock`) :
    - `save_raw(text: str) -> int` (status `received`)
    - `mark_raw(raw_id: int, status: str, error: str | None = None) -> None`
    - `insert_results(raw_id: int, results: list[Result]) -> int` (`ON CONFLICT(uid) DO NOTHING`, renvoie le nombre insere)
    - `fetch_results(after: int, limit: int) -> list[dict]` (dict au format JSON de la spec section 6, cles camelCase, `flags`/`comments` en listes)
    - `ack(up_to: int) -> None` (jamais en arriere)
    - `stats() -> dict` : `messagesToday, parseErrors, unackedResults`
    - `raw_messages(status: str | None, limit: int) -> list[dict]` ; `get_raw(raw_id: int) -> str | None`
    - `purge(retention_days: int, now: datetime) -> None`
  - `ingest(store: Store, text: str) -> int` : `save_raw` (exception propagee -> NAK), puis parse + insert + `mark_raw(parsed)` ; toute exception de parse -> `mark_raw(parse_error, str(e))`, renvoie 0.
  - `replay(store: Store, raw_id: int) -> int` : relit `get_raw`, parse + insert + mark ; `KeyError` si absent.

- [ ] **Step 1: Tests qui echouent** (`Store(":memory:")` ou `tmp_path`)

```python
def test_ingest_then_fetch(tmp_path):
    s = Store(str(tmp_path / "b.db"))
    assert ingest(s, BHCG) == 3
    items = s.fetch_results(0, 100)
    assert [i["seq"] for i in items] == [1, 2, 3]
    assert items[0]["assay"] == {"number": "0021", "name": "B-hCG", "dilution": "UNDILUTED", "status": "P"}
    assert items[0]["flags"] == ["<"] and items[0]["rawMessageId"] == 1
    assert s.fetch_results(3, 100) == []

def test_insert_is_idempotent(tmp_path):
    s = Store(str(tmp_path / "b.db"))
    ingest(s, BHCG); ingest(s, BHCG)
    assert len(s.fetch_results(0, 100)) == 3

def test_parse_error_keeps_raw(tmp_path):
    s = Store(str(tmp_path / "b.db"))
    assert ingest(s, "garbage\r") == 0
    raw = s.raw_messages("parse_error", 10)
    assert raw[0]["text"] == "garbage\r" and raw[0]["error"]
    assert s.stats()["parseErrors"] == 1

def test_replay(tmp_path):
    s = Store(str(tmp_path / "b.db"))
    rid = s.save_raw(BHCG)
    assert replay(s, rid) == 3 and replay(s, rid) == 0

def test_ack_never_goes_back(tmp_path):
    s = Store(str(tmp_path / "b.db")); ingest(s, BHCG)
    s.ack(3); s.ack(1)
    assert s.stats()["unackedResults"] == 0

def test_purge_only_acked_and_old(tmp_path):
    s = Store(str(tmp_path / "b.db")); ingest(s, BHCG); s.ack(2)
    s.purge(90, datetime.now(timezone.utc) + timedelta(days=91))
    assert [i["seq"] for i in s.fetch_results(0, 100)] == [3]
```

(`BHCG` importe depuis `tests/test_architect.py` ou deplace dans `tests/samples.py`.)

- [ ] **Step 2:** `pytest tests/test_store.py -v` -> FAIL.
- [ ] **Step 3:** Implementer `bridge/store.py` et `bridge/ingest.py`. Purge : `results` avec `seq <= acked_seq` et `received_at` du raw associe plus ancien que la retention ; puis `raw_messages` anciens non references.
- [ ] **Step 4:** `pytest -v` -> PASS (toute la suite).
- [ ] **Step 5: Commit** `git commit -m "feat: stockage SQLite, ingestion et rejeu"`

---

### Task 5: API REST

**Files:**
- Create: `bridge/api.py`, `bridge/link.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: `Store`, `replay` (Task 4).
- Produces:
  - `@dataclass LinkState` : `connected: bool = False`, `transport: str = ""`, `last_frame_at: str | None = None`, `last_message_at: str | None = None`, `error: str | None = None`.
  - `create_app(store: Store, link: LinkState, api_key: str, version: str) -> FastAPI` avec les 5 endpoints de la spec section 6. `limit` defaut 100, max 1000 (`422` au-dela). `POST /results/ack` -> `204`. `replay` sur id inconnu -> `404`.

- [ ] **Step 1: Tests qui echouent** (`fastapi.testclient.TestClient`)

```python
def make(tmp_path):
    s = Store(str(tmp_path / "b.db")); ingest(s, BHCG)
    return TestClient(create_app(s, LinkState(connected=True, transport="tcp"), "k", "0.1.0")), s

H = {"X-API-Key": "k"}

def test_requires_api_key(tmp_path):
    c, _ = make(tmp_path)
    assert c.get("/health").status_code == 401
    assert c.get("/health", headers={"X-API-Key": "bad"}).status_code == 401

def test_results_cursor(tmp_path):
    c, _ = make(tmp_path)
    r = c.get("/results?after=0&limit=2", headers=H).json()
    assert [i["seq"] for i in r["items"]] == [1, 2] and r["lastSeq"] == 2
    assert c.get("/results?after=3", headers=H).json() == {"items": [], "lastSeq": 3}
    assert c.get("/results?limit=5000", headers=H).status_code == 422

def test_ack_and_health(tmp_path):
    c, _ = make(tmp_path)
    assert c.post("/results/ack", json={"upToSeq": 3}, headers=H).status_code == 204
    h = c.get("/health", headers=H).json()
    assert h["connected"] is True and h["unackedResults"] == 0 and h["version"] == "0.1.0"

def test_raw_and_replay(tmp_path):
    c, s = make(tmp_path)
    assert c.get("/raw-messages", headers=H).json()[0]["id"] == 1
    assert c.post("/raw-messages/1/replay", headers=H).json() == {"inserted": 0}
    assert c.post("/raw-messages/99/replay", headers=H).status_code == 404
```

- [ ] **Step 2:** `pytest tests/test_api.py -v` -> FAIL.
- [ ] **Step 3:** Implementer `bridge/link.py` et `bridge/api.py` (cle verifiee par une dependance FastAPI globale, `secrets.compare_digest`).
- [ ] **Step 4:** `pytest -v` -> PASS.
- [ ] **Step 5: Commit** `git commit -m "feat: API REST (resultats, ack, health, rejeu)"`

---

### Task 6: Transports, config, main, simulateur, test de bout en bout

**Files:**
- Create: `bridge/transport/__init__.py`, `bridge/transport/serial_port.py`, `bridge/transport/tcp.py`, `bridge/config.py`, `bridge/main.py`, `simulator/__init__.py`, `simulator/architect_sim.py`, `config.example.toml`, `tests/test_e2e.py`

**Interfaces:**
- Consumes: `Transport`, `receive_session`, `send_message` (Task 2) ; `Store`, `ingest` (Task 4) ; `LinkState`, `create_app` (Task 5).
- Produces:
  - `SerialTransport(port: str, baudrate: int, bytesize: int, parity: str, stopbits: int)` ; `TcpServerTransport(host: str, port: int)` (accepte une connexion, la reaccepte apres deconnexion). Les deux implementent `Transport` + `close()`.
  - `@dataclass Config` + `load_config(path: str) -> Config` (tomllib). Sections : `[link] transport, port, baudrate, bytesize, parity, stopbits, tcp_host, tcp_port` ; `[store] path, retention_days=90` ; `[api] host="127.0.0.1", port=8085, api_key` (obligatoire, `ValueError` si vide) ; `[log] path="logs/bridge.log"`.
  - Helpers de test dans `tests/fakes.py` : `free_port() -> int`, `wait_until(cond: Callable[[], bool], timeout: float = 5.0) -> None` (AssertionError si depasse).
  - `run_connector(transport_factory: Callable[[], Transport], store: Store, link: LinkState, stop: threading.Event) -> None` : `link.transport` renseigne des que le transport est ouvert (ecoute pour TCP), `link.connected=True` quand un pair est connecte (TCP) ou le port ouvert (serie) ; boucle `receive_session(..., on_message=lambda t: ingest(store, t))`, met a jour `link`, sur erreur d'ouverture -> `link.connected=False`, `link.error`, attente 5 s, nouvelle tentative. Purge une fois par jour.
  - `main()` (point d'entree `architect-bridge = "bridge.main:main"` dans `pyproject.toml`) : config -> logging rotatif -> Store -> thread connecteur -> `uvicorn.run(create_app(...), host, port)`.
  - `python -m simulator.architect_sim --host 127.0.0.1 --port 5100 [--file messages.txt]` : se connecte en TCP et envoie les messages d'exemple (BHCG, controle, exception) via `send_message`.

- [ ] **Step 1: Test qui echoue** (`tests/test_e2e.py`)

```python
def test_simulator_to_api(tmp_path):
    store, link, stop = Store(str(tmp_path / "b.db")), LinkState(), threading.Event()
    port = free_port()
    th = threading.Thread(target=run_connector,
                          args=(lambda: TcpServerTransport("127.0.0.1", port), store, link, stop), daemon=True)
    th.start()
    wait_until(lambda: link.transport == "tcp")      # serveur en ecoute
    assert send_sample(("127.0.0.1", port), BHCG)    # helper du simulateur
    wait_until(lambda: store.stats()["unackedResults"] == 3)
    c = TestClient(create_app(store, link, "k", "test"))
    items = c.get("/results", headers={"X-API-Key": "k"}).json()["items"]
    assert [i["resultType"] for i in items] == ["F", "I", "P"]
    stop.set()

def test_config_requires_api_key(tmp_path):
    p = tmp_path / "c.toml"; p.write_text('[link]\ntransport="tcp"\n[store]\npath="b.db"\n[api]\napi_key=""\n')
    with pytest.raises(ValueError):
        load_config(str(p))
```

- [ ] **Step 2:** `pytest tests/test_e2e.py -v` -> FAIL.
- [ ] **Step 3:** Implementer transports, config, main, simulateur (`send_sample(addr, text) -> bool` expose par `simulator/architect_sim.py`). `config.example.toml` reprend toutes les cles avec les defauts de la spec (9600, 8, N, 1, COM5 en commentaire).
- [ ] **Step 4:** `pytest -v` -> PASS (toute la suite).
- [ ] **Step 5: Verification manuelle** : `copy config.example.toml config.toml` (transport tcp, port 5100, api_key renseignee) ; `architect-bridge` ; dans un autre terminal `python -m simulator.architect_sim --port 5100` ; `curl -H "X-API-Key: <cle>" http://127.0.0.1:8085/results` -> 3 items.
- [ ] **Step 6: Commit** `git commit -m "feat: transports, service principal, simulateur et test e2e"`

---

### Task 7: README d'exploitation

**Files:**
- Create: `README.md`

- [ ] **Step 1:** Rediger : objectif ; installation (`pip install -e .`) ; `config.toml` ; lancement ; reglages a faire sur l'ARCHITECT (Host - release mode : `Communications = On`, port COM5/P3, 9600 8N1, `Approved QC results` si besoin) ; cablage (null-modem 2-3 croises, masse 7 <-> 5 en DB-9) ; installation en service Windows avec NSSM (`nssm install ArchitectBridge <venv>\Scripts\architect-bridge.exe`) et unite systemd Linux ; contrat de consommation Spring (copie de la spec section 6) ; depannage (`/health`, `/raw-messages?status=parse_error`, rejeu).
- [ ] **Step 2:** Verifier que chaque commande du README fonctionne telle qu'ecrite (installation et lancement en local).
- [ ] **Step 3: Commit** `git commit -m "docs: README d'exploitation"`
