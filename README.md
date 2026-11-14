# auto-research-driver

> **English TL;DR**: An orchestration skill that drives a TMLR paper through six gated stages (S1–S6) with explicit human decision/confirmation checkpoints. The offline CLI, checkpoint specs and provider check were executed locally for this pass; the full pipeline was **NOT YET MEASURED** here because it needs external workspaces and a configured provider.

[![CI](https://github.com/aidless/auto-research-driver/actions/workflows/ci.yml/badge.svg)](https://github.com/aidless/auto-research-driver/actions/workflows/ci.yml)
[![checks](https://github.com/aidless/auto-research-driver/actions/workflows/checks.yml/badge.svg)](https://github.com/aidless/auto-research-driver/actions/workflows/checks.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> 🗂 **仓库族谱**：「自主研究循环」主线仓是 [ai-researcher](https://github.com/aidless/ai-researcher)；本仓定位是 TMLR 端到端 driver 层（agent skill，串 tmlr_pipeline / paper-writing-agent 等 5 个子系统）。

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

## Quickstart

```bash
git clone https://github.com/aidless/auto-research-driver.git && cd auto-research-driver

# 0) 入口自检（零外部依赖，离线可跑）
python3 scripts/driver.py --help

# 1) 看 S1–S6 六个阶段各自的 checkpoint 规格（决策点/确认点/签字命令）
python3 scripts/driver.py checkpoints

# 2) MiniMax 网关体检（可选 --ping 实测连通性）
python3 scripts/provider_check.py

# 3) 让 agent 读 SKILL.md 接管流水线；真正 run 需要下述 dependencies
#    列出的工作区（tmlr_pipeline / paper-writing-agent / light-* 等，见 SKILL.md frontmatter）
python3 scripts/driver.py run --idea "your idea in one sentence"
python3 scripts/driver.py status --target-dir <T>   # state.json + pending checkpoints
```

> 说明：步骤 0–2 在任何机器离线可跑；步骤 3 的完整流水线依赖 SKILL.md `dependencies`
> 里登记的本地工作区，先把它们就位再 `run`。

> **实测（2026-11-10）**：步骤 0 输出 usage 与 8 个子命令（run/status/reset/sign/checkpoints/alarms/scan-alarms/provider-check）；步骤 1 打印 S1–S6 全部 6 个 checkpoint 的决策点/确认点/签字命令；步骤 2 在本机如实报 `FAIL: config.yaml 没有 provider.minimax 段（~/.mavis/config.yaml）`——provider_check 依赖 `~/.mavis/config.yaml` 里的 `provider.minimax` 段，没配就该报 FAIL，这是正确的 fail-closed 行为而非命令损坏。

## Pipeline stages（S1–S6，摘自 SKILL.md，以原文为准）

一句话 idea / arXiv id 进，投递就绪的 paper 工程出；**每个 S 都有 checkpoint，机器不能替你拍板的地方写明了必须人工**（完整定义见 [SKILL.md](SKILL.md)）：

| Stage | 一句话 | 产出 | Checkpoint（谁签字） |
|---|---|---|---|
| S1 Idea Discovery | 扫 obsidian 聚类 + radar arXiv，产出 3–5 个候选 idea（novel claim + method sketch + TMLR 适用性 + 成本估算） | `idea_canvas.md` | **用户拍板 idea**（决策点；idea-evaluator 5 维 ≥ 7.0/10） |
| S2 Lit Review | deep-read + 引用校验，攒参考文献 | `refs.bib`（≥30 条）+ `lit_review.md` | 用户过引用清单（确认点） |
| S3 Outline + Plan | 8 章大纲 + 实验设计 | `outline.md` + `experiment_design.md` | **用户确认大纲与实验设计**（决策点，决定 S4 走向） |
| S4 Draft | 按模板逐章起草 + 出图 | `main.tex` + `chapters/*.tex` + `figures/` | 每章轻量确认（非逐字审） |
| S5 Adversarial Review Loop ★质量门 | 4 角色 review + 4 agent 模拟，分数 < 7.8 自动回 S4 重写 | `review_report.md`（CRITICAL/MAJOR/MINOR 三档） | 用户看 review 报告（阈值 v2.4 ≥ 7.8） |
| S6 Submit | 打包 arXiv ZIP + cover letter + checklist | `arxiv ZIP` + `cover_letter.md` + `submit/checklist.md` | **用户最终签字**（机器不能替代） |

预算与报警：每个 stage 有 per-stage budget 规则（`checkpoints.STAGE_BUDGET_RULES`），超限触发报警与降级策略，详见 SKILL.md「报警与降级策略」一节。

## What is in here

| Path | Contents |
|---|---|
| [SKILL.md](SKILL.md) | the orchestration definition (stages, gates, alerts) |
| `.github/workflows/` | CI, the manual regression run, release, and the scan-alarm workflow |

The repository description records the last self-test result; check the workflows for
the current one rather than trusting a number in the description.

## License

MIT. See [LICENSE](LICENSE).

## U1 live recompute (executed 2026-11-11)

The S1–S6 table above is a **specification** of checkpoints, not measured
results. The table below records what was actually executed in this pass.

| Live check | Value | Source |
|---|---|---|
| `driver.py --help` subcommands | 8 (`run`, `status`, `reset`, `sign`, `checkpoints`, `alarms`, `scan-alarms`, `provider-check`) | live `python3 scripts/driver.py --help` (exit 0) |
| `driver.py checkpoints` entries | 6 (S1–S6) | live `python3 scripts/driver.py checkpoints` (exit 0) |
| `provider_check.py` | `FAIL: config.yaml 没有 provider.minimax 段` | live exit 1: `FAIL: config.yaml 没有 provider.minimax 段（/home/liuzewen/.mavis/config.yaml）` |

Checkpoint specs as printed live:

| Checkpoint | Type | Decision / confirmation point |
|---|---|---|
| `s1_idea` | decision | S1 决策点：idea 拍板 |
| `s2_lit` | confirm  | S2 确认点：refs.bib 校验通过 |
| `s3_outline` | decision | S3 决策点：outline + 实验设计拍板 |
| `s4_draft` | confirm  | S4 确认点：每章完成后过一遍 |
| `s5_review` | confirm  | S5 质量门：v2.4 ≥ 7.8 才能进 S6 |
| `s6_submit` | decision | S6 决策点：用户最终签字（机器不能替代） |

Historical test report (committed, not re-run in this pass):

| Metric | Value | Source (path:line) |
|---|---|---|
| Unit tests | `单元测试通过率  22/22 PASS (100%)  100%  ✅` | `reports/TEST_REPORT_2026-07-10.md:14` |
| Integration smoke | `集成 smoke  7/7 步 PASS  全部通过  ✅` | `reports/TEST_REPORT_2026-07-10.md:16` |

**NOT YET MEASURED**: an end-to-end S1→S6 run. The driver needs the
`SKILL.md` dependency workspaces and a working MiniMax provider; the live
provider check above fails honestly, so no stage result is claimed.

Quickstart commands actually executed for this pass:

```bash
python3 scripts/driver.py --help        # exit 0, 8 subcommands
python3 scripts/driver.py checkpoints  # exit 0, 6 checkpoints
python3 scripts/provider_check.py      # exit 1 (missing provider.minimax config)
```

<!-- figure: pending real measurement -->

## 验收题库与复算

`eval/cases.jsonl` 是 **20 条（n=20）** 可执行验收题，覆盖九个口径：`state/schema`
（stage 顺序与推进）、`state/persist`（首次加载 / 损坏恢复 / 原子写）、
`checkpoints/gate`（decision/confirm 分布、未签列表）、`budget/alarm`（默认预算一致性、
s6 预算=1 的报警条数）、`provider/key`（占位符拒绝）、`scan/detect`（paper 识别、
7.8 质量门报警）、`wrappers/paths`（paper 名推导）、`driver/cli`（`--stale-days`
默认值）、`docs/spec`（README 与代码口径一致）。

构成：**16 条 `expr` + 2 条 `raises` + 2 条 `doc`**。expr/raises 全部真调本仓 API
（`scripts/state.py`、`scripts/checkpoints.py`、`scripts/provider_check.py`、
`scripts/scan_alarms.py`、`scripts/lib/wrappers.py`），期望值是现跑出来的，不是抄文档。

```bash
python3 eval/run_cases.py            # 通过条件：20/20 cases passed（pass_rate = 1.0）
python3 eval/run_cases.py --save     # 顺带把结果写进 eval/run-report.json
python3 eval/run_cases.py --selftest # 篡改一条期望值，必须变红（19/20）
```

**数字如何复算**：`eval/run-report.json` 里每条 case 都带 `id` / `axis` / `detail`，
把 `detail` 与 `cases.jsonl` 的 `verify` 代码一起看，就能从源码复现该数字；
`--save` 重跑一次即可重建整份报告，不需要手工抄数。

**失败归因**：`run_cases.py` 不只报通过率，失败时按 `axis` 汇总（例如
`state/schema: 1 条 —— ST-01`），直接指出是哪个模块的哪个口径坏了。
