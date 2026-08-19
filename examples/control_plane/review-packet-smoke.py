#!/usr/bin/env python3
"""Smoke-test the dashboard operator action packet contract.

The dashboard owns the operator-facing packet text. This smoke keeps a
public-safe fixture for the planned opt-in path and checks the source keeps the
copyable packet short and human-facing. The longer local gate dry-run remains
available as an advanced/debug path, not as the default copied packet.
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ACTION_PACKET = REPO_ROOT / "apps/presentation/dashboard/src/data/action-packet.ts"
STATUS_CONTRACT = REPO_ROOT / "docs/status-data-contract.md"


def command_block(command: str) -> str:
    return "\n".join(["```bash", command, "```"])


def multiline_command(*lines: str) -> str:
    return "\n".join(lines)


def assert_order(text: str, labels: list[str]) -> None:
    positions = [text.index(label) for label in labels]
    assert positions == sorted(positions), (labels, positions, text)


def source_between(source: str, start: str, end: str) -> str:
    start_index = source.index(start)
    end_index = source.index(end, start_index)
    return source[start_index:end_index]


def build_sanitized_controller_packet() -> str:
    goal_id = "planned-main-control"
    project_agent_command = multiline_command(
        "loopx \\",
        "  --registry ./examples/registry.example.json \\",
        "  --runtime-root ./tmp/runtime \\",
        "  read-only-map \\",
        f"  --goal-id {goal_id} \\",
        "  --dry-run",
    )
    return "\n".join(
        [
            "【GH Packet】",
            f"目标：{goal_id}",
            "状态：planned opt-in review fixture",
            "",
            "【用户/Gate】",
            "待办：无",
            "Gate：是否允许目标项目进入 read-only/controller opt-in？",
            f"建议：同意 {goal_id} 先做 read-only map dry-run / 暂不同意 + 一句话原因。",
            "边界：这只授权项目 Agent 预览 dry-run 路径；不写 operator gate、run history、write-control、实验控制或生产动作。",
            "记录：落盘先 dry-run。",
            "",
            "【给项目 Agent】",
            "待办：Run the read-only map dry-run after the owner todo is resolved.",
            "路径：Read-only map dry-run",
            f"命令：{project_agent_command.replace(chr(10), ' ')}",
            "回报：files / validation / next；需授权则停。",
        ]
    )


def build_sanitized_controller_packet_with_user_todo() -> str:
    goal_id = "planned-main-control"
    project_agent_command = multiline_command(
        "loopx \\",
        "  --registry ./examples/registry.example.json \\",
        "  --runtime-root ./tmp/runtime \\",
        "  read-only-map \\",
        f"  --goal-id {goal_id} \\",
        "  --dry-run",
    )
    return "\n".join(
        [
            "【GH Packet】",
            f"目标：{goal_id}",
            "状态：planned opt-in review fixture",
            "",
            "【用户/Gate】",
            "待办：Read the owner review worksheet first.（先处理/暂缓再判 gate）",
            "Gate：是否允许目标项目进入 read-only/controller opt-in？",
            f"建议：先确认待办；完成后：同意 {goal_id} 先做 read-only map dry-run / 暂不同意 + 一句话原因。",
            "边界：这只授权项目 Agent 预览 dry-run 路径；不写 operator gate、run history、write-control、实验控制或生产动作。",
            "记录：落盘先 dry-run。",
            "",
            "【给项目 Agent】",
            "路径：Read-only map dry-run",
            f"命令：{project_agent_command.replace(chr(10), ' ')}",
            "回报：files / validation / next；需授权则停。",
        ]
    )


def build_sanitized_approved_command_packet() -> str:
    goal_id = "planned-main-control"
    approved_command = "loopx read-only-map --goal-id planned-main-control --dry-run --approved"
    return "\n".join(
        [
            "【GH Packet】",
            f"目标：{goal_id}",
            "状态：operator gate approved fixture",
            "",
            "【用户/Gate】",
            "待办：无",
            "Gate：无；建议：直接转发给已认领的项目 Agent；不追加写权限、全局接管或生产动作授权。",
            "边界：只执行已批准的只读/dry-run agent_command；如需写入或更高权限，项目 Agent 必须再次停下。",
            "",
            "【给项目 Agent】",
            "路径：Approved agent command",
            f"命令：{approved_command}",
            "回报：files / validation / next；需授权则停。",
        ]
    )


def build_sanitized_focus_wait_packet() -> str:
    goal_id = "focus-wait-owner-blocker"
    status_command = (
        "loopx --registry ./examples/registry.example.json "
        "--runtime-root ./tmp/runtime diagnose --goal-id focus-wait-owner-blocker --limit 20"
    )
    return "\n".join(
        [
            "【GH Packet】",
            f"目标：{goal_id}",
            "状态：quiet until owner evidence, a clean baseline, or external eval changes",
            "",
            "【用户/Gate】",
            "待办：Provide new owner evidence, a clean baseline, or external eval before delivery resumes.",
            "Gate：无；建议：继续保持 focus wait；有新 owner evidence、clean baseline 或外部 eval 后再恢复 delivery。",
            "边界：这不是 delivery approval；项目 Agent 只做 status/history inspection，不执行交付路径、写入、reward append 或生产动作。",
            "",
            "【给项目 Agent】",
            "待办：只检查当前 state/status/history；保持 focus_wait 并用中文回报仍在等待什么。",
            "路径：Status/history inspection only",
            f"命令：{status_command}",
            "回报：files / validation / next；需授权则停。",
        ]
    )


def main() -> int:
    action_packet_source = ACTION_PACKET.read_text(encoding="utf-8")
    contract = STATUS_CONTRACT.read_text(encoding="utf-8")
    controller_contract = source_between(
        contract,
        "For controller opt-in packets",
        "`status=read_only_project_map`",
    )
    assert "the dashboard/operator view owns the human decision" in contract
    assert "the project-agent command is the after-approval dry-run path" in contract
    assert_order(
        controller_contract,
        [
            "operator question must appear before any",
            "local gate preview must appear before any",
            "project-agent command",
        ],
    )

    assert_order(action_packet_source, ["【GH Packet】", "【用户/Gate】", "【给项目 Agent】"])
    for marker in (
        "Project Asset：legacy/raw fallback",
        "Project Asset：Owner=",
        "待办：",
        "Gate：",
        "先确认待办",
        "上下文：只信当前 state/status/history 与命令输出；勿拼旧状态。",
        "input.command ? `命令：",
        "需授权则停",
    ):
        assert marker in action_packet_source, marker
    assert "Project Asset Next" in action_packet_source
    assert "Project Asset Stop" in action_packet_source
    assert "只执行下面命令" in action_packet_source
    assert "生产动作授权" in action_packet_source

    packet = build_sanitized_controller_packet()
    assert_order(
        packet,
        [
            "【用户/Gate】",
            "Gate：是否允许目标项目进入 read-only/controller opt-in？",
            "建议：同意 planned-main-control 先做 read-only map dry-run / 暂不同意 + 一句话原因。",
            "记录：落盘先 dry-run。",
            "【给项目 Agent】",
            "read-only-map",
            "需授权则停",
        ],
    )
    assert "记录：落盘先 dry-run。" in packet, packet
    assert "operator-gate \\" not in packet, packet
    assert packet.count("read-only-map") == 1, packet
    assert len(packet.splitlines()) <= 18, packet
    assert "不写 operator gate、run history、write-control、实验控制或生产动作" in packet

    packet_with_todo = build_sanitized_controller_packet_with_user_todo()
    assert_order(
        packet_with_todo,
        [
            "【用户/Gate】",
            "待办：",
            "先处理/暂缓再判 gate",
            "Gate：",
            "建议：先确认待办",
            "【给项目 Agent】",
        ],
    )
    assert "Read the owner review worksheet first." in packet_with_todo
    assert "operator-gate \\" not in packet_with_todo, packet_with_todo
    assert len(packet_with_todo.splitlines()) <= 18, packet_with_todo

    approved_packet = build_sanitized_approved_command_packet()
    assert_order(
        approved_packet,
        [
            "【用户/Gate】",
            "Gate：无；建议：直接转发给已认领的项目 Agent",
            "只执行已批准的只读/dry-run agent_command",
            "【给项目 Agent】",
            "Approved agent command",
        ],
    )
    assert "同意让 Codex 沿 safe path 继续" not in approved_packet, approved_packet
    assert "如果下一步需要写入、reward append、approval" not in approved_packet, approved_packet
    assert "不追加写权限、全局接管或生产动作授权" in approved_packet, approved_packet
    assert len(approved_packet.splitlines()) <= 18, approved_packet

    focus_wait_packet = build_sanitized_focus_wait_packet()
    assert_order(
        focus_wait_packet,
        [
            "【用户/Gate】",
            "待办：Provide new owner evidence",
            "Gate：无；建议：继续保持 focus wait",
            "【给项目 Agent】",
            "Status/history inspection only",
        ],
    )
    assert "保持 focus_wait" in focus_wait_packet, focus_wait_packet
    assert "read-only-map" not in focus_wait_packet, focus_wait_packet
    assert "operator-gate" not in focus_wait_packet, focus_wait_packet
    assert len(focus_wait_packet.splitlines()) <= 18, focus_wait_packet
    print("review-packet-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
