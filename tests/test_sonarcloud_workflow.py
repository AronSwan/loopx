from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "sonarcloud.yml"


def test_missing_sonar_token_reaches_a_successful_skip_step() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "if: ${{ secrets.SONAR_TOKEN != '' }}" not in workflow
    assert "id: sonar-token" in workflow
    assert "available=false" in workflow
    assert "if: steps.sonar-token.outputs.available != 'true'" in workflow
    assert "non-blocking analysis skipped" in workflow


def test_sonar_steps_remain_guarded_by_the_token() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count("if: steps.sonar-token.outputs.available == 'true'") == 5
    assert workflow.count("SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}") == 2
    assert "\n    env:\n      SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}" not in workflow
