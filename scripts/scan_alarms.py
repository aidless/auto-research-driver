"""scan_alarms.py - periodic alarm scanner for multi-paper research pipeline.

Scans all paper directories under RESEARCH_ROOT and produces:
  1. A Markdown report at <output_dir>/REPORT.md (human-readable)
  2. A JSON dump at <output_dir>/alarms_<timestamp>.json (machine-readable)

Two alarm classes:
  - "driver" : paper has .driver/state.json with non-empty .alarms list
  - "broad"  : heuristic checks for non-driver papers (stale, latex errors, etc.)

Usage:
  py -3 scan_alarms.py                          # scan default F:\\Research
  py -3 scan_alarms.py --root D:\\papers        # custom root
  py -3 scan_alarms.py --stale-days 30          # tune stale threshold
  py -3 scan_alarms.py --json-only              # suppress md output
  py -3 scan_alarms.py --md-only                # suppress json output

Design (2026-07-10):
  - Read-only: never modifies any paper directory
  - Zero external deps: stdlib only (json, pathlib, datetime, re, argparse)
  - Single-process safe: scan takes <5s for ~40 dirs
  - Designed for cron / Task Scheduler / GitHub Actions downstream
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# --- 路径配置 ---

DEFAULT_RESEARCH_ROOT = Path(r"F:\Research")
DEFAULT_OUTPUT_DIR = DEFAULT_RESEARCH_ROOT / "_ALARMS"

# Paper 启发式识别: 必须满足以下任一
PAPER_MARKERS = ["main.tex", "refs.bib"]
PAPER_STATE_MARKER = ".driver"  # driver 接管的 paper 才有

# 广义报警阈值(可在 CLI 覆盖)
DEFAULT_STALE_DAYS = 30  # 超过 N 天没改 main.tex/main.pdf 视为 stale
LATEX_ERROR_PATTERN = re.compile(r"^!\s+LaTeX\s+Error", re.MULTILINE | re.IGNORECASE)
LOG_FILE_GLOB = ["*.log"]


# --- 数据模型 ---


@dataclass
class Alarm:
    """单个报警条目。"""

    severity: str  # "critical" | "warning" | "info"
    category: str  # "driver_budget" | "stale_paper" | "latex_error" | "low_v24_score" | "orphan_state" | "artifact_leak"
    paper: str  # paper 目录名
    msg: str  # 一句话说明
    detail: str = ""  # 详细(可多行)


@dataclass
class PaperScan:
    """单个 paper 扫描结果。"""

    name: str
    path: str
    has_state: bool  # 是否有 .driver/state.json
    has_main_tex: bool
    has_main_pdf: bool
    has_refs_bib: bool
    last_modified: Optional[str]  # ISO 时间
    completed_stages: list = field(default_factory=list)
    current_stage: str = ""
    run_count: int = 0
    v24_score: Optional[float] = None
    alarms: list = field(default_factory=list)  # List[Alarm]


# --- 扫描逻辑 ---


def is_paper_dir(p: Path) -> bool:
    """识别是否 paper 工程目录。"""
    if not p.is_dir():
        return False
    if (p / PAPER_STATE_MARKER / "state.json").exists():
        return True
    return any((p / m).exists() for m in PAPER_MARKERS)


def safe_load_state(state_path: Path) -> Optional[dict]:
    """尝试加载 state.json; 损坏返回 None。"""
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def collect_papers(root: Path) -> list:
    """收集 root 下所有 paper 目录。"""
    if not root.exists():
        return []
    papers = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and is_paper_dir(entry):
            papers.append(entry)
    return papers


def scan_driver_paper(paper_dir: Path) -> PaperScan:
    """扫描 driver 接管的 paper。"""
    state_file = paper_dir / PAPER_STATE_MARKER / "state.json"
    state = safe_load_state(state_file)

    # main 文件 mtime (取最新的一个)
    main_files = []
    for fname in ["main.tex", "main.pdf"]:
        f = paper_dir / fname
        if f.exists():
            main_files.append(f)
    last_mtime = None
    if main_files:
        latest = max(main_files, key=lambda f: f.stat().st_mtime)
        last_mtime = datetime.fromtimestamp(latest.stat().st_mtime).isoformat(timespec="seconds")

    scan = PaperScan(
        name=paper_dir.name,
        path=str(paper_dir),
        has_state=True,
        has_main_tex=(paper_dir / "main.tex").exists(),
        has_main_pdf=(paper_dir / "main.pdf").exists(),
        has_refs_bib=(paper_dir / "refs.bib").exists(),
        last_modified=last_mtime,
    )

    if state is None:
        scan.alarms.append(Alarm(
            severity="critical",
            category="orphan_state",
            paper=paper_dir.name,
            msg=".driver/state.json 损坏或无法解析",
            detail=f"path: {state_file}",
        ))
        return scan

    scan.completed_stages = state.get("completed", [])
    scan.current_stage = state.get("stage", "")
    scan.run_count = state.get("run_count", 0)
    scan.v24_score = state.get("scores", {}).get("v24_final")

    # Driver alarms
    for a in state.get("alarms", []):
        scan.alarms.append(Alarm(
            severity="critical",
            category="driver_budget",
            paper=paper_dir.name,
            msg=a.get("msg", ""),
            detail=f"[{a.get('t', '?')}] {a.get('stage', '?')}",
        ))

    # run_count >= 3 但未触发 budget alarm 也算 warning(老报警)
    if scan.run_count >= 3 and not any(a.category == "driver_budget" for a in scan.alarms):
        scan.alarms.append(Alarm(
            severity="warning",
            category="driver_budget",
            paper=paper_dir.name,
            msg=f"run_count={scan.run_count} 但未触发 budget alarm(可能 budget 已放宽)",
        ))

    # v24_score < 7.8
    if scan.v24_score is not None and scan.v24_score < 7.8:
        scan.alarms.append(Alarm(
            severity="warning",
            category="low_v24_score",
            paper=paper_dir.name,
            msg=f"v24_final={scan.v24_score} < 7.8 质量门",
        ))

    return scan


def scan_broad_paper(paper_dir: Path, stale_days: int) -> PaperScan:
    """扫描非 driver 接管的 paper。"""
    main_files = []
    for fname in ["main.tex", "main.pdf"]:
        f = paper_dir / fname
        if f.exists():
            main_files.append(f)
    last_mtime = None
    if main_files:
        latest = max(main_files, key=lambda f: f.stat().st_mtime)
        last_mtime = datetime.fromtimestamp(latest.stat().st_mtime).isoformat(timespec="seconds")

    scan = PaperScan(
        name=paper_dir.name,
        path=str(paper_dir),
        has_state=False,
        has_main_tex=(paper_dir / "main.tex").exists(),
        has_main_pdf=(paper_dir / "main.pdf").exists(),
        has_refs_bib=(paper_dir / "refs.bib").exists(),
        last_modified=last_mtime,
    )

    # Stale check
    if last_mtime:
        last_dt = datetime.fromisoformat(last_mtime)
        age_days = (datetime.now() - last_dt).days
        if age_days > stale_days:
            scan.alarms.append(Alarm(
                severity="warning",
                category="stale_paper",
                paper=paper_dir.name,
                msg=f"main 文件已 {age_days} 天未更新 (阈值 {stale_days} 天)",
                detail=f"last_modified={last_mtime}",
            ))

    # LaTeX error 残留
    for log_glob in LOG_FILE_GLOB:
        for log_file in paper_dir.glob(log_glob):
            try:
                content = log_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if LATEX_ERROR_PATTERN.search(content):
                scan.alarms.append(Alarm(
                    severity="critical",
                    category="latex_error",
                    paper=paper_dir.name,
                    msg=f"残留 LaTeX 编译错误 ({log_file.name})",
                    detail=f"path={log_file}",
                ))
                break  # 一个 log 报一次

    # Artifact leak: 临时脚本或调试文件残留
    leak_patterns = ["_gen_report.py", "_audit*.py", "_check*.py", "_fix*.py",
                     "compile_report.md", "*.aux", "*.bbl", "*.blg"]
    leak_files = []
    for pat in leak_patterns:
        leak_files.extend(paper_dir.glob(pat))
    if leak_files:
        scan.alarms.append(Alarm(
            severity="info",
            category="artifact_leak",
            paper=paper_dir.name,
            msg=f"发现 {len(leak_files)} 个临时/调试文件残留",
            detail="\n".join(f.name for f in leak_files[:10]),
        ))

    return scan


def scan_all(root: Path, stale_days: int) -> list:
    """扫描 root 下所有 paper。"""
    paper_dirs = collect_papers(root)
    results = []
    for pd in paper_dirs:
        state_file = pd / PAPER_STATE_MARKER / "state.json"
        if state_file.exists():
            results.append(scan_driver_paper(pd))
        else:
            results.append(scan_broad_paper(pd, stale_days))
    return results


# --- 报告生成 ---


def render_markdown(results: list, root: Path, stale_days: int) -> str:
    """生成 Markdown 报告。"""
    lines = []
    ts = datetime.now().isoformat(timespec="seconds")
    lines.append(f"# 多 Paper 流水线报警汇总报告")
    lines.append("")
    lines.append(f"- **生成时间**: {ts}")
    lines.append(f"- **扫描根目录**: `{root}`")
    lines.append(f"- **Stale 阈值**: {stale_days} 天")
    lines.append(f"- **Paper 总数**: {len(results)}")
    lines.append("")

    # 1. 总览
    by_severity = Counter()
    by_category = Counter()
    by_paper_count = Counter()
    for r in results:
        for a in r.alarms:
            by_severity[a.severity] += 1
            by_category[a.category] += 1
            by_paper_count[a.paper] += 1

    lines.append("## 总览")
    lines.append("")
    lines.append("| 严重度 | 数量 |")
    lines.append("|---|---|")
    for sev in ["critical", "warning", "info"]:
        lines.append(f"| {sev} | {by_severity.get(sev, 0)} |")
    lines.append("")
    if not by_severity:
        lines.append("**✓ 所有 paper 健康,无报警。**")
        lines.append("")
        return "\n".join(lines)

    lines.append("| 类别 | 数量 |")
    lines.append("|---|---|")
    for cat, n in sorted(by_category.items(), key=lambda x: -x[1]):
        lines.append(f"| {cat} | {n} |")
    lines.append("")

    # 2. 有报警的 paper(按报警数降序)
    lines.append("## 有报警的 Paper")
    lines.append("")
    papers_with_alarms = [r for r in results if r.alarms]
    papers_with_alarms.sort(key=lambda r: (-len(r.alarms), r.name))
    for r in papers_with_alarms:
        lines.append(f"### `{r.name}` — {len(r.alarms)} 个报警")
        lines.append("")
        lines.append(f"- 路径: `{r.path}`")
        if r.has_state:
            lines.append(f"- Driver 接管: ✓ (stage=`{r.current_stage}`, completed={len(r.completed_stages)}, run_count={r.run_count})")
            if r.v24_score is not None:
                lines.append(f"- v24_final: **{r.v24_score}**")
        else:
            lines.append("- Driver 接管: ✗ (未接入)")
        if r.last_modified:
            lines.append(f"- 最近修改: {r.last_modified}")
        lines.append("")
        for a in r.alarms:
            icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}[a.severity]
            lines.append(f"- {icon} **{a.category}**: {a.msg}")
            if a.detail:
                lines.append(f"  ```\n  {a.detail}\n  ```")
        lines.append("")

    # 3. 完整 paper 清单
    lines.append("## 完整 Paper 清单")
    lines.append("")
    lines.append(f"| Paper | Driver | main.tex | main.pdf | refs.bib | 最近修改 | Alarm 数 |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in sorted(results, key=lambda x: x.name):
        driver = "✓" if r.has_state else "✗"
        tex = "✓" if r.has_main_tex else "✗"
        pdf = "✓" if r.has_main_pdf else "✗"
        bib = "✓" if r.has_refs_bib else "✗"
        lm = r.last_modified or "-"
        alarm_n = len(r.alarms)
        marker = f" ⚠️ {alarm_n}" if alarm_n > 0 else ""
        lines.append(f"| `{r.name}` | {driver} | {tex} | {pdf} | {bib} | {lm} | {alarm_n}{marker} |")
    lines.append("")

    # 4. 备注
    lines.append("## 备注")
    lines.append("")
    lines.append("- **Driver 接管**: 存在 `.driver/state.json` 的 paper 走 driver 流水线;")
    lines.append("  其报警包括 budget ALARM + v24 分数异常 + state 损坏。")
    lines.append("- **未接管 paper**: 用启发式检查(stale / LaTeX error / artifact leak)。")
    lines.append("- 报警不自动降级;用户在 `state.json.budget` 里改阈值,或手工 resurrect。")
    lines.append("- 本脚本只读不写,可放心手动跑或 cron。")
    lines.append("")

    return "\n".join(lines)


def render_json(results: list, root: Path, stale_days: int) -> dict:
    """生成 JSON 输出。"""
    return {
        "scan_meta": {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "root": str(root),
            "stale_days": stale_days,
            "n_papers": len(results),
        },
        "summary": {
            "by_severity": dict(Counter(a.severity for r in results for a in r.alarms)),
            "by_category": dict(Counter(a.category for r in results for a in r.alarms)),
            "papers_with_alarms": sum(1 for r in results if r.alarms),
        },
        "papers": [
            {
                "name": r.name,
                "path": r.path,
                "has_state": r.has_state,
                "current_stage": r.current_stage,
                "completed_stages": r.completed_stages,
                "run_count": r.run_count,
                "v24_score": r.v24_score,
                "last_modified": r.last_modified,
                "n_alarms": len(r.alarms),
                "alarms": [asdict(a) for a in r.alarms],
            }
            for r in sorted(results, key=lambda x: x.name)
        ],
    }


# --- 入口 ---


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="scan_alarms",
        description="多 paper 流水线报警扫描器 (read-only)",
    )
    ap.add_argument("--root", type=Path, default=DEFAULT_RESEARCH_ROOT,
                    help=f"paper 根目录 (默认 {DEFAULT_RESEARCH_ROOT})")
    ap.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                    help=f"报告输出目录 (默认 {DEFAULT_OUTPUT_DIR})")
    ap.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS,
                    help=f"stale 阈值天数 (默认 {DEFAULT_STALE_DAYS})")
    ap.add_argument("--json-only", action="store_true", help="只输出 JSON,不写 Markdown")
    ap.add_argument("--md-only", action="store_true", help="只输出 Markdown,不写 JSON")
    ap.add_argument("--quiet", action="store_true", help="不打印摘要到 stdout")
    args = ap.parse_args()

    if not args.root.exists():
        print(f"ERROR: root not found: {args.root}", file=sys.stderr)
        return 1

    started = time.time()
    results = scan_all(args.root, args.stale_days)
    elapsed = time.time() - started

    args.output_dir.mkdir(parents=True, exist_ok=True)

    written = []
    if not args.md_only:
        json_data = render_json(results, args.root, args.stale_days)
        ts_compact = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = args.output_dir / f"alarms_{ts_compact}.json"
        json_path.write_text(
            json.dumps(json_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        # 同步写一个 latest.json (方便下游脚本不用 glob)
        latest_path = args.output_dir / "alarms_latest.json"
        latest_path.write_text(
            json.dumps(json_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        written.append(str(json_path))

    if not args.json_only:
        md_content = render_markdown(results, args.root, args.stale_days)
        md_path = args.output_dir / "REPORT.md"
        md_path.write_text(md_content, encoding="utf-8")
        written.append(str(md_path))

    n_alarms = sum(len(r.alarms) for r in results)
    n_critical = sum(1 for r in results for a in r.alarms if a.severity == "critical")

    if not args.quiet:
        print(f"[scan_alarms] root={args.root}")
        print(f"[scan_alarms] papers={len(results)}  alarms={n_alarms}  critical={n_critical}")
        print(f"[scan_alarms] elapsed={elapsed:.2f}s")
        for w in written:
            print(f"[scan_alarms] wrote: {w}")

    # exit code: 0=clean, 2=有 critical (让 cron / scheduler 能区分)
    return 0 if n_critical == 0 else 2


if __name__ == "__main__":
    sys.exit(main())