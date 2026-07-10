"""test_provider_check.py — provider_check.py 单元测试

不真 ping（要花钱）；只测静态配置检查 + 占位符检测 + 长度校验。
跑法：py -3 tests/test_provider_check.py

覆盖目标：provider_check.py 行/分支 ≥ 85%（coverage run --branch）
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import provider_check  # noqa: E402
from provider_check import (  # noqa: E402
    validate_api_key,
    load_minimax_config,
    check_provider,
    PLACEHOLDER_PATTERNS,
    main as provider_main,
)


# ---------- 基础校验（5 个，原有） ----------

def test_placeholder_rejected():
    """占位符 apiKey 必须 fail。"""
    for bad in ["sk-xxx", "sk-XXXX", "sk-placeholder-foo", "xxx", "<your-key>"]:
        ok, msg = validate_api_key(bad)
        assert not ok, f"should reject {bad!r}: got {msg}"
    print("PASS: test_placeholder_rejected")


def test_missing_rejected():
    """None / 空 必 fail。"""
    ok, msg = validate_api_key(None)
    assert not ok
    ok, msg = validate_api_key("")
    assert not ok
    print("PASS: test_missing_rejected")


def test_format_rejected():
    """不以 sk- 开头必 fail。"""
    ok, msg = validate_api_key("abcd-efgh-1234-5678")
    assert not ok
    print("PASS: test_format_rejected")


def test_short_rejected():
    """< 20 字符必 fail。"""
    ok, msg = validate_api_key("sk-1234567890")  # 13 chars
    assert not ok
    print("PASS: test_short_rejected")


def test_real_key_format_accepted():
    """形如 sk-xxx 长度 ≥ 20 的 key 通过静态校验（不真 ping）。"""
    fake_real = "sk-" + "a" * 32  # 35 chars
    ok, msg = validate_api_key(fake_real)
    assert ok, f"should accept {fake_real[:8]}...: {msg}"
    print("PASS: test_real_key_format_accepted")


# ---------- v1.1 补测（7 个，凑 ≥85% 覆盖率） ----------

def test_load_minimax_config_missing():
    """配置文件不存在 → 返回空 dict（driver 友好的 fail-fast 输入）。"""
    bogus = Path("/nonexistent/path/config.yaml")
    cfg = load_minimax_config(bogus)
    assert cfg == {}, f"expected empty dict, got {cfg}"
    print("PASS: test_load_minimax_config_missing")


def test_load_minimax_config_yaml():
    """PyYAML 可用时 → 正确 parse 出 provider.minimax.apiKey。"""
    yaml_text = (
        "provider:\n"
        "  minimax:\n"
        "    options:\n"
        "      apiKey: sk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        "      baseURL: https://api.example.com/v1\n"
        "    models:\n"
        "      MiniMax-M3: {}\n"
        "defaultModel: minimax/MiniMax-M3\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(yaml_text)
        p = Path(f.name)
    try:
        cfg = load_minimax_config(p)
        assert "provider" in cfg
        assert cfg["provider"]["minimax"]["options"]["apiKey"].startswith("sk-")
        assert cfg["defaultModel"] == "minimax/MiniMax-M3"
    finally:
        p.unlink()
    print("PASS: test_load_minimax_config_yaml")


def test_load_minimax_config_regex_fallback():
    """PyYAML 不可用时 → 走 regex fallback 也能抓到 apiKey。"""
    yaml_text = (
        "provider:\n"
        "  minimax:\n"
        "    options:\n"
        "      apiKey: sk-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(yaml_text)
        p = Path(f.name)
    try:
        with mock.patch.object(provider_check, "yaml", None):
            cfg = load_minimax_config(p)
        assert cfg.get("_raw") is True
        assert cfg.get("apiKey", "").startswith("sk-")
    finally:
        p.unlink()
    print("PASS: test_load_minimax_config_regex_fallback")


def test_load_minimax_config_yaml_parse_error():
    """PyYAML 抛 YAMLError 时 → 走 except 打 WARN 并返回 {}。"""
    # yaml 可用 + 坏 yaml：用真实 yaml 但传非法缩进
    bad_yaml = "provider:\n  minimax:\n    options:\n     apiKey: oops\n  bad_indent:\n yes\n"
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(bad_yaml)
        p = Path(f.name)
    try:
        if provider_check.yaml is None:
            # yaml 不可用 → 该路径不会触发 except，跳过
            print("PASS: test_load_minimax_config_yaml_parse_error (skipped, no yaml)")
            return
        buf = io.StringIO()
        with redirect_stderr(buf):
            cfg = load_minimax_config(p)
        # 解析失败时返回 {}，并打 WARN
        assert cfg == {}, f"expected {{}}, got {cfg}"
        assert "WARN" in buf.getvalue()
    finally:
        p.unlink()
    print("PASS: test_load_minimax_config_yaml_parse_error")


def test_check_provider_ok_and_fail_placeholder():
    """check_provider() 主路径：OK case + 占位符 fail case + no-minimax。"""
    yaml_ok = (
        "provider:\n"
        "  minimax:\n"
        "    options:\n"
        "      apiKey: sk-cccccccccccccccccccccccccccccccc\n"
        "      baseURL: https://api.example.com/v1\n"
        "    models:\n"
        "      MiniMax-M3: {}\n"
        "defaultModel: minimax/MiniMax-M3\n"
    )
    yaml_bad = (
        "provider:\n"
        "  minimax:\n"
        "    options:\n"
        "      apiKey: sk-xxx-placeholder\n"
        "    models:\n"
        "      MiniMax-M3: {}\n"
        "defaultModel: minimax/MiniMax-M3\n"
    )
    yaml_no_minimax = "provider:\n  other: {}\n"
    yaml_default_wrong = (
        "provider:\n"
        "  minimax:\n"
        "    options:\n"
        "      apiKey: sk-eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee\n"
        "    models:\n"
        "      MiniMax-M3: {}\n"
        "defaultModel: openai/gpt-4\n"
    )
    yaml_no_models = (
        "provider:\n"
        "  minimax:\n"
        "    options:\n"
        "      apiKey: sk-ffffffffffffffffffffffffffffffff\n"
        "defaultModel: minimax/MiniMax-M3\n"
    )

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(yaml_ok); p_ok = Path(f.name)
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(yaml_bad); p_bad = Path(f.name)
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(yaml_no_minimax); p_no = Path(f.name)
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(yaml_default_wrong); p_wrong = Path(f.name)
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(yaml_no_models); p_no_models = Path(f.name)

    try:
        # 1) OK case
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = check_provider(p_ok, do_ping=False)
        assert rc == 0
        out = buf.getvalue()
        assert "OK: provider.minimax 配置正常" in out
        assert "sk-ccccc...cccc" in out
        assert "MiniMax-M3" in out

        # 2) 占位符 fail case
        buf_err = io.StringIO()
        with redirect_stderr(buf_err):
            rc = check_provider(p_bad, do_ping=False)
        assert rc == 1
        assert "FAIL" in buf_err.getvalue()
        assert "占位符" in buf_err.getvalue()

        # 3) 没有 provider.minimax 段
        buf_err2 = io.StringIO()
        with redirect_stderr(buf_err2):
            rc = check_provider(p_no, do_ping=False)
        assert rc == 1
        assert "provider.minimax" in buf_err2.getvalue()

        # 4) defaultModel 不是 minimax/* → WARN
        buf_warn = io.StringIO()
        with redirect_stdout(buf_warn), redirect_stderr(buf_warn):
            rc = check_provider(p_wrong, do_ping=False)
        assert rc == 0
        assert "WARN" in buf_warn.getvalue()
        assert "openai" in buf_warn.getvalue()

        # 5) models 为空 → FAIL
        buf_no_models = io.StringIO()
        with redirect_stderr(buf_no_models):
            rc = check_provider(p_no_models, do_ping=False)
        assert rc == 1
        assert "models 为空" in buf_no_models.getvalue()
    finally:
        for p in (p_ok, p_bad, p_no, p_wrong, p_no_models):
            try: p.unlink()
            except FileNotFoundError: pass

    print("PASS: test_check_provider_ok_and_fail_placeholder")


def test_ping_minimax_success_and_failure():
    """_ping_minimax()：mock urllib → 覆盖成功/异常两条分支。"""
    api_key = "sk-9999999999999999999999999999999999"
    mcfg_ok = {
        "options": {"baseURL": "https://api.example.com/v1"},
        "whitelist": ["MiniMax-M3"],
    }
    mcfg_no_base = {"options": {}}
    mcfg_with_chat = {
        "options": {"baseURL": "https://api.example.com/v1/chat/completions"},
    }

    # 1) 成功路径
    fake_resp = mock.MagicMock()
    fake_resp.read.return_value = json.dumps({
        "choices": [{"message": {"content": "pong"}}],
        "usage": {"total_tokens": 5},
    }).encode("utf-8")
    fake_resp.__enter__ = lambda self: self
    fake_resp.__exit__ = lambda self, *a: None

    with mock.patch("urllib.request.urlopen", return_value=fake_resp):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = provider_check._ping_minimax(api_key, mcfg_ok)
        assert rc == 0
        assert "PING OK" in buf.getvalue()
        assert "token usage" in buf.getvalue()

    # 2) urlopen 抛异常
    with mock.patch("urllib.request.urlopen", side_effect=Exception("network down")):
        buf_err = io.StringIO()
        with redirect_stderr(buf_err):
            rc = provider_check._ping_minimax(api_key, mcfg_ok)
        assert rc == 1
        assert "PING FAIL" in buf_err.getvalue()

    # 3) baseURL 缺失
    buf_no_base = io.StringIO()
    with redirect_stderr(buf_no_base):
        rc = provider_check._ping_minimax(api_key, mcfg_no_base)
    assert rc == 1
    assert "baseURL 缺失" in buf_no_base.getvalue()

    # 4) baseURL 已含 /chat/completions → 不重复拼
    with mock.patch("urllib.request.urlopen", return_value=fake_resp):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = provider_check._ping_minimax(api_key, mcfg_with_chat)
        assert rc == 0

    print("PASS: test_ping_minimax_success_and_failure")


def test_provider_cli_main():
    """CLI 入口 main()：成功路径走 argparse。"""
    yaml_text = (
        "provider:\n"
        "  minimax:\n"
        "    options:\n"
        "      apiKey: sk-dddddddddddddddddddddddddddddddd\n"
        "    models:\n"
        "      MiniMax-M3: {}\n"
        "defaultModel: minimax/MiniMax-M3\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(yaml_text)
        p = Path(f.name)
    try:
        sys.argv = ["provider_check.py", "--config", str(p)]
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = provider_main()
        assert rc == 0
        assert "OK" in buf.getvalue()
    finally:
        p.unlink()
    print("PASS: test_provider_cli_main")


# ---------- 入口 ----------

def main():
    tests = [
        test_placeholder_rejected,
        test_missing_rejected,
        test_format_rejected,
        test_short_rejected,
        test_real_key_format_accepted,
        # v1.1 补测
        test_load_minimax_config_missing,
        test_load_minimax_config_yaml,
        test_load_minimax_config_regex_fallback,
        test_load_minimax_config_yaml_parse_error,
        test_check_provider_ok_and_fail_placeholder,
        test_ping_minimax_success_and_failure,
        test_provider_cli_main,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"FAIL: {t.__name__}: {e}", file=sys.stderr)
            failed += 1
        except Exception as e:
            print(f"ERROR: {t.__name__}: {type(e).__name__}: {e}", file=sys.stderr)
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} PASS")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
