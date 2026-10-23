"""5W event schema: only who/whom/where/what/why + agent, route, rule ids, outcome, entity counts. No values, no text."""
import pytest

from niyantrak.telemetry import schema as S

from telemetry_helpers import IBAN, EMAIL, aadhaar, event


def test_valid_event_is_normalised():
    e = S.validate(event())
    assert e["who"] == "Priya (DevOps)" and e["outcome"] == "masked" and e["schema"] == S.SCHEMA
    assert e["ts"] == "2026-10-20T10:00:00.000000Z" and len(e["event_id"]) == 32
    assert e["entity_counts"] == {"EMAIL": 2} and e["rule_ids"] == ["RB-ROUTE-005"]
    assert e["whom"] is None and e["route"] is None


def test_epoch_seconds_accepted():
    assert S.validate(event(ts=1_760_954_400))["ts"].startswith("2025-10-20T10:00:00")


@pytest.mark.parametrize("field", ["message", "text", "body", "prompt", "content", "value", "user_email", "aadhaar"])
def test_unknown_or_value_fields_rejected(field):
    with pytest.raises(S.EventError) as ei:
        S.validate(event(**{field: "anything"}))
    assert field in str(ei.value)


@pytest.mark.parametrize("missing", ["ts", "who", "what", "where", "why", "outcome"])
def test_required_fields(missing):
    e = event()
    del e[missing]
    with pytest.raises(S.EventError):
        S.validate(e)


def test_long_free_text_rejected():
    with pytest.raises(S.EventError):
        S.validate(event(what="x" * 65))
    with pytest.raises(S.EventError):
        S.validate(event(why="please refund the customer because the parcel never arrived and they are upset today"))
    with pytest.raises(S.EventError):
        S.validate(event(who="line one\nline two"))


@pytest.mark.parametrize("value", [aadhaar(), IBAN, EMAIL, "+91 98450 12345", "4111 1111 1111 1111"])
@pytest.mark.parametrize("field", ["who", "whom", "what", "where", "why", "agent", "machine"])
def test_identifier_values_rejected_in_every_label(field, value):
    with pytest.raises(S.EventError) as ei:
        S.validate(event(**{field: f"x {value}"[:64]}))
    assert value not in str(ei.value)                 # errors name the field, never echo the value


def test_digit_runs_rejected():
    with pytest.raises(S.EventError):
        S.validate(event(who="customer 123456789012"))


def test_outcome_enum_rule_ids_and_counts():
    with pytest.raises(S.EventError):
        S.validate(event(outcome="maybe"))
    with pytest.raises(S.EventError):
        S.validate(event(rule_ids=["has space in it"]))
    with pytest.raises(S.EventError):
        S.validate(event(rule_ids=["R"] * 17))
    with pytest.raises(S.EventError):
        S.validate(event(entity_counts={"EMAIL": -1}))
    with pytest.raises(S.EventError):
        S.validate(event(entity_counts={EMAIL: 1}))
    with pytest.raises(S.EventError):
        S.validate(event(entity_counts={"EMAIL": "2"}))


def test_session_must_be_pseudonym():
    assert S.validate(event(session=S.pseudonym("conv-1", "salt")))["session"].startswith("p-")
    with pytest.raises(S.EventError):
        S.validate(event(session="conv-1"))


def test_pseudonym_is_stable_salted_and_irreversible():
    a, b = S.pseudonym("u-1", "s1"), S.pseudonym("u-1", "s2")
    assert a == S.pseudonym("u-1", "s1") and a != b and "u-1" not in a and len(a) == 14


def test_non_dict_rejected():
    with pytest.raises(S.EventError):
        S.validate(["who"])


# --- 5W labels may be real paths (POSIX absolute, Windows drive or UNC) --------------------------------------------

@pytest.mark.parametrize("path", [
    "/var/log", "/var/log/nginx/access.log", "/etc/niyantrak/", "/", "/opt/app (staging)",
    "/home/dev/node_modules/@scope/pkg", "/srv/data/build-2026.10", "/tmp/a b c",
    "C:\\", "C:\\Users\\Public", "C:\\Program Files\\Niyantrak\\logs", "D:/data/exports", "c:\\temp",
    "\\\\fileserver\\share\\reports",
])
@pytest.mark.parametrize("field", ["where", "what", "route"])
def test_paths_accepted_as_labels(field, path):
    assert S.validate(event(**{field: path}))[field] == path


@pytest.mark.parametrize("path", [
    "/home/someone@example.com/inbox",                      # email in a path segment
    "/data/customers/" + aadhaar().replace(" ", ""),        # Aadhaar in a path segment
    "/exports/" + IBAN.replace(" ", "") + ".csv",           # IBAN in a file name
    "C:\\Users\\someone@example.com\\Desktop",              # email in a Windows path
    "D:\\cards\\4111111111111111.txt",                      # card number in a Windows file name
    "/srv/upload/123456789012/",                            # long digit run
])
def test_identifiers_inside_paths_still_rejected(path):
    with pytest.raises(S.EventError) as ei:
        S.validate(event(where=path))
    assert "personal data" in str(ei.value) or "identifier" in str(ei.value)
    assert path not in str(ei.value)


@pytest.mark.parametrize("value", [
    "/var/log\n/etc/passwd",                                # two lines
    "/" + "a" * 70,                                         # too long
    "/a b c d e f g h i j",                                 # too many words
    "/var/log; rm -rf /",                                   # shell punctuation is not a path character
    "/var/log`id`", "/var/$HOME", "/var/<x>", "/a|b", "/a\"b",
    "C:\\Users\\x;y", "C:relative\\path", "\\single\\backslash", "\\\\",
    "please / refund the customer because it never arrived",  # free text that merely contains a slash
    "@someone", "\\tmp", "~/notes",
])
def test_free_text_and_odd_characters_still_rejected(value):
    with pytest.raises(S.EventError):
        S.validate(event(where=value))
