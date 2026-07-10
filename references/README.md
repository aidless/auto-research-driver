# auto-research-driver (v1.0) — 使用文档

> TMLR 端到端流水线编排器。driver 不是新工具，是把 `tmlr_pipeline` + `tmlr-review-simulator` + `paper-reviewer-tmlr-corpus v2.4` + `paper-writing-agent` 串起来的薄壳。

## 安装

skill 已经装在 `C:\Users\Administrator\.mavis\skills\auto-research-driver\`，并把 `driver.cmd` 拷贝到 `C:\Users\Administrator\.mavis\bin\`。`driver` 命令现在全局可用。

如果新 shell 找不到 `driver`，刷新 PATH：
```powershell
$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User')
```

## 命令清单

| 命令 | 作用 |
|------|------|
| `driver run --target-dir <T> --idea "..."` | 从 S1 跑到 S6 |
| `driver run --target-dir <T> --arxiv 2606.16682` | 复现 + 扩展 arxiv 论文 |
| `driver run --target-dir <T> --idea-auto` | auto 模式（obsidian + radar 扫描） |
| `driver run --target-dir <T> --from-stage s5 --review-mode v24` | 从 S5 起走 v2.4 4-persona |
| `driver status --target-dir <T>` | 看 state.json + pending checkpoints |
| `driver sign --target-dir <T> --checkpoint s5_review` | 签一个 checkpoint |
| `driver reset --target-dir <T>` | 清掉 state.json |
| `driver checkpoints` | 列所有 checkpoint 规格 |
| `driver provider-check [--ping]` | 验证 MiniMax provider 配置 |

## 端到端使用流程（推荐）

### 1. 验证 MiniMax provider
```powershell
driver provider-check
# 期待：OK + 列出 apiKey/baseURL/models/defaultModel
# 当前：FAIL（apiKey 是 sk-xxx 占位符，需要替换）
```

### 2. 准备 paper 工程目录
```powershell
# 已有 PAPER 工程：直接指定
driver run --target-dir F:\Research\PAPER5_CONSOLIDATED --from-stage s5 --skip-provider-check

# 新 paper：建空目录
New-Item -ItemType Directory F:\Research\new_paper -Force
driver run --target-dir F:\Research\new_paper --idea "你的 idea 一句话"
```

### 3. 跟着 checkpoint 走
driver 会在以下节点暂停并提示签字：
- **S1 决策点 🧑**：选 idea 候选
- **S3 决策点 🧑**：确认 outline + 实验设计
- **S5 质量门 ✓**：v2.4 ≥ 7.8 才能进 S6
- **S6 决策点 🧑**：用户最终签字（机器不能替代）

签字：
```powershell
driver sign --target-dir F:\Research\PAPER5_CONSOLIDATED --checkpoint s5_review --note "看过了，分数达标"
```

### 4. 续跑 / 断点恢复
driver 每次跑完会写 `<target_dir>/.driver/state.json`。重新跑会自动从上次未完成的 stage 起：

```powershell
driver run --target-dir F:\Research\PAPER5_CONSOLIDATED
# driver 会自动从 state.stage 起，跳过已完成的 stage
```

强制重跑某个 stage：
```powershell
driver run --target-dir F:\Research\PAPER5_CONSOLIDATED --from-stage s5 --force
```

## 已知限制（v1.0）

- **S1 idea discovery 是占位**：当前只生成 `idea_canvas.md` 模板，v1.1 接入 `brainstorming-research` + `idea-evaluator` + `research_radar_v2`
- **S2 lit review 是占位**：当前只生成空 `refs.bib` 模板，v1.1 接入 `deep_read_v2` + `light-literature-search` + `paper-reviewer-tmlr-corpus cite_verify`
- **S5 review-mode 默认 simulator**：`--review-mode v24` 需要 paper-reviewer-tmlr-corpus 的 multi-paper dispatch 配合，v1.1 完善
- **provider-check 没拿到 key 时整个 run 会 fail**：除非 `--skip-provider-check`（simulator 模式不需要 driver-level key）

## 与现有 skill 的关系

| 想做什么 | 用哪个 |
|---------|--------|
| 跑端到端流水线 | `driver`（本 skill） |
| 写论文 21 模块 | `paper-writing-agent` |
| 4 persona 对抗式 review | `paper-reviewer-tmlr-corpus v2.4` |
| TMLR 4-agent 模拟 review | `tmlr-review-simulator` |
| 单章润色 | `light-paper-polishing` |
| 排版 / TMLR 模板 | `light-typesetting` |
| 文献引用 + bib 校验 | `light-citation` |

## 调试

state.json 路径：`<target_dir>/.driver/state.json`
review 产物：`<target_dir>/reviews/`
logs：driver 直接 print 到 stdout

测试：
driver 保持零外部依赖（不引入 pytest），所有测试用 plain assert + sys.exit 跑：

```powershell
py -3 C:\Users\Administrator\.mavis\skills\auto-research-driver\tests\test_state.py
py -3 C:\Users\Administrator\.mavis\skills\auto-research-driver\tests\test_provider_check.py
py -3 C:\Users\Administrator\.mavis\skills\auto-research-driver\tests\test_verify_action_pin.py
py -3 C:\Users\Administrator\.mavis\skills\auto-research-driver\tests\smoke_test.py
```

期望结果：**38/38 PASS**（test_state.py 10 + test_provider_check.py 12 + test_verify_action_pin.py 16）+ smoke 集成测试通过。

覆盖率（实测）：
- `state.py`: **94%**
- `provider_check.py`: **93%**
- `verify_action_pin.py`: **62%**（main/CLI 入口覆盖率自然低，核心逻辑已覆盖）

跑法：
```powershell
pip install coverage --break-system-packages
coverage run --source=scripts/state.py,scripts/provider_check.py --branch tests/test_state.py
coverage run --source=scripts/state.py,scripts/provider_check.py --branch --append tests/test_provider_check.py
coverage report -m
```

### test_state.py — state.py 单元测试（10 个）

| # | 测试 | 验证点 |
|---|------|--------|
| 1 | `test_load_empty` | 空目录 → 新建 `DriverState(stage="s1_idea", completed=[], run_count=0)` |
| 2 | `test_save_load_roundtrip` | 写 `completed` / `scores` / `user_signatures` 后再 `load_state` 字段一致 |
| 3 | `test_mark_completed_advances_stage` | `mark_completed(s, "s1_idea")` 后 `stage` 自动推进到 `"s2_lit"` |
| 4 | `test_mark_failed_increments_run_count` | `mark_failed(s, "s5_review", "OOM")` → `run_count=1` 且 `last_error` 含 stage 名 + 错误信息 |
| 5 | `test_corrupt_state_recovery` | 写入非法 JSON 后 `load_state` 不抛异常 → 备份为 `.json.corrupt` + 新建空状态 + `last_error` 含 `"corrupt"` |
| 6 | `test_atomic_write_no_leftover_tmp` | `save_state` 后 `.json.tmp` 必须不存在（验证 atomic write 协议） |

### test_provider_check.py — provider_check.py 单元测试（12 个）

只测 `validate_api_key()` 静态校验 + mock 覆盖 `_ping_minimax()` 网络层（不真 ping，避免烧 API token）：

| # | 测试 | 验证点 |
|---|------|--------|
| 7 | `test_placeholder_rejected` | 占位符 key（`sk-xxx` / `sk-XXXX` / `sk-placeholder-foo` / `xxx` / `<your-key>`）全部 fail |
| 8 | `test_missing_rejected` | `None` 和 `""` 必 fail |
| 9 | `test_format_rejected` | 不以 `sk-` 开头的 key（`abcd-efgh-1234-5678`）必 fail |
| 10 | `test_short_rejected` | 长度 < 20 字符（`sk-1234567890` = 13 chars）必 fail |
| 11 | `test_real_key_format_accepted` | 形如 `sk-` + 32 字符（35 chars total）的 fake key 通过静态校验（不真 ping） |
| 12 | `test_load_minimax_config_missing` | config.yaml 不存在 → `load_minimax_config` 返回 `{}` |
| 13 | `test_load_minimax_config_yaml` | PyYAML 可用时正确 parse `provider.minimax.apiKey` |
| 14 | `test_load_minimax_config_regex_fallback` | mock `yaml=None` → 走 regex fallback 仍能抓 apiKey |
| 15 | `test_load_minimax_config_yaml_parse_error` | PyYAML 抛 `YAMLError` → 打 WARN + 返回 `{}` |
| 16 | `test_check_provider_ok_and_fail_placeholder` | OK / 占位符 fail / no-minimax / defaultModel 错 / models 空 共 5 个分支 |
| 17 | `test_ping_minimax_success_and_failure` | mock urllib → 成功 / urlopen 抛异常 / baseURL 缺失 / baseURL 含 `/chat/completions` 共 4 分支 |
| 18 | `test_provider_cli_main` | CLI 入口 argparse + 成功路径 |

### smoke_test.py — driver 端到端 smoke（集成测试）

不真调 MiniMax / 不真跑 `tmlr_pipeline.run_pipeline.py`（那需要 paper 才有意义），只走骨架。流程 7 步：

1. `provider-check` 子命令 → 期望 `rc≠0` 且输出含「占位符」或「FAIL」
2. `driver run --skip-provider-check --skip-checkpoints --force --to-stage s3_outline`
3. 验证 `.driver/state.json` 写出，且 `completed` 含 `s1_idea / s2_lit / s3_outline`，不含 `s4_draft / s5_review`
4. 验证 `artifacts` 含 `idea_canvas / refs_bib / outline`
5. `driver status` → 输出含 `ALL CHECKPOINTS SIGNED`
6. `driver reset` → `state.json` 删除
7. `driver checkpoints` → 输出含 `S1` ~ `S6`