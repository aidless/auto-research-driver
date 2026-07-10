"""ci/simulate_ci.py — 模拟 GitHub Actions ci.yml 本地运行

模拟 GH Actions 的关键步骤：
1. checkout（cwd 切到 skill 根）
2. setup-python 3.9（验证环境）
3. install coverage（PEP 668）
4. run ci/run_tests.py --full
5. 把 coverage report 渲染成 Markdown 表格，写到 GITHUB_STEP_SUMMARY
6. 上传 artifacts（落到本地 F:\Temp\gh_artifacts\）

不做的事（GH Actions 才能做）：
- 真的创建 release / tag
- 真的上传到 GH artifacts 服务（本地直接落到 F:\Temp\gh_artifacts\）
- concurrency 取消（同进程串行）

用法：
    py -3 ci/simulate_ci.py

环境变量覆盖：
    ARD_SKILL_ROOT       skill 根目录（默认：C:\Users\Administrator\.mavis\skills\auto-research-driver）
    GH_ARTIFACTS_DIR     artifact 输出目录（默认：F:\Temp\gh_artifacts）
    CI_MODE              full / quick / default / html-only（默认：full）
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Skill 根目录
SKILL_ROOT = Path(os.environ.get("ARD_SKILL_ROOT", r"C:\Users\Administrator\.mavis\skills\auto-research-driver"))
PY = Path(r"C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.9.25-windows-x86_64-none\python.exe")
ARTIFACT_DIR = Path(os.environ.get("GH_ARTIFACTS_DIR", r"F:\Temp\gh_artifacts"))
CI_MODE = os.environ.get("CI_MODE", "full")

# 模拟 GH Actions 环境变量
os.environ["ARD_SKILL_ROOT"] = str(SKILL_ROOT)
os.environ["GITHUB_WORKSPACE"] = str(SKILL_ROOT)
os.environ["GITHUB_STEP_SUMMARY"] = str(ARTIFACT_DIR / "step_summary.md")
os.environ["RUNNER_TEMP"] = str(ARTIFACT_DIR / "tmp")


def step(name: str):
    print("\n" + "=" * 60)
    print(f"::group::{name}")
    print("=" * 60)


def endgroup():
    print("::endgroup::")


def append_summary(text: str):
    p = Path(os.environ["GITHUB_STEP_SUMMARY"])
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(text)


def run(cmd: list[str], description: str = "", cwd: str = None) -> int:
    if description:
        print(f"\n[run] {description}")
    print(f"$ {' '.join(str(c) for c in cmd)}")
    return subprocess.call(cmd, cwd=cwd or str(SKILL_ROOT))


def main() -> int:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / "tmp").mkdir(parents=True, exist_ok=True)

    # 清空 step summary（重新生成）
    summary_path = Path(os.environ["GITHUB_STEP_SUMMARY"])
    if summary_path.exists():
        summary_path.unlink()

    print(f"::notice::Simulating GitHub Actions ci.yml locally")
    print(f"::notice::Time: {datetime.now().isoformat()}")
    print(f"::notice::GITHUB_WORKSPACE = {os.environ['GITHUB_WORKSPACE']}")
    print(f"::notice::GITHUB_STEP_SUMMARY = {os.environ['GITHUB_STEP_SUMMARY']}")
    print(f"::notice::CI_MODE = {CI_MODE}")

    rc = 0

    # ---- step 1: checkout（验证目录存在） ----
    step("Checkout code")
    if not (SKILL_ROOT / "tests" / "test_state.py").exists():
        print(f"::error::tests/test_state.py missing at {SKILL_ROOT}")
        return 2
    print(f"::notice::checkout OK: {SKILL_ROOT}")
    endgroup()

    # ---- step 2: setup-python 3.9（验证环境） ----
    step("Setup Python 3.9")
    rc = run([str(PY), "--version"], "python --version")
    if rc != 0:
        print("::error::python not found")
        return 2
    endgroup()

    # ---- step 3: install coverage ----
    step("Install coverage")
    rc = run([str(PY), "-c", "import coverage; print('coverage already installed', coverage.__version__)"],
             "check coverage")
    if rc != 0:
        print("::notice::coverage not installed, installing...")
        rc = run([str(PY), "-m", "pip", "install", "coverage", "--break-system-packages", "--quiet"],
                 "pip install coverage")
        if rc != 0:
            print("::error::pip install coverage failed")
            return 3
    endgroup()

    # ---- step 4: show environment ----
    step("Show environment")
    print(f"skill_root={SKILL_ROOT}")
    endgroup()

    # ---- step 5: run CI（核心） ----
    ci_flag = {"quick": "--quick", "default": "", "full": "--full", "html-only": "--html-only"}.get(CI_MODE, "--full")
    step(f"Run CI (ci/run_tests.py {ci_flag})")
    cmd = [str(PY), "-u", str(SKILL_ROOT / "ci" / "run_tests.py")]
    if ci_flag:
        cmd.append(ci_flag)
    rc = run(cmd, f"py -3 ci/run_tests.py {ci_flag}")
    if rc != 0:
        print(f"::error::CI failed (rc={rc})")
    endgroup()

    # ---- step 6: upload artifacts（模拟落到本地） ----
    step("Upload coverage HTML (artifact)")
    if (SKILL_ROOT / "htmlcov" / "index.html").exists():
        target = ARTIFACT_DIR / "coverage-html"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(SKILL_ROOT / "htmlcov", target)
        size_kb = sum(f.stat().st_size for f in target.rglob('*') if f.is_file()) // 1024
        print(f"::notice::artifact uploaded: {target} ({size_kb} KB)")
    else:
        print("::warning::htmlcov/index.html not found")
    endgroup()

    step("Upload .coverage raw (artifact)")
    if (SKILL_ROOT / ".coverage").exists():
        target = ARTIFACT_DIR / "coverage-data" / ".coverage"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SKILL_ROOT / ".coverage", target)
        print(f"::notice::artifact uploaded: {target}")
    endgroup()

    step("Upload CI logs (artifact)")
    if (SKILL_ROOT / "ci" / "logs").exists():
        target = ARTIFACT_DIR / "ci-logs"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(SKILL_ROOT / "ci" / "logs", target)
        n_logs = len(list(target.glob("*.log")))
        print(f"::notice::artifact uploaded: {target} ({n_logs} log files)")
    endgroup()

    # ---- step 7: print coverage summary to step_summary ----
    step("Print coverage summary to $GITHUB_STEP_SUMMARY")
    if rc == 0:
        result = subprocess.run(
            [str(PY), "-m", "coverage", "report", "-m"],
            cwd=str(SKILL_ROOT), capture_output=True, text=True, encoding="utf-8"
        )
        report_text = result.stdout

        # 计算 artifact size
        html_size = (sum(f.stat().st_size for f in (ARTIFACT_DIR / 'coverage-html').rglob('*') if f.is_file()) // 1024) \
                    if (ARTIFACT_DIR / 'coverage-html').exists() else 0

        md = []
        md.append("## ✅ CI Passed\n")
        md.append(f"**Run time**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
        md.append(f"**Mode**: `{CI_MODE}` (unit + coverage + smoke + HTML)  ")
        md.append(f"**Skill root**: `{SKILL_ROOT}`\n")
        md.append("### Coverage Summary\n")
        md.append("```\n")
        md.append(report_text)
        md.append("```\n")
        md.append("### Artifacts\n")
        md.append(f"- 📊 HTML report: `coverage-html` (size: {html_size} KB)")
        md.append(f"- 📦 Raw data: `coverage-data/.coverage`")
        md.append(f"- 📝 Logs: `ci-logs/ci_*.log`")
        md.append("")
        append_summary("\n".join(md))
        print("::notice::step summary written")
    else:
        append_summary("## ❌ CI Failed\n")
        append_summary(f"rc = {rc}\n")
        append_summary("请检查本地日志: `ci/logs/ci_*.log`\n")
        print("::notice::failure summary written")
    endgroup()

    # ---- summary ----
    print("\n" + "=" * 60)
    print(f"::notice::Simulation finished. rc={rc}")
    print(f"::notice::Step summary: {os.environ['GITHUB_STEP_SUMMARY']}")
    print(f"::notice::Artifacts: {ARTIFACT_DIR}")
    print("=" * 60)
    return rc


if __name__ == "__main__":
    sys.exit(main())