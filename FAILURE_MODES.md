# Failure modes

These are observed behaviors of this checkout, each tied to a test in `tests/test_gate_machine.py` and to a section of `evidence/s1_s6_stub_trace.json`. None of them is a paper outcome.

## 1. Missing sister workspace

`scripts/lib/wrappers.py` points at author-machine paths (`F:\Research\tmlr_pipeline`, `C:\Users\Administrator\.mavis\...`). If the script file is absent, the wrapper prints `FAIL` and returns 1. It does not start a subprocess and it does not install the missing repo.

The trace does not probe the author's real disk. It points `PIPELINE_RUN` at a stand-in path that is not there. `missing_sister.rc` is 1 and `missing_sister.subprocess_calls` is 0.

`--stub` writes placeholder files instead of calling those paths. The placeholder text says the sister repo was not called.

## 2. Provider misconfiguration

`driver run` calls `provider_check.check_provider` before any stage unless `--skip-provider-check` is set. A missing config file returns 1, and no stage function runs. The default config path is the author-machine file `~/.mavis/config.yaml` (the `provider-check` subcommand's default in `driver.py` is `C:\Users\Administrator\.mavis\config.yaml`). A fresh clone should expect `FAIL`, not a green provider.

The trace points `--config` at a file that does not exist. `provider_misconfig.stage_was_called` is false.

## 3. Budget alarm does not stop a run

Caps are S1=2, S2=3, S3=2, S4=3, S5=4, S6=1 (`checkpoints.STAGE_BUDGET_RULES`). `mark_failed` appends `state.alarms` and prints `ALARM [budget]` when `run_count` reaches the cap. It does not change `stage` by itself, does not raise, and does not block a later `driver run`.

`cmd_run` returns the stage's own non-zero code when that attempt fails. That return is the stage failure, not an alarm halt. The trace fails S6 once (cap 1), keeps the alarm, then runs S6 again successfully. `budget_alarm.stops_run` is false.

GitHub's About text currently says the alerts "stop a run before overspending". That sentence is false for this code. This file cannot edit the About text. Suggested replacement, for a person with repo admin:

> Offline gate state machine for six named TMLR stages: checkpoints, state rollback, and rerun alarms that do not stop a later run. No paper outcome is measured in this repo.

## 4. State corruption

`load_state` on invalid JSON renames the file to `state.json.corrupt`, returns a fresh `DriverState` (`stage=s1_idea`, empty `completed`), and sets `last_error` to a `corrupt:` prefix. It does not merge recoverable fields out of the broken file. The backup is the only copy of the old bytes. A reader can mistake the fresh state for "nothing has ever run".

## 5. Human sign bypass

Every stage has a decision or confirm gate. `driver run` pauses with exit code 0 when the gate is unsigned. `--skip-checkpoints` marks stages completed and continues with `user_signatures` unset. That flag is a real bypass, not a default. The trace's `sign_bypass.signatures_set` is false while all six stages are completed.

Rollback does not remove that bypass. Rollback restores `stage`, `completed`, `artifacts`, `scores`, and `user_signatures` to the snapshot taken at the start of the failed stage, then saves. It keeps `run_count`, `last_error`, `rerun_history`, and `alarms`. It does not delete files the stage already wrote under the target directory.

## Gaps that keep this off an A

1. GitHub About text, observed 2026-11-16: "An agent skill (not a library) orchestrating TMLR paper stages S1–S6 with budget alerts that stop a run before overspending." The stop/overspending clause disagrees with section 3. It is not in git.
2. `SKILL.md` is still a long specification. The banner says it is unmeasured. A reader who skips the banner can still read stage tables as results.
3. `reports/TEST_REPORT_2026-07-10.md` records an author-machine S5 note. `make check` does not recompute it, and this repo does not treat it as a submission or an acceptance.
4. `ci.yml` does not run the whole `tests/` tree. `checks.yml` and `pr-checks.yml` do, via `make check`.
