"""test_scan_alarms_imports.py — in-process coverage for the 3 refactored entry points

test_scan_alarms.py covers data-model functions via subprocess (CLI invocation).
The 3 new entry points added in the refactor (_build_argparser, main_with_args,
main) are not in-process tested there, so coverage.py sees them as missing.

This file fills that gap by importing the module and exercising those 3 functions
directly. Result: scripts/scan_alarms.py coverage rises from ~80% to ~95%.

Same plain-assert + sys.exit style as test_scan_alarms.py.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

# 把 scripts/ 加进 sys.path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import scan_alarms  # noqa: E402

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
# 1. _build_argparser() — 14 行全在内存中测
# ============================================================

def test_build_argparser_returns_argumentparser():
    ap = scan_alarms._build_argparser()
    check("_build_argparser returns ArgumentParser",
          isinstance(ap, argparse.ArgumentParser))


def test_build_argparser_has_all_six_flags():
    ap = scan_alarms._build_argparser()
    # parse empty argv 不会 fail (没有 required 参数)
    args = ap.parse_args([])
    check("--root flag exists", hasattr(args, "root"))
    check("--output-dir flag exists", hasattr(args, "output_dir"))
    check("--stale-days flag exists", hasattr(args, "stale_days"))
    check("--json-only flag exists", hasattr(args, "json_only"))
    check("--md-only flag exists", hasattr(args, "md_only"))
    check("--quiet flag exists", hasattr(args, "quiet"))


def test_build_argparser_defaults():
    ap = scan_alarms._build_argparser()
    args = ap.parse_args([])
    check("default --root = DEFAULT_RESEARCH_ROOT",
          args.root == scan_alarms.DEFAULT_RESEARCH_ROOT,
          f"got {args.root}")
    check("default --output-dir = DEFAULT_OUTPUT_DIR",
          args.output_dir == scan_alarms.DEFAULT_OUTPUT_DIR,
          f"got {args.output_dir}")
    check("default --stale-days = 30",
          args.stale_days == 30,
          f"got {args.stale_days}")
    check("default --json-only = False", args.json_only is False)
    check("default --md-only = False", args.md_only is False)
    check("default --quiet = False", args.quiet is False)


# ============================================================
# 2. main_with_args() — 不走 subprocess，直接 in-process 调用
# ============================================================

def test_main_with_args_root_not_found_returns_1():
    """If --root doesn't exist, exit 1 with error message to stderr."""
    fake_root = Path(tempfile.gettempdir()) / "definitely_does_not_exist_xyz_123"
    # 先确保不存在
    if fake_root.exists():
        fake_root.rmdir()
    args = argparse.Namespace(
        root=fake_root,
        output_dir=Path(tempfile.mkdtemp()),
        stale_days=30,
        json_only=False, md_only=False, quiet=True,
    )
    buf = io_stringio()  # 用我们自己的 helper
    with redirect_stderr(buf):
        rc = scan_alarms.main_with_args(args)
    check("main_with_args returns 1 for missing root", rc == 1,
          f"got {rc}")
    check("stderr mentions root",
          "root not found" in buf.getvalue())


def test_main_with_args_clean_empty_root():
    """Empty root dir → 0 papers → rc=0, no JSON, no MD."""
    empty = Path(tempfile.mkdtemp(prefix="sa_test_empty_"))
    out = Path(tempfile.mkdtemp(prefix="sa_test_out_"))
    args = argparse.Namespace(
        root=empty, output_dir=out, stale_days=30,
        json_only=False, md_only=False, quiet=True,
    )
    rc = scan_alarms.main_with_args(args)
    check("empty root → rc=0", rc == 0, f"got {rc}")
    # 双输出都该有
    check("alarms_latest.json written", (out / "alarms_latest.json").exists())
    check("REPORT.md written", (out / "REPORT.md").exists())


def test_main_with_args_json_only():
    """--json-only 应只写 .json, 不写 .md"""
    empty = Path(tempfile.mkdtemp(prefix="sa_test_json_"))
    out = Path(tempfile.mkdtemp(prefix="sa_test_out_"))
    args = argparse.Namespace(
        root=empty, output_dir=out, stale_days=30,
        json_only=True, md_only=False, quiet=True,
    )
    rc = scan_alarms.main_with_args(args)
    check("json-only → rc=0", rc == 0, f"got {rc}")
    check("alarms_latest.json exists", (out / "alarms_latest.json").exists())
    check("REPORT.md NOT written",
          not (out / "REPORT.md").exists())


def test_main_with_args_md_only():
    """--md-only 应只写 .md, 不写 .json"""
    empty = Path(tempfile.mkdtemp(prefix="sa_test_md_"))
    out = Path(tempfile.mkdtemp(prefix="sa_test_out_"))
    args = argparse.Namespace(
        root=empty, output_dir=out, stale_days=30,
        json_only=False, md_only=True, quiet=True,
    )
    rc = scan_alarms.main_with_args(args)
    check("md-only → rc=0", rc == 0, f"got {rc}")
    check("REPORT.md exists", (out / "REPORT.md").exists())
    check("alarms_latest.json NOT written",
          not (out / "alarms_latest.json").exists())


def test_main_with_args_critical_returns_2():
    """有 critical (latex_error) 的 fixture → rc=2"""
    root = Path(tempfile.mkdtemp(prefix="sa_test_crit_"))
    out = Path(tempfile.mkdtemp(prefix="sa_test_out_"))
    # 建一个 latex 错误的 paper
    p = root / "PAPER_FAIL"
    p.mkdir()
    (p / "main.tex").touch()
    (p / "main.log").write_text(
        "This is pdfTeX\n! LaTeX Error: missing.sty not found.\n",
        encoding="utf-8",
    )
    args = argparse.Namespace(
        root=root, output_dir=out, stale_days=30,
        json_only=True, md_only=False, quiet=True,
    )
    rc = scan_alarms.main_with_args(args)
    check("critical detected → rc=2", rc == 2, f"got {rc}")


def test_main_with_args_clean_paper_returns_0():
    """完全干净的 fixture → rc=0"""
    root = Path(tempfile.mkdtemp(prefix="sa_test_clean_"))
    out = Path(tempfile.mkdtemp(prefix="sa_test_out_"))
    # 干净 paper (driver 接管, v24=9.0, 0 alarms)
    p = root / "PAPER_CLEAN" / ".driver"
    p.mkdir(parents=True)
    (p / "state.json").write_text(json.dumps({
        "stage": "s6_submit",
        "completed": ["s1_idea", "s2_lit", "s3_outline", "s4_draft", "s5_review", "s6_submit"],
        "alarms": [],
        "scores": {"v24_final": 9.0},
        "run_count": 0,
    }), encoding="utf-8")
    (root / "PAPER_CLEAN" / "main.tex").touch()

    args = argparse.Namespace(
        root=root, output_dir=out, stale_days=30,
        json_only=True, md_only=False, quiet=True,
    )
    rc = scan_alarms.main_with_args(args)
    check("clean paper → rc=0", rc == 0, f"got {rc}")
    data = json.loads((out / "alarms_latest.json").read_text(encoding="utf-8"))
    check("clean paper → n_papers=1", data["scan_meta"]["n_papers"] == 1)
    check("clean paper → 0 alarms", data["summary"]["papers_with_alarms"] == 0)


def test_main_with_args_quiet_suppresses_stdout():
    """--quiet=True 时不应打印摘要到 stdout"""
    root = Path(tempfile.mkdtemp(prefix="sa_test_q_"))
    out = Path(tempfile.mkdtemp(prefix="sa_test_out_"))
    args = argparse.Namespace(
        root=root, output_dir=out, stale_days=30,
        json_only=False, md_only=False, quiet=True,
    )
    buf = io_stringio()
    with redirect_stdout(buf):
        scan_alarms.main_with_args(args)
    output = buf.getvalue()
    check("quiet=True 抑制 [scan_alarms] 摘要行",
          "[scan_alarms]" not in output,
          f"stdout 仍然包含 [scan_alarms]: {output[:200]}")


def test_main_with_args_not_quiet_prints_summary():
    """--quiet=False 时应打印摘要到 stdout"""
    root = Path(tempfile.mkdtemp(prefix="sa_test_nq_"))
    out = Path(tempfile.mkdtemp(prefix="sa_test_out_"))
    args = argparse.Namespace(
        root=root, output_dir=out, stale_days=30,
        json_only=False, md_only=False, quiet=False,
    )
    buf = io_stringio()
    with redirect_stdout(buf):
        scan_alarms.main_with_args(args)
    output = buf.getvalue()
    check("quiet=False 打印 [scan_alarms] 摘要",
          "[scan_alarms]" in output,
          f"stdout 没有 [scan_alarms]: {output[:200]}")


# ============================================================
# 3. main() — parse_args + main_with_args 组合
# ============================================================

def test_main_parses_argv_and_calls_main_with_args(monkeypatch_helper=None):
    """main() 解析 sys.argv 后调用 main_with_args()"""
    # 在临时目录准备空 root
    root = Path(tempfile.mkdtemp(prefix="sa_test_main_"))
    out = Path(tempfile.mkdtemp(prefix="sa_test_out_"))

    # 备份并替换 sys.argv
    saved_argv = sys.argv
    sys.argv = ["scan_alarms", "--root", str(root),
                "--output-dir", str(out), "--quiet", "--json-only"]
    try:
        rc = scan_alarms.main()
    finally:
        sys.argv = saved_argv

    check("main() with --json-only returns 0", rc == 0, f"got {rc}")
    check("alarms_latest.json exists", (out / "alarms_latest.json").exists())
    check("REPORT.md NOT written (--json-only)",
          not (out / "REPORT.md").exists())


# ============================================================
# helper
# ============================================================

def io_stringio():
    """避免与 builtin 冲突的本地 import."""
    import io
    return io.StringIO()


# ============================================================
# main runner
# ============================================================

def main():
    tests = [
        test_build_argparser_returns_argumentparser,
        test_build_argparser_has_all_six_flags,
        test_build_argparser_defaults,
        test_main_with_args_root_not_found_returns_1,
        test_main_with_args_clean_empty_root,
        test_main_with_args_json_only,
        test_main_with_args_md_only,
        test_main_with_args_critical_returns_2,
        test_main_with_args_clean_paper_returns_0,
        test_main_with_args_quiet_suppresses_stdout,
        test_main_with_args_not_quiet_prints_summary,
        test_main_parses_argv_and_calls_main_with_args,
    ]

    print(f"=== running {len(tests)} in-process tests ===\n")
    for t in tests:
        try:
            t()
        except Exception as e:
            check(f"{t.__name__} (uncaught exception)", False,
                  f"{type(e).__name__}: {e}")
        print()

    print("=" * 60)
    print(f"summary: {PASS} passed, {FAIL} failed")
    if FAIL == 0:
        print("ALL IN-PROCESS TESTS PASSED")
        return 0
    print("FAILED TESTS:")
    for f in FAILS:
        print(f"  - {f}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
