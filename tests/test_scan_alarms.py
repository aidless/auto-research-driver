"""test_scan_alarms.py - scan_alarms.py 单元测试

风格对齐同目录 test_state.py：plain assert + sys.exit，零 pytest 装饰，
但兼容 pytest 自动收集（pytest 收集时这些函数被识别为 test_* 自动跑）。

覆盖目标：
- Paper 识别（is_paper_dir）
- Driver paper 扫描（state.json 加载 + alarms 透传 + v24 分数检测）
- Broad paper 扫描（stale / latex_error / artifact_leak）
- Markdown 渲染（总览表 + 完整清单表 + 备注）
- JSON 渲染（summary + papers 字段）
- Exit code（n_critical == 0 → 0, 否则 2）

跑法：
  py -3 tests/test_scan_alarms.py          # standalone
  pytest tests/test_scan_alarms.py -v      # via pytest
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

from scan_alarms import (  # noqa: E402
    Alarm,
    PaperScan,
    PAPER_MARKERS,
    is_paper_dir,
    safe_load_state,
    collect_papers,
    scan_driver_paper,
    scan_broad_paper,
    scan_all,
    render_markdown,
    render_json,
    LATEX_ERROR_PATTERN,
)


# ---------- helpers ----------

def make_state_json(target: Path, *, stage="s5_review", completed=None,
                    run_count=0, v24=None, alarms=None):
    """造一个 state.json 到 target/.driver/state.json。"""
    if completed is None:
        completed = ["s1_idea", "s2_lit", "s3_outline", "s4_draft"]
    if alarms is None:
        alarms = []
    d = target / ".driver"
    d.mkdir(parents=True, exist_ok=True)
    state = {
        "stage": stage,
        "completed": completed,
        "artifacts": {"main_tex": str(target / "main.tex")},
        "scores": {} if v24 is None else {"v24_final": v24},
        "next_action": "rerun_s5_review_then_resume" if stage == "s5_review" else "",
        "user_signatures": {},
        "last_error": None,
        "run_count": run_count,
        "created_at": "2026-07-10T11:00:00+0800",
        "updated_at": "2026-07-10T11:00:00+0800",
        "budget": {"max_reruns_per_stage": {
            "s1_idea": 2, "s2_lit": 3, "s3_outline": 2,
            "s4_draft": 3, "s5_review": 4, "s6_submit": 1,
        }},
        "rerun_history": [],
        "alarms": alarms,
    }
    (d / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2),
                                  encoding="utf-8")


# ---------- Paper 识别 ----------

def test_is_paper_dir_detects_by_state_json():
    """有 .driver/state.json 的目录 → 是 paper。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "paper_a"
        p.mkdir()
        (p / ".driver" / "state.json").parent.mkdir(parents=True, exist_ok=True)
        (p / ".driver" / "state.json").write_text("{}", encoding="utf-8")
        assert is_paper_dir(p) is True


def test_is_paper_dir_detects_by_main_tex():
    """有 main.tex 的目录 → 是 paper（即使没有 state.json）。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "paper_b"
        p.mkdir()
        (p / "main.tex").write_text("% tex", encoding="utf-8")
        assert is_paper_dir(p) is True


def test_is_paper_dir_detects_by_refs_bib():
    """有 refs.bib 的目录 → 是 paper。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "paper_c"
        p.mkdir()
        (p / "refs.bib").write_text("% refs", encoding="utf-8")
        assert is_paper_dir(p) is True


def test_is_paper_dir_rejects_plain_dir():
    """没有任何 marker 的目录 → 不是 paper。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "not_a_paper"
        p.mkdir()
        (p / "random.txt").write_text("hi", encoding="utf-8")
        assert is_paper_dir(p) is False


def test_collect_papers_picks_only_matching_dirs():
    """collect_papers 应只挑 paper 目录，跳过无关目录。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # paper
        p1 = root / "p1"; p1.mkdir(); (p1 / "main.tex").write_text("x", encoding="utf-8")
        # paper (state)
        p2 = root / "p2"; p2.mkdir(); (p2 / ".driver").mkdir(); (p2 / ".driver" / "state.json").write_text("{}", encoding="utf-8")
        # not paper
        p3 = root / "not_paper"; p3.mkdir(); (p3 / "data.csv").write_text("a,b", encoding="utf-8")
        papers = collect_papers(root)
        names = sorted(p.name for p in papers)
        assert names == ["p1", "p2"]


# ---------- safe_load_state ----------

def test_safe_load_state_returns_dict_for_valid():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "state.json"
        p.write_text('{"stage": "s1_idea"}', encoding="utf-8")
        d = safe_load_state(p)
        assert d == {"stage": "s1_idea"}


def test_safe_load_state_returns_none_for_corrupt():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "state.json"
        p.write_text('{this is not json', encoding="utf-8")
        assert safe_load_state(p) is None


def test_safe_load_state_returns_none_for_missing():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "state.json"  # 不创建
        assert safe_load_state(p) is None


# ---------- Driver paper 扫描 ----------

def test_scan_driver_paper_passes_through_alarms():
    """driver paper 的 state.json.alarms 应被透传到 scan.alarms。"""
    with tempfile.TemporaryDirectory() as td:
        target = Path(td)
        target.joinpath("main.tex").write_text("% tex", encoding="utf-8")
        make_state_json(
            target,
            stage="s5_review",
            run_count=4,
            v24=7.4,
            alarms=[{
                "stage": "s5_review",
                "t": "2026-07-10T11:00:00+0800",
                "msg": "ALARM [budget]: s5_review 已失败 4 次 ≥ 预算 4",
            }],
        )
        s = scan_driver_paper(target)
        assert s.has_state is True
        assert s.has_main_tex is True
        assert s.current_stage == "s5_review"
        assert s.run_count == 4
        assert s.v24_score == 7.4
        # 至少有 driver_budget 报警(可能还有 low_v24_score)
        categories = [a.category for a in s.alarms]
        assert "driver_budget" in categories


def test_scan_driver_paper_emits_low_v24_score():
    """v24_score < 7.8 应产生 low_v24_score 报警。"""
    with tempfile.TemporaryDirectory() as td:
        target = Path(td)
        target.joinpath("main.tex").write_text("% tex", encoding="utf-8")
        make_state_json(target, stage="s5_review", v24=7.5)
        s = scan_driver_paper(target)
        cats = [a.category for a in s.alarms]
        assert "low_v24_score" in cats
        low = [a for a in s.alarms if a.category == "low_v24_score"][0]
        assert "7.5" in low.msg and "7.8" in low.msg


def test_scan_driver_paper_no_low_score_when_above_threshold():
    """v24_score >= 7.8 不应触发 low_v24_score。"""
    with tempfile.TemporaryDirectory() as td:
        target = Path(td)
        target.joinpath("main.tex").write_text("% tex", encoding="utf-8")
        make_state_json(target, stage="s5_review", v24=8.1)
        s = scan_driver_paper(target)
        cats = [a.category for a in s.alarms]
        assert "low_v24_score" not in cats


def test_scan_driver_paper_corrupt_state_marks_orphan():
    """state.json 损坏时应有 orphan_state 报警（critical）。"""
    with tempfile.TemporaryDirectory() as td:
        target = Path(td)
        (target / ".driver").mkdir()
        (target / ".driver" / "state.json").write_text("garbage", encoding="utf-8")
        s = scan_driver_paper(target)
        cats = [a.category for a in s.alarms]
        assert "orphan_state" in cats
        orphan = [a for a in s.alarms if a.category == "orphan_state"][0]
        assert orphan.severity == "critical"


def test_scan_driver_paper_run_count_3_no_budget_alarm_still_warns():
    """run_count ≥ 3 但 budget alarm 列表为空时，应给一条 warning（run_count 老报警）。

    场景：用户把 budget 调大（比如 s5_review 改成 50），所以 budget ALARM 不触发；
    但 run_count 已经 ≥ 3 老阈值，应当用 warning 提示用户留意。
    """
    with tempfile.TemporaryDirectory() as td:
        target = Path(td)
        target.joinpath("main.tex").write_text("% tex", encoding="utf-8")
        make_state_json(target, run_count=3, alarms=[])  # 没 budget alarm
        s = scan_driver_paper(target)
        # 应有 warning 级别的 driver_budget，提示 run_count ≥ 3 但 budget 没触发
        warn_alarms = [a for a in s.alarms
                       if a.category == "driver_budget" and a.severity == "warning"]
        assert len(warn_alarms) >= 1, "应至少有 1 条 warning 级别 driver_budget"
        assert "run_count=3" in warn_alarms[0].msg


# ---------- Broad paper 扫描 ----------

def test_scan_broad_paper_detects_stale():
    """main.tex mtime 超过 stale_days → stale_paper warning。"""
    with tempfile.TemporaryDirectory() as td:
        target = Path(td)
        tex = target / "main.tex"
        tex.write_text("% tex", encoding="utf-8")
        # 把 mtime 改成 60 天前
        old = (datetime.now() - timedelta(days=60)).timestamp()
        import os
        os.utime(tex, (old, old))
        s = scan_broad_paper(target, stale_days=30)
        cats = [a.category for a in s.alarms]
        assert "stale_paper" in cats
        stale = [a for a in s.alarms if a.category == "stale_paper"][0]
        assert "60" in stale.msg
        assert stale.severity == "warning"


def test_scan_broad_paper_fresh_no_stale_alarm():
    """最近修改的 paper 不应有 stale_paper。"""
    with tempfile.TemporaryDirectory() as td:
        target = Path(td)
        (target / "main.tex").write_text("% tex", encoding="utf-8")
        s = scan_broad_paper(target, stale_days=30)
        cats = [a.category for a in s.alarms]
        assert "stale_paper" not in cats


def test_scan_broad_paper_detects_latex_error():
    """log 文件含 '! LaTeX Error' → latex_error critical。"""
    with tempfile.TemporaryDirectory() as td:
        target = Path(td)
        (target / "main.tex").write_text("% tex", encoding="utf-8")
        log = target / "main.log"
        log.write_text(
            "This is pdfTeX, Version 3.141592653\n"
            "! LaTeX Error: Missing \\begin{document}.\n"
            "l.10 \\foo\n",
            encoding="utf-8",
        )
        s = scan_broad_paper(target, stale_days=30)
        cats = [a.category for a in s.alarms]
        assert "latex_error" in cats
        le = [a for a in s.alarms if a.category == "latex_error"][0]
        assert le.severity == "critical"
        assert "main.log" in le.msg


def test_scan_broad_paper_detects_artifact_leak():
    """残留 .aux / .bbl / _fix_*.py → artifact_leak info。"""
    with tempfile.TemporaryDirectory() as td:
        target = Path(td)
        (target / "main.tex").write_text("% tex", encoding="utf-8")
        (target / "main.aux").write_text("aux", encoding="utf-8")
        (target / "main.bbl").write_text("bbl", encoding="utf-8")
        (target / "_fix_typo.py").write_text("# fix", encoding="utf-8")
        s = scan_broad_paper(target, stale_days=30)
        cats = [a.category for a in s.alarms]
        assert "artifact_leak" in cats
        leak = [a for a in s.alarms if a.category == "artifact_leak"][0]
        assert leak.severity == "info"
        assert "3" in leak.msg  # 3 个残留


def test_scan_broad_paper_clean_returns_no_alarms():
    """只有 main.tex + 没 log + 没 leak → 0 alarm。"""
    with tempfile.TemporaryDirectory() as td:
        target = Path(td)
        (target / "main.tex").write_text("% tex", encoding="utf-8")
        s = scan_broad_paper(target, stale_days=30)
        assert s.alarms == []


# ---------- 渲染: Markdown ----------

def test_render_markdown_includes_header():
    md = render_markdown([], Path("/tmp"), 30)
    assert "# 多 Paper 流水线报警汇总报告" in md
    assert "扫描根目录" in md
    assert "Stale 阈值" in md


def test_render_markdown_marks_clean_when_no_alarms():
    md = render_markdown([], Path("/tmp"), 30)
    assert "✓ 所有 paper 健康" in md


def test_render_markdown_includes_alarm_table_when_present():
    p = PaperScan(name="TEST_PAPER", path="/tmp/TEST_PAPER",
                  has_state=False, has_main_tex=True, has_main_pdf=False,
                  has_refs_bib=False, last_modified=None,
                  alarms=[Alarm("critical", "latex_error", "TEST_PAPER", "x")])
    md = render_markdown([p], Path("/tmp"), 30)
    assert "TEST_PAPER" in md
    assert "latex_error" in md
    assert "critical" in md
    assert "🔴" in md


def test_render_markdown_includes_complete_paper_table():
    """无论有无 alarm，完整 paper 清单表都应渲染。"""
    p = PaperScan(name="AAA", path="/tmp/AAA", has_state=True, has_main_tex=True,
                  has_main_pdf=True, has_refs_bib=True, last_modified=None,
                  current_stage="s5_review", completed_stages=["s1", "s2", "s3"],
                  run_count=2, v24_score=7.5,
                  alarms=[Alarm("warning", "low_v24_score", "AAA", "v24=7.5<7.8")])
    md = render_markdown([p], Path("/tmp"), 30)
    assert "## 完整 Paper 清单" in md
    assert "`AAA`" in md
    assert "| Paper | Driver | main.tex | main.pdf | refs.bib |" in md


# ---------- 渲染: JSON ----------

def test_render_json_structure():
    p = PaperScan(name="BBB", path="/tmp/BBB", has_state=False, has_main_tex=True,
                  has_main_pdf=False, has_refs_bib=False, last_modified=None,
                  alarms=[Alarm("critical", "latex_error", "BBB", "x")])
    j = render_json([p], Path("/tmp"), 30)
    assert "scan_meta" in j
    assert "summary" in j
    assert "papers" in j
    assert j["scan_meta"]["n_papers"] == 1
    assert j["summary"]["by_severity"]["critical"] == 1
    assert j["summary"]["papers_with_alarms"] == 1
    assert j["papers"][0]["name"] == "BBB"
    assert j["papers"][0]["alarms"][0]["category"] == "latex_error"


def test_render_json_handles_empty():
    j = render_json([], Path("/tmp"), 30)
    assert j["scan_meta"]["n_papers"] == 0
    assert j["summary"]["by_severity"] == {}
    assert j["papers"] == []


# ---------- 端到端: scan_all + exit code ----------

def test_scan_all_picks_driver_and_broad():
    """scan_all 同时识别 driver paper 和 broad paper。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # driver paper (有 state + main.tex + 报警)
        dp = root / "dp"; dp.mkdir()
        (dp / "main.tex").write_text("% tex", encoding="utf-8")
        make_state_json(dp, run_count=4, v24=7.4,
                        alarms=[{"stage": "s5_review", "t": "t", "msg": "alarm msg"}])
        # broad paper with latex error
        bp = root / "bp"; bp.mkdir()
        (bp / "main.tex").write_text("% tex", encoding="utf-8")
        (bp / "main.log").write_text("! LaTeX Error: foo\n", encoding="utf-8")
        # plain dir (not a paper)
        np = root / "np"; np.mkdir(); (np / "x.txt").write_text("hi", encoding="utf-8")

        results = scan_all(root, stale_days=30)
        names = sorted(r.name for r in results)
        assert names == ["bp", "dp"]
        # dp has driver_budget
        dp_scan = [r for r in results if r.name == "dp"][0]
        assert any(a.category == "driver_budget" for a in dp_scan.alarms)
        # bp has latex_error
        bp_scan = [r for r in results if r.name == "bp"][0]
        assert any(a.category == "latex_error" for a in bp_scan.alarms)


def test_cli_exit_code_zero_when_clean():
    """没有 critical alarm 时 exit code 应为 0。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # 一个干净的 broad paper
        p = root / "clean_paper"; p.mkdir()
        (p / "main.tex").write_text("% tex", encoding="utf-8")
        out = Path(td) / "alarms_out"
        r = subprocess.run(
            [sys.executable,
             str(HERE.parent / "scripts" / "scan_alarms.py"),
             "--root", str(root),
             "--output-dir", str(out),
             "--quiet"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
        # 产物应存在
        assert (out / "REPORT.md").exists()
        assert (out / "alarms_latest.json").exists()


def test_cli_exit_code_two_when_critical():
    """有 critical alarm 时 exit code 应为 2。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / "broken_paper"; p.mkdir()
        (p / "main.tex").write_text("% tex", encoding="utf-8")
        (p / "main.log").write_text("! LaTeX Error: missing\n", encoding="utf-8")
        out = Path(td) / "alarms_out"
        r = subprocess.run(
            [sys.executable,
             str(HERE.parent / "scripts" / "scan_alarms.py"),
             "--root", str(root),
             "--output-dir", str(out),
             "--quiet"],
            capture_output=True, text=True,
        )
        assert r.returncode == 2, f"expected 2, got {r.returncode}; stderr={r.stderr}"
        # JSON 应包含 critical
        j = json.loads((out / "alarms_latest.json").read_text(encoding="utf-8"))
        assert j["summary"]["by_severity"].get("critical", 0) >= 1


def test_cli_md_only_skips_json():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / "p"; p.mkdir()
        (p / "main.tex").write_text("% tex", encoding="utf-8")
        out = Path(td) / "out"
        r = subprocess.run(
            [sys.executable,
             str(HERE.parent / "scripts" / "scan_alarms.py"),
             "--root", str(root),
             "--output-dir", str(out),
             "--md-only", "--quiet"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0
        assert (out / "REPORT.md").exists()
        # 没有时间戳 json（只有 md_only 模式）
        json_files = list(out.glob("alarms_*.json"))
        assert json_files == []


# ---------- 入口 ----------

def main():
    tests = [
        # Paper 识别
        test_is_paper_dir_detects_by_state_json,
        test_is_paper_dir_detects_by_main_tex,
        test_is_paper_dir_detects_by_refs_bib,
        test_is_paper_dir_rejects_plain_dir,
        test_collect_papers_picks_only_matching_dirs,
        # safe_load_state
        test_safe_load_state_returns_dict_for_valid,
        test_safe_load_state_returns_none_for_corrupt,
        test_safe_load_state_returns_none_for_missing,
        # Driver paper 扫描
        test_scan_driver_paper_passes_through_alarms,
        test_scan_driver_paper_emits_low_v24_score,
        test_scan_driver_paper_no_low_score_when_above_threshold,
        test_scan_driver_paper_corrupt_state_marks_orphan,
        test_scan_driver_paper_run_count_3_no_budget_alarm_still_warns,
        # Broad paper 扫描
        test_scan_broad_paper_detects_stale,
        test_scan_broad_paper_fresh_no_stale_alarm,
        test_scan_broad_paper_detects_latex_error,
        test_scan_broad_paper_detects_artifact_leak,
        test_scan_broad_paper_clean_returns_no_alarms,
        # Markdown 渲染
        test_render_markdown_includes_header,
        test_render_markdown_marks_clean_when_no_alarms,
        test_render_markdown_includes_alarm_table_when_present,
        test_render_markdown_includes_complete_paper_table,
        # JSON 渲染
        test_render_json_structure,
        test_render_json_handles_empty,
        # 端到端
        test_scan_all_picks_driver_and_broad,
        test_cli_exit_code_zero_when_clean,
        test_cli_exit_code_two_when_critical,
        test_cli_md_only_skips_json,
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