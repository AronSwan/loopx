from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_runner() -> object:
    path = Path(__file__).resolve().parents[1] / "run_widesearch_case.py"
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("run_widesearch_case", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_app_server_command_disables_multi_agent_for_responses_compat() -> None:
    mod = _load_runner()
    command = mod._app_server_command(
        codex_bin="codex",
        enable_web_search=True,
        shell_policy_args=("-c", "shell-policy"),
    )
    assert "features.multi_agent=false" in command
    assert "tools.web_search=true" in command
    assert command[0] == "codex"
    assert "shell-policy" in command


def test_app_server_command_can_disable_web_search() -> None:
    mod = _load_runner()
    command = mod._app_server_command(
        codex_bin="codex",
        enable_web_search=False,
        shell_policy_args=(),
    )
    assert "tools.web_search=false" in command
    assert "tools.web_search=true" not in command


def test_app_server_environment_drops_unrelated_ambient_secrets() -> None:
    mod = _load_runner()
    environment = mod._app_server_environment(
        {
            "PATH": "/bin",
            "HOME": "/home/runner",
            "ARK_OPENAI_BASE_URL": "https://provider.invalid/v1",
            "ARK_OPENAI_API_KEY": "fixture-provider-value",
            "UNRELATED_PRIVATE_TOKEN": "must-not-propagate",
        }
    )
    assert environment == {
        "PATH": "/bin",
        "HOME": "/home/runner",
        "ARK_OPENAI_BASE_URL": "https://provider.invalid/v1",
        "ARK_OPENAI_API_KEY": "fixture-provider-value",
    }


def test_pier_agent_uses_gateway_sentinel_instead_of_provider_secret() -> None:
    template = (
        Path(__file__).resolve().parents[1] / "pier" / "job.yaml.template"
    ).read_text(encoding="utf-8")
    agent_section = template.partition("datasets:")[0]
    assert "<RUNNER_LOCAL_GATEWAY_BASE_URL>" in agent_section
    assert "LOOPX_MODEL_PROVIDER_SENTINEL" in agent_section
    assert "OPENAI_API_KEY" not in agent_section
    assert "<INJECT_VIA_RUNTIME_ENV>" not in agent_section
