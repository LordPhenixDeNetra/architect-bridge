"""Decoupage des messages ASTM E1394 (enregistrements, champs, composants)."""


def parse_message(text: str) -> list[list[str]]:
    """Message (enregistrements separes par CR) -> liste d'enregistrements en champs bruts."""
    records = [r for r in text.split("\r") if r.strip("\n")]
    records = [r.lstrip("\n") for r in records]
    # Le delimiteur de champ est le 2e caractere de l'en-tete H.
    sep = records[0][1] if records and records[0][:1] in "Hh" and len(records[0]) > 1 else "|"
    return [r.split(sep) for r in records]


PATIENT_IDENTITY_FIELDS = (6, 8, 9)  # nom, date de naissance, sexe


def redact_patient_identity(text: str) -> str:
    """Vide les champs d'identite des enregistrements P ; le reste du message est intact."""
    sep = text[1] if text[:1] in "Hh" and len(text) > 1 else "|"
    out = []
    for rec in text.split("\r"):
        if rec.lstrip("\n")[:1] in ("P", "p"):
            fields = rec.split(sep)
            for i in PATIENT_IDENTITY_FIELDS:
                if i <= len(fields):
                    fields[i - 1] = ""
            rec = sep.join(fields)
        out.append(rec)
    return "\r".join(out)


def field(record: list[str], i: int) -> str:
    """Champ ASTM numero i (record[0] = type = champ 1) ; "" si absent."""
    return record[i - 1] if 0 < i <= len(record) else ""


def comp(value: str, i: int) -> str | None:
    """Composant i (a partir de 1, separateur ^) ; None si absent ou vide."""
    parts = value.split("^")
    return (parts[i - 1] or None) if 0 < i <= len(parts) else None
