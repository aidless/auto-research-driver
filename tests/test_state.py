"""test_state.py — state.py 单元测试

不引入 pytest 框架（driver 保持零外部 deps）；用 plain assert + sys.exit。
跑法：py -3 tests/test_state.py

覆盖目标：state.py 行/分支 ≥ 85%（coverage run --branch）
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

# 把 scripts/ 加到 sys.path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

from state import (  # noqa: E402
    DriverState,
    load_state,
    save_state,
    mark_completed,
    mark_failed,
    state_path,
    _next_stage,
    main as state_main,
)


# ---------- 基础功能（6 个，原有） ----------

def test_load_empty():
    """state.json 不存在时新建空状态。"""
    with tempfile.TemporaryDirectory() as td:
        s = load_state(Path(td))
        assert s.stage == "s1_idea"
        assert s.completed == []
        assert s.run_count == 0
        print("PASS: test_load_empty")


def test_save_load_roundtrip():
    """写完能读回。"""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        s = load_state(td)
        s.completed = ["s1_idea", "s2_lit"]
        s.scores = {"v24_final": 7.85}
        s.user_signatures = {"s1_idea": True, "s2_lit": True}
        save_state(s, td)

        s2 = load_state(td)
        assert s2.completed == ["s1_idea", "s2_lit"]
        assert s2.scores == {"v24_final": 7.85}
        assert s2.user_signatures == {"s1_idea": True, "s2_lit": True}
        print("PASS: test_save_load_roundtrip")


def test_mark_completed_advances_stage():
    """mark_completed 后 stage 自动推进。"""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        s = load_state(td)
        mark_completed(s, "s1_idea", td)
        assert "s1_idea" in s.completed
        assert s.stage == "s2_lit"
        assert s.run_count == 0
        print("PASS: test_mark_completed_advances_stage")


def test_mark_failed_increments_run_count():
    """mark_failed 后 run_count +1 + last_error 记录。"""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        s = load_state(td)
        mark_failed(s, "s5_review", "OOM", td)
        assert s.run_count == 1
        assert "s5_review" in s.last_error
        assert "OOM" in s.last_error
        print("PASS: test_mark_failed_increments_run_count")


def test_corrupt_state_recovery():
    """state.json 损坏时备份 + 重建，不抛异常。"""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        sp = state_path(td)
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text("{ this is not valid json", encoding="utf-8")

        s = load_state(td)  # 不应抛
        assert s.stage == "s1_idea"
        assert s.last_error and "corrupt" in s.last_error
        # 备份文件应存在
        bak = sp.with_suffix(".json.corrupt")
        assert bak.exists()
        print("PASS: test_corrupt_state_recovery")


def test_atomic_write_no_leftover_tmp():
    """save_state 不留 .tmp 残留。"""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        s = load_state(td)
        save_state(s, td)
        tmp = state_path(td).with_suffix(".json.tmp")
        assert not tmp.exists(), f"tmp leftover: {tmp}"
        print("PASS: test_atomic_write_no_leftover_tmp")


# ---------- v1.1 补测（4 个，凑 ≥85% 覆盖率） ----------

def test_mark_completed_idempotent():
    """重复 mark_completed 同一 stage 不应重复 append。"""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        s = load_state(td)
        mark_completed(s, "s1_idea", td)
        mark_completed(s, "s1_idea", td)  # 第二次幂等
        mark_completed(s, "s1_idea", td)  # 第三次幂等
        assert s.completed.count("s1_idea") == 1
        assert s.stage == "s2_lit"  # 仍是 s2_lit，不会越界
        print("PASS: test_mark_completed_idempotent")


def test_mark_failed_alarm_at_3():
    """run_count ≥ 3 时 mark_failed 触发 ALARM 输出。"""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        s = load_state(td)
        buf = io.StringIO()
        with redirect_stderr(buf):
            mark_failed(s, "s5_review", "OOM", td)       # run_count=1
            mark_failed(s, "s5_review", "OOM", td)       # run_count=2
            mark_failed(s, "s5_review", "OOM", td)       # run_count=3 → ALARM
        err_out = buf.getvalue()
        assert s.run_count == 3
        assert "ALARM" in err_out, f"expected ALARM in stderr, got: {err_out!r}"
        assert "s5_review" in err_out
        print("PASS: test_mark_failed_alarm_at_3")


def test_next_stage_at_end():
    """_next_stage: s6_submit 是末尾 → 保持不变；未知 stage 名 → 原样返回。"""
    # 末尾
    assert _next_stage("s6_submit") == "s6_submit"
    # 中间连续推进
    assert _next_stage("s2_lit") == "s3_outline"
    assert _next_stage("s5_review") == "s6_submit"
    # 未知 stage 名 → ValueError 捕获 → 原样返回
    assert _next_stage("bogus_stage") == "bogus_stage"
    print("PASS: test_next_stage_at_end")


def test_state_cli_show_reset_mark_complete():
    """CLI 子模式：show / reset / mark-complete 直接调 main() 入口。"""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)

        # 1) show on empty dir → 返回空状态 JSON
        sys.argv = ["state.py", "show", "--target-dir", str(td)]
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = state_main()
        assert rc == 0
        out = buf.getvalue()
        assert '"stage": "s1_idea"' in out
        assert '"completed": []' in out

        # 2) mark-complete s1_idea
        sys.argv = ["state.py", "mark-complete", "s1_idea", "--target-dir", str(td)]
        rc = state_main()
        assert rc == 0
        assert state_path(td).exists()

        # 3) reset
        sys.argv = ["state.py", "reset", "--target-dir", str(td)]
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = state_main()
        assert rc == 0
        assert not state_path(td).exists()
        assert "reset: removed" in buf.getvalue()

        # 4) mark-complete 缺 stage 参数 → 报错返回 1
        sys.argv = ["state.py", "mark-complete", "--target-dir", str(td)]
        buf_err = io.StringIO()
        with redirect_stderr(buf_err):
            rc = state_main()
        assert rc == 1
        assert "requires <stage>" in buf_err.getvalue()

    print("PASS: test_state_cli_show_reset_mark_complete")


# ---------- 入口 ----------

def test_new_fields_have_defaults():
    """v1.1 增字段: budget / rerun_history / alarms 默认值正确。"""
    s = DriverState()
    assert "max_reruns_per_stage" in s.budget
    assert s.budget["max_reruns_per_stage"]["s5_review"] == 4
    assert s.rerun_history == []
    assert s.alarms == []


def test_mark_failed_records_rerun_history():
    """mark_failed 应该在 rerun_history 追加一条记录。"""
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        s = DriverState(stage="s5_review")
        mark_failed(s, "s5_review", "v24=7.2<7.8", td)
        assert len(s.rerun_history) == 1
        rec = s.rerun_history[0]
        assert rec["stage"] == "s5_review"
        assert rec["reason"] == "v24=7.2<7.8"
        assert "t" in rec
        # t 字段是 ISO 时间戳,起码长度 19
        assert len(rec["t"]) >= 19


def test_mark_failed_emits_budget_alarm_when_exceeded():
    """s5_review 默认预算=4,budget=2 时第 2 次 mark_failed 应触发 budget ALARM。"""
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        s = DriverState(stage="s5_review")
        # 先把 budget 调小到 2,加速测试
        s.budget["max_reruns_per_stage"]["s5_review"] = 2
        # 第 1 次失败 run_count=1 < 预算 2,不报警
        mark_failed(s, "s5_review", "fail0", td)
        assert s.alarms == [], f"should have no alarms yet, got {s.alarms}"
        # 第 2 次失败 run_count=2 ≥ 预算 2,应报警
        mark_failed(s, "s5_review", "fail1-budget-exceed", td)
        assert len(s.alarms) == 1, f"expected 1 alarm, got {len(s.alarms)}"
        alarm = s.alarms[0]
        assert alarm["stage"] == "s5_review"
        assert "ALARM" in alarm["msg"] and "预算 2" in alarm["msg"]
        # alarm 必须落盘:重新 load 应该看得到
        s2 = load_state(td)
        assert len(s2.alarms) == 1
        # 验证 rerun_history 两条都有
        assert len(s2.rerun_history) == 2


def test_check_budget_returns_none_when_within_budget():
    """run_count < max 时 check_budget 应返回 None(不报警)。"""
    from state import check_budget
    s = DriverState(stage="s5_review")
    s.run_count = 1
    s.budget["max_reruns_per_stage"]["s5_review"] = 4
    assert check_budget("s5_review", s) is None


def test_check_budget_returns_message_when_exceeded():
    """run_count >= max 时 check_budget 返回报警消息。"""
    from state import check_budget
    s = DriverState(stage="s5_review")
    s.run_count = 4
    s.budget["max_reruns_per_stage"]["s5_review"] = 4
    msg = check_budget("s5_review", s)
    assert msg is not None
    assert "ALARM" in msg
    assert "s5_review" in msg


def test_check_budget_respects_state_override():
    """state.budget 里的 per-stage 值应覆盖默认 STAGE_BUDGET_RULES。"""
    from state import check_budget
    s = DriverState(stage="s5_review")
    s.run_count = 10  # 远超默认 4
    s.budget["max_reruns_per_stage"]["s5_review"] = 50  # 但用户放宽到 50
    assert check_budget("s5_review", s) is None, "custom budget 50 should suppress alarm"


def test_get_stage_reruns_counts_correctly():
    """get_stage_reruns 应正确统计 rerun_history 中某 stage 的次数。"""
    from state import get_stage_reruns
    s = DriverState()
    s.rerun_history = [
        {"stage": "s5_review", "t": "t1"},
        {"stage": "s5_review", "t": "t2"},
        {"stage": "s4_draft",   "t": "t3"},
        {"stage": "s5_review", "t": "t4"},
    ]
    assert get_stage_reruns(s, "s5_review") == 3
    assert get_stage_reruns(s, "s4_draft") == 1
    assert get_stage_reruns(s, "s1_idea") == 0


def test_rerun_history_capped_at_50():
    """rerun_history 应被截断到 50 条以防无限增长。"""
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        s = DriverState(stage="s5_review")
        # 制造 55 次失败
        for i in range(55):
            mark_failed(s, "s5_review", f"fail{i}", td)
        assert len(s.rerun_history) == 50, f"expected cap at 50, got {len(s.rerun_history)}"
        # 最后一条应是 fail54
        assert s.rerun_history[-1]["reason"] == "fail54"


def main():
    tests = [
        test_load_empty,
        test_save_load_roundtrip,
        test_mark_completed_advances_stage,
        test_mark_failed_increments_run_count,
        test_corrupt_state_recovery,
        test_atomic_write_no_leftover_tmp,
        # v1.1 补测
        test_mark_completed_idempotent,
        test_mark_failed_alarm_at_3,
        test_next_stage_at_end,
        test_state_cli_show_reset_mark_complete,
        # 2026-07-10 新增: per-stage budget + rerun_history + alarms
        test_new_fields_have_defaults,
        test_mark_failed_records_rerun_history,
        test_mark_failed_emits_budget_alarm_when_exceeded,
        test_check_budget_returns_none_when_within_budget,
        test_check_budget_returns_message_when_exceeded,
        test_check_budget_respects_state_override,
        test_get_stage_reruns_counts_correctly,
        test_rerun_history_capped_at_50,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"FAIL: {t.__name__}: {e}", file=sys.stderr)
            failed += 1
        except Exception as e:
            print(f"ERROR: {t.__name__}: {type(e).__name__}: {e}", file=sys.stderr)
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} PASS")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())