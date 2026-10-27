import pytest

from bridge.drivers.architect import parse_architect
from tests.samples import BHCG, CONTROL, EXCEPTION, H


def test_bhcg_f_i_p():
    rs = parse_architect(BHCG)
    assert [r.result_type for r in rs] == ["F", "I", "P"]
    f = rs[0]
    assert (f.value, f.units, f.reference_range, f.flags) == ("<1.20", "mIU/mL", "0.35 TO 4.94", ["<"])
    assert (f.specimen_id, f.carrier_id, f.position) == ("SID13", "A123", 5)
    assert (f.assay_number, f.assay_name, f.reagent_lot) == ("0021", "B-hCG", "47331M100")
    assert f.uid == "I20100|SID13|0021|F|1999-07-15T08:10:30"
    assert f.kind == "patient" and f.patient_id_3 == "PIDSID13"
    assert f.completed_at == "1999-07-15T08:10:30" and f.result_status == "F"
    assert rs[1].value == "NEGATIVE"
    assert rs[2].comments == ["Example Result Comment"]


def test_no_patient_name_stored():
    assert not any("PATIENT" in str(v) for v in vars(parse_architect(BHCG)[0]).values())


def test_control_result():
    r = parse_architect(CONTROL)[0]
    assert r.kind == "control" and r.control_lot == "40080"
    assert (r.operator_order, r.operator_release) == ("ECB", "RY")


def test_exception_record():
    r = parse_architect(EXCEPTION)[0]
    assert (r.kind, r.result_type, r.value) == ("exception", "X", None)
    assert r.comments == ["Sample short"] and r.instrument_serial == "123456789"
    assert r.completed_at == "1999-07-15T08:15:00"
    assert r.uid == "123456789|SID9|0241|X|1999-07-15T08:15:00|1"


def test_multiple_flags_split_on_repeat_delimiter():
    msg = BHCG.replace("|0.35 TO 4.94|<|", "|0.35 TO 4.94|<\\EXP|")
    assert parse_architect(msg)[0].flags == ["<", "EXP"]


def test_short_fields_do_not_crash():
    rs = parse_architect(H + "P|1\rO|1|S1\rR|1|^^^0241\rL|1\r")
    assert rs[0].assay_number == "0241" and rs[0].value is None


def test_rejects_non_header():
    with pytest.raises(ValueError):
        parse_architect("P|1\rL|1\r")
