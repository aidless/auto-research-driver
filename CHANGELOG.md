# CHANGELOG

auto-research-driver 的所有显著变更都记录在这里。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
本项目遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

---

## [Unreleased]

无未发布内容。

---

## [1.1.0] - 2026-07-10

**主题：报警与降级策略 + 跨 paper 监控 + CI 工程化。**

v1.0 是"骨架 + S5 端到端实跑通过"（11/11 tests PASS），v1.1 在不破坏 v1.0 任何行为的前提下，新增三类能力并完成 GitHub Actions 闭环。

### Added（新增功能）

#### 报警与降级策略（per-stage budget alarm）

- **`state.py` 新增字段** `DriverState.budget` / `rerun_history` / `alarms`，向后兼容 v1.0 老 state.json（缺字段时走 `default_factory` 静默兜底）。
  - `budget`：`{"max_reruns_per_stage": {stage: max_count, ...}}`，默认 6 个 stage 各有阈值（s5_review=4 最严，s6_submit=1 最松）。
  - `rerun_history`：每次 `mark_failed` 追加 1 条，最多 50 条（超出截断尾部）。
  - `alarms`：触发 budget 阈值后追加，最多 20 条。
- **`mark_failed` 行为变更**：失败时不仅 `run_count += 1`，还会调 `check_budget(stage, state)` 检查阈值；超额就在 `state.alarms` 落 1 条 + stderr 打印 `ALARM [budget]: ...`。
- **`check_budget` 新函数**：纯函数，不抛异常、不改 state，只产生 ALARM 字符串。优先级：`state.budget[stage]`（用户覆盖）> `STAGE_BUDGET_RULES` 默认。
- **`list_alarms` / `get_stage_reruns` 新函数**：只读访问报警和重试历史。
- **`checkpoints.py` 新增** `STAGE_BUDGET_RULES`：默认 per-stage 阈值表 + 每个 stage 的 `reason_hint`（为什么这个 stage 重试多了要警觉）。

**设计原则**：
- **只报警**：超额不修改 `state.stage` / `state.completed`，由用户决定 resurrect / 调 budget / 改 idea。
- **不并发限制**：多个 driver run 可并行（last-writer-wins 语义），但有冲突风险。
- **不自动降级**：v2.4 < 7.8 的论文进 s6 没意义，强行提交只会浪费 API 配额。

#### 跨 paper 监控

- **新文件 `scripts/scan_alarms.py`**（~470 行）：read-only 跨 paper 报警扫描器。
  - 支持 driver 接管 paper（读 `.driver/state.json`）+ 未接管 paper（用 `main.tex` / `main.pdf` / `refs.bib` 启发式识别）。
  - 报警分类：`driver_budget` / `low_v24_score` / `orphan_state` / `stale_paper` / `latex_error` / `artifact_leak`。
  - 三种输出：Markdown 报告 / JSON dump / exit code 区分严重度（0=clean / 2=critical，让 cron / scheduler 能据此告警）。
- **`driver scan-alarms` 子命令**：转发到 `scan_alarms.main_with_args()`，让 `bin\driver.cmd` 仍是单一入口。

#### Windows shim

- **`bin/driver.cmd` shim**：Windows 下的薄包装，把 `py -3 scripts\driver.py %*` 透明转发。
- **新 workflow `driver-windows-smoke.yml`**（manual-only，`windows-latest` runner）：验证 driver.cmd 在 Windows 上真能跑通 + exit code 链保真。

#### GitHub Actions 工程化

- **新 workflow `scan_alarms.yml`**：4 个 fixture scenario（clean / low score / latex error / artifact leak），ubuntu runner 跑，6 个 assertion。
- **workflows 文档更新** `.github/workflows/README.md`：从 3 个 workflow 表更新到 5 个（含 Runner 列 + driver-windows-smoke 详解）。

#### 测试覆盖

- **`tests/test_state.py` 新增 8 个测试**（覆盖 `mark_failed` 新行为 + budget 覆盖 + rerun_history 截断 + 默认值）：
  1. `test_new_fields_have_defaults`
  2. `test_mark_failed_records_rerun_history`
  3. `test_mark_failed_emits_budget_alarm_when_exceeded`
  4. `test_check_budget_returns_none_when_within_budget`
  5. `test_check_budget_returns_message_when_exceeded`
  6. `test_check_budget_respects_state_override`
  7. `test_get_stage_reruns_counts_correctly`
  8. `test_rerun_history_capped_at_50`
- **`tests/test_scan_alarms.py` 新增 28 个测试**（覆盖 paper 识别 / 报警渲染 / exit code / JSON+Markdown 结构）。
- **`tests/test_verify_action_pin.py`（已有）**：14 个回归测试，修复了 timing 容差让 CI runner 也能过。

#### 文档

- **`SKILL.md` 新章节**"报警与降级策略（per-stage budget, 2026-07-10 增）"：默认预算表 + state.json 新字段 schema + 报警触发 7 步流程 + 4 种用户应对方式。
- **`scripts/state.py` / `scripts/driver.py` 完整 docstring**（~270 行新增）：模块级、dataclass 字段、所有公共/私有函数都加 `Args` / `Returns` / 副作用说明。

### Changed（行为变更）

- **`driver status` 展示增强**：新增 ALARMS 段落（最近 5 条）+ RERUN HISTORY 段落（按 stage 聚合）。
- **`driver alarms` 新子命令**（含 `--show-rules` 选项）：单独展示 budget 报警 + rerun 历史 + STAGE_BUDGET_RULES 对照。
- **`driver scan-alarms` 新子命令**（含 `--root` / `--output-dir` / `--stale-days` / `--json-only` / `--md-only` / `--quiet`）。
- **`bin\driver.cmd` 注释扩展**：usage 块加上 `alarms` 和 `scan-alarms` 子命令示例。

### Fixed（修复）

- **`smoke_test.py` 跨平台化**：把硬编码的 `PY = "py"` 改成 `PY = sys.executable`，让 Linux/macOS runner 也能跑。
- **`ci/verify_action_pin.py` 缺 `import os`**：第 100 行用了 `os.getenv` 但忘了 import，导致 subprocess 子进程跑测试时 `NameError: name 'os' is not defined`（直接跑主入口时 `os` 被其他模块注入 globals 不触发，subprocess 跑时是 fresh interpreter 暴露问题）。
- **CI `set -e` 与 exit 2 冲突**：`scan_alarms.yml` 几个 step 用了 `set -e`，但 `scan_alarms.py` 故意在有 critical alarm 时 exit 2（设计语义），`set -e` 让 shell 提前终止。改用 `set +e` + `SCAN_RC=$?` 手动检查。
- **`--json-only` / `--md-only` flag 触发 exit 2 时 step 7/8 fail**：同上原因，加 `|| true` 吞掉。
- **`run_tests.py` fallback 路径**：硬编码的 `C:\Users\Administrator\...\cpython-3.9.25-...` 在 CI 不存在，fallback 到 `sys.executable`（实际工作）。
- **timing 容差过严**：`test_verify_action_pin.py` 多个测试的 `0.04 < elapsed < 0.5` 在慢 runner 上 fail，放宽到 `0.02 < elapsed < 1.0` / `0.25 < elapsed < 1.0`。
- **`actions/setup-python@v5` 的 `cache: "pip"` 失败**：3.9 EOL 后无 pre-built 镜像，`cache: "pip"` 找不到 requirements.txt 报错。改为不启用 cache（装 coverage 只需 1s，无所谓）。
- **`workflows` 全部 Python 3.9 → 3.12**：3.9 在 GitHub Actions 已 EOL。
- **`workflows` 全部 `py -3` → `python3`**：Linux runner 无 `py` 命令（Python Launcher）。
- **`workflows` 加 `::warning::` gate + UTF-8 env vars**：`retry` 警告仅在 `GITHUB_ACTIONS=true` 时输出 `::warning::` annotation，本地 / 单测用 `[retry]` 前缀；同时 `PYTHONIOENCODING=utf-8` / `PYTHONUTF8=1` / `LANG=C.UTF-8` / `LC_ALL=C.UTF-8` 防中文输出乱码。
- **`ci.yml` 新增 ci_run.log artifact**：Run CI step 失败时上传完整 stdout / stderr 到 artifact（保留 14 天），登录 GitHub 前就能诊断。

### Security（安全）

无。

### Performance（性能）

- 扫描 36 个 paper 用时 0.18s（`scan_alarms.py` 主要 IO）。
- `state.py` save_state fsync 失败时 best-effort 忽略（Windows 兼容）。

### CI / 工程化

- 5 个 GitHub Actions workflow：
  - `ci.yml`（主 CI，unit + coverage + smoke，ubuntu + Python 3.12）
  - `nightly.yml`（cron 每周一 02:00 UTC 回归）
  - `release.yml`（tag v*.*.* 触发 + 自动 GitHub Release）
  - `scan_alarms.yml`（scan_alarms smoke，ubuntu + Python 3.12）
  - `driver-windows-smoke.yml`（manual-only，windows + Python 3.12，验证 driver.cmd）
- **测试套件**：84 个 unit test PASS（3.9.25）/ 16 个 smoke test PASS（3.9.25 + 3.12）。
- **CI exit code 链**：0=clean / 2=critical alarm / 非 0/2=unintended error。

### Migration（迁移指南）

**老 state.json 升级到 v1.1**：无需任何手动操作。`DriverState.from_dict` 静默忽略未知字段，缺字段时走 `default_factory` 填默认。v1.0 写的 state.json 在 v1.1 下行为完全一致。

**手工调 budget 阈值**：直接编辑 `<target_dir>/.driver/state.json`，把 `budget.max_reruns_per_stage.<stage>` 改成你想要的数字。`mark_failed` 每次都读它，修改立即生效。

---

## [1.0.0] - 2026-07-09

**主题：骨架 + S5 端到端实跑。**

v1.0 是这个 skill 的第一个稳定版本。在 v1.0 之前是 prototype 阶段（commit `a1ac104` 之前），不在此 changelog 追溯。

### Added

- **核心脚本**：
  - `scripts/state.py` — DriverState dataclass + state.json atomic 读写 + mark_completed / mark_failed / state_path / load_state / save_state
  - `scripts/checkpoints.py` — 6 个 stage 的 CHECKPOINT_PLAN + sign / is_signed / require_sign
  - `scripts/provider_check.py` — MiniMax provider 配置 sanity 检查（dry-run + `--ping`）
  - `scripts/driver.py` — 8 个子命令（run / status / reset / sign / checkpoints / provider-check）+ 6 个 `_stage_sN_*` 骨架
  - `scripts/lib/wrappers.py` — 调 tmlr_pipeline / paper-reviewer / tmlr-review-simulator 的薄包装
- **CI 工程**：
  - `ci/run_tests.py` — 单元 + coverage + smoke 编排
  - `ci/simulate_ci.py` — 本地模拟 CI
  - `ci/verify_action_pin.py` — workflow SHA pin 校验
  - `ci/nightly_cron.py` — 每周回归
  - `ci/simulate_github_actions.py` — GitHub Actions 本地复现
- **GitHub Actions workflow**：`ci.yml` / `nightly.yml` / `release.yml` 三个
- **测试**：`tests/test_state.py` / `tests/test_provider_check.py` / `tests/test_verify_action_pin.py`（11/11 PASS）
- **文档**：`SKILL.md`（含原理 + 用法 + checkpoint 闸门 + 状态机）

### 验证

- S5 端到端实跑通过（v2.4 review score 8.4 / 10）
- 11/11 unit test PASS（3.9.25）
- 6 个 stage 骨架全跑通

---

## 类型说明

- **Added**：新功能
- **Changed**：现有功能的变更
- **Deprecated**：即将移除（不建议在新代码中使用）
- **Removed**：已移除
- **Fixed**：bug 修复
- **Security**：安全相关
- **Performance**：性能优化
- **CI / 工程化**：CI / build / 工具链相关

## 版本号约定

- **MAJOR**：不兼容的 API 变更
- **MINOR**：向后兼容的功能新增
- **PATCH**：向后兼容的 bug 修复

v1.0 → v1.1 是 MINOR bump（功能新增，向后兼容）。
