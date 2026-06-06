import hashlib
import hmac
import time


def compute_signature(secret: str, timestamp: str, body: bytes) -> str:
    signed = timestamp.encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


def verify_signature(secret, timestamp, body, signature, max_age_seconds=300) -> bool:
    try:
        age = abs(time.time() - int(timestamp))
    except (TypeError, ValueError):
        return False
    if age > max_age_seconds:
        return False
    expected = compute_signature(secret, timestamp, body)
    return hmac.compare_digest(expected, signature)