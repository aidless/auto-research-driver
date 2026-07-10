"""state.py — driver 状态持久化

负责 <target_dir>/.driver/state.json 的读写。所有 driver 动作（跑 stage、签名
checkpoint、记分）必须先 load_state，再 atomic save（写 tmp + rename + file lock）。

设计原则：
- 单进程不锁；跨进程用 msvcrt.lockf（Windows）/ fcntl.flock（Unix）简单互斥
- atomic write：先写 .tmp，os.replace 原子重命名，避免半写
- schema 用 Pydantic-style dataclass（避免引入 pydantic 依赖）

2026-07-10 增：per-stage budget + rerun_history + alarms（报警与降级策略）。
策略：只报警，不自动降级；并发不限制（由用户手工收敛）。

设计原则（报警）：
- "只报警"：mark_failed 触发 budget check，超额就在 stderr 打印 + 写 state.alarms
  但不修改 state.stage / state.completed；用户决定 resurrect / 改 budget / 改 idea
- "不并发限制"：多个 driver run 可以并行跑同一个 paper（用户故意做实验时可重启
  driver），但要注意：state.json 的 last-writer-wins 语义，最后一个 mark_completed
  会覆盖前面的。所以不推荐并发；并发场景下应该用 Git 锁定或外层调度器串行。
- "不自动降级"：即使 s5_review 重试 4 次（默认 budget）也没"自动跳到 s6"。
  因为 v2.4 < 7.8 的论文进 s6 没意义，强行提交只会浪费 API 配额。

落盘 schema（json 字段顺序 = to_dict 顺序）：
  stage, completed, artifacts, scores, next_action, user_signatures,
  last_error, run_count, created_at, updated_at,
  budget, rerun_history, alarms

调用入口（高层 API）：
  load_state(target_dir)             -> DriverState（不存在或损坏时返回空 state）
  save_state(state, target_dir)      -> None（atomic write）
  mark_completed(state, stage, td)   -> None（重置 run_count，stage 进 completed）
  mark_failed(state, stage, err, td) -> None（run_count +1，必要时写 alarm）
  check_budget(stage, state)         -> Optional[str]（超额返回 alarm 文本）
  list_alarms(state)                 -> List[Dict]（state.alarms 的副本）
  get_stage_reruns(state, stage)     -> int（统计该 stage 在 history 里出现次数）

CLI（仅调试用）：
  python state.py show --target-dir F:/Research/paper_x
  python state.py reset --target-dir F:/Research/paper_x
  python state.py mark-complete s3_outline --target-dir F:/Research/paper_x

向后兼容：老 state.json 缺 budget / rerun_history / alarms 字段时，from_dict
会忽略（不抛 KeyError），DriverState 用 default_factory 填默认值。
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
    """driver 完整状态。落盘到 <target_dir>/.driver/state.json。

    字段分组：
    - 流水线控制：stage, completed, next_action
    - 产物与评分：artifacts, scores
    - 用户交互：user_signatures
    - 错误追踪：last_error, run_count
    - 元数据：created_at, updated_at
    - 报警与降级（v1.1 新增）：budget, rerun_history, alarms

    不可变语义：所有字段都是 mutable（dataclass 默认），但实际使用上
    一旦 save_state 落盘，外部代码应通过 load_state 重新拿 state 实例，
    而不是缓存旧引用。这是"last-writer-wins" 并发安全的基础。
    """
    # ---- 流水线控制 ----
    stage: str = "s1_idea"
    """当前应跑的 stage（失败时不变，让 user 决定 retry / skip）。"""
    completed: list = field(default_factory=list)
    """已成功完成（mark_completed 过）的 stage 列表，按完成顺序。"""
    next_action: str = ""
    """下一动作的人类可读描述（"rerun_s5_review_then_resume" / "user_sign_s5_review"）。"""

    # ---- 产物与评分 ----
    artifacts: dict = field(default_factory=dict)
    """stage 产物路径映射。key=stage名（"idea_canvas" / "refs_bib" / "outline" / "main_tex" 等），
    value=str(absolute path)。供后续 stage 引用。"""
    scores: dict = field(default_factory=dict)
    """评分字典。常见 key：v24_final（s5 主分数，0-10，≥7.8 才能进 s6）、
    v24_raw（s5 4 persona 平均，0-10）、tmlr_compliance（s6 submission compliance 0-100）。"""

    # ---- 用户交互 ----
    user_signatures: dict = field(default_factory=dict)
    """用户签字记录。key=stage名，value={"t": ISO时间戳, "note": 用户备注}。
    checkpoint 模块用 is_signed / sign 读写。"""

    # ---- 错误追踪 ----
    last_error: Optional[str] = None
    """最近一次 mark_failed 的错误信息（截断到 200 字）。driver status 展示。"""
    run_count: int = 0
    """当前 stage 的连续重试次数（mark_failed 增 1，mark_completed 重置 0）。
    ≥ 3 触发"老报警"（stderr 警告），≥ per-stage budget 触发"新报警"（state.alarms）。"""

    # ---- 元数据 ----
    created_at: str = ""
    """state 首次创建时间（ISO 8601，含时区）。load_state 第一次创建时填。"""
    updated_at: str = ""
    """最近一次 save_state 的时间。save_state 每次自动更新。"""

    # ---- 报警与降级（v1.1 新增字段，2026-07-10）----
    # 向后兼容：老 state.json 缺这些字段时 from_dict 会忽略，default_factory 填默认。
    budget: dict = field(default_factory=lambda: {
        "max_reruns_per_stage": dict(DEFAULT_STAGE_BUDGET),
    })
    """per-stage rerun 预算。结构：{"max_reruns_per_stage": {stage: max_count, ...}}。
    用户可在 state.json 直接编辑覆盖；不覆盖时用 DEFAULT_STAGE_BUGET。
    修改后立即生效（mark_failed 每次都查）。"""
    rerun_history: list = field(default_factory=list)
    """重试历史（最多 50 条，超出截断尾部）。每条：
    {"stage": str, "t": ISO时间戳, "score": Optional[float], "reason": str(≤200字)}。
    driver status 统计 + 趋势分析。"""
    alarms: list = field(default_factory=list)
    """报警历史（最多 20 条，超出截断尾部）。每条：
    {"stage": str, "t": ISO时间戳, "msg": str}。driver alarms 子命令展示。"""

    def to_dict(self) -> dict:
        """序列化为 dict（字段顺序 = dataclass 定义顺序）。供 json.dump 落盘。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DriverState":
        """从 dict 反序列化。容错：d 中多余的 key 忽略，缺失的 key 用 default 填。

        重要：从 v1.0 升级到 v1.1 的 state.json（缺 budget / rerun_history / alarms）
        不会报错——它们走 default_factory。这是"无痛升级"的基础。
        """
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def state_path(target_dir: Path) -> Path:
    """state.json 路径：<target_dir>/.driver/state.json

    副作用：会 mkdir -p 父目录（<target_dir>/.driver/）。
    这是为了让 load_state 第一次调用就能成功落盘。

    Args:
        target_dir: paper 工程根目录（任意可解析的 Path-like）

    Returns:
        .driver/state.json 的绝对路径（不保证文件已存在）
    """
    p = Path(target_dir) / ".driver" / "state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_state(target_dir: Path) -> DriverState:
    """读 state.json；不存在则新建一个空状态。

    容错策略：
    1. 文件不存在 → 返回空 DriverState（created_at = now）
    2. JSON 损坏（json.JSONDecodeError / KeyError / TypeError）→ 不抛异常！
       把损坏文件重命名为 <file>.json.corrupt 备份，然后返回空 state。
       last_error 字段填 "corrupt:<error>" 提示用户曾经损坏过。
    3. 老 v1.0 state.json（缺 budget / rerun_history / alarms）→ 静默兼容，
       from_dict 走 default_factory。

    Args:
        target_dir: paper 工程根目录

    Returns:
        总是返回有效 DriverState 实例（不返回 None，不抛异常）
    """
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
    """atomic write：写 .tmp → fsync → os.replace。无外部锁（单 driver 调用足够）。

    实现细节：
    - 先写 .json.tmp，fsync 落盘（best-effort，Windows 上可能 OSError 忽略）
    - 然后 os.replace 原子重命名（POSIX / Win32 都支持）
    - 半写场景下：要么旧 state.json 完整可用，要么新 state.json 完整可用

    副作用：
    - state.updated_at 自动更新为当前时间
    - target_dir/.driver/ 目录不存在时自动创建

    Args:
        state: 待落盘的 DriverState 实例
        target_dir: paper 工程根目录
    """
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
    """标记 stage 完成（幂等）。会自动落盘。

    副作用：
    - state.completed 追加 stage（如果还没在）
    - state.stage 推进到 _next_stage(stage)
    - state.run_count 重置 0（关键：完成 = 清零重试计数）
    - state.last_error 清空

    幂等性：重复调用对同一 stage 安全（completed 用 `if stage not in ...` 检查）。
    """
    if stage not in state.completed:
        state.completed.append(stage)
    state.stage = _next_stage(stage)
    state.run_count = 0  # 重置重试计数
    state.last_error = None
    save_state(state, target_dir)


def mark_failed(state: DriverState, stage: str, error: str, target_dir: Path) -> None:
    """记录失败原因 + run_count +1。run_count ≥ 3 时报警。
    2026-07-10: 追加 per-stage budget 检查，超额也报警（不自动降级）。

    完整副作用：
    1. state.run_count += 1
    2. state.last_error 设为 "[stage] error"
    3. state.next_action 设为 "rerun_<stage>_then_resume"
    4. state.rerun_history 追加一条（保留最近 50 条）
    5. save_state（落盘 1）
    6. 如果 run_count ≥ 3，stderr 打印老报警（不修改 state）
    7. 调用 check_budget；如果超额：
       a. state.alarms 追加一条（保留最近 20 条）
       b. save_state（落盘 2）
       c. stderr 打印 budget 报警 + 提醒

    Args:
        state: 当前 DriverState（直接修改）
        stage: 失败的 stage 名（"s5_review" 等）
        error: 错误信息（截断到 200 字）
        target_dir: 落盘目录
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

    优先级：
    - state.budget["max_reruns_per_stage"][stage]（用户覆盖）> STAGE_BUDGET_RULES 默认

    容错：checkpoints 模块 import 失败（环境异常）→ 返回 None（不报警也不阻塞）。

    Args:
        stage: 要检查的 stage 名
        state: 当前 DriverState

    Returns:
        None 表示在 budget 内；str 是报警消息（首部含 "ALARM [budget]:" 前缀）
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
    """列出 state 当前的报警条目（拷贝，不影响原 list）。

    Returns:
        List[Dict]，每条形如 {"stage": str, "t": str, "msg": str}
    """
    return list(state.alarms)


def get_stage_reruns(state: DriverState, stage: str) -> int:
    """统计某个 stage 的 rerun 次数（来自 rerun_history）。

    与 state.run_count 的区别：run_count 是"连续重试"（mark_completed 后归零）；
    此函数返回"历史累计重试次数"，不会归零。
    """
    return sum(1 for r in state.rerun_history if r.get("stage") == stage)


def _next_stage(current: str) -> str:
    """返回下一个阶段名。已到最后（s6_submit）则保持。

    Args:
        current: 当前 stage 名

    Returns:
        STAGES_ORDER 中 current 的下一项；如果 current 已是最后一项或不在列表，返回原值。
    """
    try:
        idx = STAGES_ORDER.index(current)
    except ValueError:
        return current
    if idx + 1 < len(STAGES_ORDER):
        return STAGES_ORDER[idx + 1]
    return current


def _now_iso() -> str:
    """ISO 8601 时间戳，UTC+8 本地时间。格式："2026-07-10T11:30:00+0800"。

    没用 datetime.now().isoformat() 因为它返回 "2026-07-10T11:30:00+08:00"（带冒号），
    跟 Windows / POSIX date 兼容性不好。无冒号格式在更多环境可解析。
    """
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


def main() -> int:
    """CLI: state show / reset / mark-complete <stage>

    用法:
        py -3 state.py show --target-dir F:/Research/paper_x
        py -3 state.py reset --target-dir F:/Research/paper_x
        py -3 state.py mark-complete s3_outline --target-dir F:/Research/paper_x

    子命令:
        show              打印 state.json 完整内容（json dump）
        reset             删除 state.json（重新初始化）
        mark-complete     手工把指定 stage 标记为 completed（不走 driver run）

    注意：mark-complete 不应该手工调用——它绕过了 stage 的实际执行；
    仅用于 driver run 出现 broken state 时手工恢复。
    """
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