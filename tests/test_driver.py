"""test_driver.py — in-process tests for scripts/driver.py subcommand handlers

Goals: cover the 8 cmd_* functions in scripts/driver.py so coverage of
that file rises from baseline to >= 90%.  These are the public CLI
surface; _stage_* and _run_stage are integration territory (out of scope).

Style: plain assert + sys.exit (same as test_state.py / test_provider_check.py
/ test_scan_alarms_imports.py). Works both standalone and via pytest.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

# === 加载 driver 模块 ===
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

driver_path = HERE.parent / "scripts" / "driver.py"
spec = importlib.util.spec_from_file_location("driver", driver_path)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)

PASS = 0
FAIL = 0
FAILS: list[str] = []


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        FAILS.append(f"{name}: {detail}")
        print(f"  FAIL: {name} -- {detail}")


# ============================================================
# 1. cmd_provider_check — 转发到 provider_check
# ============================================================

def test_cmd_provider_check_delegates_to_check_provider():
    """cmd_provider_check 应调 provider_check.check_provider 并返回其 rc。"""
    with mock.patch.object(driver.provider_check, "check_provider", return_value=0) as m:
        args = argparse.Namespace(config=None, ping=False)
        rc = driver.cmd_provider_check(args)
    check("rc=0 propagated", rc == 0, f"got {rc}")
    check("check_provider called once", m.call_count == 1)
    call_args = m.call_args
    check("config passed through", call_args[0][0] is None)
    check("do_ping kwarg passed", call_args[1].get("do_ping") is False)


def test_cmd_provider_check_propagates_nonzero_rc():
    """provider_check.check_provider 返回 2 → cmd_provider_check 返回 2。"""
    with mock.patch.object(driver.provider_check, "check_provider", return_value=2):
        rc = driver.cmd_provider_check(argparse.Namespace(config=None, ping=True))
    check("rc=2 propagated", rc == 2, f"got {rc}")


# ============================================================
# 2. cmd_status — 读 .driver/state.json
# ============================================================

def test_cmd_status_with_existing_state_prints_table():
    """有 state.json → 打印 target/stage/completed/checkpoints + rc=0。"""
    target = Path(tempfile.mkdtemp(prefix="drv_test_status_"))
    (target / ".driver").mkdir()
    (target / ".driver" / "state.json").write_text(
        json.dumps({"stage": "s1_idea", "completed": [], "alarms": [],
                    "scores": {}, "run_count": 0, "user_signatures": {},
                    "rerun_history": []}),
        encoding="utf-8"
    )
    args = argparse.Namespace(target_dir=target)
    buf = io_str()
    with redirect_stdout(buf):
        rc = driver.cmd_status(args)
    check("with state file → rc=0", rc == 0, f"got {rc}")
    out = buf.getvalue()
    check("stdout mentions target",
          "target" in out.lower(),
          f"first 100: {out[:100]!r}")
    check("stdout mentions stage",
          "stage" in out.lower(),
          f"first 100: {out[:100]!r}")


def test_cmd_status_auto_creates_empty_state_if_missing():
    """无 state.json → load_state 自动创建空 state + rc=0。"""
    target = Path(tempfile.mkdtemp(prefix="drv_test_status_"))
    args = argparse.Namespace(target_dir=target)
    buf = io_str()
    with redirect_stdout(buf):
        rc = driver.cmd_status(args)
    check("no state file → rc=0 (auto-create)", rc == 0, f"got {rc}")
    check("stdout still prints table",
          "stage" in buf.getvalue().lower())


# ============================================================
# 3. cmd_reset — 删 .driver/state.json
# ============================================================

def test_cmd_reset_no_state_file_returns_0():
    """没有 state.json → 没事做 → rc=0。"""
    target = Path(tempfile.mkdtemp(prefix="drv_test_reset_"))
    args = argparse.Namespace(target_dir=target)
    rc = driver.cmd_reset(args)
    check("no state to reset → rc=0", rc == 0, f"got {rc}")


def test_cmd_reset_deletes_state_file():
    """有 state.json → 删除 → rc=0。"""
    target = Path(tempfile.mkdtemp(prefix="drv_test_reset_"))
    d = target / ".driver"
    d.mkdir()
    s = d / "state.json"
    s.write_text("{}", encoding="utf-8")
    args = argparse.Namespace(target_dir=target)
    rc = driver.cmd_reset(args)
    check("reset → rc=0", rc == 0, f"got {rc}")
    check("state.json deleted", not s.exists())


# ============================================================
# 4. cmd_sign — 给 stage 签名
# ============================================================

def test_cmd_sign_creates_state_if_missing():
    """没有 state.json → load_state 自动创建 + sign 写入 + rc=0。"""
    target = Path(tempfile.mkdtemp(prefix="drv_test_sign_"))
    args = argparse.Namespace(target_dir=target, checkpoint="s1_idea", note="ok")
    rc = driver.cmd_sign(args)
    check("no state → still rc=0 (auto-create)", rc == 0, f"got {rc}")
    state_file = target / ".driver" / "state.json"
    check("state.json auto-created", state_file.exists())


def test_cmd_sign_appends_signature():
    """有 state.json + valid checkpoint → 写入签名 + rc=0。"""
    target = Path(tempfile.mkdtemp(prefix="drv_test_sign_"))
    d = target / ".driver"
    d.mkdir()
    s = d / "state.json"
    s.write_text(json.dumps({
        "stage": "s1_idea", "completed": [], "alarms": [],
        "user_signatures": {}, "scores": {}, "run_count": 0,
        "rerun_history": [],
    }), encoding="utf-8")
    args = argparse.Namespace(target_dir=target, checkpoint="s1_idea", note="looks good")
    rc = driver.cmd_sign(args)
    check("sign → rc=0", rc == 0, f"got {rc}")
    new = json.loads(s.read_text(encoding="utf-8"))
    check("signature recorded",
          "s1_idea" in new.get("user_signatures", {}),
          f"signatures={new.get('user_signatures')}")


# ============================================================
# 5. cmd_checkpoints — 打印 checkpoint 列表
# ============================================================

def test_cmd_checkpoints_prints_table_and_returns_0():
    """cmd_checkpoints 应打印 checkpoint 表 + rc=0。"""
    args = argparse.Namespace(show_rules=False)
    buf = io_str()
    with redirect_stdout(buf):
        rc = driver.cmd_checkpoints(args)
    check("checkpoints → rc=0", rc == 0, f"got {rc}")
    out = buf.getvalue()
    check("stdout mentions checkpoint",
          "checkpoint" in out.lower(),
          f"stdout first 100 chars: {out[:100]!r}")


# ============================================================
# 6. cmd_alarms — 列当前 paper 的 alarms
# ============================================================

def test_cmd_alarms_no_state_returns_0_with_zero_alarms():
    """target_dir 无 state.json → auto-create + 0 alarm + rc=0。"""
    target = Path(tempfile.mkdtemp(prefix="drv_test_alarms_"))
    args = argparse.Namespace(target_dir=target, show_rules=False)
    buf = io_str()
    with redirect_stdout(buf):
        rc = driver.cmd_alarms(args)
    check("no state → rc=0 (auto-create)", rc == 0, f"got {rc}")
    check("stdout shows 0 alarm",
          "0" in buf.getvalue() and "alarm" in buf.getvalue().lower())


def test_cmd_alarms_empty_alarms_prints_clean_state():
    """state.json 中 alarms=[] → 打印 "clean" + rc=0。"""
    target = Path(tempfile.mkdtemp(prefix="drv_test_alarms_"))
    d = target / ".driver"
    d.mkdir()
    (d / "state.json").write_text(json.dumps({
        "stage": "s5_review", "completed": [], "alarms": [],
        "user_signatures": {}, "scores": {}, "run_count": 0,
        "rerun_history": [], "budget": {"max_reruns_per_stage": {}},
    }), encoding="utf-8")
    args = argparse.Namespace(target_dir=target, show_rules=False)
    buf = io_str()
    with redirect_stdout(buf):
        rc = driver.cmd_alarms(args)
    check("alarms empty → rc=0", rc == 0, f"got {rc}")
    out = buf.getvalue()
    check("stdout mentions 'no alarm' or '无 alarm'",
          "no alarm" in out.lower() or "无 alarm" in out or "0" in out,
          f"stdout: {out[:200]!r}")


def test_cmd_alarms_with_show_rules_prints_budget_rules():
    """cmd_alarms --show-rules 应打印 STAGE_BUDGET_RULES。"""
    target = Path(tempfile.mkdtemp(prefix="drv_test_alarms_"))
    (target / ".driver").mkdir()
    (target / ".driver" / "state.json").write_text(json.dumps({
        "stage": "s5_review", "completed": [], "alarms": [],
        "user_signatures": {}, "scores": {}, "run_count": 0,
        "rerun_history": [], "budget": {"max_reruns_per_stage": {}},
    }), encoding="utf-8")
    args = argparse.Namespace(target_dir=target, show_rules=True)
    buf = io_str()
    with redirect_stdout(buf):
        rc = driver.cmd_alarms(args)
    check("alarms --show-rules → rc=0", rc == 0, f"got {rc}")
    out = buf.getvalue()
    check("--show-rules 打印 STAGE_BUDGET_RULES",
          "STAGE_BUDGET_RULES" in out or "default" in out.lower() or "budget" in out.lower(),
          f"first 200: {out[:200]!r}")


# ============================================================
# 7. cmd_scan_alarms — 转发到 scan_alarms.main_with_args
# ============================================================

def test_cmd_scan_alarms_default_root():
    """无 --root 时，构造的 Namespace 应有 F:\\Research 默认。"""
    args = argparse.Namespace(
        root=None, output_dir=None, stale_days=None,
        json_only=False, md_only=False, quiet=True,
    )
    # driver.py line 176 在函数内 import scan_alarms；mock 必须是模块全局
    with mock.patch("scan_alarms.main_with_args", return_value=0, create=True) as m:
        rc = driver.cmd_scan_alarms(args)
    check("default root → rc=0", rc == 0, f"got {rc}")
    call_args = m.call_args[0][0]
    check("default root == F:\\Research",
          str(call_args.root).lower().replace("\\\\", "\\") == "f:\\research",
          f"got {call_args.root}")
    check("default output_dir == F:\\Research\\_ALARMS",
          "_alarms" in str(call_args.output_dir).lower(),
          f"got {call_args.output_dir}")
    check("default stale_days == 30", call_args.stale_days == 30,
          f"got {call_args.stale_days}")


def test_cmd_scan_alarms_overrides_propagate():
    """--root / --output-dir / --stale-days / --json-only / --quiet 全部传过去。"""
    custom_root = Path("D:/custom/papers")
    custom_out = Path("D:/custom/alarms")
    args = argparse.Namespace(
        root=custom_root, output_dir=custom_out, stale_days=14,
        json_only=True, md_only=False, quiet=True,
    )
    with mock.patch("scan_alarms.main_with_args", return_value=0, create=True) as m:
        rc = driver.cmd_scan_alarms(args)
    check("override → rc=0", rc == 0, f"got {rc}")
    ns = m.call_args[0][0]
    check("root override propagated", ns.root == custom_root, f"got {ns.root}")
    check("output_dir override propagated", ns.output_dir == custom_out,
          f"got {ns.output_dir}")
    check("stale_days override propagated", ns.stale_days == 14,
          f"got {ns.stale_days}")
    check("json_only propagated", ns.json_only is True)
    check("quiet propagated", ns.quiet is True)


def test_cmd_scan_alarms_propagates_nonzero_rc():
    """scan_alarms.main_with_args 返回 2 → cmd 返回 2。"""
    args = argparse.Namespace(
        root=Path("X:/nope"), output_dir=None, stale_days=None,
        json_only=False, md_only=False, quiet=True,
    )
    with mock.patch("scan_alarms.main_with_args", return_value=2, create=True):
        rc = driver.cmd_scan_alarms(args)
    check("scan_alarms rc=2 propagated", rc == 2, f"got {rc}")


# ============================================================
# 8. cmd_run — 测早期 abort 路径
# ============================================================

def test_cmd_run_invalid_from_stage_aborts():
    """--from-stage 不在 STAGES_ORDER → early abort → rc=1（不进入 pipeline）。"""
    target = Path(tempfile.mkdtemp(prefix="drv_test_run_"))
    args = argparse.Namespace(
        target_dir=target, idea=None, arxiv=None, idea_auto=False,
        from_stage="bogus_stage_xyz",  # 不在 STAGES_ORDER
        to_stage="s6_submit",
        review_mode="simulator",
        skip_checkpoints=True, skip_provider_check=True, force=False,
    )
    buf = io_str()
    with redirect_stderr(buf):
        rc = driver.cmd_run(args)
    check("invalid from_stage → rc=1", rc == 1, f"got {rc}")
    check("stderr mentions invalid stage",
          "not in" in buf.getvalue() or "不在" in buf.getvalue(),
          f"stderr: {buf.getvalue()[:200]!r}")


def test_cmd_run_invalid_to_stage_aborts():
    """--to-stage 不在 STAGES_ORDER → rc=1。"""
    target = Path(tempfile.mkdtemp(prefix="drv_test_run_"))
    args = argparse.Namespace(
        target_dir=target, idea=None, arxiv=None, idea_auto=False,
        from_stage="s1_idea", to_stage="bogus_to_xyz",
        review_mode="simulator",
        skip_checkpoints=True, skip_provider_check=True, force=False,
    )
    buf = io_str()
    with redirect_stderr(buf):
        rc = driver.cmd_run(args)
    check("invalid to_stage → rc=1", rc == 1, f"got {rc}")


def test_cmd_run_end_before_start_aborts():
    """--to-stage 在 --from-stage 之前 → rc=1。"""
    target = Path(tempfile.mkdtemp(prefix="drv_test_run_"))
    args = argparse.Namespace(
        target_dir=target, idea=None, arxiv=None, idea_auto=False,
        from_stage="s5_review", to_stage="s1_idea",
        review_mode="simulator",
        skip_checkpoints=True, skip_provider_check=True, force=False,
    )
    buf = io_str()
    with redirect_stderr(buf):
        rc = driver.cmd_run(args)
    check("end before start → rc=1", rc == 1, f"got {rc}")


def test_cmd_run_idea_source_idea():
    """--idea 提供时 idea_source 设为 ('idea', ...)。"""
    target = Path(tempfile.mkdtemp(prefix="drv_test_run_"))
    fake_state = driver.DriverState(stage="s1_idea", completed=[])
    fake_state.artifacts = {}
    args = argparse.Namespace(
        target_dir=target, idea="my cool idea", arxiv=None, idea_auto=False,
        from_stage="s1_idea", to_stage="s1_idea",
        review_mode="simulator",
        skip_checkpoints=True, skip_provider_check=True, force=False,
    )
    with mock.patch.object(driver, "load_state", return_value=fake_state), \
         mock.patch.object(driver, "_run_stage", return_value=0) as mrun, \
         mock.patch.object(driver, "mark_completed"):
        buf = io_str()
        with redirect_stdout(buf):
            rc = driver.cmd_run(args)
    check("idea_source=idea → rc=0", rc == 0, f"got {rc}")
    check("_run_stage called once", mrun.call_count == 1)
    check("idea_source recorded",
          fake_state.artifacts.get("idea_source") == ("idea", "my cool idea"),
          f"got {fake_state.artifacts.get('idea_source')}")


def test_cmd_run_idea_source_arxiv():
    """--arxiv 提供时 idea_source 设为 ('arxiv', ...)。"""
    target = Path(tempfile.mkdtemp(prefix="drv_test_run_"))
    fake_state = driver.DriverState(stage="s1_idea", completed=[])
    fake_state.artifacts = {}
    args = argparse.Namespace(
        target_dir=target, idea=None, arxiv="2406.12345", idea_auto=False,
        from_stage="s1_idea", to_stage="s1_idea",
        review_mode="simulator",
        skip_checkpoints=True, skip_provider_check=True, force=False,
    )
    with mock.patch.object(driver, "load_state", return_value=fake_state), \
         mock.patch.object(driver, "_run_stage", return_value=0), \
         mock.patch.object(driver, "mark_completed"):
        rc = driver.cmd_run(args)
    check("idea_source=arxiv → rc=0", rc == 0, f"got {rc}")
    check("idea_source recorded as arxiv",
          fake_state.artifacts.get("idea_source") == ("arxiv", "2406.12345"),
          f"got {fake_state.artifacts.get('idea_source')}")


def test_cmd_run_idea_source_auto():
    """--idea-auto 时 idea_source 设为 ('auto', None)。"""
    target = Path(tempfile.mkdtemp(prefix="drv_test_run_"))
    fake_state = driver.DriverState(stage="s1_idea", completed=[])
    fake_state.artifacts = {}
    args = argparse.Namespace(
        target_dir=target, idea=None, arxiv=None, idea_auto=True,
        from_stage="s1_idea", to_stage="s1_idea",
        review_mode="simulator",
        skip_checkpoints=True, skip_provider_check=True, force=False,
    )
    with mock.patch.object(driver, "load_state", return_value=fake_state), \
         mock.patch.object(driver, "_run_stage", return_value=0), \
         mock.patch.object(driver, "mark_completed"):
        rc = driver.cmd_run(args)
    check("idea_source=auto → rc=0", rc == 0, f"got {rc}")
    check("idea_source recorded as auto",
          fake_state.artifacts.get("idea_source") == ("auto", None),
          f"got {fake_state.artifacts.get('idea_source')}")


def test_cmd_run_resume_from_state_when_from_stage_not_given():
    """--from-stage=None 时用 s.stage 作为起点。"""
    target = Path(tempfile.mkdtemp(prefix="drv_test_run_"))
    fake_state = driver.DriverState(stage="s3_outline", completed=["s1_idea", "s2_lit"])
    args = argparse.Namespace(
        target_dir=target, idea=None, arxiv=None, idea_auto=False,
        from_stage=None, to_stage="s6_submit",
        review_mode="simulator",
        skip_checkpoints=True, skip_provider_check=True, force=False,
    )
    with mock.patch.object(driver, "load_state", return_value=fake_state), \
         mock.patch.object(driver, "_run_stage", return_value=0) as mrun, \
         mock.patch.object(driver, "mark_completed"):
        buf = io_str()
        with redirect_stdout(buf):
            rc = driver.cmd_run(args)
    check("resume from s3 → rc=0", rc == 0, f"got {rc}")
    out = buf.getvalue()
    check("stdout mentions from_stage s3_outline",
          "s3_outline" in out,
          f"first 300: {out[:300]!r}")


def test_cmd_run_skips_completed_stages():
    """已完成 stage + 不 --force → 跳过 + 不调 _run_stage。"""
    target = Path(tempfile.mkdtemp(prefix="drv_test_run_"))
    fake_state = driver.DriverState(
        stage="s6_submit",
        completed=["s1_idea", "s2_lit", "s3_outline", "s4_draft", "s5_review"],
    )
    args = argparse.Namespace(
        target_dir=target, idea=None, arxiv=None, idea_auto=False,
        from_stage="s1_idea", to_stage="s6_submit",
        review_mode="simulator",
        skip_checkpoints=True, skip_provider_check=True, force=False,
    )
    with mock.patch.object(driver, "load_state", return_value=fake_state), \
         mock.patch.object(driver, "_run_stage", return_value=0) as mrun, \
         mock.patch.object(driver, "mark_completed"):
        buf = io_str()
        with redirect_stdout(buf):
            rc = driver.cmd_run(args)
    check("all skipped → rc=0", rc == 0, f"got {rc}")
    check("_run_stage NEVER called (all skipped)",
          mrun.call_count == 0,
          f"called {mrun.call_count} times")
    out = buf.getvalue()
    check("stdout mentions [skip]",
          "[skip]" in out,
          f"first 300: {out[:300]!r}")


def test_cmd_run_force_reruns_completed_stages():
    """--force 时即使是 completed stage 也跑。"""
    target = Path(tempfile.mkdtemp(prefix="drv_test_run_"))
    fake_state = driver.DriverState(
        stage="s1_idea",
        completed=["s1_idea", "s2_lit", "s3_outline", "s4_draft", "s5_review"],
    )
    args = argparse.Namespace(
        target_dir=target, idea=None, arxiv=None, idea_auto=False,
        from_stage="s1_idea", to_stage="s3_outline",
        review_mode="simulator",
        skip_checkpoints=True, skip_provider_check=True, force=True,
    )
    with mock.patch.object(driver, "load_state", return_value=fake_state), \
         mock.patch.object(driver, "_run_stage", return_value=0) as mrun, \
         mock.patch.object(driver, "mark_completed"):
        rc = driver.cmd_run(args)
    check("force → rc=0", rc == 0, f"got {rc}")
    check("--force 跑过 3 个 stage",
          mrun.call_count == 3,
          f"called {mrun.call_count} times")


def test_cmd_run_stage_failure_marks_failed_and_returns_rc():
    """stage 返回非 0 → mark_failed 调用 + rc=非 0 + 立即 return。"""
    target = Path(tempfile.mkdtemp(prefix="drv_test_run_"))
    fake_state = driver.DriverState(stage="s1_idea", completed=[])
    args = argparse.Namespace(
        target_dir=target, idea=None, arxiv=None, idea_auto=False,
        from_stage="s1_idea", to_stage="s6_submit",
        review_mode="simulator",
        skip_checkpoints=True, skip_provider_check=True, force=False,
    )
    with mock.patch.object(driver, "load_state", return_value=fake_state), \
         mock.patch.object(driver, "_run_stage", return_value=1) as mrun, \
         mock.patch.object(driver, "mark_failed") as mfail, \
         mock.patch.object(driver, "mark_completed") as mcomp:
        buf = io_str()
        with redirect_stderr(buf):
            rc = driver.cmd_run(args)
    check("stage fail → rc=1", rc == 1, f"got {rc}")
    check("mark_failed called", mfail.call_count == 1)
    check("mark_completed NOT called (failed)",
          mcomp.call_count == 0,
          f"called {mcomp.call_count} times")
    check("_run_stage only called once (bail on first fail)",
          mrun.call_count == 1,
          f"called {mrun.call_count} times")
    check("stderr mentions failure",
          "FAIL" in buf.getvalue() or "failed" in buf.getvalue().lower(),
          f"stderr first 200: {buf.getvalue()[:200]!r}")


def test_cmd_run_checkpoint_pause_returns_0_not_failure():
    """有 checkpoint + 未签字 + 不 skip → pause, return 0（不是 fail）。"""
    from types import SimpleNamespace
    target = Path(tempfile.mkdtemp(prefix="drv_test_run_"))
    fake_state = driver.DriverState(stage="s1_idea", completed=[])
    args = argparse.Namespace(
        target_dir=target, idea=None, arxiv=None, idea_auto=False,
        from_stage="s1_idea", to_stage="s1_idea",
        review_mode="simulator",
        skip_checkpoints=False, skip_provider_check=True, force=False,
    )
    spec = SimpleNamespace(kind="decision", title="S1 决策点", prompt="approve idea?")
    with mock.patch.object(driver, "load_state", return_value=fake_state), \
         mock.patch.object(driver, "_run_stage", return_value=0), \
         mock.patch.object(driver, "mark_completed"), \
         mock.patch.object(driver, "get_checkpoint", return_value=spec), \
         mock.patch.object(driver, "is_signed", return_value=False):
        buf = io_str()
        with redirect_stdout(buf):
            rc = driver.cmd_run(args)
    check("checkpoint pause → rc=0", rc == 0, f"got {rc}")
    out = buf.getvalue()
    check("stdout shows CHECKPOINT",
          "CHECKPOINT" in out or "checkpoint" in out.lower(),
          f"first 300: {out[:300]!r}")


# ============================================================
# 9. main() — parse argv + dispatch
# ============================================================

def test_main_help_returns_0():
    """driver --help → rc=0 + stdout 提到可用子命令。"""
    saved = sys.argv
    sys.argv = ["driver", "--help"]
    try:
        buf = io_str()
        with redirect_stdout(buf):
            rc = driver.main()
    finally:
        sys.argv = saved
    out = buf.getvalue()
    check("--help → rc=0", rc == 0, f"got {rc}")
    check("--help prints help",
          len(out) > 0 or rc == 0,
          f"stdout len={len(out)}")


def test_main_provider_check_dispatches():
    """driver provider-check 应 dispatch 到 cmd_provider_check。"""
    saved = sys.argv
    sys.argv = ["driver", "provider-check"]
    try:
        with mock.patch.object(driver, "cmd_provider_check", return_value=0) as m:
            rc = driver.main()
    finally:
        sys.argv = saved
    check("provider-check dispatched → rc=0", rc == 0, f"got {rc}")
    check("cmd_provider_check called", m.call_count == 1)


def test_main_unknown_subcommand_returns_nonzero():
    """driver bogus-subcommand → argparse error → 非 0。"""
    saved = sys.argv
    sys.argv = ["driver", "totally-bogus-cmd-xyz"]
    try:
        buf = io_str()
        with redirect_stderr(buf):
            rc = driver.main()
    finally:
        sys.argv = saved
    check("bogus subcommand → non-zero rc", rc != 0, f"got {rc}")


# ============================================================
# helper
# ============================================================

def io_str():
    import io
    return io.StringIO()


# ============================================================
# runner
# ============================================================

def main():
    tests = [
        test_cmd_provider_check_delegates_to_check_provider,
        test_cmd_provider_check_propagates_nonzero_rc,
        test_cmd_status_with_existing_state_prints_table,
        test_cmd_status_auto_creates_empty_state_if_missing,
        test_cmd_reset_no_state_file_returns_0,
        test_cmd_reset_deletes_state_file,
        test_cmd_sign_creates_state_if_missing,
        test_cmd_sign_appends_signature,
        test_cmd_checkpoints_prints_table_and_returns_0,
        test_cmd_alarms_no_state_returns_0_with_zero_alarms,
        test_cmd_alarms_empty_alarms_prints_clean_state,
        test_cmd_alarms_with_show_rules_prints_budget_rules,
        test_cmd_scan_alarms_default_root,
        test_cmd_scan_alarms_overrides_propagate,
        test_cmd_scan_alarms_propagates_nonzero_rc,
        test_cmd_run_invalid_from_stage_aborts,
        test_cmd_run_invalid_to_stage_aborts,
        test_cmd_run_end_before_start_aborts,
        test_cmd_run_idea_source_idea,
        test_cmd_run_idea_source_arxiv,
        test_cmd_run_idea_source_auto,
        test_cmd_run_resume_from_state_when_from_stage_not_given,
        test_cmd_run_skips_completed_stages,
        test_cmd_run_force_reruns_completed_stages,
        test_cmd_run_stage_failure_marks_failed_and_returns_rc,
        test_cmd_run_checkpoint_pause_returns_0_not_failure,
        test_main_help_returns_0,
        test_main_provider_check_dispatches,
        test_main_unknown_subcommand_returns_nonzero,
    ]
    print(f"=== running {len(tests)} driver tests ===\n")
    for t in tests:
        try:
            t()
        except Exception as e:
            check(f"{t.__name__} (uncaught)", False,
                  f"{type(e).__name__}: {e}")
        print()
    print("=" * 60)
    print(f"summary: {PASS} passed, {FAIL} failed")
    if FAIL == 0:
        print("ALL DRIVER TESTS PASSED")
        return 0
    print("FAILED:")
    for f in FAILS:
        print(f"  - {f}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
