"""wrappers.py — driver 对 4 个被驱动组件的薄包装

不重写逻辑，只 subprocess 调用 + returncode + 路径规范化。所有硬编码路径统一在此模块，
driver.py 不知道 F:/Research/ 在哪——换环境只改这里。

被包装的入口：
- run_pipeline.py     : F:/Research/tmlr_pipeline/src/run_pipeline.py  (S1-S6 全跑)
- simulate_review.py  : F:/Research/tmlr-review-simulator/simulate_review.py  (单篇 simulator)
- multi_review.py     : tmlr-review-simulator/multi_review.py  (3 persona)
- regression_suite.py : paper-reviewer-tmlr-corpus/scripts/regression_suite.py  (v2.4 多篇)
- multi_paper_dispatch.py : paper-reviewer-tmlr-corpus/scripts/multi_paper_dispatch.py  (v2.4 并行)
- global_checklist.py : paper-reviewer-tmlr-corpus/scripts/global_checklist.py  (v2.5 写作风格)
- tmlr_compliance.py  : paper-reviewer-tmlr-corpus/scripts/tmlr_compliance.py  (R1-R13 13-rule gate)
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence


# 路径常量（junction-aware：junction 在 Python 里自动 resolve）
PIPELINE_ROOT = Path(r"F:\Research\tmlr_pipeline")
PIPELINE_RUN = PIPELINE_ROOT / "src" / "run_pipeline.py"

# tmlr-review-simulator 在两个位置都有；优先 .mavis/skills（junction 自动 resolve）
SIMULATOR_ROOT = Path(r"C:\Users\Administrator\.mavis\skills\tmlr-review-simulator")
SIMULATOR_SCRIPT = SIMULATOR_ROOT / "simulate_review.py"
SIMULATOR_MULTI = SIMULATOR_ROOT / "multi_review.py"

# paper-reviewer-tmlr-corpus v2.4 也在 .mavis/skills（不是 F:\Research）
REVIEWER_ROOT = Path(r"C:\Users\Administrator\.mavis\skills\paper-reviewer-tmlr-corpus")
REVIEWER_REGRESSION = REVIEWER_ROOT / "scripts" / "regression_suite.py"
REVIEWER_DISPATCH = REVIEWER_ROOT / "scripts" / "multi_paper_dispatch.py"
REVIEWER_TMLR_COMPLIANCE = REVIEWER_ROOT / "scripts" / "tmlr_compliance.py"
REVIEWER_GLOBAL_CHECKLIST = REVIEWER_ROOT / "scripts" / "global_checklist.py"

PY = "py"  # Windows launcher for Python 3.9 (Python 3.11 不可用)


def _stream(cmd: Sequence[str], cwd: Optional[Path] = None) -> int:
    """subprocess.run + 实时 stdout。失败返回非零。"""
    print(f"  $ {' '.join(shlex.quote(str(c)) for c in cmd)}")
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None).returncode


def run_full_pipeline(target_dir: Path, from_stage: str = "s1",
                      downloads: Optional[Path] = None,
                      skip_simulator: bool = False) -> int:
    """S1-S6 全跑或部分跑。走 tmlr_pipeline.run_pipeline.py。"""
    if not PIPELINE_RUN.exists():
        print(f"FAIL: {PIPELINE_RUN} 不存在", file=sys.stderr)
        return 1
    cmd = [PY, "-3", str(PIPELINE_RUN),
           "--target-dir", str(target_dir),
           "--from-stage", from_stage]
    if downloads:
        cmd += ["--downloads", str(downloads)]
    if skip_simulator:
        cmd += ["--skip-simulator"]
    return _stream(cmd)


def run_simulator_single(paper: Path, out: Path, quiet: bool = True) -> int:
    """单篇 adversarial review（tmlr-review-simulator）。"""
    if not SIMULATOR_SCRIPT.exists():
        print(f"FAIL: {SIMULATOR_SCRIPT} 不存在", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [PY, "-3", str(SIMULATOR_SCRIPT), str(paper), "--out", str(out)]
    if quiet:
        cmd.append("--quiet")
    return _stream(cmd)


def run_simulator_multi(paper: Path, out_dir: Path) -> int:
    """3 persona review（tmlr-review-simulator）。"""
    if not SIMULATOR_MULTI.exists():
        print(f"FAIL: {SIMULATOR_MULTI} 不存在", file=sys.stderr)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [PY, "-3", str(SIMULATOR_MULTI), str(paper), "--out", str(out_dir)]
    return _stream(cmd)


def run_v24_review(paper_name: str, paper_dir: Path,
                   dispatch: bool = True, out: Optional[Path] = None) -> int:
    """v2.4 4-persona review（paper-reviewer-tmlr-corpus）。

    paper_name 比如 'paper5'，对应 target/<paper_name>/main.tex
    """
    if not REVIEWER_REGRESSION.exists():
        print(f"FAIL: {REVIEWER_REGRESSION} 不存在", file=sys.stderr)
        return 1
    cmd = [PY, "-3", str(REVIEWER_REGRESSION), "--papers", paper_name]
    if dispatch:
        cmd.append("--dispatch")
    if out:
        cmd += ["--out", str(out)]
    return _stream(cmd)


def run_tmlr_compliance(paper_name: str) -> int:
    """13-rule TMLR compliance gate（R1-R13）。"""
    if not REVIEWER_TMLR_COMPLIANCE.exists():
        print(f"FAIL: {REVIEWER_TMLR_COMPLIANCE} 不存在", file=sys.stderr)
        return 1
    cmd = [PY, "-3", str(REVIEWER_TMLR_COMPLIANCE), paper_name]
    return _stream(cmd)


def run_global_checklist(paper_dir: Path) -> int:
    """v2.5 写作风格扫描（register/cite-command/abbreviation/parallelism）。"""
    if not REVIEWER_GLOBAL_CHECKLIST.exists():
        print(f"FAIL: {REVIEWER_GLOBAL_CHECKLIST} 不存在", file=sys.stderr)
        return 1
    cmd = [PY, "-3", str(REVIEWER_GLOBAL_CHECKLIST), str(paper_dir)]
    return _stream(cmd)


def find_main_tex(target_dir: Path) -> Optional[Path]:
    """在 target_dir 下找 main.tex；找不到返回 None。"""
    cand = target_dir / "main.tex"
    return cand if cand.exists() else None


def find_main_pdf(target_dir: Path) -> Optional[Path]:
    cand = target_dir / "main.pdf"
    return cand if cand.exists() else None


def paper_name_from_dir(target_dir: Path) -> str:
    """从 target_dir 路径推导 paper 名（最后一段 path 的 stem）。"""
    return Path(target_dir).stem.lower().replace(" ", "-")