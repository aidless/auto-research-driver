"""Build a deterministic S1–S6 stub trace.

The trace records gate blocks, signatures, rollback, a budget alarm that does
not stop the next run, a missing sister-repo stand-in, the --skip-checkpoints
bypass, a missing provider config, and corrupt-state recovery.

It does not call sister repositories and it does not record a paper score.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import checkpoints  # noqa: E402
import driver  # noqa: E402
import provider_check  # noqa: E402
from lib import wrappers as W  # noqa: E402
from state import STAGES_ORDER, load_state, state_path  # noqa: E402

TRACE_PATH = Path(__file__).resolve().parent / "s1_s6_stub_trace.json"


def build_trace(root: Path) -> dict:
    """Run the stub scenarios under `root` and return a JSON-ready dict."""
    root = Path(root)
    saved_fail = os.environ.pop("ARD_FAIL_STAGE", None)
    calls = {"n": 0}
    original_run = subprocess.run

    def spy(*args, **kwargs):
        calls["n"] += 1
        return original_run(*args, **kwargs)

    try:
        with mock.patch.object(subprocess, "run", spy):
            trace = _scenarios(root)
        trace["sister_repos_invoked"] = calls["n"] != 0
        trace["subprocess_calls"] = calls["n"]
        trace["budget_alarm_stops_run"] = trace["budget_alarm"]["stops_run"]
        return trace
    finally:
        if saved_fail is not None:
            os.environ["ARD_FAIL_STAGE"] = saved_fail


def _scenarios(root: Path) -> dict:
    walk_dir = root / "walk"
    walk = _walk(walk_dir)
    budget = _budget(root / "budget")
    return {
        "schema": "gate-trace-v1",
        "paper_outcome": None,
        "v24_final": walk["v24_final"],
        "budget_caps": {stage: rule["max"] for stage, rule in checkpoints.STAGE_BUDGET_RULES.items()},
        "events": walk["events"],
        "final_completed": walk["final_completed"],
        "pending_after_signs": walk["pending_after_signs"],
        "stub_markers": walk["stub_markers"],
        "rollback": _rollback(root / "rollback"),
        "budget_alarm": budget,
        "missing_sister": _missing_sister(root / "missing"),
        "sign_bypass": _sign_bypass(root / "bypass"),
        "provider_misconfig": _provider(root / "provider"),
        "corrupt_recovery": _corrupt(root / "corrupt"),
    }


def _walk(td: Path) -> dict:
    td.mkdir(parents=True)
    events = []
    for index, stage in enumerate(STAGES_ORDER):
        rc = driver.cmd_run(_args(
            td, stage, stage,
            skip_checkpoints=False,
            idea="stub-walk" if index == 0 else None,
        ))
        state = load_state(td)
        spec = checkpoints.get_checkpoint(stage)
        if rc != 0:
            raise RuntimeError(f"stub stage {stage} returned {rc}, expected a checkpoint pause")
        if stage not in state.completed:
            raise RuntimeError(f"{stage} was not recorded completed before the gate")
        if checkpoints.is_signed(state, stage):
            raise RuntimeError(f"{stage} was already signed before the human sign")
        events.append({"event": "stage_completed", "stage": stage, "rc": rc})
        events.append({
            "event": "checkpoint_blocked",
            "stage": stage,
            "kind": spec.kind,
        })
        checkpoints.sign(state, stage, td, note="stub-trace")
        events.append({"event": "signed", "stage": stage})
    final = load_state(td)
    review = (td / "reviews" / "STUB_REVIEW.md").read_text(encoding="utf-8")
    checklist = (td / "submit" / "checklist.md").read_text(encoding="utf-8")
    main_tex = (td / "main.tex").read_text(encoding="utf-8")
    return {
        "events": events,
        "final_completed": list(final.completed),
        "pending_after_signs": len(checkpoints.list_pending(final)),
        "v24_final": final.scores.get("v24_final"),
        "stub_markers": {
            "main_tex": main_tex.startswith("% STUB"),
            "review_null_score": "v24_final: null" in review,
            "checklist_not_submitted": "Nothing was submitted." in checklist,
        },
    }


def _rollback(td: Path) -> dict:
    td.mkdir(parents=True)
    first = driver.cmd_run(_args(td, "s1_idea", "s1_idea", skip_checkpoints=False, idea="rollback-demo"))
    os.environ["ARD_FAIL_STAGE"] = "s2_lit"
    try:
        failed = driver.cmd_run(_args(td, "s2_lit", "s2_lit", skip_checkpoints=True, idea=None))
    finally:
        os.environ.pop("ARD_FAIL_STAGE", None)
    state = load_state(td)
    return {
        "first_rc": first,
        "failed_stage": "s2_lit",
        "rc": failed,
        "stage_after": state.stage,
        "completed_after": list(state.completed),
        "failed_stage_in_completed": "s2_lit" in state.completed,
        "run_count": state.run_count,
        "next_action": state.next_action,
        "budget_alarm_count": len(state.alarms),
        "refs_bib_exists": (td / "refs.bib").exists(),
    }


def _budget(td: Path) -> dict:
    td.mkdir(parents=True)
    driver.cmd_run(_args(td, "s1_idea", "s5_review", skip_checkpoints=True, idea="budget-demo"))
    os.environ["ARD_FAIL_STAGE"] = "s6_submit"
    try:
        first_rc = driver.cmd_run(_args(td, "s6_submit", "s6_submit", skip_checkpoints=True, idea=None))
    finally:
        os.environ.pop("ARD_FAIL_STAGE", None)
    mid = load_state(td)
    second_rc = driver.cmd_run(_args(td, "s6_submit", "s6_submit", skip_checkpoints=True, idea=None))
    final = load_state(td)
    alarm = mid.alarms[0] if mid.alarms else {"stage": None, "msg": ""}
    s6_done = "s6_submit" in final.completed
    return {
        "first_rc": first_rc,
        "alarm_stage": alarm.get("stage"),
        "alarm_has_budget_prefix": str(alarm.get("msg", "")).startswith("ALARM [budget]:"),
        "completed_after_first": list(mid.completed),
        "s6_completed_after_first": "s6_submit" in mid.completed,
        "second_rc": second_rc,
        "s6_completed_after_second": s6_done,
        "alarm_count_after_second": len(final.alarms),
        "stops_run": not (second_rc == 0 and s6_done and len(final.alarms) >= 1),
    }


def _missing_sister(td: Path) -> dict:
    td.mkdir(parents=True)
    # Read the source literal. Path joining is OS-specific and must not enter
    # the committed trace.
    source = (ROOT / "scripts" / "lib" / "wrappers.py").read_text(encoding="utf-8")
    missing = td / "missing_run_pipeline.py"
    calls = {"n": 0}

    def boom(*_args, **_kwargs):
        calls["n"] += 1
        raise AssertionError("sister subprocess must not start for a missing script")

    with mock.patch.object(W, "PIPELINE_RUN", missing), mock.patch.object(subprocess, "run", boom):
        rc = W.run_full_pipeline(td, from_stage="s4")
    return {
        "rc": rc,
        "subprocess_calls": calls["n"],
        "author_machine_literal_in_source": (
            "F:\\Research\\tmlr_pipeline" in source
            and "C:\\Users\\Administrator" in source
        ),
        "path_class": "author-machine",
    }


def _sign_bypass(td: Path) -> dict:
    td.mkdir(parents=True)
    rc = driver.cmd_run(_args(td, "s1_idea", "s6_submit", skip_checkpoints=True, idea="bypass"))
    state = load_state(td)
    return {
        "rc": rc,
        "completed": list(state.completed),
        "signatures_set": any(bool(state.user_signatures.get(stage)) for stage in STAGES_ORDER),
        "v24_final": state.scores.get("v24_final"),
    }


def _provider(td: Path) -> dict:
    td.mkdir(parents=True)
    missing = td / "no-config.yaml"
    args = _args(td, "s1_idea", "s1_idea", skip_checkpoints=True, idea="should-not-run")
    args.skip_provider_check = False
    args.config = missing
    rc = driver.cmd_run(args)
    return {
        "rc": rc,
        "stage_was_called": (td / "idea_canvas.md").exists(),
        "completed": list(load_state(td).completed),
        "direct_check_rc": provider_check.check_provider(missing),
    }


def _corrupt(td: Path) -> dict:
    td.mkdir(parents=True)
    path = state_path(td)
    path.write_text("{not json", encoding="utf-8")
    fresh = load_state(td)
    prefix = (fresh.last_error or "").split(":", 1)[0]
    return {
        "last_error_prefix": prefix,
        "backup_exists": path.with_suffix(".json.corrupt").is_file(),
        "stage": fresh.stage,
        "completed_empty": fresh.completed == [],
    }


def _args(td: Path, start: str, end: str, *, skip_checkpoints: bool, idea):
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
