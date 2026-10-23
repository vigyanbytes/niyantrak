"""Shared fixtures for the 5W telemetry tests: generic, made-up values only."""
from niyantrak.recognizers import verhoeff_ok

IBAN = "GB82 WEST 1234 5698 7654 32"          # the textbook example IBAN (valid checksum, not a real account)
EMAIL = "someone@example.com"
# published test/example health identifiers (NHS test number, ABHA address shape, KVNR worked example, CMS NPI example)
NHS = "943 476 5919"
ABHA_ADDRESS = "priya.sharma@abdm"
KVNR = "A123456780"
NPI = "1234567893"


def aadhaar():
    """A made-up 12-digit number with a valid Verhoeff checksum (so the recognizer treats it as an Aadhaar)."""
    for last in range(10):
        n = f"23456789012{last}"
        if verhoeff_ok(n):
            return f"{n[:4]} {n[4:8]} {n[8:]}"
    raise AssertionError("no checksum digit")


def event(**kw):
    e = {"ts": "2026-10-20T10:00:00Z", "who": "Priya (DevOps)", "agent": "Claude Code", "what": "Edit code",
         "where": "Cloud", "why": "RB-ROUTE-005 internal code may use cloud", "outcome": "masked",
         "rule_ids": ["RB-ROUTE-005"], "entity_counts": {"EMAIL": 2}, "machine": "control-01"}
    e.update(kw)
    return e


def otlp(records, resource=None):
    def kv(d):
        out = []
        for k, v in d.items():
            if isinstance(v, bool):
                val = {"boolValue": v}
            elif isinstance(v, int):
                val = {"intValue": str(v)}
            elif isinstance(v, list):
                val = {"arrayValue": {"values": [{"stringValue": x} for x in v]}}
            else:
                val = {"stringValue": v}
            out.append({"key": k, "value": val})
        return out
    return {"resourceLogs": [{"resource": {"attributes": kv(resource or {})},
                              "scopeLogs": [{"scope": {"name": "test"},
                                             "logRecords": [{"timeUnixNano": str(r.pop("_ns", 1_760_954_400_000_000_000)),
                                                             "body": {"stringValue": r.pop("_body", "")},
                                                             "attributes": kv(r)} for r in records]}]}]}
