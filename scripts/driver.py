"""driver.py — auto-research-driver 主入口

用法：
  driver run --target-dir F:\\Research\\PAPER5_CONSOLIDATED --from-stage s5
  driver run --idea "..." --idea-auto --target-dir F:\\Research\\new_paper
  driver run --arxiv 2606.16682 --target-dir F:\\Research\\repro
  driver sign --target-dir F:\\Research\\PAPER5_CONSOLIDATED --checkpoint s5_review
  driver status --target-dir ...
  driver reset --target-dir ...
  driver provider-check [--ping]
  driver checkpoints --target-dir ...
  driver alarms --target-dir ... [--show-rules]
  driver scan-alarms [--root F:\\Research] [--stale-days 30] [--quiet]

设计：driver 是 stateful 的薄壳。所有"做什么"由 lib/wrappers.py 调用既有组件。
driver 只负责：(1) provider sanity，(2) state.json 持久化，(3) checkpoint 闸门，
(4) 失败时回滚到上一个 safe stage。

不在这里实现真正的 TMLR 流水线逻辑——那是 tmlr_pipeline.run_pipeline.py 的事。

子命令清单（与 bin/driver.cmd 同步）：
  run              跑流水线主入口（cmd_run）
  status           看 state.json + pending checkpoints（cmd_status）
  reset            清掉 state.json（cmd_reset）
  sign             签一个 checkpoint（cmd_sign）
  checkpoints      列所有 checkpoint 规格（cmd_checkpoints）
  alarms           列 budget 报警 + rerun 历史（cmd_alarms, 2026-07-10 增）
  scan-alarms      跨多 paper 报警扫描（cmd_scan_alarms, 2026-07-10 增）
  provider-check   验证 MiniMax provider 配置（cmd_provider_check）

调度模型：
- driver run 是 sequential 的（按 STAGES_ORDER 顺序跑，每个完成才进下一个）
- checkpoint 是 blocking 的（默认未签字就 pause，--skip-checkpoints 跳过）
- 失败时 pause（return 非零），但 state.run_count 持续累加
- 用户用 driver sign 签字后，再用 driver run 续跑（从 checkpoint stage 重启）

不在这里实现：
- idea brainstorm / evaluator（v1.1+ 才接）
- deep_read / paper-reviewer 自动化（v1.1+ 才接）
- TMLR submission 真投递（S6 只生成 checklist，不真投递）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

# 兼容两种调用方式：
#   1) py -3 scripts/driver.py    (直接当脚本)
#   2) py -m scripts.driver       (当模块)
_THIS = Path(__file__).resolve().parent
if str(_THIS) not in sys.path:
    sys.path.insert(0, str(_THIS))

# 同包内 import（用绝对 import 兼容两种调用方式）
from state import (
    DriverState, STAGES_ORDER, load_state, save_state,
    mark_completed, mark_failed, state_path,
)
from checkpoints import (
    CHECKPOINT_PLAN, get_checkpoint, is_signed, sign, require_sign, list_pending,
)
import provider_check
from lib import wrappers as W


def cmd_provider_check(args) -> int:
    """子命令: provider-check [--ping]

    验证 MiniMax provider 配置（config.yaml + API key）。
    默认是 dry-run（只检查 key 格式），加 --ping 才会真打网关。
    """
    return provider_check.check_provider(args.config, do_ping=args.ping)


def cmd_status(args) -> int:
    """子命令: status --target-dir ...

    打印 state.json 的关键字段 + 列出 pending checkpoint + 报警 + rerun 历史。
    只读，不修改 state。
    """
    from state import list_alarms, get_stage_reruns
    s = load_state(args.target_dir)
    print(f"target      : {args.target_dir}")
    print(f"stage       : {s.stage}")
    print(f"completed   : {s.completed}")
    print(f"run_count   : {s.run_count}")
    print(f"last_error  : {s.last_error or '(none)'}")
    print(f"updated_at  : {s.updated_at}")
    print(f"scores      : {s.scores}")
    print()
    pending = list_pending(s)
    if pending:
        print(f"PENDING CHECKPOINTS ({len(pending)}):")
        for stage, kind, title in pending:
            print(f"  [{kind:8s}] {stage}: {title}")
    else:
        print("ALL CHECKPOINTS SIGNED")

    # 2026-07-10 增：报警与 rerun 历史一览
    alarms = list_alarms(s)
    if alarms:
        print()
        print(f"!! ALARMS ({len(alarms)}) — 超 per-stage budget 或 run_count ≥ 3:")
        for a in alarms[-5:]:  # 只显示最近 5 条
            print(f"  [{a['t']}] {a['stage']}: {a['msg']}")
    rerun_n = sum(1 for r in s.rerun_history)
    if rerun_n > 0:
        print()
        print(f"RERUN HISTORY ({rerun_n} entries, capped at 50):")
        # 按 stage 聚合
        from collections import Counter
        per_stage = Counter(r.get("stage", "?") for r in s.rerun_history)
        for stage, n in sorted(per_stage.items()):
            print(f"  {stage}: {n} 次")
    return 0


def cmd_reset(args) -> int:
    """子命令: reset --target-dir ...

    删除 state.json（重新初始化时用）。不删 .driver/ 目录。
    """
    p = state_path(args.target_dir)
    if p.exists():
        p.unlink()
        print(f"removed: {p}")
    else:
        print(f"no state at {p} (already clean)")
    return 0


def cmd_sign(args) -> int:
    """子命令: sign --target-dir ... --checkpoint <stage> [--note ...]

    用户对一个 checkpoint 签字（确认 stage 输出满意）。
    签字后 driver run 才允许从下一 stage 续跑。
    """
    s = load_state(args.target_dir)
    sign(s, args.checkpoint, args.target_dir, note=args.note or "")
    return 0


def cmd_checkpoints(args) -> int:
    """子命令: checkpoints --target-dir ... 列出所有 checkpoint 规格。

    显示 CHECKPOINT_PLAN（来自 checkpoints.py）的所有 stage + kind + title + prompt。
    用于人工查看 driver 的 gate 策略。
    """
    for stage, spec in CHECKPOINT_PLAN.items():
        print(f"\n[{spec.kind:8s}] {stage}: {spec.title}")
        print(f"  prompt : {spec.prompt}")
    return 0


def cmd_alarms(args) -> int:
    """子命令: alarms --target-dir ... 列出所有 budget 报警 + rerun 历史。

    用法：
      driver alarms --target-dir F:\\Research\\paper_x
      driver alarms --target-dir F:\\Research\\paper_x --show-rules

    不修改 state；只读展示。提供 budget 规则参考供用户手工调阈值。
    """
    from state import list_alarms, get_stage_reruns
    from checkpoints import STAGE_BUDGET_RULES
    s = load_state(args.target_dir)
    alarms = list_alarms(s)

    print(f"target      : {args.target_dir}")
    print(f"alarms      : {len(alarms)} 条")
    print(f"rerun_total : {len(s.rerun_history)} 条 (cap 50)")
    print()

    if alarms:
        print(f"!! ALARMS (最近 {min(len(alarms), 20)} 条):")
        for a in alarms[-20:]:
            print(f"  [{a['t']}] {a['stage']}: {a['msg']}")
    else:
        print("无 alarm。")

    if args.show_rules:
        print()
        print("STAGE_BUDGET_RULES (默认 per-stage 上限):")
        for stage, rule in STAGE_BUDGET_RULES.items():
            current = s.budget.get("max_reruns_per_stage", {}).get(stage, rule["max"])
            override = " (已覆盖)" if current != rule["max"] else ""
            print(f"  {stage:12s}  default={rule['max']:<2d}  current={current:<2d}{override}")
            print(f"                hint: {rule['reason_hint']}")
            print(f"                reruns = {get_stage_reruns(s, stage)}")
            print()
    return 0


def cmd_scan_alarms(args) -> int:
    """子命令: scan-alarms [scan_alarms.py 的全部参数]

    转发到 scan_alarms.main_with_args()，让 driver.cmd 仍是单一入口。
    默认参数：--root F:\\Research，--output-dir F:\\Research\\_ALARMS。

    用法：
      driver scan-alarms
      driver scan-alarms --stale-days 14 --quiet
      driver scan-alarms --root D:\\papers --json-only

    设计：直接调用 scan_alarms.main_with_args(namespace) 而不是 sys.argv 注入，
    避免 monkey-patch。
    """
    sa_args = argparse.Namespace(
        root=Path(args.root) if getattr(args, "root", None) else Path(r"F:\Research"),
        output_dir=Path(args.output_dir) if getattr(args, "output_dir", None) else Path(r"F:\Research\_ALARMS"),
        stale_days=int(args.stale_days) if getattr(args, "stale_days", None) is not None else 30,
        json_only=bool(getattr(args, "json_only", False)),
        md_only=bool(getattr(args, "md_only", False)),
        quiet=bool(getattr(args, "quiet", False)),
    )
    import scan_alarms
    return scan_alarms.main_with_args(sa_args)


def cmd_run(args) -> int:
    """子命令: run — 跑流水线主入口。

    顺序：
    1. provider sanity check（fail-fast）
    2. 加载 / 初始化 state
    3. 按 from_stage 起，顺序跑 stage
    4. 每个 stage 完成 → mark_completed + save_state
    5. 每个 stage 完成 → 检查 checkpoint（如未签字，pause）
    6. 失败 → mark_failed + save_state（run_count +1）

    Returns:
        0 = 正常完成或 pause（不是失败，pause 是 waiting for user signature）
        非 0 = 失败（provider check / stage rc != 0 / 参数错）
    """
    # 1. provider sanity
    if not args.skip_provider_check:
        rc = provider_check.check_provider()
        if rc != 0:
            print("ABORT: provider check failed; use --skip-provider-check to override", file=sys.stderr)
            return rc

    # 2. load state
    target = Path(args.target_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    s = load_state(target)

    # 从 from_stage 起；自动跑剩下的
    start = args.from_stage or s.stage
    if start not in STAGES_ORDER:
        print(f"FAIL: --from-stage {start} 不在 {STAGES_ORDER}", file=sys.stderr)
        return 1
    start_idx = STAGES_ORDER.index(start)

    end_stage = args.to_stage or STAGES_ORDER[-1]
    if end_stage not in STAGES_ORDER:
        print(f"FAIL: --to-stage {end_stage} 不在 {STAGES_ORDER}", file=sys.stderr)
        return 1
    end_idx = STAGES_ORDER.index(end_stage)
    if end_idx < start_idx:
        print(f"FAIL: --to-stage {end_stage} 在 --from-stage {start} 之前", file=sys.stderr)
        return 1

    # idea 来源
    idea_source = None
    if args.idea:
        idea_source = ("idea", args.idea)
    elif args.arxiv:
        idea_source = ("arxiv", args.arxiv)
    elif args.idea_auto:
        idea_source = ("auto", None)
    if idea_source:
        s.artifacts["idea_source"] = idea_source

    print("=" * 60)
    print(f"  auto-research-driver")
    print(f"  target      : {target}")
    print(f"  from_stage  : {start}")
    print(f"  review_mode : {args.review_mode}")
    print(f"  idea_source : {idea_source or '(resume from state)'}")
    print("=" * 60)

    # 3. 顺序跑
    stages_to_run = STAGES_ORDER[start_idx:end_idx + 1]
    for stage in stages_to_run:
        # 已签字的 checkpoint 可以跳过（断点续跑）
        if stage in s.completed and not args.force:
            print(f"[skip] {stage} already in completed")
            continue

        print(f"\n[run] {stage}")
        rc = _run_stage(stage, target, args, s)

        if rc != 0:
            mark_failed(s, stage, f"rc={rc}", target)
            print(f"FAIL: stage {stage} 返回 {rc}; state 已记录 last_error", file=sys.stderr)
            return rc

        # 4. mark complete + 5. checkpoint
        mark_completed(s, stage, target)
        print(f"[done] {stage} → completed")

        # checkpoint gating
        spec = get_checkpoint(stage)
        if spec and not is_signed(s, stage) and not args.skip_checkpoints:
            print(f"\n{'='*60}\n  CHECKPOINT: {spec.title}\n{'='*60}")
            print(spec.prompt)
            print(f"{'='*60}")
            print(f"drive paused at {stage}. use 'driver sign ...' to continue.")
            return 0  # pause，正常退出（不是失败）

    print(f"\n[finish] all stages from {start} completed")
    return 0


def _run_stage(stage: str, target: Path, args, state: DriverState) -> int:
    """stage 字符串 → 调对应 _stage_sN_* 实现。

    Args:
        stage: stage 名（"s1_idea" 等）
        target: paper 工程目录
        args: cmd_run 收到的 argparse.Namespace
        state: 当前 DriverState（被 stage 内部直接修改 + save_state）

    Returns:
        subprocess rc：0 = 成功，非 0 = 失败
    """
    if stage == "s1_idea":
        return _stage_s1_idea(target, args, state)
    elif stage == "s2_lit":
        return _stage_s2_lit(target, args, state)
    elif stage == "s3_outline":
        return _stage_s3_outline(target, args, state)
    elif stage == "s4_draft":
        return _stage_s4_draft(target, args, state)
    elif stage == "s5_review":
        return _stage_s5_review(target, args, state)
    elif stage == "s6_submit":
        return _stage_s6_submit(target, args, state)
    else:
        print(f"WARN: unknown stage {stage}, treating as no-op", file=sys.stderr)
        return 0


def _stage_s1_idea(target: Path, args, state: DriverState) -> int:
    """S1: idea discovery。

    当前策略：把 idea_source 写到 target/idea_canvas.md，让人工 / 后续 LLM 填充。
    完整 automation 需要 brainstorming-research + idea-evaluator + research_radar_v2，
    那部分 v1.1 再说；v1.0 先骨架。

    三种 idea 来源：
    - "idea"     用户 --idea 传入的一句话
    - "arxiv"    用户 --arxiv 传入的 arxiv id
    - "auto"     用户 --idea-auto 标记（obsidian 14 tag + research_radar v1.1 接入）
    - None       resume mode（state 已有 idea_source）；生成 placeholder

    副作用：state.artifacts["idea_canvas"] = <绝对路径>
    """
    canvas = target / "idea_canvas.md"
    src = state.artifacts.get("idea_source")
    if not src:
        canvas.write_text(
            "# Idea Canvas\n\n_resume mode: 没有 idea_source；请手填或 --idea 重启_\n",
            encoding="utf-8",
        )
        return 0
    kind, val = src
    if kind == "idea":
        canvas.write_text(
            f"# Idea Canvas\n\n## user-provided idea\n\n> {val}\n\n"
            f"_待 brainstorming-research + idea-evaluator 填充 3-5 个候选 / 5 维评分_\n",
            encoding="utf-8",
        )
    elif kind == "arxiv":
        canvas.write_text(
            f"# Idea Canvas\n\n## arxiv source\n\n- arxiv id: {val}\n"
            f"_待 deep-research 三段式扫描 + 文献综述生成_\n",
            encoding="utf-8",
        )
    elif kind == "auto":
        canvas.write_text(
            "# Idea Canvas\n\n## auto mode\n\n_待 obsidian 14 tag 聚类 + research_radar 30 天 arxiv 扫描_\n"
            "_v1.0 占位：v1.1 接入 brainstorming-research + research_radar_v2_\n",
            encoding="utf-8",
        )
    state.artifacts["idea_canvas"] = str(canvas)
    return 0


def _stage_s2_lit(target: Path, args, state: DriverState) -> int:
    """S2: lit review。

    v1.0 占位：只生成 refs.bib 模板 + lit_review.md 模板。
    完整 automation（deep_read_v2 + light-literature-search + paper-reviewer cite_verify）
    v1.1 接入。

    副作用：state.artifacts["refs_bib"] + state.artifacts["lit_review"] 写入
    """
    refs = target / "refs.bib"
    review = target / "lit_review.md"
    if not refs.exists():
        refs.write_text(
            "% refs.bib — S2 generated by driver\n"
            "% 待 light-citation + paper-reviewer-tmlr-corpus cite_verify v2 填充 ≥30 条\n",
            encoding="utf-8",
        )
    review.write_text(
        "# Literature Review\n\n_v1.0 占位：v1.1 接入 deep_read_v2 + must-cite delta_\n",
        encoding="utf-8",
    )
    state.artifacts["refs_bib"] = str(refs)
    state.artifacts["lit_review"] = str(review)
    return 0


def _stage_s3_outline(target: Path, args, state: DriverState) -> int:
    """S3: outline + experiment design 模板。

    生成 8 章 outline + experiment design 模板，v1.1 接入 tmlr_pipeline.templates。

    副作用：state.artifacts["outline"] + state.artifacts["experiment_design"] 写入
    """
    outline = target / "outline.md"
    design = target / "experiment_design.md"
    if not outline.exists():
        outline.write_text(
            "# Outline (8 章)\n\n_v1.0 占位：v1.1 接入 tmlr_pipeline.templates.outline.md 模板渲染_\n",
            encoding="utf-8",
        )
    if not design.exists():
        design.write_text(
            "# Experiment Design\n\n_v1.0 占位：v1.1 接入 brainstorming-research/chapter-templates_\n",
            encoding="utf-8",
        )
    state.artifacts["outline"] = str(outline)
    state.artifacts["experiment_design"] = str(design)
    return 0


def _stage_s4_draft(target: Path, args, state: DriverState) -> int:
    """S4: draft。

    如果 target 已有 main.tex，跳过（避免覆盖）；否则从 tmlr_pipeline 模板复制。

    Args:
        target: paper 工程目录
        args: cmd_run Namespace；args.force=true 强制覆盖
        state: 当前 DriverState

    Returns:
        0 = 成功（无论覆盖或跳过）；非 0 = subprocess 失败
    """
    if (target / "main.tex").exists() and not args.force:
        print(f"  [s4] main.tex exists; skip (use --force to overwrite)")
        state.artifacts["main_tex"] = str(target / "main.tex")
        return 0
    # 复用 tmlr_pipeline.run_pipeline.py 的 s4 行为
    return W.run_full_pipeline(target, from_stage="s4")


def _stage_s5_review(target: Path, args, state: DriverState) -> int:
    """S5: adversarial review。

    review_mode 默认 'simulator'（v1.0 走 tmlr-review-simulator，因为 v2.4 多 paper
    dispatch 在 driver 这种单 paper 场景需要额外配置）。--review-mode v24 走
    paper-reviewer-tmlr-corpus 4 persona（v1.1 接入）。

    Args:
        target: paper 工程目录（须有 main.tex 或 main.pdf）
        args: cmd_run Namespace；args.review_mode ∈ {"simulator", "v24"}
        state: DriverState，v2.4 模式下 state.scores["v24_final"] 会被填

    Returns:
        subprocess rc：0 = 成功；非 0 = 找不到 paper / 模拟器失败
    """
    paper = W.find_main_tex(target) or W.find_main_pdf(target)
    if paper is None:
        print(f"FAIL: {target} 下找不到 main.tex / main.pdf", file=sys.stderr)
        return 1
    reviews_dir = target / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)

    if args.review_mode == "v24":
        paper_name = W.paper_name_from_dir(target)
        rc = W.run_v24_review(paper_name, target, dispatch=True)
        if rc == 0:
            # 解析 v2.4 分数
            score = _parse_v24_score(target, paper_name)
            if score:
                state.scores["v24_final"] = score
        return rc

    # default: simulator
    rc = W.run_simulator_single(paper, reviews_dir / "main_review-prompt.md")
    if rc != 0:
        return rc
    rc = W.run_simulator_multi(paper, reviews_dir / "multi_personas")
    return rc


def _parse_v24_score(target: Path, paper_name: str) -> Optional[float]:
    """从 v2.4 报告里解析 v24_final。

    路径约定：F:/Research/_paper_reviews/baseline/reviews/p{n}_review_rev{N}.md
    取最新 rev 报告（lexicographic max），从中正则抓分数。

    Args:
        target: paper 工程目录（本函数不用，但保留以备扩展）
        paper_name: paper 名（用于 glob pattern）

    Returns:
        分数 float（0-10），或 None（找不到 / 解析失败）
    """
    # v2.4 报告路径约定：F:/Research/_paper_reviews/baseline/reviews/p{n}_review_rev{N}.md
    review_dir = Path(r"F:\Research\_paper_reviews\baseline\reviews")
    if not review_dir.exists():
        return None
    cands = sorted(review_dir.glob(f"{paper_name}_review_rev*.md"), reverse=True)
    if not cands:
        return None
    import re
    text = cands[0].read_text(encoding="utf-8")
    m = re.search(r"v24[_\-]?final[^\d]*(\d+\.\d+)", text, re.IGNORECASE)
    if m:
        return float(m.group(1))
    m = re.search(r"总分[^\d]*(\d+\.\d+)", text)
    if m:
        return float(m.group(1))
    return None


def _stage_s6_submit(target: Path, args, state: DriverState) -> int:
    """S6: submit checklist。

    生成 submission checklist 模板（v1.1 接入 tmlr_pipeline.templates）。
    S6 是"决策点"：用户最终签字才会真投递。

    副作用：state.artifacts["submit_checklist"] 写入
    """
    p = target / "submit"
    p.mkdir(parents=True, exist_ok=True)
    checklist = p / "checklist.md"
    if not checklist.exists():
        checklist.write_text(
            "# Submission Checklist\n\n"
            "_v1.0 占位：v1.1 接入 tmlr_pipeline.templates.submission_checklist.md 模板_\n"
            "_S6 是决策点：用户最终签字后才会真投递。_\n",
            encoding="utf-8",
        )
    state.artifacts["submit_checklist"] = str(checklist)
    return 0


def main() -> int:
    """CLI 入口：注册 8 个子命令并 dispatch。

    用法：
        driver run --target-dir F:/Research/paper_x
        driver status --target-dir F:/Research/paper_x
        driver alarms --target-dir F:/Research/paper_x --show-rules
        driver scan-alarms --root F:/Research --quiet
        ...

    Returns:
        args.func(args) 的返回值（0 = 成功，非 0 = 失败）。
        实际 exit code 由 sys.exit 传给 shell。
    """
    ap = argparse.ArgumentParser(
        prog="driver",
        description="auto-research-driver — TMLR end-to-end pipeline driver",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    # run
    p_run = sub.add_parser("run", help="跑流水线主入口")
    p_run.add_argument("--target-dir", type=Path, required=True, help="paper 工程目录")
    p_run.add_argument("--idea", help="一句话 idea")
    p_run.add_argument("--arxiv", help="arxiv id")
    p_run.add_argument("--idea-auto", action="store_true", help="auto mode")
    p_run.add_argument("--from-stage", choices=STAGES_ORDER, default=None,
                       help="从哪个 stage 开始（默认从 state.stage 续跑）")
    p_run.add_argument("--to-stage", choices=STAGES_ORDER, default=None,
                       help="到哪个 stage 结束（含），smoke test 用")
    p_run.add_argument("--review-mode", choices=["simulator", "v24"], default="simulator",
                       help="S5 review 模式（v1.0=simulator, v1.1=v24）")
    p_run.add_argument("--skip-checkpoints", action="store_true", help="不暂停在 checkpoint")
    p_run.add_argument("--skip-provider-check", action="store_true", help="跳过 provider sanity")
    p_run.add_argument("--force", action="store_true", help="覆盖已完成 stage")
    p_run.set_defaults(func=cmd_run)

    # status
    p_status = sub.add_parser("status", help="看 state.json + pending checkpoints")
    p_status.add_argument("--target-dir", type=Path, required=True)
    p_status.set_defaults(func=cmd_status)

    # reset
    p_reset = sub.add_parser("reset", help="清掉 state.json")
    p_reset.add_argument("--target-dir", type=Path, required=True)
    p_reset.set_defaults(func=cmd_reset)

    # sign
    p_sign = sub.add_parser("sign", help="签一个 checkpoint")
    p_sign.add_argument("--target-dir", type=Path, required=True)
    p_sign.add_argument("--checkpoint", required=True, choices=STAGES_ORDER)
    p_sign.add_argument("--note", default="")
    p_sign.set_defaults(func=cmd_sign)

    # checkpoints
    p_cp = sub.add_parser("checkpoints", help="列所有 checkpoint 规格")
    p_cp.add_argument("--target-dir", type=Path, required=False)
    p_cp.set_defaults(func=cmd_checkpoints)

    # alarms (2026-07-10 增)
    p_al = sub.add_parser("alarms", help="列 budget 报警 + rerun 历史")
    p_al.add_argument("--target-dir", type=Path, required=True)
    p_al.add_argument("--show-rules", action="store_true",
                      help="同时打印 STAGE_BUDGET_RULES 和当前 budget 覆盖")
    p_al.set_defaults(func=cmd_alarms)

    # scan-alarms (2026-07-10 增)：跨多 paper 报警扫描
    p_sa = sub.add_parser("scan-alarms", help="扫描所有 paper 目录，生成报警汇总报告")
    _sa_root_default = Path(r"F:\Research")
    _sa_out_default = Path(r"F:\Research\_ALARMS")
    p_sa.add_argument("--root", type=Path, default=None,
                      help="paper 根目录 (默认 {})".format(_sa_root_default))
    p_sa.add_argument("--output-dir", type=Path, default=None,
                      help="报告输出目录 (默认 {})".format(_sa_out_default))
    p_sa.add_argument("--stale-days", type=int, default=None,
                      help="stale 阈值天数 (默认 30)")
    p_sa.add_argument("--json-only", action="store_true", help="只输出 JSON")
    p_sa.add_argument("--md-only", action="store_true", help="只输出 Markdown")
    p_sa.add_argument("--quiet", action="store_true", help="不打印摘要到 stdout")
    p_sa.set_defaults(func=cmd_scan_alarms)

    # provider-check
    p_pc = sub.add_parser("provider-check", help="验证 MiniMax provider 配置")
    p_pc.add_argument("--config", type=Path, default=Path(r"C:\Users\Administrator\.mavis\config.yaml"))
    p_pc.add_argument("--ping", action="store_true", help="真 ping 网关")
    p_pc.set_defaults(func=cmd_provider_check)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())