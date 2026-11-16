# Stub gate trace

This directory is a recomputable record of the offline state machine. It is not a paper run.

`s1_s6_stub_trace.json` is produced by `gate_trace.py` with `--stub` stages, a forced stage failure (`ARD_FAIL_STAGE`), a missing-script stand-in, and a missing provider file. Sister repositories are not called. `v24_final` is null. `paper_outcome` is null.

```bash
python3 evidence/verify_trace.py
```

`--write` overwrites the committed trace. Use it only after you have read the diff and still intend the new machine behavior.
