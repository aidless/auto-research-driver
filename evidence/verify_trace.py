#!/usr/bin/env python3
"""Recompute the stub S1–S6 gate trace and compare it to the committed file.

Stdlib plus this repository. No sister repos, no network, no pytest.

    python3 evidence/verify_trace.py          # exit 0 when the trace matches
    python3 evidence/verify_trace.py --write  # overwrite the committed trace
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evidence.gate_trace import TRACE_PATH, build_trace  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="recompute the stub gate trace")
    parser.add_argument("--write", action="store_true", help="overwrite the committed trace")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        got = build_trace(Path(tmp))
    text = json.dumps(got, indent=2, sort_keys=True) + "\n"
    if args.write:
        TRACE_PATH.write_text(text, encoding="utf-8")
        print(f"wrote {TRACE_PATH}")
        return 0
    if not TRACE_PATH.is_file():
        print(f"missing committed trace: {TRACE_PATH}", file=sys.stderr)
        return 1
    expected = json.loads(TRACE_PATH.read_text(encoding="utf-8"))
    if got != expected:
        print("stub gate trace does not match the committed file", file=sys.stderr)
        before = json.dumps(expected, indent=2, sort_keys=True).splitlines()
        after = text.splitlines()
        diff = difflib.unified_diff(before, after, fromfile="committed", tofile="recomputed", lineterm="")
        print("\n".join(list(diff)[:240]), file=sys.stderr)
        return 1
    print(f"trace ok ({TRACE_PATH.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
