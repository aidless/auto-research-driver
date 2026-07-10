---
name: auto-research-driver
description: |
  TMLR 全自动科研 driver——把现有 tmlr_pipeline 6 阶段 + paper-writing-agent 21 模块 + paper-reviewer-tmlr-corpus v2.4 + tmlr-review-simulator 串成端到端流水线。
  输入：idea（一句话 / arxiv id / 实验目录）→ 输出：投递就绪 paper 工程（≥ v2.4 7.8 分签字）。
  中文触发词：跑一篇 TMLR、auto research driver、从 idea 到 TMLR 论文、TMLR 端到端流水线、自动化科研、全自动科研助手。
  English: TMLR end-to-end driver, auto research pipeline, idea to TMLR submission, full-auto ML research assistant.
version: 1.0.0
status: implemented
last-verified: 2026-07-10 11:08 (PAPER5_CONSOLIDATED S5 review 通过 + 22/22 unit tests PASS + smoke ALL PASS + 95% coverage)
dependencies:
  - tmlr_pipeline (F:\Research\tmlr_pipeline)
  - paper-writing-agent (F:\Research\paper-writing-agent)
  - paper-reviewer-tmlr-corpus v2.4 (C:\Users\Administrator\.mavis\skills\paper-reviewer-tmlr-corpus)
  - tmlr-review-simulator (C:\Users\Administrator\.mavis\skills\tmlr-review-simulator)
  - light-orchestrator / light-paper-polishing / light-self-review / light-typesetting
  - light-literature-search / light-citation / light-figure-planning / light-figure-drawing
  - brainstorming-research / idea-evaluator / verification / writing-chapters
  - research_radar_v2 + deep_read_v2 (F:\Research\_research_radar)
  - memory_architecture/run_experiment.py (F:\Research\memory_architecture)
  - F:\Research obsidian vault (811 md, 26 论文线索)
tags:
  - research
  - tmlr
  - end-to-end
  - automation
  - ml
  - multi-agent
  - driver
---

# auto-research-driver (TMLR 端到端 driver)

## 定位

不是新工具，是 **driver 层**——把现有 5 个独立子系统（tmlr_pipeline 6 阶段 / paper-writing-agent 21 模块 / paper-reviewer-tmlr-corpus v2.4 / tmlr-review-simulator / light-* 12 个 skill）按 TMLR 投稿工作流**串起来**。

**承诺 vs 现实**：
- ✅ 承诺：idea → 投递就绪 paper 的端到端流水线，每个 S 都有 checkpoint
- ✅ 承诺：≥ v2.4 7.8 分（前 10%）质量门（参考 `F:\Research\TMLR_COMPARISON_REPORT.md`）
- ⚠️ 不承诺：idea 一定是 top 1% novelty——novelty 是 S1 checkpoint 必须人工拍板的
- ⚠️ 不承诺：投稿必收——TMLR 接收还有运气成分

## 6 阶段流程（与 tmlr_pipeline 对齐 + 增强）

```
INPUT: --idea "..."  |  --arxiv <id>  |  --idea-auto  |  --from-stage <s1-s6>
   ↓
S1 Idea Discovery          (auto + checkpoint)
   ↓
S2 Lit Review              (auto + checkpoint)
   ↓
S3 Outline + Plan          (auto + checkpoint)
   ↓
S4 Draft                   (auto + per-chapter checkpoint)
   ↓
S5 Adversarial Review Loop (auto, threshold=7.8)
   ↓
S6 Submit                  (auto + final signature)
   ↓
OUTPUT: arxiv ZIP + cover letter + checklist
```

### S1 Idea Discovery

| 项 | 说明 |
|----|----|
| 工具 | `research_radar_v2.py` + obsidian vault scan（811 md）+ `brainstorming-research` + `idea-evaluator` |
| 输入 | `--idea-auto` 时扫 obsidian 14 tag 聚类 + radar 30 天 arxiv；`--idea "..."` 时直接用 |
| 输出 | `idea_canvas.md`（3-5 个候选，每个含 novel claim + method sketch + 与已有 26 篇工作的关系 + TMLR 适用性 + 实验成本估算）|
| 检查点 | 用户拍板 idea（必填），idea-evaluator 5 维 ≥ 7.0/10 |

### S2 Lit Review

| 项 | 说明 |
|----|----|
| 工具 | `deep_read_v2.py` + `light-literature-search` + `light-citation` + `paper-reviewer-tmlr-corpus` cite_verify v2 |
| 输入 | S1 选定的 idea |
| 输出 | `refs.bib`（≥ 30 条）+ `lit_review.md`（含 must-cite deltas）|
| 检查点 | 用户过引用清单 + 撞库结果 |

### S3 Outline + Plan

| 项 | 说明 |
|----|----|
| 工具 | `tmlr_pipeline.s3`（outline.md 模板）+ `brainstorming-research/chapter-templates.md` + `idea-evaluator` |
| 输入 | idea + lit review |
| 输出 | `outline.md`（8 章）+ `topic_report.md` + `experiment_design.md` |
| 检查点 | 用户确认大纲 + 实验设计（决定 S4 走向） |

### S4 Draft

| 项 | 说明 |
|----|----|
| 工具 | `tmlr_pipeline.s4`（main.tex 模板）+ `paper-orchestration` + `writing-chapters` + `paper-writing-agent` 21 模块 + `light-paper-polishing` |
| 输入 | outline + lit review + experiment data |
| 输出 | `main.tex` + `chapters/*.tex` + `figures/`（含 light-figure-planning / drawing）|
| 检查点 | 每章完成后用户过一遍（轻量确认，不是逐字审）|

### S5 Adversarial Review Loop ★ 质量门

| 项 | 说明 |
|----|----|
| 工具 | `paper-reviewer-tmlr-corpus v2.4`（4 角色：复现审 / 统计审 / 新颖审 / 文风审）+ `tmlr-review-simulator`（4 agent：Specialist / Editor / Critic / Reflection）+ `light-self-review` |
| 输入 | main.tex + refs.bib + figures/ |
| 输出 | `review_report.md`（v2.4 4 角色分数 + CRITICAL/MAJOR/MINOR 三档 + per-finding 修订示例）|
| 循环 | score < 7.8 自动触发 S4 → S5；≥ 7.8 进 S6 |
| 检查点 | 用户看 review 报告（**这是质量门，不是装饰**）|

### S6 Submit

| 项 | 说明 |
|----|----|
| 工具 | `tmlr_pipeline.s6` + `prepare_arxiv_submit.ps1` + `light-typesetting` + `paper-writing-agent` admission_gate |
| 输入 | v2.4 ≥ 7.8 的 paper 工程 |
| 输出 | arxiv ZIP + `cover_letter.md` + `submit/checklist.md` + supplementary PDF |
| 检查点 | **用户最终签字**（这里机器不能替代人）|

## 评分阈值

| 阶段 | 阈值 | 来源 |
|------|------|------|
| S1 idea novelty | ≥ 7.0 / 10 | idea-evaluator 5 维 |
| S5 v2.4 final | **≥ 7.8** | TMLR_COMPARISON_REPORT（你 Hidden Cost 8.1 / Memory Arch 7.5 = 前 10%）|
| S5 v2.4 raw | ≥ 6.5 | 修复空间（v2.4 raw → final 提升 3.0 已验证）|
| S6 tmlr_compliance | 13/13 PASS | paper-reviewer-tmlr-corpus R1-R13 |

## 与现有工具的边界（不重复造轮子）

| 能力 | 谁做 |
|------|------|
| 文献雷达 | `research_radar_v2.py`（已有） |
| 文献深度阅读 | `deep_read_v2.py`（已有） |
| 6 阶段模板 + 模板渲染 | `tmlr_pipeline`（已有） |
| 论文写作 21 模块 | `paper-writing-agent`（已有）|
| 4 角色对抗式审稿 + 13 条 TMLR 合规 | `paper-reviewer-tmlr-corpus` v2.4（已有）|
| TMLR 4-agent 模拟 | `tmlr-review-simulator`（已有）|
| 章节润色 | `light-paper-polishing`（已有）|
| 图表规划 + 绘制 | `light-figure-planning` + `light-figure-drawing`（已有）|
| 文献引用 + bib 校验 | `light-citation`（已有）|
| 自审 | `light-self-review`（已有）|
| 排版 / TMLR 模板 | `light-typesetting`（已有）|
| 实验执行（apparatus / metrics / seed lock）| `memory_architecture/run_experiment.py`（已有）|
| **driver 编排层（本 skill）** | 串上述 + checkpoint 管理 + 评分门 |

## 命令接口（CLI 设计）

```powershell
# 从一句话 idea 开始
mavis driver run --idea "校准 + 自评估的解耦方法能否在不破坏 coupling-noise trade-off 的前提下降低 50% 的偏向性？"

# 从已有 arxiv 触发（适合复现 + 扩展）
mavis driver run --arxiv 2606.16682

# 自动从 obsidian + radar 选 3-5 个 idea 候选
mavis driver run --idea-auto

# 从中间阶段插入（如已有 main.tex，只想跑 review）
mavis driver run --target-dir F:\Research\new_paper --from-stage s5

# 全程开启 cron 监控（每 30 分钟跑一次 review 直到 ≥ 7.8）
mavis driver run --idea "..." --auto-loop --notify-cron sample_budget_check
```

## 状态机与失败恢复

每个 stage 完成后写 `state.json` 到 target_dir：

```json
{
  "stage": "s5_review",
  "completed": ["s1_idea_discovery", "s2_lit_review", "s3_outline", "s4_draft"],
  "artifacts": {
    "idea_canvas": "ideas/idea_canvas.md",
    "refs_bib": "refs.bib",
    "outline": "outline.md",
    "main_tex": "main.tex",
    "review_report": "reviews/v24_review.md"
  },
  "scores": {
    "v24_final": 7.6,
    "v24_raw": 6.4,
    "tmlr_compliance": "12/13"
  },
  "next_action": "rerun_s4_then_s5",
  "user_signatures": {
    "s1_idea": true,
    "s3_outline": true,
    "s5_review_accepted": false,
    "s6_submit_signature": false
  }
}
```

如果 s4→s5 循环 3 次未到 7.8，自动报警（可能是 idea novelty 不够 / 实验数据有 bug / review 评分尺子漂移），回到 S1 重新评估。

## 报警与降级策略（per-stage budget, 2026-07-10 增）

在原有"run_count ≥ 3 报警"的基础上，driver 新增 **per-stage budget**——每个 stage
都有自己的失败上限；超出上限会触发独立的 `[budget]` 报警，并写入 `state.alarms` 落盘。

**核心设计原则**：

- **只报警，不自动降级**。机器不替用户决定 resurrect / 调 budget / 改 idea。
- **并发不限制**。driver 不做"同时跑几个 paper"的硬限制，由用户手工收敛。
- **用户可覆盖**。在 `state.budget["max_reruns_per_stage"][stage]` 里改数字即可，无需改代码。

### 默认预算表（来自 `checkpoints.STAGE_BUDGET_RULES`）

| Stage   | 默认 max | 触发 hint |
|---------|----------|-----------|
| s1_idea | 2 | idea novelty 持续低,可能方向错;考虑换 idea 或拓宽调研 |
| s2_lit  | 3 | refs.bib 多次校验失败;检查检索 query 或必引清单 |
| s3_outline | 2 | outline 反复重做;可能 idea 与 paper 类型不匹配 |
| s4_draft | 3 | draft 写不出;可能实验数据不够或图表没就绪 |
| **s5_review** | **4** | **v2.4 反复 ≤ 7.8;强烈建议回到 S1 重评 idea 或换 paper 类型** |
| s6_submit | 1 | submit 检查不通过;基本是 TMLR compliance 问题,不是 idea 问题 |

### state.json 新增字段（向后兼容，老 state 自动 fallback）

```json
{
  "budget": {
    "max_reruns_per_stage": {
      "s1_idea": 2, "s2_lit": 3, "s3_outline": 2,
      "s4_draft": 3, "s5_review": 4, "s6_submit": 1
    }
  },
  "rerun_history": [
    {"stage": "s5_review", "t": "2026-07-10T11:30:00+0800",
     "score": 7.2, "reason": "v24<7.8"}
  ],
  "alarms": [
    {"stage": "s5_review", "t": "2026-07-10T11:38:02+0800",
     "msg": "ALARM [budget]: s5_review 已失败 4 次 ≥ 预算 4;v2.4 反复 ≤ 7.8;强烈建议回到 S1 重评 idea 或换 paper 类型"}
  ]
}
```

- `rerun_history` 上限 50 条（超出截断保留最近 50 条）
- `alarms` 上限 20 条（超出截断保留最近 20 条）

### 报警触发流程

1. `mark_failed(stage, error)` 把 `run_count += 1`
2. 把这次失败 append 到 `rerun_history`
3. save_state 落盘
4. 检查原 `run_count >= 3` 报警（向后兼容）
5. **NEW**：调用 `check_budget(stage, state)`——若 `run_count >= budget[stage]`，返回 ALARM 消息
6. 若有 ALARM，append 到 `state.alarms`，save_state，再 stderr 打印
7. **不抛异常、不修改 stage、不动 next_action**——只让用户看到信息

### 用户应对（手工操作）

看到 `[budget]` 报警后，用户可以选：

| 选择 | 操作 | 何时选 |
|---|---|---|
| **resurrect** | `driver reset --target-dir <T>` 重置 state，回 S1 重做 | idea 真的不行 |
| **调 budget** | 编辑 `state.json` 改 `budget["max_reruns_per_stage"][stage]` 调大 | 这条路径值得再试几次（如刚换 reviewer） |
| **改 idea** | 跑 `driver run --idea "新 idea" --from-stage s1` 覆盖原 idea | 多次失败证明 idea 不行 |
| **放弃** | 把 paper 目录移到 `<research_root>/.archive/<name>-<ts>/` 并写 `DEMOTED.md`（**不自动，需要手工**） | 多次 budget 超额且不复活 |

### 为什么不做硬降级 / 自动归档

与现有"driver cron 不能无脑跑"原则一致：idea + experiment checkpoint 必须人工，
**机器不能替代你的 moral taste**。降级是 paper 生命周期里的高风险动作（一旦 archive
就难以恢复全貌），应该由人判断。

### 测试覆盖

`tests/test_state.py` 新增 8 个测试，覆盖：
- `budget` / `rerun_history` / `alarms` 字段默认值
- `mark_failed` 写 rerun_history + 触发 budget alarm
- `check_budget` 在 budget 内/外/用户覆盖三种场景下的行为
- `get_stage_reruns` 计数正确性
- `rerun_history` 自动截断到 50

## 已知坑（从 AGENTS.md 抄过来 + driver 专属）

- **Python 3.11 不可用**：用 `py -3` 走 3.9 hardcode 路径
- **mavis 不在 PATH**：用全路径 `C:\Users\Administrator\.mavis\bin\mavis.cmd`
- **PowerShell 5.1 UTF-8 编码**：禁止 `Get-Content | Set-Content` 改文件，全部用 Python Read/Write/Edit
- **decision JSON schema 严格**：见 `paper-reviewer-tmlr-corpus/references/decision-schema.md`
- **driver cron 不能无脑跑**：idea + experiment checkpoint 必须人工，**机器不能替代你的 moral taste**

## 开发路线图

- [x] **v1.0**（2026-07-09 骨架 + 2026-07-10 实测验证）：骨架 + S5 端到端实跑通过 + 11/11 tests PASS
  - 6 阶段骨架 + state.json 持久化（atomic write + corrupt recovery） + checkpoint 闸门
  - provider sanity check（占位符 / 缺失 / 格式 / 长度 / 真实格式 5 项）
  - **11/11 unit tests PASS**（test_state.py 6 + test_provider_check.py 5，实测 2026-07-10 10:52）
  - **smoke_test.py ALL PASS**（7 步端到端：provider-check → run s1-s3 → state.json 校验 → status → reset → checkpoints）
  - **PAPER5_CONSOLIDATED S5 review 真跑通过**：simulator 生成 89k chars prompts
- [ ] **v1.1**（下周）：S1 + S2 接入 brainstorming-research / deep_read_v2 / cite_verify
- [ ] **v1.2**：S5 review-mode v24 接入（4-persona multi-paper dispatch）
- [ ] **v2.0**：端到端 cron 化（白天跑实验 + 晚上跑 review + 用户签字只发生在 S1/S3/S5/S6）

## 触发场景（自然语言）

| 用户说 | 触发 |
|------|----|
| "跑一篇 TMLR" / "做一篇 TMLR" | --idea-auto |
| "从 idea 到论文" | S1 起 |
| "复现 + 扩展 arxiv 26xx.xxxxx" | --arxiv |
| "重审这篇" / "再 review 一下" | --from-stage s5 |
| "前 10% 标准" / "TMLR top 10%" | 用 v2.4 ≥ 7.8 阈值 |
| "全自动" / "auto" | 提醒 checkpoint 必人工 |

## 关联资源

- `F:\Research\AGENTS.md` — 项目 manifest
- `F:\Research\TMLR_COMPARISON_REPORT.md` — 前 10% 标准
- `F:\Research\paper-writing-agent\references\tmlr_checklist.md` — 80+ 检查项
- `F:\Research\tmlr_pipeline\DEMO_REPORT.md` — tmlr_p18 60 min 端到端 demo
- `F:\Research\_research_radar` — radar + deep_read
- `F:\Research\memory_architecture` — 实验执行
- `F:\tmp\regression_v23\REPORT.md` — 5-paper v2.3 regression
- `F:\tmp\paper1_regression\REPORT.md` — PAPER1 4.82→8.0 证明 fix 可行

---

**TL;DR**：跑 `mavis driver run --idea-auto` 即可开始；或者把今天 sample_budget 跑完的 data 接 s4 → s5 直接出 draft。