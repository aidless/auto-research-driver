# auto-research-driver

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
python3 scripts/driver.py status        # state.json + pending checkpoints
```

> 说明：步骤 0–2 在任何机器离线可跑；步骤 3 的完整流水线依赖 SKILL.md `dependencies`
> 里登记的本地工作区，先把它们就位再 `run`。

## What is in here

| Path | Contents |
|---|---|
| [SKILL.md](SKILL.md) | the orchestration definition (stages, gates, alerts) |
| `.github/workflows/` | CI, the manual regression run, release, and the scan-alarm workflow |

The repository description records the last self-test result; check the workflows for
the current one rather than trusting a number in the description.

## License

MIT. See [LICENSE](LICENSE).
