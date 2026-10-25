"""niyantrak — free parts: identifier detectors with checksums, node cards + discovery, web panel. Apache-2.0."""
__version__ = "0.1.1"

from .recognizers import PACKS, aadhaar_ok, gstin_ok, iban_ok, luhn_ok, pan_ok, us_ssn_ok, verhoeff_ok  # noqa: F401
