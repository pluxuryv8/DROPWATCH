from __future__ import annotations

import base64


def encode_secret(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def decode_secret(value_b64: str | None) -> str | None:
    if not value_b64:
        return None
    try:
        decoded = base64.b64decode(value_b64.encode("ascii"), validate=True).decode("utf-8")
    except Exception:
        return None
    decoded = decoded.strip()
    return decoded or None
