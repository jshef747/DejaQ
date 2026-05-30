"""Parse raw model output into a binary verdict.

The expected output is a single token: VALID or INVALID.
We also accept synonyms and do substring scan as fallback.
UNPARSEABLE is counted as INVALID in production (fail-safe).
"""

from __future__ import annotations

import re


def parse_verdict(text: str) -> tuple[str, str]:
    """Return (verdict, raw_text) where verdict is VALID, INVALID, or UNPARSEABLE."""
    raw = text.strip()
    upper = raw.upper()

    first = re.split(r"[\s\.,:;!\?]+", upper, maxsplit=1)[0]

    if first in ("VALID", "YES", "TRUE", "CORRECT", "MATCH"):
        return ("VALID", raw)
    if first in ("INVALID", "NO", "FALSE", "INCORRECT", "MISMATCH", "NOMATCH"):
        return ("INVALID", raw)

    # substring scan — INVALID and negations before VALID
    if "INVALID" in upper or "NOT VALID" in upper or "NOT VALID" in upper:
        return ("INVALID", raw)
    if "VALID" in upper:
        return ("VALID", raw)

    return ("UNPARSEABLE", raw)


if __name__ == "__main__":
    cases = [
        ("VALID", "VALID"),
        ("INVALID", "INVALID"),
        ("valid", "VALID"),
        ("invalid reason: missing data", "INVALID"),
        ("VALID.", "VALID"),
        ("INVALID\nsome explanation", "INVALID"),
        ("NO", "INVALID"),
        ("YES", "VALID"),
        ("not valid", "INVALID"),
        ("The answer is valid", "VALID"),
        ("gibberish", "UNPARSEABLE"),
        ("", "UNPARSEABLE"),
    ]
    ok = True
    for text, expected in cases:
        verdict, _ = parse_verdict(text)
        status = "OK" if verdict == expected else "FAIL"
        if status == "FAIL":
            ok = False
        print(f"  {status}  parse_verdict({text!r}) = {verdict!r}  (expected {expected!r})")
    print("All OK" if ok else "FAILURES above")
