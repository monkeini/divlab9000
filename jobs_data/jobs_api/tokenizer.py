from __future__ import annotations

import re

TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9+#.\-]*", re.IGNORECASE)


def tokenize(text: str | None) -> list[str]:
    if not text:
        return []
    return [match.group(0).lower() for match in TOKEN_PATTERN.finditer(text)]
