"""state.py — driver 状态持久化

负责 <target_dir>/.driver/state.json 的读写。所有 driver 动作（跑 stage、签名
checkpoint、记分）必须先 load_state，再 atomic save（写 tmp + rename + file lock）。

设计原则：
- 单进程不锁；跨进程用 msvcrt.lockf（Windows）/ fcntl.flock（Unix）简单互斥
- atomic write：先写 .tmp，os.replace 原子重命名，避免半写
- schema 用 Pydantic-style dataclass（避免引入 pydantic 依赖）

2026-07-10 增：per-stage budget + rerun_history + alarms（报警与降级策略）。
策略：只报警，不自动降级；并发不限制（由用户手工收敛）。
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# Stage 顺序与 SKILL.md 对齐
STAGES_ORDER = ["s1_idea", "s2_lit", "s3_outline", "s4_draft", "s5_review", "s6_submit"]


# 默认 per-stage budget（per paper）。用户可在 state.budget["max_reruns_per_stage"] 中覆盖。
DEFAULT_STAGE_BUDGET = {
    "s1_idea":    2,
    "s2_lit":     3,
    "s3_outline": 2,
    "s4_draft":   3,
    "s5_review":  4,   # 关键:idea 不够 top-10% 时的告警点
    "s6_submit":  1,
}


@dataclass
class DriverState:
    """driver 完整状态。落盘到 <target_dir>/.driver/state.json。"""
    stage: str = "s1_idea"              # 当前阶段
    completed: list = field(default_factory=list)   # 已完成阶段
    artifacts: dict = field(default_factory=dict)    # 阶段产物路径
    scores: dict = field(default_factory=dict)       # v24_final / v24_raw / tmlr_compliance 等
    next_action: str = ""                # 下一动作描述
    user_signatures: dict = field(default_factory=dict)  # 哪些 checkpoint 已签字
    last_error: Optional[str] = None    # 最近一次失败原因
    run_count: int = 0                  # 同阶段重试次数（>3 报警）
    created_at: str = ""                # ISO 时间戳
    updated_at: str = ""

    # 2026-07-10 新增字段（向后兼容：旧 state 缺这些字段时 from_dict 会忽略）
    budget: dict = field(default_factory=lambda: {
        "max_reruns_per_stage": dict(DEFAULT_STAGE_BUDGET),
    })
    rerun_history: list = field(default_factory=list)
    # 形如: [{"stage":"s5_review","t":"2026-07-10T11:30:00+0800",
    #         "score":7.2,"reason":"v24<7.8"}]
    alarms: list = field(default_factory=list)
    # 形如: [{"stage":"s5_review","t":"...","msg":"rerun 4 次 ≥ 预算 4;..."}]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DriverState":
        # 兼容老 state（缺字段时用 default）
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def state_path(target_dir: Path) -> Path:
    """state.json 路径：<target_dir>/.driver/state.json"""
    p = Path(target_dir) / ".driver" / "state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_state(target_dir: Path) -> DriverState:
    """读 state.json；不存在则新建一个空状态。"""
    p = state_path(target_dir)
    if not p.exists():
        now = _now_iso()
        return DriverState(created_at=now, updated_at=now)
    try:
        return DriverState.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        # state.json 损坏时不要静默——备份后重建
        bak = p.with_suffix(".json.corrupt")
        p.rename(bak)
        print(f"WARN: state.json corrupt, backed up to {bak.name}; starting fresh", file=sys.stderr)
        now = _now_iso()
        return DriverState(created_at=now, updated_at=now, last_error=f"corrupt:{e}")


def save_state(state: DriverState, target_dir: Path) -> None:
    """atomic write：写 .tmp → fsync → os.replace。无外部锁（单 driver 调用足够）。"""
    state.updated_at = _now_iso()
    p = state_path(target_dir)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    # best-effort fsync
    try:
        if hasattr(os, "fdopen"):
            fd = os.open(tmp, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    except OSError:
        pass  # Windows 上 tmp 文件可能仍被句柄持有，忽略
    os.replace(tmp, p)


def mark_completed(state: DriverState, stage: str, target_dir: Path) -> None:
    """标记 stage 完成（幂等）。"""
    if stage not in state.completed:
        state.completed.append(stage)
    state.stage = _next_stage(stage)
    state.run_count = 0  # 重置重试计数
    state.last_error = None
    save_state(state, target_dir)


def mark_failed(state: DriverState, stage: str, error: str, target_dir: Path) -> None:
    """记录失败原因 + run_count +1。run_count ≥ 3 时报警。
    2026-07-10: 追加 per-stage budget 检查，超额也报警（不自动降级）。
    """
    state.run_count += 1
    state.last_error = f"[{stage}] {error}"
    state.next_action = f"rerun_{stage}_then_resume"
    # 记录 rerun 历史（最多保留 50 条，避免无限增长）
    state.rerun_history.append({
        "stage": stage,
        "t": _now_iso(),
        "score": state.scores.get("v24_final"),
        "reason": error[:200],
    })
    if len(state.rerun_history) > 50:
        state.rerun_history = state.rerun_history[-50:]
    save_state(state, target_dir)
    if state.run_count >= 3:
        print(
            f"ALARM: stage {stage} 已失败 {state.run_count} 次；"
            f"可能原因：idea novelty 不够 / 实验数据 bug / review 评分尺子漂移。"
            f"建议回到 S1 重新评估。",
            file=sys.stderr,
        )
    # NEW: per-stage budget check（延迟导入避免循环依赖）
    alarm_msg = check_budget(stage, state)
    if alarm_msg:
        state.alarms.append({"stage": stage, "t": _now_iso(), "msg": alarm_msg})
        # 保留最近 20 条 alarm
        if len(state.alarms) > 20:
            state.alarms = state.alarms[-20:]
        save_state(state, target_dir)
        print(alarm_msg, file=sys.stderr)
        print(
            "  → 不自动降级；用户决定是 resurrect / 调 budget / 改 idea。",
            file=sys.stderr,
        )


def check_budget(stage: str, state: DriverState) -> Optional[str]:
    """per-stage budget 检查。返回 None = OK；返回 str = 报警消息。

    注：本函数不抛异常、不修改 state，只产生 ALARM 字符串。
    由 mark_failed 调用，把 ALARM 写进 state.alarms。
    """
    # 延迟导入避免循环依赖（checkpoints 反向 import state）
    try:
        from checkpoints import STAGE_BUDGET_RULES
    except Exception:
        return None
    rule = STAGE_BUDGET_RULES.get(stage)
    if rule is None:
        return None
    # 优先用 state 自定义 budget，否则用 rule["max"]
    per_stage = state.budget.get("max_reruns_per_stage", {}) if state.budget else {}
    max_reruns = per_stage.get(stage, rule["max"])
    if state.run_count >= max_reruns:
        return (
            f"ALARM [budget]: {stage} 已失败 {state.run_count} 次 ≥ 预算 {max_reruns}；"
            f"{rule['reason_hint']}"
        )
    return None


def list_alarms(state: DriverState) -> list:
    """列出 state 当前的报警条目。"""
    return list(state.alarms)


def get_stage_reruns(state: DriverState, stage: str) -> int:
    """统计某个 stage 的 rerun 次数（来自 rerun_history）。"""
    return sum(1 for r in state.rerun_history if r.get("stage") == stage)


def _next_stage(current: str) -> str:
    """返回下一个阶段名。已到最后则保持。"""
    try:
        idx = STAGES_ORDER.index(current)
    except ValueError:
        return current
    if idx + 1 < len(STAGES_ORDER):
        return STAGES_ORDER[idx + 1]
    return current


def _now_iso() -> str:
    """ISO 8601 时间戳，UTC+8 本地时间。"""
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


def main() -> int:
    """CLI: state show / reset / mark-complete <stage>"""
    import argparse
    ap = argparse.ArgumentParser(description="driver state CLI")
    ap.add_argument("action", choices=["show", "reset", "mark-complete"])
    ap.add_argument("stage", nargs="?", default=None)
    ap.add_argument("--target-dir", type=Path, required=True)
    args = ap.parse_args()

    if args.action == "show":
        s = load_state(args.target_dir)
        print(json.dumps(s.to_dict(), ensure_ascii=False, indent=2))
    elif args.action == "reset":
        p = state_path(args.target_dir)
        if p.exists():
            p.unlink()
        print(f"reset: removed {p}")
    elif args.action == "mark-complete":
        if not args.stage:
            print("ERROR: mark-complete requires <stage>", file=sys.stderr)
            return 1
        s = load_state(args.target_dir)
        mark_completed(s, args.stage, args.target_dir)
        print(f"marked {args.stage} complete; current stage = {s.stage}")
    return 0


if __name__ == "__main__":
    sys.exit(main())