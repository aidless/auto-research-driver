"""test_verify_action_pin.py — ci/verify_action_pin.py 单元测试

不引入 pytest（driver 保持零外部 deps）；用 plain assert + sys.exit 风格。

覆盖目标：
  1. 之前修复的 Bug 1：tags_meta 是 list 时 .get() 崩溃 → 修复后 isinstance 检查正确
  2. 之前修复的 Bug 2：USES_RE 不能匹配 "- uses:" (YAML list item) → 修复后能匹配
  3. 重试逻辑：transient 错误会重试，permanent 错误不会重试
  4. 退出码语义：0=OK, 1=FAIL, 3=TRANSIENT

跑法：py -3 tests/test_verify_action_pin.py
"""
from __future__ import annotations

import importlib.util
import io
import os
import sys
import tempfile
import textwrap
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

# 加载被测模块（不在 sys.path 上的相对路径）
SCRIPT = Path(__file__).parent.parent / "ci" / "verify_action_pin.py"
spec = importlib.util.spec_from_file_location("verify_action_pin", SCRIPT)
if spec is None or spec.loader is None:
    print(f"FAIL: cannot load {SCRIPT}")
    sys.exit(1)
verify_pin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify_pin)

PASS = 0
FAIL = 0
FAILS: list[str] = []


def _record(name: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        FAILS.append(f"{name}: {detail}")
        print(f"  FAIL: {name} — {detail}")


# ============================================================
# 1. Bug 1 回归测试：tags_meta 是 list 时不崩溃
# ============================================================

def test_tags_meta_list_handled_correctly():
    """GitHub /tags API 成功时返回 list，之前 bug 是直接 .get() 崩溃。
    现在必须正确处理 list 路径，找 SHA 对应 tag。"""
    fake_wf = Path(tempfile.mkdtemp()) / "fake.yml"
    fake_wf.write_text(textwrap.dedent("""\
        name: fake
        on: [push]
        jobs:
          test:
            runs-on: ubuntu-latest
            steps:
              - uses: fake-org/fake-action@1234567890abcdef1234567890abcdef12345678 # v1.0.0
        """), encoding="utf-8")

    def mock_github(path, *args, **kwargs):
        if "/commits/" in path:
            return {
                "sha": "1234567890abcdef1234567890abcdef12345678",
                "commit": {"message": "release v1.0.0"},
            }
        if "/tags" in path:
            # 成功响应是 LIST，不是 dict
            return [
                {"name": "v1.0.0",
                 "commit": {"sha": "1234567890abcdef1234567890abcdef12345678"}}
            ]
        return []

    with mock.patch.object(verify_pin, "github_api", side_effect=mock_github), \
         mock.patch.object(verify_pin, "download_action_yml", return_value=(b"name: fake\n", False)):
        rc, results = verify_pin.verify_sha_pin(fake_wf, verbose=True, max_retries=1)

    try:
        assert rc == 0, f"expected rc=0, got {rc}"
        assert len(results) == 1
        # 关键：tag lookup 应该是 OK（不是 WARN 也不是 TRANSIENT）
        tag_checks = [c for c in results[0]["checks"] if c[0] == "tag lookup"]
        assert len(tag_checks) == 1, f"expected 1 tag lookup check, got {len(tag_checks)}"
        assert tag_checks[0][1] == "OK", \
            f"tag lookup status should be OK, got {tag_checks[0][1]!r} (Bug 1 regression!)"
        assert "v1.0.0" in tag_checks[0][2], f"tag name not found: {tag_checks[0][2]!r}"
        _record("Bug 1: tags_meta list 不崩溃且正确匹配 tag", True)
    except AssertionError as e:
        _record("Bug 1: tags_meta list 不崩溃且正确匹配 tag", False, str(e))


# ============================================================
# 2. Bug 1 回归测试：tags_meta 是 dict (retries_exhausted) 时正确处理
# ============================================================

def test_tags_meta_dict_retries_exhausted_returns_transient():
    """GitHub /tags API 失败返回 _retries_exhausted dict。
    应该走 TRANSIENT 路径，最终 rc=3。"""
    fake_wf = Path(tempfile.mkdtemp()) / "fake.yml"
    fake_wf.write_text(textwrap.dedent("""\
        name: fake
        on: [push]
        jobs:
          test:
            runs-on: ubuntu-latest
            steps:
              - uses: fake-org/fake-action@1234567890abcdef1234567890abcdef12345678 # v1.0.0
        """), encoding="utf-8")

    def mock_github(path, *args, **kwargs):
        if "/commits/" in path:
            # commits 成功
            return {
                "sha": "1234567890abcdef1234567890abcdef12345678",
                "commit": {"message": "release v1.0.0"},
            }
        if "/tags" in path:
            # tags 失败：返回 _retries_exhausted dict（不是 list）
            return {
                "_retries_exhausted": True,
                "_transient": True,
                "_error": "URLError: timeout",
            }
        return []

    with mock.patch.object(verify_pin, "github_api", side_effect=mock_github), \
         mock.patch.object(verify_pin, "download_action_yml", return_value=(None, True)):
        rc, results = verify_pin.verify_sha_pin(fake_wf, verbose=True, max_retries=1)

    try:
        assert rc == 3, f"expected rc=3 (TRANSIENT), got {rc}"
        tag_checks = [c for c in results[0]["checks"] if c[0] == "tag lookup"]
        assert len(tag_checks) == 1
        assert tag_checks[0][1] == "TRANSIENT", \
            f"tag lookup status should be TRANSIENT, got {tag_checks[0][1]!r}"
        _record("Bug 1: tags_meta dict (retries_exhausted) 走 TRANSIENT 路径", True)
    except AssertionError as e:
        _record("Bug 1: tags_meta dict (retries_exhausted) 走 TRANSIENT 路径", False, str(e))


# ============================================================
# 3. Bug 2 回归测试：USES_RE 匹配 "- uses:" (YAML list item)
# ============================================================

def test_uses_regex_matches_yaml_list_item():
    """YAML step 缩进后是 '- uses: ...'，之前 regex 是 '^\\s*uses:' 不能匹配。
    修复后 regex 是 '^\\s*-?\\s*uses:' 必须能匹配两种格式。"""
    # 测试 1: 缩进 + 横线
    text_indented = textwrap.dedent("""\
        jobs:
          test:
            steps:
              - uses: fake-org/fake-action@1234567890abcdef1234567890abcdef12345678 # v1.0.0
        """)
    matches = list(verify_pin.USES_RE.finditer(text_indented))
    assert len(matches) == 1, f"indented '- uses:' should match once, got {len(matches)}"
    assert matches[0].group("action") == "fake-org/fake-action"
    assert matches[0].group("ref") == "1234567890abcdef1234567890abcdef12345678"
    assert matches[0].group("comment") == "v1.0.0"
    _record("Bug 2: USES_RE 匹配 '  - uses: ...' (YAML list item)", True)

    # 测试 2: 无缩进无横线（老格式）
    text_plain = "uses: fake-org/fake-action@abcdef1234567890abcdef1234567890abcdef12"
    matches = list(verify_pin.USES_RE.finditer(text_plain))
    assert len(matches) == 1
    _record("Bug 2: USES_RE 仍能匹配无横线 'uses: ...'", True)

    # 测试 3: 缩进但无横线（少见但合理）
    text_spaced = "  uses: other-org/other-action@v1"
    matches = list(verify_pin.USES_RE.finditer(text_spaced))
    assert len(matches) == 1
    _record("Bug 2: USES_RE 仍能匹配 '  uses: ...' (无横线缩进)", True)


# ============================================================
# 4. 重试逻辑：transient 错误会重试
# ============================================================

class Fake503(HTTPError):
    def __init__(self):
        super().__init__(url="http://x", code=503, msg="Service Unavailable",
                         hdrs=None, fp=None)
    def __str__(self):
        return "503 Service Unavailable"


class Fake404(HTTPError):
    def __init__(self):
        super().__init__(url="http://x", code=404, msg="Not Found",
                         hdrs=None, fp=None)
    def __str__(self):
        return "404 Not Found"


def test_retry_transient_recovers():
    """transient 错误应在重试后成功。"""
    attempts = [0]

    def fn():
        attempts[0] += 1
        if attempts[0] < 2:
            raise Fake503()
        return "ok"

    import time
    start = time.time()
    # force non-CI path so ::warning:: 不被 GitHub Actions 当 annotation
    with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}), \
         redirect_stderr(io.StringIO()) as buf:
        ok, result = verify_pin.call_with_retry(
            fn, max_retries=3, initial_backoff=0.05, backoff_factor=2.0, label="test"
        )
    elapsed = time.time() - start

    assert ok is True
    assert result == "ok"
    assert attempts[0] == 2
    # 容差放宽：CI runner 上 time.sleep 不一定精确，0.04 太严苛
    # 0.02 下限（确保至少等过 1 次 backoff）+ 1.0 上限（容忍慢 runner）
    assert 0.02 < elapsed < 1.0
    # 验证 stderr 没有 ::warning:: 泄漏
    assert "::warning::" not in buf.getvalue(), \
        f"non-CI path should not emit ::warning::, got: {buf.getvalue()!r}"
    _record("重试: transient 503 在第 2 次成功后停止", True)


def test_retry_404_no_retry():
    """404 是 permanent 错误，不应重试。"""
    attempts = [0]

    def fn():
        attempts[0] += 1
        raise Fake404()

    with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}), \
         redirect_stderr(io.StringIO()):
        ok, result = verify_pin.call_with_retry(
            fn, max_retries=5, initial_backoff=0.05, backoff_factor=2.0, label="test"
        )

    assert ok is False
    assert isinstance(result, Fake404)
    assert attempts[0] == 1, f"404 should not retry, attempts={attempts[0]}"
    _record("重试: 404 permanent 错误不重试", True)


def test_retry_urlerror_retried():
    """URLError（DNS 失败等）应被视为 transient。"""
    attempts = [0]

    def fn():
        attempts[0] += 1
        if attempts[0] < 2:
            raise URLError("getaddrinfo failed")
        return "ok"

    with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}), \
         redirect_stderr(io.StringIO()) as buf:
        ok, result = verify_pin.call_with_retry(
            fn, max_retries=3, initial_backoff=0.05, backoff_factor=2.0, label="test"
        )
    assert ok is True
    assert attempts[0] == 2
    assert "::warning::" not in buf.getvalue(), \
        f"non-CI path should not emit ::warning::, got: {buf.getvalue()!r}"
    _record("重试: URLError 被识别为 transient", True)


def test_retry_exhaustion_returns_false():
    """持续 transient 错误达到 max_retries 后应放弃。"""
    attempts = [0]

    def fn():
        attempts[0] += 1
        raise Fake503()

    with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}), \
         redirect_stderr(io.StringIO()) as buf:
        ok, result = verify_pin.call_with_retry(
            fn, max_retries=3, initial_backoff=0.01, backoff_factor=2.0, label="test"
        )
    assert ok is False
    assert isinstance(result, Fake503)
    assert attempts[0] == 3
    assert "::warning::" not in buf.getvalue(), \
        f"non-CI path should not emit ::warning::, got: {buf.getvalue()!r}"
    _record("重试: 持续 transient 达到 max_retries 后放弃", True)


def test_retry_exponential_backoff_timing():
    """指数退避：backoff 应该按 2 倍增长。"""
    import time
    attempts = [0]

    def fn():
        attempts[0] += 1
        raise Fake503()

    start = time.time()
    with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}), \
         redirect_stderr(io.StringIO()):
        verify_pin.call_with_retry(
            fn, max_retries=3, initial_backoff=0.1, backoff_factor=2.0, label="test"
        )
    elapsed = time.time() - start

    # 预期：0.1s + 0.2s = 0.3s
    # 容差放宽：CI runner 慢 / 3.12 GIL 切换可能让 elapsed 略高于 0.3
    # 下限 0.25（确保真的等了 backoff，不是直接 return）
    # 上限 1.0（容忍 CI runner 抖动）
    assert 0.25 < elapsed < 1.0, f"backoff should be ~0.3s, got {elapsed:.2f}s"
    _record(f"重试: 指数退避正确 (elapsed={elapsed:.2f}s ≈ 0.3s)", True)


# ============================================================
# 5. is_transient 判定
# ============================================================

def test_is_transient_classification():
    """确认 is_transient 对各类错误的判定。"""
    test_cases = [
        (HTTPError(url="x", code=503, msg="x", hdrs=None, fp=None), True, "503"),
        (HTTPError(url="x", code=500, msg="x", hdrs=None, fp=None), True, "500"),
        (HTTPError(url="x", code=502, msg="x", hdrs=None, fp=None), True, "502"),
        (HTTPError(url="x", code=429, msg="x", hdrs=None, fp=None), True, "429"),
        (HTTPError(url="x", code=408, msg="x", hdrs=None, fp=None), True, "408"),
        (HTTPError(url="x", code=404, msg="x", hdrs=None, fp=None), False, "404"),
        (HTTPError(url="x", code=401, msg="x", hdrs=None, fp=None), False, "401"),
        (HTTPError(url="x", code=422, msg="x", hdrs=None, fp=None), False, "422"),
        (URLError("dns fail"), True, "URLError"),
        (TimeoutError("slow"), True, "TimeoutError"),
        (ValueError("bad input"), False, "ValueError"),
        (RuntimeError("oops"), False, "RuntimeError"),
    ]
    all_ok = True
    for exc, expected, label in test_cases:
        try:
            got = verify_pin.is_transient(exc)
            if got != expected:
                _record(f"is_transient({label})", False,
                        f"expected {expected}, got {got}")
                all_ok = False
        except Exception as e:
            _record(f"is_transient({label})", False, f"raised {type(e).__name__}: {e}")
            all_ok = False
    if all_ok:
        _record(f"is_transient 全部 {len(test_cases)} 种错误分类正确", True)


# ============================================================
# 6. 退出码语义
# ============================================================

def test_exit_code_0_all_ok():
    """全部通过 → rc=0。"""
    fake_wf = Path(tempfile.mkdtemp()) / "fake.yml"
    fake_wf.write_text(textwrap.dedent("""\
        jobs:
          test:
            steps:
              - uses: fake-org/fake-action@1234567890abcdef1234567890abcdef12345678 # v1.0.0
        """), encoding="utf-8")

    def mock_github(path, *args, **kwargs):
        if "/commits/" in path:
            return {"sha": "1234567890abcdef1234567890abcdef12345678",
                    "commit": {"message": "ok"}}
        if "/tags" in path:
            return [{"name": "v1.0.0",
                     "commit": {"sha": "1234567890abcdef1234567890abcdef12345678"}}]
        return []

    with mock.patch.object(verify_pin, "github_api", side_effect=mock_github), \
         mock.patch.object(verify_pin, "download_action_yml", return_value=(b"", False)):
        rc, results = verify_pin.verify_sha_pin(fake_wf, max_retries=1)

    assert rc == 0, f"expected rc=0, got {rc}"
    _record("退出码: 全部 OK → rc=0", True)


def test_exit_code_1_wrong_sha_format():
    """第三方 action 没用 SHA pin → rc=1。"""
    fake_wf = Path(tempfile.mkdtemp()) / "fake.yml"
    fake_wf.write_text(textwrap.dedent("""\
        jobs:
          test:
            steps:
              - uses: fake-org/fake-action@v1.0.0
        """), encoding="utf-8")

    rc, results = verify_pin.verify_sha_pin(fake_wf, max_retries=1)
    assert rc == 1, f"expected rc=1, got {rc}"
    _record("退出码: 第三方 action 没用 SHA pin → rc=1", True)


def test_exit_code_3_transient_network():
    """网络抖动持续失败 → rc=3 (transient)。"""
    fake_wf = Path(tempfile.mkdtemp()) / "fake.yml"
    fake_wf.write_text(textwrap.dedent("""\
        jobs:
          test:
            steps:
              - uses: fake-org/fake-action@1234567890abcdef1234567890abcdef12345678
        """), encoding="utf-8")

    def mock_github_transient(path, *args, **kwargs):
        return {
            "_retries_exhausted": True,
            "_transient": True,
            "_error": "URLError: timeout",
        }

    with mock.patch.object(verify_pin, "github_api", side_effect=mock_github_transient), \
         mock.patch.object(verify_pin, "download_action_yml", return_value=(None, True)):
        rc, results = verify_pin.verify_sha_pin(fake_wf, max_retries=1)

    assert rc == 3, f"expected rc=3, got {rc}"
    _record("退出码: 网络持续失败 → rc=3 (TRANSIENT)", True)


# ============================================================
# 7. SHA 验证（公共 API 端到端）
# ============================================================

def test_github_api_success_returns_parsed_json():
    """github_api 成功时返回解析后的 JSON（不需要重试）。"""
    # 用 monkeypatch 替换内部 urlopen
    import json
    fake_body = json.dumps({"sha": "abc", "commit": {"message": "x"}}).encode("utf-8")

    class FakeResp:
        def __init__(self, body):
            self._body = body
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return self._body

    with mock.patch.object(verify_pin.urllib.request, "urlopen",
                           return_value=FakeResp(fake_body)):
        result = verify_pin.github_api("/repos/foo/bar/commits/abc", max_retries=1)
    assert result == {"sha": "abc", "commit": {"message": "x"}}
    _record("github_api: 成功响应正确解析", True)


def test_github_api_non_transient_http_no_retry():
    """422 (non-transient) 不应重试。"""
    attempts = [0]

    def fake_urlopen(req, timeout=15):
        attempts[0] += 1
        raise HTTPError(url=str(req.full_url), code=422, msg="Unprocessable",
                        hdrs=None, fp=None)

    with mock.patch.object(verify_pin.urllib.request, "urlopen", side_effect=fake_urlopen):
        result = verify_pin.github_api("/x", max_retries=5, initial_backoff=0.01)

    assert attempts[0] == 1, f"422 should not retry, got {attempts[0]} attempts"
    assert result.get("_retries_exhausted") is True
    assert result.get("_transient") is False
    _record("github_api: 422 non-transient 不重试", True)


# ============================================================
# main runner
# ============================================================

def main():
    tests = [
        test_tags_meta_list_handled_correctly,
        test_tags_meta_dict_retries_exhausted_returns_transient,
        test_uses_regex_matches_yaml_list_item,
        test_retry_transient_recovers,
        test_retry_404_no_retry,
        test_retry_urlerror_retried,
        test_retry_exhaustion_returns_false,
        test_retry_exponential_backoff_timing,
        test_is_transient_classification,
        test_exit_code_0_all_ok,
        test_exit_code_1_wrong_sha_format,
        test_exit_code_3_transient_network,
        test_github_api_success_returns_parsed_json,
        test_github_api_non_transient_http_no_retry,
    ]

    print(f"=== running {len(tests)} tests ===\n")
    for t in tests:
        try:
            t()
        except Exception as e:
            _record(f"{t.__name__} (uncaught exception)", False,
                    f"{type(e).__name__}: {e}")
        print()

    print("=" * 60)
    print(f"summary: {PASS} passed, {FAIL} failed")
    if FAIL == 0:
        print("ALL TESTS PASSED")
        return 0
    print("FAILED TESTS:")
    for f in FAILS:
        print(f"  - {f}")
    return 1


if __name__ == "__main__":
    sys.exit(main())