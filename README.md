# auto-research-driver

**STATUS: WORK-IN-PROGRESS — not A yet.** The GitHub About text is outside this repo and still says budget alerts stop a run. They do not. The gap list is in [FAILURE_MODES.md](FAILURE_MODES.md).

Offline, this repo proves checkpoint gates (decision/confirm), `state.json` transitions, rollback of a failed stage's progress fields, and per-stage rerun alarms (S1=2, S2=3, S3=2, S4=3, S5=4, S6=1). An alarm is stored; it does not stop a later run.

Not proven here: any TMLR paper, submission, acceptance, sister-repo install, or cost saving. The 7.8 figure is prompt text in `checkpoints.py`, not a measured score.

Recompute the stub S1–S6 trace with `make check` (no sister repos, no network). The five failure modes are in [FAILURE_MODES.md](FAILURE_MODES.md).

## Fresh clone

```bash
python3 -m pip install pytest pyyaml
make check
```

`make check` runs `pytest` on `tests/`, `evidence/verify_trace.py`, and `eval/run_cases.py`. That path does not clone sister repos and does not call a model provider. On this machine it finishes in seconds, inside a 15-minute fresh-clone budget. `python3 evidence/verify_trace.py` alone uses the standard library.

`driver run` without `--stub` reaches `scripts/lib/wrappers.py`. Those call sites use author-machine Windows paths. A missing script returns exit code 1 and does not start a subprocess.

## What CI covers

| Workflow | Runs | Does not run |
|---|---|---|
| `checks.yml` | `make check` on Python 3.10 and 3.12 | sister repos, provider network, a paper |
| `ci.yml` | `ci/run_tests.py --full` (coverage of `tests/test_state.py`, `tests/test_provider_check.py`, `tests/test_verify_action_pin.py`, plus `tests/smoke_test.py` for placeholder S1–S3) and `evidence/verify_trace.py` | the rest of `tests/`, sister repos, a paper |
| `pr-checks.yml` | `make check` | sister repos, a paper |

Nightly, release, packaging, publish, sast, scan-alarms, and the Windows smoke workflow are not part of this offline evidence claim.

`tests/test_driver.py` and `tests/test_scan_alarms_imports.py` raise `AssertionError` from `check()`, so a failed case fails `pytest` instead of only printing `FAIL`.

Do not cite a frozen test count from an old README. The count is whatever `pytest` prints on this commit.

## Sister repos and author-machine paths

`scripts/lib/wrappers.py` and `SKILL.md` name `F:\Research\...` and `C:\Users\Administrator\...`. Those are the author's Windows paths. This repository does not install them. The stub trace reads those literals from source and forces a missing stand-in; `sister_repos_invoked` in the trace is false.

`reports/TEST_REPORT_2026-07-10.md` is an author-machine archive. It is not recomputed by `make check`.

## License

MIT. See [LICENSE](LICENSE).
