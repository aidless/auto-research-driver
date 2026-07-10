"""ci/run_tests.py — auto-research-driver CI 一键复现脚本（Python 实现）

避开 Trae IDE 终端的 safe_rm_aliases.ps1 hook（它会拦截 PowerShell 的 $变量）。
纯 Python subprocess + 文件 I/O，所有平台通用（Windows / Linux / macOS）。

用法：
    py -3 ci/run_tests.py                # 默认：unit + smoke + coverage
    py -3 ci/run_tests.py --quick         # 只跑单元测试
    py -3 ci/run_tests.py --full          # unit + smoke + coverage + HTML
    py -3 ci/run_tests.py --html-only     # 仅生成 HTML（前提：已有 .coverage）
    py -3 ci/run_tests.py --no-log        # 不写日志到文件
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ANSI 颜色（Win10+ / Linux / macOS 都支持）
def _enable_vt() -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x4
            for handle_id in (-11, -12):  # STDOUT, STDERR
                handle = kernel32.GetStdHandle(handle_id)
                mode = ctypes.c_uint32()
                if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                    kernel32.SetConsoleMode(handle, mode.value | 0x4)
        except Exception:
            pass


_enable_vt()


class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    DGREY = "\033[90m"


def cprint(msg: str, color: str = "") -> None:
    if color:
        print(f"{color}{msg}{C.RESET}")
    else:
        print(msg)


# Skill 根目录 = 本文件的上级目录
# 注：Windows 上 .mavis 是 .minimax 的 junction；.resolve() 会跟到 junction 真实路径
# 所以用 abspath（不解析 junction），且允许环境变量 ARD_SKILL_ROOT 覆盖
_env_root = os.environ.get("ARD_SKILL_ROOT")
if _env_root:
    SKILL_ROOT = Path(_env_root)
else:
    SKILL_ROOT = Path(os.path.abspath(Path(__file__).parent.parent))

PY = Path(r"C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.9.25-windows-x86_64-none\python.exe")
if not PY.exists():
    # fallback：找系统 python
    PY = Path(sys.executable)

LOG_DIR = SKILL_ROOT / "ci" / "logs"


def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def run_py(args: list[str], description: str, log_file: Path | None, log_handle) -> int:
    """跑 Python 子进程，stdout/stderr 写到 log_file + console。

    返回 exit code。
    """
    cprint(f"\n[C.YELLOW]{'[step] ' + description}{C.RESET}")
    cmd_line = f'"{PY}" {" ".join(args)}'
    cprint(f"[CI] exec: {cmd_line}", C.DIM)

    if log_handle is None:
        # NoLog: 直接打到 stdout
        rc = subprocess.call([str(PY), *args], cwd=str(SKILL_ROOT))
        return rc

    log_handle.write(f"\n[stdout/stderr] {cmd_line}\n")
    log_handle.flush()

    # 捕获 stdout+stderr（合并），subprocess.run + text=True
    try:
        result = subprocess.run(
            [str(PY), *args],
            cwd=str(SKILL_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.stdout:
            log_handle.write(result.stdout)
            if not result.stdout.endswith("\n"):
                log_handle.write("\n")
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        if result.stderr:
            log_handle.write(result.stderr)
            if not result.stderr.endswith("\n"):
                log_handle.write("\n")
            cprint(result.stderr, C.DIM)
        return result.returncode
    except Exception as e:
        cprint(f"[CI] FAIL to run: {e}", C.RED)
        return -1


def main() -> int:
    ap = argparse.ArgumentParser(description="auto-research-driver CI")
    ap.add_argument("--quick", action="store_true", help="只跑单元测试")
    ap.add_argument("--full", action="store_true", help="unit + smoke + coverage + HTML")
    ap.add_argument("--html-only", action="store_true", help="仅生成 HTML（前提：已有 .coverage）")
    ap.add_argument("--no-log", action="store_true", help="不写日志到文件")
    args = ap.parse_args()

    mode = "html-only" if args.html_only else ("quick" if args.quick else ("full" if args.full else "default"))

    # 日志
    timestamp = now_ts()
    log_file: Path | None = None
    log_handle = None
    if not args.no_log:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = LOG_DIR / f"ci_{timestamp}.log"
        log_handle = log_file.open("w", encoding="utf-8")

    # header
    cprint("=" * 60, C.MAGENTA)
    cprint("  auto-research-driver CI", C.MAGENTA)
    cprint(f"  SkillRoot : {SKILL_ROOT}", C.MAGENTA)
    cprint(f"  Python    : {PY}", C.MAGENTA)
    cprint(f"  LogFile   : {log_file or '(no-log)'}", C.MAGENTA)
    cprint(f"  Mode      : {mode}", C.MAGENTA)
    cprint(f"  Time      : {timestamp}", C.MAGENTA)
    cprint("=" * 60, C.MAGENTA)
    if log_handle:
        log_handle.write("=" * 60 + "\n")
        log_handle.write(f"auto-research-driver CI  -  {timestamp}\n")
        log_handle.write(f"SkillRoot={SKILL_ROOT}\n")
        log_handle.write(f"Python={PY}\n")
        log_handle.write(f"Mode={mode}\n")
        log_handle.write("=" * 60 + "\n")

    rc = 0

    # ---------------- step 0: preflight ----------------
    cprint("\n[step] step 0: preflight", C.YELLOW)
    if log_handle:
        log_handle.write("\n[step] step 0: preflight\n")
    if not PY.exists():
        cprint(f"[FAIL] Python not found at {PY}", C.RED)
        if log_handle: log_handle.close()
        return 2
    if not (SKILL_ROOT / "tests" / "test_state.py").exists():
        cprint("[FAIL] tests/test_state.py missing", C.RED)
        if log_handle: log_handle.close()
        return 2
    cprint("[CI] preflight OK", C.CYAN)
    if log_handle: log_handle.write("[CI] preflight OK\n")

    # ---------------- step 1: ensure coverage ----------------
    cprint("\n[step] step 1: ensure coverage installed", C.YELLOW)
    if log_handle: log_handle.write("\n[step] step 1: ensure coverage installed\n")
    try:
        import coverage  # noqa: F401
        cprint("[CI] coverage already installed", C.CYAN)
        if log_handle: log_handle.write("[CI] coverage already installed\n")
    except ImportError:
        cprint("[CI] installing coverage via pip --break-system-packages", C.CYAN)
        if log_handle: log_handle.write("[CI] installing coverage via pip --break-system-packages\n")
        rc = run_py(["-m", "pip", "install", "coverage", "--break-system-packages", "--quiet"],
                    "pip install coverage", log_file, log_handle)
        if rc != 0:
            cprint(f"[FAIL] pip install coverage (rc={rc})", C.RED)
            if log_handle: log_handle.close()
            return 3

    # ---------------- step 2: clean .coverage ----------------
    if not args.html_only:
        cov_file = SKILL_ROOT / ".coverage"
        if cov_file.exists():
            cov_file.unlink()
            cprint("[CI] removed old .coverage", C.CYAN)
            if log_handle: log_handle.write("[CI] removed old .coverage\n")

    # ---------------- step 3: unit tests + coverage ----------------
    # 用 --include 而非 --source：state.py 是 sys.path.insert 后 import，模块名是 state
    # 不是 scripts.state，所以 --source 匹配不上；--include glob 模式可以
    if not args.html_only:
        # 3.1: test_state.py — 覆盖 scripts/state.py
        rc = run_py(["-m", "coverage", "run",
                     "--include=scripts/state.py,scripts/provider_check.py,ci/verify_action_pin.py",
                     "--branch",
                     "tests/test_state.py"],
                    "step 3.1: coverage run test_state.py", log_file, log_handle)
        if rc != 0:
            cprint(f"[CI] FAIL: test_state.py (rc={rc})", C.RED)
            rc = 1
        else:
            cprint("[CI] test_state.py OK", C.GREEN)

        # 3.2: test_provider_check.py — 覆盖 scripts/provider_check.py
        rc2 = run_py(["-m", "coverage", "run",
                      "--include=scripts/state.py,scripts/provider_check.py,ci/verify_action_pin.py",
                      "--branch", "--append",
                      "tests/test_provider_check.py"],
                     "step 3.2: coverage run test_provider_check.py", log_file, log_handle)
        if rc2 != 0:
            cprint(f"[CI] FAIL: test_provider_check.py (rc={rc2})", C.RED)
            rc = 1
        else:
            cprint("[CI] test_provider_check.py OK", C.GREEN)

        # 3.3: test_verify_action_pin.py — 覆盖 ci/verify_action_pin.py
        rc3 = run_py(["-m", "coverage", "run",
                      "--include=scripts/state.py,scripts/provider_check.py,ci/verify_action_pin.py",
                      "--branch", "--append",
                      "tests/test_verify_action_pin.py"],
                     "step 3.3: coverage run test_verify_action_pin.py", log_file, log_handle)
        if rc3 != 0:
            cprint(f"[CI] FAIL: test_verify_action_pin.py (rc={rc3})", C.RED)
            rc = 1
        else:
            cprint("[CI] test_verify_action_pin.py OK", C.GREEN)

        rc4 = run_py(["-m", "coverage", "report", "-m"],
                     "step 3.4: coverage report -m", log_file, log_handle)
        if rc4 != 0:
            rc = 1

    # ---------------- step 4: smoke ----------------
    if not args.quick and not args.html_only:
        rc4 = run_py(["-u", "tests/smoke_test.py"],
                     "step 4: smoke_test.py (end-to-end integration)", log_file, log_handle)
        if rc4 != 0:
            cprint(f"[CI] FAIL: smoke_test.py (rc={rc4})", C.RED)
            rc = 1
        else:
            cprint("[CI] smoke_test.py OK", C.GREEN)

    # ---------------- step 5: HTML ----------------
    if (args.full or args.html_only) and rc == 0:
        rc5 = run_py(["-m", "coverage", "html", "-d", "htmlcov"],
                     "step 5: coverage html", log_file, log_handle)
        if rc5 != 0:
            rc = 1

    # ---------------- summary ----------------
    cprint("\n" + "=" * 60, C.MAGENTA)
    if rc == 0:
        cprint("  [CI] ALL GREEN  -  exit code 0", C.GREEN)
        cprint(f"  [CI] log: {log_file or '(no-log)'}", C.GREEN)
        if args.full or args.html_only:
            cprint(f"  [CI] HTML: {SKILL_ROOT}\\htmlcov\\index.html", C.GREEN)
        if log_handle:
            log_handle.write("\n[CI] ALL GREEN - exit code 0\n")
            log_handle.close()
        return 0
    else:
        cprint("  [CI] FAILED  -  exit code 1", C.RED)
        cprint(f"  [CI] log: {log_file or '(no-log)'}", C.RED)
        if log_handle:
            log_handle.write("\n[CI] FAILED - exit code 1\n")
            log_handle.close()
        return 1


if __name__ == "__main__":
    sys.exit(main())