"""Pattern recognizers with checksums, grouped into packs: jurisdiction packs (india, eu, uk, us, global) and the
sector pack `health` (health identifiers from every region). Every recognizer carries a region tag (REGIONS).

Each recognizer: (entity, compiled regex, validator or None). A validator rejects look-alikes (e.g. any 12 digits is
not an Aadhaar; the Verhoeff checksum must hold). Patterns and checksums only: names, places and free-text
details are not detected by this module.
"""
import re

# ── checksums ─────────────────────────────────────────────────────────────────────────────────────────────
_VD = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
       [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
       [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
       [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_VP = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
       [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
       [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def digits(s):
    return re.sub(r"\D", "", s)


def verhoeff_ok(num):
    c = 0
    for i, ch in enumerate(reversed(num)):
        c = _VD[c][_VP[i % 8][int(ch)]]
    return c == 0


def aadhaar_ok(s):
    d = digits(s)
    return len(d) == 12 and d[0] not in "01" and verhoeff_ok(d)


def luhn_ok(s):
    d = digits(s)
    if not 13 <= len(d) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(d)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


_B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_ok(s):
    s = s.upper()
    if len(s) != 15:
        return False
    total = 0
    for i, ch in enumerate(s[:14]):
        p = _B36.index(ch) * (1 if i % 2 == 0 else 2)
        total += p // 36 + p % 36
    return _B36[(36 - total % 36) % 36] == s[14]


def iban_ok(s):
    s = re.sub(r"\s", "", s).upper()
    if not 15 <= len(s) <= 34:
        return False
    r = s[4:] + s[:4]
    return int("".join(str(_B36.index(c)) for c in r)) % 97 == 1


def pan_ok(s):
    return s[3].upper() in "PCHFATBLJG"          # 4th letter = holder type (person, company, HUF, firm, …)


def us_ssn_ok(s):
    d = digits(s)
    return len(d) == 9 and d[:3] not in ("000", "666") and not d.startswith("9") and d[3:5] != "00" and d[5:] != "0000"


def npi_ok(s):
    """US National Provider Identifier: 10 digits, starts 1 or 2, Luhn over the card-issuer prefix 80840 + NPI."""
    d = digits(s)
    return len(d) == 10 and d[0] in "12" and luhn_ok("80840" + d)


def nhs_ok(s):
    """UK NHS number: 10 digits, mod 11 with weights 10..2; a check value of 10 is never issued."""
    d = digits(s)
    if len(d) != 10 or len(set(d)) == 1:
        return False
    check = 11 - sum(int(c) * w for c, w in zip(d[:9], range(10, 1, -1))) % 11
    check = 0 if check == 11 else check
    return check != 10 and check == int(d[9])


def kvnr_ok(s):
    """German health insurance number (Krankenversichertennummer, on the eGK / German EHIC): letter + 8 digits +
    check digit. The letter becomes its two-digit position (A=01), weights alternate 1,2; digit sums of the
    products are added and the total mod 10 is the check digit."""
    s = s.strip().upper()
    if len(s) != 10 or not s[0].isalpha() or not s[0].isascii() or not s[1:].isdigit():
        return False
    body = f"{ord(s[0]) - 64:02d}" + s[1:9]
    total = 0
    for i, ch in enumerate(body):
        p = int(ch) * (1 if i % 2 == 0 else 2)
        total += p // 10 + p % 10
    return total % 10 == int(s[9])


_MBI_A = "AC-HJKMNP-RT-Y"           # letters A-Z except S, L, O, I, B, Z
_MBI_RX = re.compile(rf"[1-9][{_MBI_A}][{_MBI_A}0-9]\d(-?)[{_MBI_A}][{_MBI_A}0-9]\d\1[{_MBI_A}]{{2}}\d{{2}}")


def mbi_ok(s):
    """US Medicare Beneficiary Identifier: 11 characters in a fixed letter/digit layout (no checksum is published)."""
    return bool(_MBI_RX.fullmatch(s.strip()))


# ── packs ─────────────────────────────────────────────────────────────────────────────────────────────────
B = r"(?<![\w@.])"     # not glued to a word, email or dotted name
E = r"(?![\w@])"
PACKS = {
    "india": [
        ("AADHAAR", re.compile(B + r"[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}" + E), aadhaar_ok),
        ("PAN", re.compile(B + r"[A-Za-z]{5}\d{4}[A-Za-z]" + E), pan_ok),
        ("GSTIN", re.compile(B + r"\d{2}[A-Za-z]{5}\d{4}[A-Za-z][1-9A-Za-z][Zz][0-9A-Za-z]" + E), gstin_ok),
        ("IFSC", re.compile(B + r"[A-Z]{4}0[A-Z0-9]{6}" + E), None),
        ("UPI_ID", re.compile(B + r"[a-zA-Z0-9][a-zA-Z0-9._-]{1,255}@[a-zA-Z]{2,64}" + r"(?![\w.@])"), None),
        ("IN_PHONE", re.compile(r"(?<![\w+])(?:\+91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}" + E), None),
    ],
    "eu": [
        ("IBAN", re.compile(B + r"[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?" + E), iban_ok),
    ],
    "uk": [
        ("UK_NINO", re.compile(B + r"(?!BG|GB|NK|KN|TN|NT|ZZ)[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]" + E), None),
    ],
    "us": [
        ("US_SSN", re.compile(B + r"\d{3}-\d{2}-\d{4}" + E), us_ssn_ok),
    ],
    # Health identifiers. Checksummed where the issuer defines one (NPI, NHS, KVNR); otherwise a strong format
    # (ABHA number 2-4-4-4, ABHA address @abdm, Medicare MBI layout). Region per entity in REGIONS.
    "health": [
        ("ABHA_NUMBER", re.compile(r"(?<![\w@.-])\d{2}([\s-])\d{4}\1\d{4}\1\d{4}(?![\w@]|[\s-]\d)"), None),
        ("ABHA_ADDRESS", re.compile(B + r"[A-Za-z0-9][A-Za-z0-9._]{2,31}@(?:abdm|sbx|ndhm)(?![\w.@-])"), None),
        ("US_NPI", re.compile(B + r"[12]\d{9}" + E), npi_ok),
        ("US_MBI", re.compile(B + r"[1-9][A-Z][A-Z0-9]\d-?[A-Z][A-Z0-9]\d-?[A-Z]{2}\d{2}" + E), mbi_ok),
        ("UK_NHS", re.compile(B + r"\d{3}([\s-]?)\d{3}\1\d{4}" + E), nhs_ok),
        ("DE_KVNR", re.compile(B + r"[A-Za-z]\d{9}" + E), kvnr_ok),
    ],
    "global": [
        ("EMAIL", re.compile(B + r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}" + E), None),
        ("CARD", re.compile(B + r"\d{4}(?:[\s-]?\d{4}){2}[\s-]?\d{1,7}" + E), luhn_ok),
        ("PHONE", re.compile(r"(?<![\w+])\+(?:[1-9]\d{0,2})[\s-]?\d{2,4}(?:[\s-]?\d{2,4}){2,3}" + E), None),
    ],
}

# ISO 3166 region of the issuing scheme ("*" = not tied to one region). The pack says what a recognizer is for; the
# region says whose law usually governs it -- packs are never a substitute for picking the laws that apply to you.
REGIONS = {
    "AADHAAR": "IN", "PAN": "IN", "GSTIN": "IN", "IFSC": "IN", "UPI_ID": "IN", "IN_PHONE": "IN",
    "IBAN": "EU", "UK_NINO": "GB", "US_SSN": "US",
    "ABHA_NUMBER": "IN", "ABHA_ADDRESS": "IN", "US_NPI": "US", "US_MBI": "US", "UK_NHS": "GB", "DE_KVNR": "DE",
    "EMAIL": "*", "CARD": "*", "PHONE": "*",
}
SECTORS = {"health": frozenset(e for e, _rx, _ok in PACKS["health"])}

# On an identical span the more specific recognizer wins (an ABHA address also has the shape of a UPI id).
PRIORITY = {"ABHA_ADDRESS": -1}
