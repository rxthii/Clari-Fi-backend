from app.services.categorizer import untrusted_text
import re


def data_block(label: str, rows, limit: int = 6000) -> str:
    import json
    safe = json.dumps(rows, ensure_ascii=False, default=str)
    return f"<untrusted_{label}>\n{untrusted_text(safe, limit)}\n</untrusted_{label}>"


def sanitize_chat_text(value: str) -> str:
    text = untrusted_text(value, 4000)
    text = re.sub(r"(?i)\b(bearer\s+)[A-Za-z0-9._~-]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)\b(pin|password|passcode|jwt|token)\s*(?:is|=|:)?\s*[^\s,;]+", r"\1 [REDACTED]", text)
    return text
