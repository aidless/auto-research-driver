# auto-research-driver

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

An orchestration **skill / driver layer** that drives the stages of a TMLR paper
from S1 to S6, with checkpoint gates between stages and per-stage budget alerts
so a run stops (or at least warns) before it spends more than intended.

## 解决了什么问题 / 为什么重要

Writing a TMLR submission by hand is a long, multi-week pipeline: idea discovery,
lit review, outline, draft, an adversarial self-review loop, and submission
packaging. Existing pieces (tmlr_pipeline, paper-writing-agent,
paper-reviewer-tmlr-corpus, tmlr-review-simulator, the light-* skills) each solve
one slice, but nothing **orchestrates** them into one runnable end-to-end flow —
so the human has to remember which stage ran, what failed last time, and how much
budget is left. This repo is that missing orchestration layer.

## 我用了什么方法

The design is **stateful driver + pure gate logic**, deliberately thin:

- **Driver is a thin stateful shell** (`scripts/driver.py`). It owns (1) provider
  sanity check, (2) `state.json` persistence, (3) checkpoint gates, (4) rollback
  to the last safe stage on failure. All "what to do" is delegated to
  `lib/wrappers.py`, which calls the existing subsystems — the driver does **not**
  reimplement the TMLR pipeline.
- **Stages are sequential** (run in `STAGES_ORDER`, one completes before the next
  starts), and **checkpoints are blocking** (`scripts/checkpoints.py`): a stage
  that needs a user decision (`decision`) or a machine report the user must ack
  (`confirm`) pauses the run until the user signs via `driver sign`.
- **Per-stage budget** (`scripts/checkpoints.py:STAGE_BUDGET_RULES`): each stage
  has a max-rerun cap (S1=2, S2=3, S3=2, S4=3, S5=4, S6=1). Exceeding it raises
  a `[budget]` alarm written to `state.alarms` — **alarm only, never auto-demote**;
  the human decides whether to raise the budget, re-run, or demote the paper.
- **Fail-closed state persistence** (`scripts/state.py`): atomic write (no leftover
  `.json.tmp`), corrupt-JSON recovery to `.json.corrupt` + fresh state, `run_count`
  increments on failure, and alarm on `run_count >= 3`.

## 结果如何

- **Unit + integration suite: 113 tests pass** (`python -m pytest tests/ -q`),
  covering `state.py` (save/load/mark-completed/mark-failed/corrupt-recovery/
  atomic-write/alarm-at-3/next-stage/CLI), `provider_check.py`,
  `scan_alarms.py`, `verify_action_pin.py`, and `driver.py` orchestration.
- **Historical verified run** (2026-07-10, archived report
  `reports/TEST_REPORT_2026-07-10.md`): 22/22 unit PASS, **95% line/branch
  coverage** (state.py 96%, provider_check.py 93%), 7/7 smoke steps PASS, and an
  end-to-end real run of **PAPER5_CONSOLIDATED S5 review** passed (simulator
  processed 89k chars of prompts).
- The S5 adversarial review loop enforces a **quality gate of v2.4 ≥ 7.8**
  (top-10% band per `TMLR_COMPARISON_REPORT.md`); score < 7.8 auto-triggers
  S4→S5 revision, ≥ 7.8 advances to S6.

## 本仓证明了什么 / 不证明什么

**证明了什么（可复算的工程事实）：**

- 一个 **stateful 驱动层**能串起 6 阶段，且 checkpoint 门控、per-stage budget
  报警、失败回滚都作为**可单测的纯逻辑**实现（113 项测试，见上）。
- **budget 规则只报警、不自动降级**：机器替用户记住"这个 stage 失败几次了"，
  但**不替用户决定** resurrect / 调 budget / 改 idea。这是 fail-closed 边界——
  决策权始终在人。
- **provider 配置与 action pin 有独立校验**（`scripts/provider_check.py`、
  `ci/verify_action_pin.py`），防止"配置错误却假装成功"。
- 状态持久化是**原子 + 可恢复**的：写坏状态文件会被检测、备份、从空状态重建，
  不静默丢数据。

**不证明什么（边界）：**

- **不证明任何一篇论文会中 TMLR**。本仓只编排到"S6 生成 checklist"——**S6 不真
  投递**（`scripts/driver.py` docstring 明言"S6 只生成 checklist，不真投递"）。
  接收还有运气成分，本仓不承诺投稿必收。
- **不证明 idea 一定是 top 1% novelty**：novelty 是 S1 checkpoint 必须人工拍板
  的，机器只生成候选 + 5 维评分（≥ 7.0/10 默认阈值），不替人判断。
- **不证明质量门 7.8 是校准过的绝对分**：7.8 分（前 10%）来自
  `TMLR_COMPARISON_REPORT.md` 的历史比较，是**相对 band** 而非经外部基准校准的
  绝对质量度量。
- **不证明本仓自带 TMLR 流水线**：driver 是编排薄壳，真正的 pipeline 逻辑在
  tmlr_pipeline / paper-writing-agent 等**外部依赖**里。本仓单独存在时只有
  状态机 + 门控 + 报警，没有论文产出。
- 测试依赖是 **可选的**（`requirements.txt` 全部在 try/except ImportError 或
  函数体内，缺了也能跑）；覆盖率数字（95%）来自 2026-07-10 的归档报告，不是
  当前每次跑都保证的数字。

## 复算

```bash
# 全部 113 项测试（Linux / Windows 通用，无外部 API 调用）
python -m pytest tests/ -q

# CI 一键复现（unit + coverage + smoke），与 GitHub Actions 行为一致
python3 ci/run_tests.py            # 默认：unit + smoke + coverage
python3 ci/run_tests.py --full     # 加 HTML 覆盖率报告
```

- `ci/run_tests.py` 是**唯一推荐 CI 入口**（纯 Python，避免 Trae IDE 的
  `safe_rm_aliases.ps1` hook 拦截 PowerShell 变量）。
- `ci/ci_test_ubuntu.sh` 用 `python:3.12-slim` Docker 镜像模拟 GitHub Actions
  ubuntu runner，失败时本地可重现 CI 报错，不用反复 push。
- 归档的 22/22 + 95% + 7/7 smoke 数字出自 `reports/TEST_REPORT_2026-07-10.md`
  （2026-07-10 11:09，Python 3.9.25 + coverage 7.x）；仓库描述里的 self-test
  数字可能过时，**以 workflow 当前运行结果为准**（见"诚实边界"）。

## 目录结构

```
auto-research-driver/
├── SKILL.md                  # 编排定义（6 阶段 / checkpoint / budget / 报警降级策略）
├── scripts/
│   ├── driver.py             # 主入口：run/status/reset/sign/checkpoints/alarms/scan-alarms/provider-check
│   ├── state.py              # state.json 持久化（原子写 + 损坏恢复 + run_count + 报警）
│   ├── checkpoints.py        # CHECKPOINT_PLAN + STAGE_BUDGET_RULES（门控规格）
│   ├── scan_alarms.py        # 跨多 paper 的 [budget] 报警扫描
│   ├── provider_check.py     # MiniMax provider 配置校验
│   └── lib/wrappers.py       # 调既有组件的薄封装（不实现流水线逻辑）
├── bin/driver.cmd            # Windows 入口（与 scripts/driver.py 子命令同步）
├── tests/                    # 113 项：state / provider_check / scan_alarms / verify_action_pin / driver / smoke
├── ci/                       # run_tests.py + ci_test_ubuntu.sh（一键复现 CI）
├── reports/TEST_REPORT_2026-07-10.md   # 归档测试报告（22/22 + 95% + 7/7）
├── .github/workflows/        # CI / 手动回归 / release / scan-alarm / Windows smoke
├── .gitleaks.toml            # secret 扫描配置
└── references/               # 参考文档（README）
```

## Usage

This is an agent skill, not a library: point your agent at
[SKILL.md](SKILL.md), which defines the stages, the gates between them, and the budget
thresholds.

## What is in here

| Path | Contents |
|---|---|
| [SKILL.md](SKILL.md) | the orchestration definition (stages, gates, alerts) |
| `.github/workflows/` | CI, the manual regression run, release, and the scan-alarm workflow |

The repository description records the last self-test result; check the workflows for
the current one rather than trusting a number in the description.

## License

MIT. See [LICENSE](LICENSE).
