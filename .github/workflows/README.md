# auto-research-driver GitHub Actions Workflows

本目录包含 5 个 GitHub Actions workflow：

| Workflow | 触发 | 用途 | Runner | 频率 |
|----------|------|------|--------|------|
| `ci.yml` | push / PR / manual | **主 CI** — 跑单元 + 集成 + coverage + HTML | ubuntu | 每次 commit |
| `nightly.yml` | cron 每周一 02:00 UTC / manual | **回归测试** — 防止外部依赖升级破坏 | ubuntu | 每周 1 次 |
| `release.yml` | push `v*.*.*` tag / manual | **发布** — 跑 quick test + 打包 + GitHub Release | ubuntu | 手动 / tag 触发 |
| `scan_alarms.yml` | push / PR / manual | **scan_alarms.py smoke** — 跨多 paper 报警扫描 + 6 个断言 | ubuntu | 每次 commit |
| `driver-windows-smoke.yml` | manual only | **driver.cmd Windows smoke** — 验证 Windows shim 在 windows-latest 上跑通 | **windows** | 手动 |

> 主 CI 与 nightly/release 统一调用 `ci/run_tests.py`；`scan_alarms.yml` 直接调 `scripts/scan_alarms.py`；`driver-windows-smoke.yml` 直接调 `bin\driver.cmd`。

### `driver-windows-smoke.yml` — Windows shim 烟雾测试

**触发条件**：仅手动 `workflow_dispatch`（无 push/PR 自动触发，节省 Windows runner 配额）。

**为什么需要**：
- `bin\driver.cmd` 是 Windows 专属 shim，**在 ubuntu runner 上跑不了**（`.cmd` 文件会立刻失败）
- 主 CI 用 ubuntu，但本地开发者在 Windows 上用 `driver.cmd` 调用
- 这个 workflow 用 `windows-latest` runner 验证 shim 在 Windows 上真能跑通 + exit code 链保真（0 / 2）

**关键设计**：
- 10 个步骤：checkout → setup-python → 准备 fixture → `driver.cmd --help` → `driver.cmd scan-alarms --help` → 真跑 + 关键 step → 校验产物 + 6 个断言 → 空 root → step summary → 上传 artifact
- fixture 用 `%TEMP%\papers\`（避免默认 `F:\Research` 在 runner 上不存在）
- 6 个断言：2 papers scanned / 有 critical / PAPER_CLEAN 0 alarm / latex_error category / 空 root exit 0
- `workflow_dispatch` input `stale_days` 透传给 `driver.cmd scan-alarms --stale-days`
- artifact `driver-cmd-windows-report` 保留 14 天

**调用方式**：
```powershell
# 在 GitHub Actions UI 手动触发
# 路径: Actions → driver.cmd Windows smoke → Run workflow → [可选: stale_days]
```

## 依赖

- **Python 3.9**（与本地一致，避开 3.11 encodings 坑）
- **coverage 7.x**（PEP 668 环境用 `--break-system-packages`）

## 与本地 CI 的一致性

workflow 里调用的命令：

```bash
python ci/run_tests.py --full
```

与本地一键复现命令完全一致（参考 [ci/README.md](../../ci/README.md)）。在本地能跑通的，CI 上必跑通。

## 配置

### 1. 启用 workflow

把 `.github/workflows/` 目录 commit 到 GitHub repo 即可自动生效。

### 2. 必需的 GitHub Secrets

当前 3 个 workflow 都不需要额外 secrets（只用默认 `GITHUB_TOKEN`）。如果以后要发到 PyPI / 内部 registry，再加。

### 3. 必需的 GitHub Labels

`nightly.yml` 失败时会自动创建 issue 并打 `regression` + `nightly` label。需要在 repo 里预先创建这两个 label（Settings → Issues → Labels）。

## 各 workflow 详解

### `ci.yml` — 主 CI

**触发条件**：
- push 到 `main` / `master`
- 任何 PR（包含 draft）
- 手动 `workflow_dispatch`（可选 `--quick` / `--full` / `--html-only`）

**关键设计**：
- `concurrency.cancel-in-progress: true` — 同一 branch 的多次 push 取消旧 run，节省 CI 配额
- `setup-python` + `cache: pip` — 缓存依赖
- 3 个 artifacts：
  - `coverage-html` (14 天) — HTML 报告
  - `coverage-data` (7 天) — 原始 `.coverage` 文件
  - `ci-logs` (7 天) — CI 运行日志
- `$GITHUB_STEP_SUMMARY` 写入 coverage 表格 — PR 页面直接看
- 失败时 `$GITHUB_STEP_SUMMARY` 提示下载 artifact
- **PR-only**: `Verify action SHA pins` step 只在 PR 跑（push 到 main 时跳过，省 GitHub API rate limit）
  - 调 `ci/verify_action_pin.py` 校验 3 个 workflow 的所有 `uses:`
  - 失败 → `::error::` annotation + step summary 显示 ❌ + exit 1

### `nightly.yml` — 每周一回归

**触发条件**：
- cron `0 2 * * 1`（UTC 02:00 = 北京 10:00 每周一）
- 手动 `workflow_dispatch`

**关键设计**：
- 失败时自动创建 GitHub issue（标签 `regression` + `nightly`）
- artifacts 保留更久（HTML 30 天，logs 14 天）
- 用于发现外部依赖（tmlr_pipeline / paper-reviewer-tmlr-corpus）悄悄升级导致的回归

### `release.yml` — 发布

**触发条件**：
- push `v*.*.*` tag（如 `v1.0.0`）
- 手动 `workflow_dispatch`（指定 version）

**关键设计**：
- 两阶段：先跑 quick CI 验证，必须 100% 通过才进入 release 阶段
- 打包 `tar.gz` 排除 `.git` / `__pycache__` / `.coverage` / `htmlcov` / `ci/logs` / `.pytest_cache`
- 自动创建 GitHub Release + 上传附件 + generate release notes

## 在 PR 里查看结果

1. 提交 PR → 自动触发 `ci.yml`
2. PR 页面底部「Checks」section 会显示 `test` job
3. 点进 `test` job 可看每个 step 输出
4. coverage 表格在 `$GITHUB_STEP_SUMMARY`（页面顶部 Summary 标签）

## 在 PR 里跳过 CI

PR 标题或 commit message 包含以下任一关键词可跳过 CI：

- `[skip ci]`
- `[ci skip]`
- `[no ci]`

适合 docs-only / typo 修正的 commit。

## 本地模拟 CI

```bash
# 完全模拟 ci.yml 流程
py -3 ci/run_tests.py --full

# 只跑 quick（模拟 release 阶段的 validate job）
py -3 ci/run_tests.py --quick
```

## Action 版本策略

| Action | Pin 方式 | 理由 |
|--------|----------|------|
| `actions/checkout@v4` | major-version tag | GitHub 官方，破坏性变更会发 v5 |
| `actions/setup-python@v5` | major-version tag | GitHub 官方 |
| `actions/upload-artifact@v4` | major-version tag | GitHub 官方 |
| `actions/github-script@v7` | major-version tag | GitHub 官方 |
| `softprops/action-gh-release@<SHA> # v2.3.2` | **SHA pin** | 第三方 action，防 tag 劫持 |

> **GitHub 官方 action** 用 major-version tag 是行业标准（破坏性变更会升 major）；**第三方 action** 必须 SHA pin，因为 maintainer 可能失信或 tag 被 force-push 重写。

升级第三方 action 时：
```bash
# 查最新 release 的 commit SHA
gh release list --repo softprops/action-gh-release --limit 5
# 改 release.yml 里的 SHA + 注释里的版本号
```

## 故障排查

| 现象 | 可能原因 | 修复 |
|------|----------|------|
| `coverage` 未安装 | PEP 668 拒绝 pip install | 已用 `--break-system-packages` 处理 |
| workflow 找不到 `ci/run_tests.py` | repo 根目录结构不对 | 确保 `ci/run_tests.py` 在仓库根的 `ci/` 子目录 |
| nightly 失败 issue 没人收 | 没设 assignee | 在 issue 创建脚本里加 `assignees: [...]` |
| release 失败但 CI 通过 | 可能是打包脚本（tar 排除规则）问题 | 看 `List archive contents` step 输出 |
