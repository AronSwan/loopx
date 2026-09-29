"""The smoke runner suppresses telemetry in actual child processes."""
import json

from loopx.canary import runner


def test_smoke_subprocess_overrides_parent_telemetry_enable(tmp_path, monkeypatch):
    examples = tmp_path / "examples"
    examples.mkdir()
    (examples / "environment.py").write_text(
        "import json,os\nprint(json.dumps({k:os.environ.get(k) for k in "
        "['LOOPX_USAGE_PING','CI','SYNTHETIC_VALUE']}))\n", encoding="utf-8",
    )
    monkeypatch.setattr(runner, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("LOOPX_USAGE_PING", "1")
    monkeypatch.setenv("SYNTHETIC_VALUE", "preserved")
    monkeypatch.delenv("CI", raising=False)
    result = runner._run_check({"command": "python examples/environment.py"}, timeout_seconds=10)
    assert result["ok"], result
    assert json.loads(result["stdout_tail"]) == {
        "LOOPX_USAGE_PING": "0", "CI": None, "SYNTHETIC_VALUE": "preserved",
    }
