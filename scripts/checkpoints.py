"""checkpoints.py — checkpoint gating logic
两种 checkpoint（来自 light-orchestrator SKILL.md §3）：
- 决策点 🧑：需要用户选分支才能继续（idea 选哪个 / outline 怎么定 / 投哪个 venue）
- 确认点 ✓：机器先验证出报告，用户看过确认后推进（S5 review ≥ 7.8 等）

driver 在每个 stage 完成后、进入下一个之前，按 CHECKPOINT_PLAN 决定是否需要
用户签字。state.json 里的 user_signatures 记录所有 checkpoint 的签字状态。

不在此模块做实际校验——校验由各 stage 自己负责（v24_review.py 读 v24_final 分等）。
本模块只负责：
1. 定义每个 stage 的 checkpoint 类型
2. 判定当前 stage 是否需要 gate
3. 写 user_signatures

2026-07-10 增：per-stage budget rules（STAGE_BUDGET_RULES）。
作用：state.mark_failed 调用 check_budget 判定是否超额，超额时报警（不自动降级）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# 兼容两种调用方式
import sys
from pathlib import Path as _P
_THIS = _P(__file__).resolve().parent
if str(_THIS) not in sys.path:
    sys.path.insert(0, str(_THIS))

from state import DriverState


@dataclass
class CheckpointSpec:
    stage: str
    kind: str  # "decision" or "confirm"
    title: str
    prompt: str           # 给用户看的提示
    gate_field: str       # state.user_signatures 里的 key


# 每个 stage 完成后的 checkpoint 规格
# decision: 用户必须拍板才能进下一 stage
# confirm : 机器出报告，用户 ack 后才能进
# 2026-07-10 新增：per-stage budget 上限。state.mark_failed 用此判定报警。
# 策略：只报警不自动降级；用户可手工改 state.budget["max_reruns_per_stage"][stage] 覆盖。
STAGE_BUDGET_RULES = {
    "s1_idea": {
        "max": 2,
        "reason_hint": "idea novelty 持续低,可能方向错;考虑换 idea 或拓宽调研",
    },
    "s2_lit": {
        "max": 3,
        "reason_hint": "refs.bib 多次校验失败;检查检索 query 或必引清单",
    },
    "s3_outline": {
        "max": 2,
        "reason_hint": "outline 反复重做;可能 idea 与 paper 类型不匹配",
    },
    "s4_draft": {
        "max": 3,
        "reason_hint": "draft 写不出;可能实验数据不够或图表没就绪",
    },
    "s5_review": {
        "max": 4,
        "reason_hint": "v2.4 反复 ≤ 7.8;强烈建议回到 S1 重评 idea 或换 paper 类型",
    },
    "s6_submit": {
        "max": 1,
        "reason_hint": "submit 检查不通过;基本是 TMLR compliance 问题,不是 idea 问题",
    },
}


# 每个 stage 完成后的 checkpoint 规格
# decision: 用户必须拍板才能进下一 stage
# confirm : 机器出报告，用户 ack 后才能进
CHECKPOINT_PLAN = {
    "s1_idea": CheckpointSpec(
        stage="s1_idea",
        kind="decision",
        title="S1 决策点：idea 拍板",
        prompt=(
            "已生成 idea_canvas.md（含 3-5 个候选 + 与已有 26 篇工作的关系 + TMLR 适用性）。\n"
            "请选一个 idea（或修改 / 重跑 S1）。\n"
            "默认通过阈值：idea-evaluator 5 维 ≥ 7.0/10。\n"
            "签字命令：driver sign --target-dir <T> --checkpoint s1_idea"
        ),
        gate_field="s1_idea",
    ),
    "s2_lit": CheckpointSpec(
        stage="s2_lit",
        kind="confirm",
        title="S2 确认点：refs.bib 校验通过",
        prompt=(
            "已生成 refs.bib（≥30 条）+ lit_review.md（含 must-cite deltas）。\n"
            "请过引用清单 + 撞库结果。\n"
            "签字命令：driver sign --target-dir <T> --checkpoint s2_lit"
        ),
        gate_field="s2_lit",
    ),
    "s3_outline": CheckpointSpec(
        stage="s3_outline",
        kind="decision",
        title="S3 决策点：outline + 实验设计拍板",
        prompt=(
            "已生成 outline.md（8 章）+ topic_report.md + experiment_design.md。\n"
            "请确认大纲 + 实验设计（决定 S4 走向）。\n"
            "签字命令：driver sign --target-dir <T> --checkpoint s3_outline"
        ),
        gate_field="s3_outline",
    ),
    "s4_draft": CheckpointSpec(
        stage="s4_draft",
        kind="confirm",
        title="S4 确认点：每章完成后过一遍",
        prompt=(
            "main.tex + chapters/*.tex + figures/ 已生成。\n"
            "轻量确认（不是逐字审），看 structure / figure / 公式编号 OK 就签字。\n"
            "签字命令：driver sign --target-dir <T> --checkpoint s4_draft"
        ),
        gate_field="s4_draft",
    ),
    "s5_review": CheckpointSpec(
        stage="s5_review",
        kind="confirm",
        title="S5 质量门：v2.4 ≥ 7.8 才能进 S6",
        prompt=(
            "v2.4 review 报告 + 4 persona 分数 + CRITICAL/MAJOR/MINOR 已生成。\n"
            "质量门阈值：v24_final ≥ 7.8（来自 TMLR_COMPARISON_REPORT 前 10% 标准）。\n"
            "未达标会自动触发 S4→S5 循环。\n"
            "签字命令：driver sign --target-dir <T> --checkpoint s5_review"
        ),
        gate_field="s5_review",
    ),
    "s6_submit": CheckpointSpec(
        stage="s6_submit",
        kind="decision",
        title="S6 决策点：用户最终签字（机器不能替代）",
        prompt=(
            "arxiv ZIP + cover_letter.md + submit/checklist.md + supplementary PDF 已就绪。\n"
            "**这里必须你亲自签字**——机器不能替代 moral taste。\n"
            "签字命令：driver sign --target-dir <T> --checkpoint s6_submit"
        ),
        gate_field="s6_submit",
    ),
}


def get_checkpoint(stage: str) -> Optional[CheckpointSpec]:
    return CHECKPOINT_PLAN.get(stage)


def is_signed(state: DriverState, stage: str) -> bool:
    """检查某个 stage 的 checkpoint 是否已签字。"""
    spec = get_checkpoint(stage)
    if spec is None:
        return True  # 没定义 checkpoint = 默认通过
    return bool(state.user_signatures.get(spec.gate_field, False))


def require_sign(state: DriverState, stage: str, target_dir) -> None:
    """raise SystemExit 当 stage 未签字。"""
    if is_signed(state, stage):
        return
    spec = get_checkpoint(stage)
    print("=" * 60)
    print(f"  CHECKPOINT BLOCKED: {spec.title}")
    print("=" * 60)
    print(spec.prompt)
    print("=" * 60)
    raise SystemExit(2)  # 退出码 2 = 需要用户介入


def sign(state: DriverState, stage: str, target_dir, note: str = "") -> None:
    """签一个 checkpoint。"""
    spec = get_checkpoint(stage)
    if spec is None:
        print(f"WARN: stage {stage} has no checkpoint spec; signing anyway")
    state.user_signatures[spec.gate_field if spec else stage] = True
    if note:
        state.user_signatures[f"{spec.gate_field if spec else stage}_note"] = note
    from state import save_state
    save_state(state, target_dir)
    print(f"signed: {stage}")


def list_pending(state: DriverState) -> list:
    """列出所有未签字的 checkpoint。"""
    pending = []
    for stage, spec in CHECKPOINT_PLAN.items():
        if not is_signed(state, stage):
            pending.append((stage, spec.kind, spec.title))
    return pending