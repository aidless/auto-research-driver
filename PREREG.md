# 预注册规格（Preregistration）— auto-research-driver

> 本文件是 **auto-research-driver 的预注册/规格文档**，声明本仓在真实代码里
> 检验的研究假设、评测方案与成功标准，以及**明确的证明边界**。
> 一切陈述均对应仓库内真实可复算的实现（`scripts/`、`ci/`、`tests/`、`SKILL.md`）。

## 1. 研究问题（本仓回答什么）

本仓回答一个工程问题：**能否用一个"薄状态机 + 纯门控逻辑"的驱动层，
把已有的 TMLR 论文子流程（idea → lit review → outline → draft → 对抗自审 →
checklist）串成一条**可单测、可回滚、带预算报警**的端到端编排，而**不重新实现**
任何一段流水线逻辑？

这个问题是**真问题**：手写 TMLR 投稿是多周流水线，现有组件
（tmlr_pipeline / paper-writing-agent / paper-reviewer-tmlr-corpus /
tmlr-review-simulator / light-* skills）各管一段，但缺少把六段串起来、能记住
"哪段跑过、上次失败在哪、预算还剩多少"的编排层。本仓回答"这个编排层是否存在、
是否可测"。

## 2. 先验假设（声明：验证什么，不验证什么）

- **H1（编排层存在且薄）**：驱动层只做状态持久化、checkpoint 门控、回滚与预算
  报警，"做什么"全部委托给外部子系统（`scripts/lib/wrappers.py` 调用
  tmlr_pipeline / paper-writing-agent 等）。**本仓单独存在时没有论文产出**。
- **H2（checkpoint 是阻塞的）**：需要用户决策（`decision`）或需要用户确认机器报告
  （`confirm`）的阶段会暂停运行，直到用户通过 `driver sign` 签字。
- **H3（预算规则只报警、不自动降级）**：超过 per-stage max-rerun 上限只写
  `[budget]` 报警，**不自动** resurrect / 调预算 / 换 idea——决策权在人
  （fail-closed 边界）。
- **H4（状态持久化原子且可恢复）**：state.json 原子写、损坏自动备份并重建、
  `run_count` 递增、`run_count >= 3` 报警。

### 成功标准（可复算）

| 假设 | 成功判据 | 复算入口 |
|------|---------|---------|
| H1 | `scripts/lib/wrappers.py` 不含流水线重实现，只调外部组件 | `python -m pytest tests/ -q`（113 项通过） |
| H2 | checkpoint 规格在 `scripts/checkpoints.py:CHECKPOINT_PLAN`，阻塞语义有单测 | 同上 |
| H3 | `scripts/checkpoints.py:STAGE_BUDGET_RULES`（S1=2,S2=3,S3=2,S4=3,S5=4,S6=1），报警不降级有单测 | 同上 |
| H4 | `scripts/state.py` 损坏恢复/原子写/报警有单测 | 同上 |

## 3. 评测方案（如何判定成功）

**单元 + 集成测试套件**（`python -m pytest tests/ -q`，113 项）覆盖：

- `state.py`：save / load / mark-completed / mark-failed / corrupt-recovery /
  atomic-write / alarm-at-3 / next-stage / CLI。
- `provider_check.py`：provider 配置校验（防"配置错误却假装成功"）。
- `scan_alarms.py`：跨 paper 的 `[budget]` 报警扫描。
- `verify_action_pin.py`：action pin 校验。
- `driver.py`：S1–S6 编排 + 回滚到 last-safe-stage。

**CI 一键复现**：`python3 ci/run_tests.py`（unit + smoke + coverage），与 GitHub
Actions 行为一致；`ci/ci_test_ubuntu.sh` 用 `python:3.12-slim` Docker 模拟
ubuntu runner，本地可复现 CI 报错。

**归档基准**：`reports/TEST_REPORT_2026-07-10.md`（22/22 unit PASS，95%
line/branch coverage，7/7 smoke PASS，PAPER5_CONSOLIDATED S5 review 真实跑通，
simulator 处理 89k 字符 prompt）。**覆盖率数字来自该归档报告**，不是当前每次跑
都保证的数字。

## 4. 质量门与预算规则（真实值）

- S5 对抗自审循环执行 **质量门 v2.4 ≥ 7.8**（`scripts/checkpoints.py` 明言来自
  `TMLR_COMPARISON_REPORT` 前 10% 标准）；score < 7.8 触发 S4→S5 修订，
  ≥ 7.8 才进 S6。
- per-stage budget：`STAGE_BUDGET_RULES = {S1:2, S2:3, S3:2, S4:3, S5:4, S6:1}`
  （max-rerun cap，超限写 `[budget]` 报警）。
- S6 **只生成 checklist，不真投递**（`scripts/driver.py` docstring 明言
  "S6 只生成 checklist，不真投递"）；S6 是决策点，用户最终签字才真投递。

## 5. 明确边界（证明什么 / 不证明什么）

**本仓证明（可复算工程事实）：**

1. 一个 stateful 驱动层能串起 6 阶段，checkpoint 门控 / per-stage budget 报警 /
   失败回滚均为**可单测的纯逻辑**（113 项测试）。
2. budget 规则**只报警、不自动降级**——机器替用户记住"失败几次"，不替用户
   决定 resurrect / 调 budget / 改 idea（fail-closed 边界）。
3. provider 配置与 action pin 有独立校验，防"配置错误却假装成功"。
4. 状态持久化原子 + 可恢复：坏状态文件被检测、备份、从空状态重建，不静默丢数据。

**本仓不证明（边界）：**

- **不证明任何一篇论文会中 TMLR**：本仓只编排到 S6 生成 checklist，不真投递。
- **不证明 idea 一定是 top 1% novelty**：novelty 是 S1 checkpoint 必须人工拍板
  的，机器只生成候选 + 5 维评分（≥ 7.0/10 默认阈值），不替人判断。
- **不证明 7.8 质量门是校准过的绝对分**：7.8（前 10%）来自
  `TMLR_COMPARISON_REPORT.md` 历史比较，是相对 band 而非外部基准校准的绝对度量。
- **不证明本仓自带 TMLR 流水线**：driver 是编排薄壳，真正 pipeline 逻辑在外部
  依赖里；本仓单独存在时只有状态机 + 门控 + 报警，没有论文产出。

## 6. 已知限制

- 测试依赖是**可选的**（`requirements.txt` 全部在 try/except ImportError 或函数
  体内，缺了也能跑）。
- 覆盖率数字（95%）来自 2026-07-10 归档报告，不是当前每次跑都保证的数字。
- 依赖指向本机路径（`F:\Research\...`、`C:\Users\Administrator\.mavis\skills\...`），
  换机器需按 `SKILL.md` 的 `dependencies` 重新指向。
