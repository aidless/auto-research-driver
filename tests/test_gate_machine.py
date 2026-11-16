"""Offline evidence for the S1–S6 gate state machine.

These tests use stub stages. They do not call sister repositories, and they
do not record a paper score, a submission, or an acceptance.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import driver  # noqa: E402
from evidence.gate_trace import TRACE_PATH, build_trace  # noqa: E402
from lib import wrappers as W  # noqa: E402
import provider_check  # noqa: E402
from state import (  # noqa: E402
    STAGES_ORDER,
    load_state,
    mark_completed,
    mark_failed,
    progress_snapshot,
    rollback_progress,
    state_path,
)


def test_rollback_progress_restores_fields_and_keeps_run_count():
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        state = load_state(td)
        mark_completed(state, "s1_idea", td)
        snap = progress_snapshot(state)
        state.artifacts["extra"] = "should-not-survive"
        state.completed.append("s2_lit")
        state.stage = "s3_outline"
        mark_failed(state, "s2_lit", "boom", td)
        rollback_progress(state, snap, "s2_lit", td)
        again = load_state(td)
    assert again.stage == "s2_lit"
    assert again.completed == ["s1_idea"]
    assert "extra" not in again.artifacts
    assert again.run_count == 1
    assert again.last_error is not None and "boom" in again.last_error
    assert again.next_action == "rolled_back_before_s2_lit"


def test_budget_alarm_does_not_block_the_next_run():
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        args = _run_args(td, "s1_idea", "s5_review", skip_checkpoints=True)
        assert driver.cmd_run(args) == 0
        os.environ["ARD_FAIL_STAGE"] = "s6_submit"
        try:
            failed = driver.cmd_run(_run_args(td, "s6_submit", "s6_submit", skip_checkpoints=True))
        finally:
            os.environ.pop("ARD_FAIL_STAGE", None)
        mid = load_state(td)
        assert failed != 0
        assert any(a["stage"] == "s6_submit" and "ALARM [budget]" in a["msg"] for a in mid.alarms)
        assert "s6_submit" not in mid.completed
        again = driver.cmd_run(_run_args(td, "s6_submit", "s6_submit", skip_checkpoints=True))
        final = load_state(td)
    assert again == 0
    assert "s6_submit" in final.completed
    assert any(a["stage"] == "s6_submit" for a in final.alarms)


def test_missing_sister_workspace_does_not_start_a_process():
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        missing = td / "missing_run_pipeline.py"
        with mock.patch.object(W, "PIPELINE_RUN", missing), \
             mock.patch.object(subprocess, "run") as run:
            rc = W.run_full_pipeline(td, from_stage="s4")
    assert rc == 1
    assert run.call_count == 0
    assert "F:\\Research\\tmlr_pipeline" in str(W.PIPELINE_ROOT)


def test_skip_checkpoints_is_a_human_sign_bypass():
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        rc = driver.cmd_run(_run_args(td, "s1_idea", "s6_submit", skip_checkpoints=True, idea="bypass"))
        state = load_state(td)
    assert rc == 0
    assert state.completed == STAGES_ORDER
    assert state.user_signatures == {} or not any(state.user_signatures.get(s) for s in STAGES_ORDER)


def test_provider_misconfig_aborts_before_a_stage():
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        missing = td / "no-config.yaml"
        args = _run_args(td, "s1_idea", "s1_idea", skip_checkpoints=True)
        args.skip_provider_check = False
        args.config = missing
        with mock.patch.object(driver, "_run_stage") as run_stage:
            rc = driver.cmd_run(args)
    assert rc == 1
    assert run_stage.call_count == 0
    assert provider_check.check_provider(missing) == 1


def test_corrupt_state_is_backed_up_and_not_treated_as_success():
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        path = state_path(td)
        path.write_text("{not json", encoding="utf-8")
        fresh = load_state(td)
        backup = path.with_suffix(".json.corrupt")
        assert fresh.last_error is not None and fresh.last_error.startswith("corrupt:")
        assert fresh.stage == "s1_idea"
        assert fresh.completed == []
        assert backup.is_file()


def test_stub_trace_records_gates_without_a_paper_outcome():
    with tempfile.TemporaryDirectory() as d:
        trace = build_trace(Path(d))
    assert trace["schema"] == "gate-trace-v1"
    assert trace["sister_repos_invoked"] is False
    assert trace["paper_outcome"] is None
    assert trace["v24_final"] is None
    assert trace["budget_alarm_stops_run"] is False
    assert trace["final_completed"] == list(STAGES_ORDER)
    blocked = [e["stage"] for e in trace["events"] if e["event"] == "checkpoint_blocked"]
    signed = [e["stage"] for e in trace["events"] if e["event"] == "signed"]
    assert blocked == list(STAGES_ORDER)
    assert signed == list(STAGES_ORDER)
    assert trace["rollback"]["failed_stage_in_completed"] is False
    assert trace["rollback"]["run_count"] == 1
    assert trace["budget_alarm"]["stops_run"] is False
    assert trace["budget_alarm"]["second_rc"] == 0
    assert trace["missing_sister"]["subprocess_calls"] == 0
    assert trace["missing_sister"]["rc"] == 1
    assert trace["sign_bypass"]["signatures_set"] is False
    assert trace["provider_misconfig"]["stage_was_called"] is False
    assert trace["corrupt_recovery"]["last_error_prefix"] == "corrupt"


def test_committed_trace_matches_a_fresh_recompute():
    assert TRACE_PATH.is_file(), "committed trace missing; run evidence/verify_trace.py --write"
    with tempfile.TemporaryDirectory() as d:
        got = build_trace(Path(d))
    expected = json.loads(TRACE_PATH.read_text(encoding="utf-8"))
    assert got == expected


def _run_args(td: Path, start: str, end: str, *, skip_checkpoints: bool, idea: str | None = "stub"):
    return driver.argparse.Namespace(
        target_dir=td,
        idea=idea,
        arxiv=None,
        idea_auto=False,
        from_stage=start,
        to_stage=end,
        review_mode="simulator",
        skip_checkpoints=skip_checkpoints,
        skip_provider_check=True,
        force=False,
        stub=True,
        config=None,
    )
