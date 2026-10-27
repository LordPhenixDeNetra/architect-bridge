from bridge.codec import comp, field, parse_message

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
