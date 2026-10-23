"""Identifier detectors: checksums accept real shapes and reject look-alikes."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from niyantrak import PACKS, aadhaar_ok, gstin_ok, iban_ok, luhn_ok, pan_ok, us_ssn_ok  # noqa: E402


def test_aadhaar_verhoeff():
    assert aadhaar_ok("2345 6789 0124") and not aadhaar_ok("2345 6789 0123")
    assert not aadhaar_ok("1345 6789 0124")            # cannot start with 0 or 1


def test_pan_holder_type():
    assert pan_ok("ABCPE1234F") and not pan_ok("ABCXE1234F")


def test_gstin_checksum():
    assert gstin_ok("29AAMCV3593N1ZA") and not gstin_ok("29AAMCV3593N1ZB")


def test_cards_iban_ssn():
    assert luhn_ok("4111 1111 1111 1111") and not luhn_ok("4111 1111 1111 1112")
    assert iban_ok("GB82 WEST 1234 5698 7654 32") and not iban_ok("GB82 WEST 1234 5698 7654 33")
    assert us_ssn_ok("123-45-6789") and not us_ssn_ok("666-45-6789")


def find(pack, text):
    return [(e, m.group(0)) for e, rx, ok in PACKS[pack] for m in rx.finditer(text) if ok is None or ok(m.group(0))]


def test_upi_vs_email():
    found = find("india", "pay ramesh@okhdfc or mail ramesh@example.com")
    assert ("UPI_ID", "ramesh@okhdfc") in found
    assert not any(v == "ramesh@example.com" for e, v in found if e == "UPI_ID")


def test_indian_mobile():
    assert ("IN_PHONE", "+91 98450 12345") in find("india", "call +91 98450 12345 today")
