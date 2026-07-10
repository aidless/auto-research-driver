# auto-research-driver CI 一键复现脚本

本目录提供 2 个 CI 入口脚本，统一封装以下流程：

- `run_tests.py` — Windows / Linux 本地一键复现 9 个 step（unit + coverage + smoke）
- `ci_test_ubuntu.sh` — **Docker 模拟 GitHub Actions ubuntu runner**（python:3.12-slim 镜像）
  - 用法：`./ci/ci_test_ubuntu.sh` 或 `bash ci/ci_test_ubuntu.sh`
  - 镜像内执行 `python3 ci/run_tests.py` 复现 CI 行为
  - 需要 Docker Desktop 已启动
  - 失败时可本地重现 GitHub Actions 报错，不用反复 push + 等 CI

1. **preflight** — 校验 Python 路径 + 测试文件存在
2. **ensure coverage** — 检测 `coverage` 是否安装，缺失则自动 `pip install coverage --break-system-packages`
3. **clean .coverage** — 删除旧 `.coverage`（html-only 模式除外）
4. **run unit tests** — 用 `coverage run --include=... --branch` 跑 `test_state.py` + `test_provider_check.py`（`--append` 累积 .coverage）
5. **coverage report** — 输出行/分支覆盖率表格
6. **run smoke** — 跑 `smoke_test.py` 端到端集成
7. **coverage html** — 生成可点击的 HTML 报告（`htmlcov/index.html`）

## 为什么是 Python 而不是 .ps1 / .cmd / .sh？

Trae IDE 内嵌的 PowerShell 终端有 `safe_rm_aliases.ps1` hook，会拦截 `& $Variable` 语法（把 `&` 当成后台运行符吞掉 `$Variable`），导致 `.ps1` 脚本运行 `Start-Process` / `cmd /c` 时 `ArgumentList` 变 null，CI 跑不下去。

Python 的 `subprocess.run` 不受 hook 影响，跨平台通用，所以本 CI 用纯 Python 实现。

## 脚本清单

| 脚本 | 平台 | 推荐用法 |
|------|------|----------|
| `run_tests.py` | 全平台 | **唯一入口** |

## 用法

### 默认（unit + coverage + smoke）

```powershell
py -3 C:\Users\Administrator\.mavis\skills\auto-research-driver\ci\run_tests.py
```

### 仅单元测试（快速验证）

```powershell
py -3 ci\run_tests.py --quick
```

### 完整流程（unit + coverage + smoke + HTML）

```powershell
py -3 ci\run_tests.py --full
```

### 仅生成 HTML（前提：已有 .coverage）

```powershell
py -3 ci\run_tests.py --html-only
```

### 不写日志（实时打印到 stdout）

```powershell
py -3 ci\run_tests.py --no-log
```

## 退出码

| 退出码 | 含义 |
|--------|------|
| `0` | 全部通过（unit + smoke + coverage report 都 OK） |
| `1` | 至少一步失败（看 `ci/logs/ci_*.log` 查详情） |
| `2` | preflight 失败（Python 缺失 / 测试文件缺失） |
| `3` | pip install coverage 失败 |

CI 系统（GitHub Actions / Jenkins / GitLab CI）根据退出码判断成败。

## 日志

每次跑会写一份日志到 `ci/logs/ci_<timestamp>.log`，命名格式：

```
ci_20260710_112518.log
```

日志同时 stdout 实时输出 + 文件落盘，方便调试。

## 一键复制粘贴

```powershell
# 在 PowerShell 里跑一次完整 CI
$env:ARD_SKILL_ROOT = "C:\Users\Administrator\.mavis\skills\auto-research-driver"
& "C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.9.25-windows-x86_64-none\python.exe" -u "C:\Users\Administrator\.mavis\skills\auto-research-driver\ci\run_tests.py" --full
```

> **ARD_SKILL_ROOT 环境变量** 是因为 Windows 上 `\.mavis` 是 `\.minimax` 的目录连接（junction），`Path.resolve()` 会跟随到 `\.minimax`，影响日志和报告的路径对齐。设置 `ARD_SKILL_ROOT` 可强制走 `\.mavis` 路径。

## 依赖

- **Python**: `C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.9.25-windows-x86_64-none\python.exe`（脚本里硬编码，找不到时 fallback 到 `sys.executable`）
- **coverage**: 第一次跑自动 `pip install coverage --break-system-packages`（PEP 668 环境）
- **测试文件**: `tests/test_state.py` / `tests/test_provider_check.py` / `tests/smoke_test.py`

> **修改 Python 路径**只改 `run_tests.py` 顶部的 `PY = Path(...)` 变量。

## v1.0 实测

2026-07-10 11:25 实跑结果：

```
22/22 PASS（unit）+ 7/7 步 PASS（smoke）
state.py 96% / provider_check.py 93% / TOTAL 95%
exit code 0
HTML: htmlcov/index.html
```

完整报告：[`reports/TEST_REPORT_2026-07-10.md`](../reports/TEST_REPORT_2026-07-10.md)