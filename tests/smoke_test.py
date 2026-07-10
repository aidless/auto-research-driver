"""smoke_test.py — driver 端到端 smoke test

跑法：py -3 tests/smoke_test.py

做什么：
1. 起一个临时 target_dir
2. 跑 driver run --skip-provider-check --skip-checkpoints --force --from-stage s1
3. 验证 state.json 写出来了
4. 验证每个 stage 的 artifact 路径都登记了
5. 跑 driver status 看是否显示 ALL CHECKPOINTS SIGNED（因 skip-checkpoints）
6. 跑 driver reset 清掉

不真调 MiniMax / 不真跑 tmlr_pipeline.run_pipeline.py（那是 review 阶段才真跑，
review 阶段本身需要 paper 才有意义；smoke 只走骨架）。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DRIVER_PY = HERE.parent / "scripts" / "driver.py"
PY = "py"


def _run(args: list, cwd=None) -> tuple[int, str]:
    cmd = [PY, "-3", str(DRIVER_PY)] + args
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        print(f"[smoke] target_dir = {td}")

        # 1. provider-check （会失败，因为真实 config.yaml 是 sk-xxx 占位符）
        rc, out = _run(["provider-check"])
        print(f"[smoke] provider-check rc={rc}")
        assert rc != 0, "provider-check should fail with placeholder key"
        assert "占位符" in out or "FAIL" in out, f"unexpected output: {out[:200]}"

        # 2. driver run --skip-provider-check --skip-checkpoints --force --to-stage s3_outline
        # 只跑 s1-s3，不碰 s4 (需要真 paper) / s5 (需要 simulator)
        rc, out = _run([
            "run",
            "--target-dir", str(td),
            "--idea", "smoke test idea",
            "--from-stage", "s1_idea",
            "--to-stage", "s3_outline",
            "--skip-provider-check",
            "--skip-checkpoints",
            "--force",
        ])
        print(f"[smoke] run rc={rc}\n{out[:2000]}")
        assert rc == 0, f"run failed: rc={rc}, out={out[:500]}"

        # 3. verify state.json
        state_path = td / ".driver" / "state.json"
        assert state_path.exists(), "state.json not written"
        import json
        state = json.loads(state_path.read_text(encoding="utf-8"))
        print(f"[smoke] state.completed = {state['completed']}")
        assert "s1_idea" in state["completed"]
        assert "s2_lit" in state["completed"]
        assert "s3_outline" in state["completed"]
        assert "s4_draft" not in state["completed"]
        assert "s5_review" not in state["completed"]

        # 4. verify artifacts
        assert "idea_canvas" in state["artifacts"]
        assert "refs_bib" in state["artifacts"]
        assert "outline" in state["artifacts"]
        print(f"[smoke] artifacts = {list(state['artifacts'].keys())}")

        # 5. driver status
        rc, out = _run(["status", "--target-dir", str(td)])
        print(f"[smoke] status rc={rc}\n{out}")
        assert "ALL CHECKPOINTS SIGNED" in out or "stage" in out

        # 6. driver reset
        rc, out = _run(["reset", "--target-dir", str(td)])
        assert rc == 0
        assert not state_path.exists(), "reset didn't remove state.json"
        print(f"[smoke] reset OK")

        # 7. driver checkpoints
        rc, out = _run(["checkpoints"])
        print(f"[smoke] checkpoints (first 500 chars):\n{out[:500]}")
        assert "S1" in out and "S6" in out

    print(f"\n[smoke] ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())