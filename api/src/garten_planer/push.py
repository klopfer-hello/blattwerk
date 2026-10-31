"""Web push helpers. Subscriptions may only point to the real push services
(an endpoint is a URL the worker will POST to: anything else would be an SSRF
hole, see Frame Hub #021). `python -m garten_planer.push keygen` prints a new
VAPID key pair for the host's .env (run there, never on the PC)."""

import base64
import re
import sys
from urllib.parse import urlsplit, urlunsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

# Exact hosts or (with a leading dot) host suffixes of the browser push services.
PUSH_HOSTS = ("fcm.googleapis.com", ".push.apple.com", "updates.push.services.mozilla.com", ".notify.windows.com")
B64URL = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")
NETLOC = re.compile(r"^[A-Za-z0-9.-]+$")  # plain host name only: no userinfo, port, \, % or non-ASCII


def push_endpoint_ok(url: str) -> bool:
    r"""Strict on purpose (review M3b): Python's urlsplit and urllib3 (used by the sender)
    disagree on hosts like "evil.example\.push.apple.com", so the authority must be a
    plain host name and the URL must survive a split/unsplit round trip unchanged."""
    if not url.isascii() or any(ch.isspace() for ch in url):
        return False
    parts = urlsplit(url)
    if parts.scheme != "https" or not NETLOC.match(parts.netloc) or urlunsplit(parts) != url:
        return False
    host = parts.netloc.lower()
    return any(host == h or (h.startswith(".") and host.endswith(h) and len(host) > len(h)) for h in PUSH_HOSTS)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def keygen() -> tuple[str, str]:
    """(public: raw uncompressed P-256 point, private: DER PKCS8), both base64url."""
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    private = key.private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return _b64(public), _b64(private)


if __name__ == "__main__" and sys.argv[1:] == ["keygen"]:
    pub, priv = keygen()
    print(f"GP_VAPID_PUBLIC={pub}\nGP_VAPID_PRIVATE={priv}")
