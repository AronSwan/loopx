from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "sonarcloud.yml"


def test_missing_sonar_token_reaches_a_successful_skip_step() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "if: ${{ secrets.SONAR_TOKEN != '' }}" not in workflow
    assert "SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}" in workflow
    assert "if: env.SONAR_TOKEN == ''" in workflow
    assert "non-blocking analysis skipped" in workflow


def test_sonar_steps_remain_guarded_by_the_token() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count("if: env.SONAR_TOKEN != ''") == 5
