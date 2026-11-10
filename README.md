# auto-research-driver

[![CI](https://github.com/aidless/auto-research-driver/actions/workflows/ci.yml/badge.svg)](https://github.com/aidless/auto-research-driver/actions/workflows/ci.yml)
[![checks](https://github.com/aidless/auto-research-driver/actions/workflows/checks.yml/badge.svg)](https://github.com/aidless/auto-research-driver/actions/workflows/checks.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> 🗂 **仓库族谱**：「自主研究循环」主线仓是 [ai-researcher](https://github.com/aidless/ai-researcher)；本仓定位是 TMLR 端到端 driver 层（agent skill，串 tmlr_pipeline / paper-writing-agent 等 5 个子系统）。

An orchestration skill that drives the stages of a TMLR paper from S1 to S6, with
budget alerts so a run stops before it spends more than intended.

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
