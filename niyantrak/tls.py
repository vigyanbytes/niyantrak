"""TLS for the join listener: a self-signed certificate made on first start, pinned by its SHA-256 fingerprint.

No certificate authority is involved: the operator reads the fingerprint in the panel (it is part of the join
one-liner), and the joining machine refuses any server whose certificate does not hash to it — before the token is
sent. The certificate is made with the `openssl` command; the private key is written with mode 0600 in a 0700 folder.
"""
import hashlib
import http.client
import os
import re
import shutil
import ssl
import subprocess

CERT, KEY = "join-cert.pem", "join-key.pem"


def ensure_cert(state_dir, common_name="niyantrak-join", days=3650):
    """Return (cert_path, key_path), creating a self-signed EC P-256 certificate if there is none yet."""
    os.makedirs(state_dir, mode=0o700, exist_ok=True)
    os.chmod(state_dir, 0o700)
    cert, key = os.path.join(state_dir, CERT), os.path.join(state_dir, KEY)
    if not (os.path.isfile(cert) and os.path.isfile(key)):
        if not shutil.which("openssl"):
            raise RuntimeError("the join listener needs the openssl command to create its certificate")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                        "-nodes", "-keyout", key, "-out", cert, "-days", str(days), "-subj", f"/CN={common_name}"],
                       check=True, capture_output=True, preexec_fn=lambda: os.umask(0o077))
    os.chmod(key, 0o600)
    return cert, key


def fingerprint(cert_path):
    """Lower-case hex SHA-256 of the certificate (DER), the value the client pins."""
    with open(cert_path) as f:
        return hashlib.sha256(ssl.PEM_cert_to_DER_cert(f.read())).hexdigest()


def normalise_pin(pin):
    """Accept 'sha256:<hex>', plain hex, or colon-separated hex; return 64 lower-case hex characters."""
    h = str(pin or "").strip().lower()
    h = re.sub(r"[:\s]", "", h[7:] if h.startswith("sha256:") else h)
    if not re.fullmatch(r"[0-9a-f]{64}", h):
        raise ValueError("certificate pin must be a SHA-256 fingerprint (64 hex characters)")
    return h


def server_context(cert, key):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key)
    return ctx


class PinMismatch(ssl.SSLError):
    pass


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS that trusts exactly one certificate: the one whose SHA-256 equals `pin` (checked before any request)."""

    def __init__(self, host, port=None, pin=None, timeout=30):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.check_hostname = False        # self-signed: identity comes from the pin, not from a CA or a name
        ctx.verify_mode = ssl.CERT_NONE
        super().__init__(host, port, timeout=timeout, context=ctx)
        self.pin = normalise_pin(pin)

    def connect(self):
        super().connect()
        got = hashlib.sha256(self.sock.getpeercert(binary_form=True) or b"").hexdigest()
        if got != self.pin:
            self.sock.close()
            raise PinMismatch(f"server certificate sha256:{got} does not match the pinned certificate")
