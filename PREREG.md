# Preregistration — what this checkout measures

This file replaces earlier claims that a 7.8 quality loop and a sister-repo pipeline had been executed here.

## Question

Can the gate state machine be recomputed on a fresh clone without a paper, a provider, or the sister repos?

## What a passing `make check` shows

- Unsigned decision/confirm gates pause `driver run` (exit 0) until `driver sign`.
- `--skip-checkpoints` completes stages with no signature.
- A failed stage restores progress fields to the pre-stage snapshot and keeps `run_count` / alarms.
- S6's budget cap of 1 writes one `[budget]` alarm and does not block the next run.
- A missing pipeline script returns 1 without a subprocess.
- A missing provider config aborts before a stage.
- Corrupt `state.json` is renamed aside and replaced with an empty state.

The committed witness is `evidence/s1_s6_stub_trace.json`. `evidence/verify_trace.py` rebuilds it in a temp directory.

## What it does not show

No TMLR submission, acceptance, score, cost saving, or sister-repo install. The number 7.8 is leftover prompt text, not a score this driver computes. `scripts/driver.py` does not loop from S5 back to S4.
