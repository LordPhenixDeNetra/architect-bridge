"""Interpretation des messages ARCHITECT (manuel ASI, section 4) en resultats."""
from dataclasses import dataclass, field as dc_field

from bridge.codec import comp, field, parse_message


@dataclass
class Result:
    uid: str
    kind: str  # patient | control | exception
    specimen_id: str | None = None
    instrument_specimen_id: str | None = None
    carrier_id: str | None = None
    position: int | None = None
    patient_id_practice: str | None = None
    patient_id_lab: str | None = None
    patient_id_3: str | None = None
    assay_number: str | None = None
    assay_name: str | None = None
    dilution: str | None = None
    assay_status: str | None = None
    reagent_lot: str | None = None
    reagent_serial: str | None = None
    control_lot: str | None = None
    result_type: str | None = None  # F | I | P | X
    value: str | None = None
    units: str | None = None
    reference_range: str | None = None
    flags: list[str] = dc_field(default_factory=list)
    result_status: str | None = None
    operator_order: str | None = None
    operator_release: str | None = None
    completed_at: str | None = None
    instrument_serial: str | None = None
    priority: str | None = None
    comments: list[str] = dc_field(default_factory=list)


def _iso(ts: str) -> str | None:
    """YYYYMMDDHHMMSS -> YYYY-MM-DDTHH:MM:SS ; valeur brute si format inattendu."""
    ts = ts.strip()
    if len(ts) == 14 and ts.isdigit():
        return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}T{ts[8:10]}:{ts[10:12]}:{ts[12:14]}"
    return ts or None


def _int(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None


def _uid(r: Result) -> str:
    return f"{r.instrument_serial}|{r.specimen_id}|{r.assay_number}|{r.result_type}|{r.completed_at}"


def parse_architect(text: str) -> list[Result]:
    records = parse_message(text)
    if not records or records[0][0] not in ("H", "h"):
        raise ValueError("Le message ne commence pas par un en-tete H")
    header = records[0]
    scc_serial = comp(field(header, 5), 3)
    header_date = _iso(field(header, 14))

    results: list[Result] = []
    patient: dict = {}
    order: dict = {}
    last: Result | None = None
    for rec in records[1:]:
        rtype = rec[0].upper()
        if rtype == "P":
            patient = {
                "patient_id_practice": field(rec, 3) or None,
                "patient_id_lab": field(rec, 4) or None,
                "patient_id_3": field(rec, 5) or None,
            }
            order, last = {}, None
        elif rtype == "O":
            test, inst = field(rec, 5), field(rec, 4)
            report = field(rec, 26).upper()
            order = {
                "kind": "exception" if report == "X" else "control" if field(rec, 12).upper() == "Q" else "patient",
                "specimen_id": field(rec, 3) or None,
                "instrument_specimen_id": comp(inst, 1),
                "carrier_id": comp(inst, 2),
                "position": _int(comp(inst, 3)),
                "assay_number": comp(test, 4),
                "assay_name": comp(test, 5),
                "dilution": comp(test, 6),
                "assay_status": comp(test, 7),
                "priority": field(rec, 6) or None,
            }
            last = None
            if order["kind"] == "exception":
                last = Result(uid="", **patient, **order, result_type="X",
                              completed_at=header_date, instrument_serial=scc_serial)
                # Repetitions d'un meme test : seule la sequence O les distingue (meme H.14).
                last.uid = f"{_uid(last)}|{field(rec, 2)}"
                results.append(last)
        elif rtype == "R":
            test, ops = field(rec, 3), field(rec, 11)
            base = {**order, "kind": order.get("kind", "patient")}
            base.update(assay_number=comp(test, 4) or base.get("assay_number"),
                        assay_name=comp(test, 5) or base.get("assay_name"),
                        dilution=comp(test, 6) or base.get("dilution"),
                        assay_status=comp(test, 7) or base.get("assay_status"))
            last = Result(
                uid="", **patient, **base,
                reagent_lot=comp(test, 8),
                reagent_serial=comp(test, 9),
                control_lot=comp(test, 10),
                result_type=comp(test, 11),
                value=field(rec, 4) or None,
                units=field(rec, 5) or None,
                reference_range=field(rec, 6) or None,
                flags=[f for f in field(rec, 7).split("\\") if f],
                result_status=field(rec, 9) or None,
                operator_order=comp(ops, 1),
                operator_release=comp(ops, 2),
                completed_at=_iso(field(rec, 13)),
                instrument_serial=field(rec, 14) or scc_serial,
            )
            last.uid = _uid(last)
            results.append(last)
        elif rtype == "C" and last is not None:
            if field(rec, 4):
                last.comments.append(field(rec, 4))
    return results
