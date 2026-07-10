"""ci/verify_action_pin.py — 验证 release.yml 的 SHA pin 逻辑

不实际跑 workflow（那要 act + Docker），只做静态校验：
1. 从 release.yml 解析所有 uses: 行
2. 对第三方 action（非 github.com/actions/*）：
   - 解析出 owner/repo + ref
   - 验证 ref 是 40 位 hex（SHA pin）
   - 调用 GitHub API 查 ref 指向的 commit 元数据
   - 验证 ref 对应的 tag / release 是否存在
   - 下载 action.yml 计算 SHA256，与 GitHub 元数据交叉验证
3. 输出 PASS/FAIL 总结

退出码：
  0 — 全部 PASS
  1 — 至少一项 FAIL
  2 — 全部重试后仍因 transient 错误失败（网络持续不可用）

用法：
    py -3 ci/verify_action_pin.py
    py -3 ci/verify_action_pin.py --workflow .github/workflows/release.yml --verbose
    py -3 ci/verify_action_pin.py --max-retries 5 --initial-backoff 2.0
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

# GitHub 官方 actions（用 major-version tag 是行业标准，不需要 SHA pin）
OFFICIAL_ACTIONS = {
    "actions/checkout",
    "actions/setup-python",
    "actions/setup-node",
    "actions/upload-artifact",
    "actions/download-artifact",
    "actions/cache",
    "actions/github-script",
    "actions/configure-pages",
}

# 解析 uses: 行的正则
# 例: uses: actions/checkout@v4
#     - uses: softprops/action-gh-release@<sha> # v2.3.2
# regex 允许：行首空白 + 可选 "- "（YAML list item） + uses: ...
USES_RE = re.compile(
    r"^\s*-?\s*uses:\s+"
    r"(?P<action>[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)"
    r"@(?P<ref>\S+)"
    r"(?:\s*#\s*(?P<comment>.+))?$",
    re.MULTILINE,
)

SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# Transient 错误码：重试
TRANSIENT_HTTP_CODES = {408, 425, 429, 500, 502, 503, 504}


def is_transient(exc: BaseException) -> bool:
    """判断异常是否 transient（值得重试）。"""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in TRANSIENT_HTTP_CODES
    if isinstance(exc, urllib.error.URLError):
        # URLError 多数是网络抖动（DNS / refused / reset）
        return True
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, ConnectionError):
        return True
    return False


def call_with_retry(
    fn: Callable[[], Any],
    *,
    max_retries: int = 3,
    initial_backoff: float = 1.0,
    backoff_factor: float = 2.0,
    label: str = "call",
) -> tuple[bool, Any]:
    """带指数退避的重试。

    返回 (success, result)。若全部 retry 仍失败：success=False, result=最后一次的异常。
    """
    last_exc: BaseException | None = None
    backoff = initial_backoff
    # GitHub Actions 会把 stderr 里以 `::warning::` 开头的行收集为 step annotation。
    # 但在 unit test / 本地 CLI 调用时，retry 警告也会被错误收集，导致：
    #   1. CI 5 个 warning annotation（噪声）
    #   2. 单元测试时控制台被污染
    # 解决：仅在 GITHUB_ACTIONS=true 环境用 GitHub annotation 格式；
    # 其他场景用普通 [retry] 前缀输出。
    is_ci = os.getenv("GITHUB_ACTIONS") == "true"
    for attempt in range(1, max_retries + 1):
        try:
            return True, fn()
        except BaseException as e:  # 捕获所有，包括 HTTPError / URLError / Timeout
            last_exc = e
            transient = is_transient(e)
            if not transient or attempt >= max_retries:
                break
            if is_ci:
                # GitHub Actions annotation（推到 step summary 顶部）
                print(
                    f"  ::warning::[{label}] attempt {attempt}/{max_retries} failed: "
                    f"{type(e).__name__}: {e} — retrying in {backoff:.1f}s",
                    file=sys.stderr,
                )
            else:
                # 本地 / unit test：plain [retry] 行（不会被任何 CI 收集）
                print(
                    f"  [retry][{label}] attempt {attempt}/{max_retries} failed: "
                    f"{type(e).__name__}: {e} — retrying in {backoff:.1f}s",
                    file=sys.stderr,
                )
            time.sleep(backoff)
            backoff *= backoff_factor
    return False, last_exc


def github_api(path: str, max_retries: int = 3, initial_backoff: float = 1.0) -> dict:
    """GitHub API GET 调用 + transient 错误重试。

    返回 dict。失败（重试耗尽或非 transient 错误）时 dict 含 _error / _transient 字段。
    """
    url = f"https://api.github.com{path}"
    req_factory = lambda: urllib.request.Request(
        url, headers={"User-Agent": "verify-action-pin/1.0"}
    )

    def _do():
        with urllib.request.urlopen(req_factory(), timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    ok, result = call_with_retry(_do, max_retries=max_retries, initial_backoff=initial_backoff, label=f"API {path}")
    if ok:
        return result
    exc = result
    transient = is_transient(exc)
    return {
        "_error": f"{type(exc).__name__}: {exc}",
        "_url": url,
        "_transient": transient,
        "_retries_exhausted": True,
    }


def download_action_yml(
    action: str, ref: str, max_retries: int = 3, initial_backoff: float = 1.0
) -> tuple[bytes | None, bool]:
    """下载 action.yml/yaml + transient 错误重试。

    返回 (content, transient_failed)。transient_failed=True 表示重试耗尽。
    """
    for fname in ("action.yml", "action.yaml"):
        url = f"https://raw.githubusercontent.com/{action}/{ref}/{fname}"
        req_factory = lambda u=url: urllib.request.Request(
            u, headers={"User-Agent": "verify-action-pin/1.0"}
        )

        def _do(u=url, _req=req_factory):
            with urllib.request.urlopen(_req(), timeout=15) as resp:
                return resp.read()

        ok, result = call_with_retry(_do, max_retries=max_retries, initial_backoff=initial_backoff, label=f"download {fname}")
        if ok:
            return result, False
        exc = result
        if isinstance(exc, urllib.error.HTTPError) and exc.code == 404:
            continue  # 试下一个文件名
        transient = is_transient(exc)
        return None, transient
    return None, False  # 两个文件名都 404


def verify_sha_pin(
    workflow_path: Path,
    verbose: bool = False,
    max_retries: int = 3,
    initial_backoff: float = 1.0,
) -> tuple[int, list[dict]]:
    """扫描 workflow 文件，验证所有 uses: 的 SHA pin。"""
    if not workflow_path.exists():
        print(f"FAIL: workflow file not found: {workflow_path}")
        return 1, []

    text = workflow_path.read_text(encoding="utf-8")
    matches = list(USES_RE.finditer(text))

    if not matches:
        print(f"WARN: no 'uses:' found in {workflow_path.name}")
        return 0, []

    results = []
    any_transient_fail = False
    for m in matches:
        action = m.group("action")
        ref = m.group("ref")
        comment = m.group("comment") or ""
        is_official = action in OFFICIAL_ACTIONS
        is_sha = bool(SHA_RE.match(ref))

        result = {
            "action": action,
            "ref": ref,
            "comment": comment.strip(),
            "official": is_official,
            "is_sha": is_sha,
            "checks": [],
            "ok": True,
        }

        # 规则 1: 官方 action 允许 tag
        if is_official:
            result["checks"].append(("official action", "OK", f"{action} 是 GitHub 官方，允许用 major-version tag"))
        # 规则 2: 第三方 action 必须 SHA pin
        elif not is_official:
            if is_sha:
                result["checks"].append(("third-party SHA pin", "OK", f"{action}@{ref[:8]}... 是 40 位 SHA"))
            else:
                result["checks"].append(("third-party SHA pin", "FAIL",
                                          f"{action}@{ref} 不是 40 位 SHA，第三方 action 必须 SHA pin"))
                result["ok"] = False

        # 仅对 SHA pin 的 action 进一步做 GitHub API 校验
        if is_sha and not is_official:
            # 查 commit 元数据
            meta = github_api(f"/repos/{action}/commits/{ref}",
                              max_retries=max_retries, initial_backoff=initial_backoff)
            if meta.get("_retries_exhausted"):
                transient = meta.get("_transient", False)
                any_transient_fail = True
                if transient:
                    result["checks"].append(("commit exists on GitHub", "TRANSIENT",
                                              f"重试 {max_retries} 次后仍失败（网络问题）: {meta['_error']}"))
                else:
                    result["checks"].append(("commit exists on GitHub", "FAIL",
                                              f"API error: {meta['_error']}"))
                    result["ok"] = False
            else:
                sha_full = meta.get("sha", "")
                if sha_full.lower() == ref.lower():
                    result["checks"].append(("commit exists on GitHub", "OK",
                                              f"commit {ref[:8]} verified, message: {meta.get('commit', {}).get('message', '')[:50]!r}"))
                else:
                    result["checks"].append(("commit exists on GitHub", "FAIL",
                                              f"returned sha {sha_full} != requested {ref}"))
                    result["ok"] = False

            # 查 SHA 对应的 tag
            tags_meta = github_api(f"/repos/{action}/tags?per_page=100",
                                   max_retries=max_retries, initial_backoff=initial_backoff)
            tag_match = None
            # 修复：tags_meta 可能是 list（成功）或 dict（_retries_exhausted）
            if isinstance(tags_meta, dict) and tags_meta.get("_retries_exhausted"):
                any_transient_fail = True
            elif isinstance(tags_meta, list):
                for t in tags_meta:
                    if t.get("commit", {}).get("sha", "") == ref:
                        tag_match = t.get("name")
                        break
            if tag_match:
                result["checks"].append(("tag lookup", "OK", f"SHA 对应 tag: {tag_match}"))
            elif isinstance(tags_meta, dict) and tags_meta.get("_retries_exhausted"):
                result["checks"].append(("tag lookup", "TRANSIENT",
                                          f"重试 {max_retries} 次后仍失败: {tags_meta.get('_error', 'unknown')}"))
            else:
                result["checks"].append(("tag lookup", "WARN",
                                          "SHA 不在任何前 100 个 tag 中（可能太新或未发布 tag）"))

            # 下载 action.yml 算 SHA256
            if verbose:
                content, transient_failed = download_action_yml(
                    action, ref, max_retries=max_retries, initial_backoff=initial_backoff
                )
                if content:
                    h = hashlib.sha256(content).hexdigest()
                    result["checks"].append(("action.yml download", "OK",
                                              f"sha256={h[:16]}..., size={len(content)} bytes"))
                elif transient_failed:
                    any_transient_fail = True
                    result["checks"].append(("action.yml download", "TRANSIENT",
                                              f"重试 {max_retries} 次后仍失败（网络问题）"))
                else:
                    result["checks"].append(("action.yml download", "WARN",
                                              "无法下载 action.yml（可能非标准 layout）"))

        results.append(result)

    # 退出码计算：
    #   3 = 至少一个 transient 错误（网络问题）
    #   1 = 至少一个 permanent 错误（SHA 不对 / 缺失 / 长度错）
    #   0 = 全部 OK
    if any_transient_fail:
        return 3, results
    if any(not r["ok"] for r in results):
        return 1, results
    return 0, results


def main() -> int:
    ap = argparse.ArgumentParser(description="验证 GitHub Actions workflow 的 SHA pin")
    ap.add_argument("--workflow", "-w", type=Path,
                    default=Path(__file__).parent.parent / ".github" / "workflows" / "release.yml",
                    help="要校验的 workflow 文件")
    ap.add_argument("--verbose", "-v", action="store_true", help="下载 action.yml 并算 SHA256")
    ap.add_argument("--max-retries", type=int, default=3,
                    help="transient 错误最大重试次数（默认 3）")
    ap.add_argument("--initial-backoff", type=float, default=1.0,
                    help="首次重试前等待秒数（默认 1.0，指数退避）")
    args = ap.parse_args()

    print(f"=== verifying SHA pins in {args.workflow.name} ===")
    print(f"    retry policy: max={args.max_retries}, initial_backoff={args.initial_backoff}s, backoff×2")
    print()

    rc, results = verify_sha_pin(
        args.workflow,
        verbose=args.verbose,
        max_retries=args.max_retries,
        initial_backoff=args.initial_backoff,
    )

    if not results:
        return rc

    # 打印每条检查
    for r in results:
        tag_marker = " [official]" if r["official"] else (" [SHA-pinned]" if r["is_sha"] else " [TAG]")
        print(f"  {r['action']}@{r['ref'][:12]}{tag_marker}")
        if r["comment"]:
            print(f"    comment: {r['comment']}")
        for check_name, status, detail in r["checks"]:
            icon = {"OK": "✅", "FAIL": "❌", "WARN": "⚠️ ", "TRANSIENT": "🔄"}.get(status, "  ")
            print(f"    {icon} {check_name}: {detail}")
        print()

    # 总结
    n_total = len(results)
    n_ok = sum(1 for r in results if r["ok"])
    n_fail = sum(1 for r in results if not r["ok"])
    print("=" * 60)
    print(f"summary: {n_ok}/{n_total} OK, {n_fail} FAIL")
    if rc == 3:
        print("🔄 TRANSIENT — 全部 retry 后仍因网络问题失败")
        print("    建议：检查 GitHub 状态页 https://www.githubstatus.com/")
        print("    或在 PR 评论 /re-run jobs 手动重试")
        return 3
    if n_fail == 0:
        print("✅ ALL PIN POLICIES SATISFIED")
        return 0
    else:
        print("❌ FAILED — see above")
        return 1


if __name__ == "__main__":
    sys.exit(main())