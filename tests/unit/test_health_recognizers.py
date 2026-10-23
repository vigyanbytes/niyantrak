"""Health identifiers (the `health` pack): checksum or strong-format recognizers, each tagged with its region.

Reference values are the published textbook/test examples (CMS NPI spec, NHS test number, CMS MBI example,
the KVNR worked example), not real people.
"""
import pytest

from niyantrak import recognizers as R
from niyantrak.cli import detect
from niyantrak.telemetry import schema as S

from telemetry_helpers import event

ABHA_NUMBER = "91-1234-5678-9012"
ABHA_ADDRESS = "priya.sharma@abdm"
NPI = "1234567893"
NHS = "943 476 5919"
MBI = "1EG4-TE5-MK73"
KVNR = "A123456780"
HEALTH = {"ABHA_NUMBER": ABHA_NUMBER, "ABHA_ADDRESS": ABHA_ADDRESS, "US_NPI": NPI, "UK_NHS": NHS, "US_MBI": MBI,
          "DE_KVNR": KVNR}


def found(text, packs=("health",)):
    return [(e, v) for _s, _t, e, v in detect(text, list(packs))]


def test_health_pack_exists_with_every_recognizer():
    assert "health" in R.PACKS
    assert {e for e, _rx, _ok in R.PACKS["health"]} == set(HEALTH)


@pytest.mark.parametrize("entity,region", [("ABHA_NUMBER", "IN"), ("ABHA_ADDRESS", "IN"), ("US_NPI", "US"),
                                           ("US_MBI", "US"), ("UK_NHS", "GB"), ("DE_KVNR", "DE")])
def test_region_tags(entity, region):
    assert R.REGIONS[entity] == region
    assert entity in R.SECTORS["health"]


def test_every_recognizer_in_every_pack_has_a_region_tag():
    for pack in R.PACKS.values():
        for entity, _rx, _ok in pack:
            assert entity in R.REGIONS, entity


# ---- checksums ------------------------------------------------------------------------------------------------

def test_npi_luhn_with_80840_prefix():
    assert R.npi_ok("1234567893") and not R.npi_ok("1234567894")
    assert not R.npi_ok("3234567893")                   # NPIs start with 1 or 2
    assert not R.npi_ok("123456789")                    # 10 digits exactly
    assert not R.luhn_ok("80840" + "1234567894")


def test_nhs_mod11():
    assert R.nhs_ok("943 476 5919") and R.nhs_ok("9434765919") and not R.nhs_ok("943 476 5918")
    # a check value of 10 is never issued: find one and make sure it is rejected for every final digit
    for n in range(100000000, 100001000):
        body = str(n)
        s = sum(int(c) * w for c, w in zip(body, range(10, 1, -1)))
        if 11 - s % 11 == 10:
            assert not any(R.nhs_ok(body + str(d)) for d in range(10))
            break
    else:
        raise AssertionError("no check-10 body found")
    assert not R.nhs_ok("0000000000")                   # all same digit: valid mod-11, never issued


def test_kvnr_checksum():
    assert R.kvnr_ok("A123456780") and not R.kvnr_ok("A123456781")
    assert R.kvnr_ok("a123456780")                      # case-insensitive letter
    assert not R.kvnr_ok("1123456780")


def test_mbi_format():
    assert R.mbi_ok("1EG4-TE5-MK73") and R.mbi_ok("1EG4TE5MK73")
    for bad in ("0EG4TE5MK73",           # position 1 is 1-9
                "1SG4TE5MK73",           # S, L, O, I, B, Z are never used
                "1EG4TE5MK7A",           # position 11 is numeric
                "1EG4-TE5MK73"):         # dashes all or none
        assert not R.mbi_ok(bad), bad


# ---- detection in text ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("entity,value", sorted(HEALTH.items()))
def test_detected_in_text(entity, value):
    assert (entity, value) in found(f"patient record: id {value} updated")


@pytest.mark.parametrize("text", [
    "NPI 1234567894",                 # bad Luhn
    "NHS 943 476 5918",               # bad mod 11
    "KVNR A123456781",                # bad check digit
    "ref 0EG4-TE5-MK73",              # not an MBI shape
    "ABHA 91-1234-5678",              # too short
    "card 91-1234-5678-9012-3456",    # too long, not an ABHA number
    "mail priya.sharma@abdm.example.com",   # an email domain, not an ABHA address
    "build v1234567893beta",          # glued to a word
])
def test_lookalikes_not_detected(text):
    assert found(text) == []


def test_abha_address_wins_over_upi_id_on_the_same_span():
    assert found(f"link {ABHA_ADDRESS} now", packs=("india", "health")) == [("ABHA_ADDRESS", ABHA_ADDRESS)]
    assert found(f"link {ABHA_ADDRESS} now", packs=("health", "india")) == [("ABHA_ADDRESS", ABHA_ADDRESS)]
    assert found("pay ramesh@okhdfc", packs=("india", "health")) == [("UPI_ID", "ramesh@okhdfc")]


def test_abha_number_not_split_into_an_aadhaar():
    spans = found(f"ABHA {ABHA_NUMBER}", packs=("india", "health"))
    assert spans == [("ABHA_NUMBER", ABHA_NUMBER)]


def test_scan_cli_default_packs_include_health(capsys):
    from niyantrak import cli
    assert cli.main(["scan", "--json", f"NHS number {NHS}"]) == 0
    out = capsys.readouterr().out
    assert '"UK_NHS"' in out and NHS not in out


# ---- leak tests: health values never pass into 5W labels -------------------------------------------------------

@pytest.mark.parametrize("value", sorted(HEALTH.values()))
@pytest.mark.parametrize("field", ["who", "whom", "what", "where", "why"])
def test_health_identifiers_rejected_in_labels(field, value):
    with pytest.raises(S.EventError) as ei:
        S.validate(event(**{field: f"x {value}"}))
    assert value not in str(ei.value)
