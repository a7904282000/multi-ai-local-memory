#!/usr/bin/env python3
"""Minimal dependency-free validator for portable memory atoms."""
import json
import sys
from pathlib import Path

ALLOWED_STATUS = {"VERIFIED", "UNVERIFIED", "OBSOLETE", "CONFLICT"}
ALLOWED_SENSITIVITY = {"normal", "sensitive", "secret"}
REQUIRED = {
    "category", "fact", "status", "source_type", "source_agent",
    "last_known_date", "confidence", "mutable", "sensitivity"
}

def validate(obj):
    errors = []
    missing = sorted(REQUIRED - obj.keys())
    if missing:
        errors.append("missing=" + ",".join(missing))
    if obj.get("status") not in ALLOWED_STATUS:
        errors.append("invalid status")
    if obj.get("sensitivity") not in ALLOWED_SENSITIVITY:
        errors.append("invalid sensitivity")
    c = obj.get("confidence")
    if not isinstance(c, (int, float)) or isinstance(c, bool) or not (0 <= c <= 1):
        errors.append("confidence must be 0..1")
    if not isinstance(obj.get("mutable"), bool):
        errors.append("mutable must be boolean")
    if not isinstance(obj.get("fact"), str) or not obj.get("fact", "").strip():
        errors.append("fact must be non-empty string")
    if obj.get("sensitivity") == "secret":
        errors.append("secret values must not be stored as long-term memory")
    return errors

def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: validate_memory_atom.py <atom.json>")
    p = Path(sys.argv[1])
    obj = json.loads(p.read_text(encoding="utf-8"))
    errors = validate(obj)
    if errors:
        print("MEMORY_ATOM=FAIL")
        for e in errors:
            print("ERROR=" + e)
        raise SystemExit(1)
    print("MEMORY_ATOM=PASS")

if __name__ == "__main__":
    main()
