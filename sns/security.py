import base64
import hashlib
import hmac
import secrets

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1
TOKEN_PREFIX = "sns_"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    candidate = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=32)
    return hmac.compare_digest(candidate, _unb64(digest))


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Tokens are high-entropy random strings, so a plain SHA-256 is enough for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def parse_bearer(header_value: str | None) -> str | None:
    if not header_value:
        return None
    scheme, _, value = header_value.partition(" ")
    value = value.strip()
    return value if scheme.lower() == "bearer" and value else None
