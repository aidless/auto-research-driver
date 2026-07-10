"""provider_check.py — MiniMax Token Plan provider 验证

driver 启动前必须验证：
1. ~/.mavis/config.yaml 里 provider.minimax 存在
2. apiKey 不是占位符（sk-xxx / 长度异常）
3. defaultModel 至少有一个 MiniMax 模型

这是诚信门——MiniMax Token Plan 没接上时，driver 应该 fail-fast 而不是带着假 key 跑出
一堆 401 错误。

不在这里做实际 ping（要花钱）；只做静态配置检查。ping 单独跑 `python provider_check.py --ping`。
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Optional

try:
    import yaml  # PyYAML；driver 自带 deps 时会有
except ImportError:
    yaml = None


CONFIG_PATH = Path("~/.mavis/config.yaml").expanduser()
PLACEHOLDER_PATTERNS = [
    re.compile(r"^sk-xxx", re.IGNORECASE),
    re.compile(r"^sk-placeholder", re.IGNORECASE),
    re.compile(r"^xxx$", re.IGNORECASE),
    re.compile(r"^<.*>$"),  # <your-key-here>
]


def load_minimax_config(config_path: Path = CONFIG_PATH) -> dict:
    """读 ~/.mavis/config.yaml；不存在 / 解析失败时返回空 dict。"""
    if not config_path.exists():
        return {}
    text = config_path.read_text(encoding="utf-8")
    if yaml is not None:
        try:
            return yaml.safe_load(text) or {}
        except yaml.YAMLError as e:
            print(f"WARN: config.yaml parse error: {e}", file=sys.stderr)
            return {}
    # fallback: 简单 regex 抓 provider.minimax.apiKey
    out = {"_raw": True}
    m = re.search(r"provider:\s*\n(?:\s+\w+:.*\n)*?\s+minimax:\s*\n(?:\s+\w+:.*\n)+", text, re.MULTILINE)
    if m:
        block = m.group(0)
        km = re.search(r"apiKey:\s*['\"]?([^'\"\s]+)['\"]?", block)
        if km:
            out["apiKey"] = km.group(1)
    return out


def validate_api_key(api_key: Optional[str]) -> tuple[bool, str]:
    """返回 (ok, msg)。True = 通过。"""
    if not api_key:
        return False, "apiKey 缺失（config.yaml provider.minimax.apiKey）"
    for pat in PLACEHOLDER_PATTERNS:
        if pat.match(api_key):
            return False, f"apiKey 是占位符（{api_key[:8]}...）；请替换为真实 MiniMax key"
    if not api_key.startswith("sk-"):
        return False, f"apiKey 格式异常（应以 'sk-' 开头）"
    if len(api_key) < 20:
        return False, f"apiKey 长度异常（{len(api_key)} < 20）"
    return True, "ok"


def check_provider(config_path: Path = CONFIG_PATH, do_ping: bool = False) -> int:
    """driver 入口的 provider sanity check。返回 0 = OK，1 = FAIL。"""
    cfg = load_minimax_config(config_path)
    if not cfg or "minimax" not in cfg.get("provider", {}):
        print(f"FAIL: config.yaml 没有 provider.minimax 段（{config_path}）", file=sys.stderr)
        return 1

    m = cfg["provider"]["minimax"]
    api_key = m.get("options", {}).get("apiKey") or m.get("apiKey")
    ok, msg = validate_api_key(api_key)
    if not ok:
        print(f"FAIL: {msg}", file=sys.stderr)
        return 1

    default_model = cfg.get("defaultModel", "")
    if "minimax" not in str(default_model).lower():
        print(f"WARN: defaultModel={default_model!r} 不是 minimax/*", file=sys.stderr)

    models = m.get("models", {})
    if not models:
        print("FAIL: provider.minimax.models 为空", file=sys.stderr)
        return 1

    print(f"OK: provider.minimax 配置正常")
    print(f"  apiKey     : {api_key[:8]}...{api_key[-4:]}  (len={len(api_key)})")
    print(f"  baseURL    : {m.get('options', {}).get('baseURL', '?')}")
    print(f"  models     : {', '.join(models.keys())}")
    print(f"  defaultModel: {default_model}")

    if do_ping:
        return _ping_minimax(api_key, m)
    return 0


def _ping_minimax(api_key: str, mcfg: dict) -> int:
    """实际 ping MiniMax 网关；不通过就 fail。"""
    base = mcfg.get("options", {}).get("baseURL", "").rstrip("/")
    if not base:
        print("FAIL: baseURL 缺失", file=sys.stderr)
        return 1
    url = base + "/chat/completions" if not base.endswith("/chat/completions") else base
    payload = {
        "model": mcfg.get("whitelist", ["MiniMax-M3"])[0] if isinstance(mcfg.get("whitelist"), list) else "MiniMax-M3",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 8,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage", {})
        print(f"PING OK: {content[:50]!r}")
        if usage:
            print(f"  token usage: {usage}")
        return 0
    except Exception as e:
        print(f"PING FAIL: {e}", file=sys.stderr)
        return 1


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="MiniMax provider sanity check")
    ap.add_argument("--config", type=Path, default=CONFIG_PATH)
    ap.add_argument("--ping", action="store_true", help="actual ping the gateway")
    args = ap.parse_args()
    return check_provider(args.config, do_ping=args.ping)


if __name__ == "__main__":
    sys.exit(main())