# -*- coding: utf-8 -*-
"""research_run2.py 控制器回归套: 全离线,execute_turn/stage_route/run_phase/cli 一律 mock。

覆盖(坑1-10的防线):
P0-2 _failing_phases映射  P0-7 run_phase签名与委托(第10坑)  P0-8 next_instance计数
P0-1 gate_with_repair三态(救回/有界/结构性不修)  P0-3..6 ensure_phase四语义
P1-9 auto阶段顺序与双门禁序列  P1-10 stage_route staging
"""
import inspect
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import research_run2 as r2

GOOD_URLS = " https://a.example/x https://b.example/y https://c.example/z "
FILLER = "背景填充。" * 40  # 240B


def make_root(tmp_path, n=2, bad=()):
    """合成运行根: 不依赖 .local 证据根。bad 里放要做坏的工件名(如 'research-2')。"""
    root = Path(tmp_path)
    (root / "project").mkdir(parents=True, exist_ok=True)
    (root / "project" / "REQUIREMENTS.md").write_text(
        "# 研究委托: 测试课题\n\n## 本次研究要回答\n1. 问?\n2. 产出: 一份测试清单\n", encoding="utf-8")
    (root / "demo.json").write_text(json.dumps({"requests": ["req-1"]}), encoding="utf-8")
    (root / "agents/planner/outputs").mkdir(parents=True, exist_ok=True)
    (root / "agents/planner/outputs/plan.json").write_text(json.dumps(
        {"N": n, "subtopics": [{"id": i + 1, "scope": f"子课题{i+1}"} for i in range(n)],
         "difficulty_reasoning": "x"}, ensure_ascii=False), encoding="utf-8")
    for k in range(1, n + 1):
        d = root / "agents" / f"researcher-{k}" / "outputs"
        d.mkdir(parents=True, exist_ok=True)
        body = f"# 测试课题研究{k}\n{FILLER}{GOOD_URLS * 5}\n" if f"research-{k}" not in bad \
            else "太短"
        (d / f"research-{k}.md").write_text(body, encoding="utf-8")
    for actor in ("planner", "architect", "reviewer-1", "reviewer-2", "finalizer"):
        (root / "agents" / actor / "tasks").mkdir(parents=True, exist_ok=True)
    a = root / "agents/architect/outputs"
    a.mkdir(parents=True, exist_ok=True)
    (a / "architecture.md").write_text(
        "# 测试课题架构\n" + FILLER * 8 + GOOD_URLS + "\n", encoding="utf-8")  # >1500B
    for rv in ("reviewer-1", "reviewer-2"):
        d = root / "agents" / rv / "outputs"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"review-{rv[-1]}.md").write_text(
            f"# 测试课题评审\n{FILLER * 2}\n裁决:修改后采纳\n", encoding="utf-8")  # >400B+真裁决
    f = root / "agents/finalizer/outputs"
    f.mkdir(parents=True, exist_ok=True)
    (f / "final-plan.md").write_text(
        "# 测试课题终案\n决策摘要\n" + FILLER * 10 + "\n行动检查表(可打勾) 清单\n", encoding="utf-8")
    return root


# ==== P0-2 纯函数 ====
def test_failing_phases_maps_and_excludes_structural():
    rep = {"checks": [
        {"check": "research-2 引用>=3", "pass": False, "detail": "1"},
        {"check": "review-1.md 结构词", "pass": False, "detail": ""},
        {"check": "盲评隔离(reviewer-1不见reviewer-2)", "pass": False, "detail": ""}]}
    assert r2._failing_phases(rep) == ["researcher-2", "reviewer-1"]


def test_failing_phases_all_pass_is_empty():
    assert r2._failing_phases({"checks": [{"check": "x 非空", "pass": True}]}) == []


# ==== P0-8 next_instance ====
def test_next_instance_counts_home_glob(tmp_path):
    assert r2.next_instance(tmp_path, "planner") == "planner"
    (tmp_path / "home-planner").mkdir()
    assert r2.next_instance(tmp_path, "planner") == "planner-r1"
    (tmp_path / "home-planner-r1").mkdir()
    assert r2.next_instance(tmp_path, "planner") == "planner-r2"


# ==== P0-7 第10坑回归: run_phase 签名与委托 ====
def test_run_phase_signature_pinned():
    params = list(inspect.signature(r2.run_phase).parameters)
    assert params[:2] == ["root", "phase"]


def test_run_phase_delegates_without_extra_args(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(r2, "stage_route", lambda r, p, s=None: calls.append(("stage", p)))
    monkeypatch.setattr(r2, "execute_turn", lambda r, p: calls.append(("exec", p)) or {})
    r2.run_phase(tmp_path, "architect")
    assert calls == [("stage", "architect"), ("exec", "architect")]


# ==== P0-1 gate_with_repair 三态 ====
def test_gate_repair_recovers_after_rerun(tmp_path, monkeypatch):
    root = make_root(tmp_path, bad=("research-2",))

    def fake_run_phase(r, ph, *a, **k):
        (r / "agents/researcher-2/outputs/research-2.md").write_text(
            "修复稿 " + GOOD_URLS * 5 + FILLER, encoding="utf-8")
        return {"status": "committed"}
    monkeypatch.setattr(r2, "run_phase", fake_run_phase)
    assert r2.gate_with_repair(root, include_final=True) is True
    fb = root / "agents/researcher-2/outputs/repair-feedback.md"
    assert fb.exists() and "终验门禁失败项" in fb.read_text(encoding="utf-8")


def test_gate_repair_bounded_rounds(tmp_path, monkeypatch):
    root = make_root(tmp_path, bad=("research-2",))
    monkeypatch.setattr(r2, "run_phase", lambda r, p, *a, **k: {})
    assert r2.gate_with_repair(root, include_final=True, max_rounds=2) is False


def test_gate_structural_failure_never_reruns(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    (root / "agents/reviewer-1/inputs").mkdir(parents=True)
    (root / "agents/reviewer-1/inputs/review-2.md").write_text("x", encoding="utf-8")
    called = []
    monkeypatch.setattr(r2, "run_phase", lambda r, p, *a, **k: called.append(p))
    assert r2.gate_with_repair(root, include_final=True) is False
    assert called == []


# ==== P0-3..6 ensure_phase ====
def test_ensure_phase_skips_validated(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    monkeypatch.setattr(r2, "execute_turn", lambda *a: pytest.fail("不得调模型"))
    assert r2.ensure_phase(root, "researcher-1") == {"status": "committed", "skipped": True}


def test_ensure_phase_bounded_and_writes_feedback(tmp_path, monkeypatch):
    root = make_root(tmp_path, bad=("research-1",))
    monkeypatch.setattr(r2, "stage_route", lambda *a, **k: None)
    monkeypatch.setattr(r2, "execute_turn", lambda *a: {"status": "failed"})
    with pytest.raises(SystemExit):
        r2.ensure_phase(root, "researcher-1", max_tries=2)
    fb = root / "agents/researcher-1/outputs/repair-feedback.md"
    assert fb.exists() and "针对性修复要求" in fb.read_text(encoding="utf-8")


def test_ensure_phase_artifact_first(tmp_path, monkeypatch):
    root = make_root(tmp_path, bad=("research-1",))

    def boom(root, phase):  # turn 结算挂但工件好
        (root / "agents/researcher-1/outputs/research-1.md").write_text(
            "好文 " + GOOD_URLS * 5 + FILLER, encoding="utf-8")
        raise SystemExit("CLI failed")
    monkeypatch.setattr(r2, "stage_route", lambda *a, **k: None)
    monkeypatch.setattr(r2, "execute_turn", boom)
    assert r2.ensure_phase(root, "researcher-1")["artifact_first"] is True


# ==== P1-9 auto 顺序与双门禁 ====
def test_auto_orders_phases_and_gates(tmp_path, monkeypatch):
    root = make_root(tmp_path, n=2)
    seq, gates = [], []
    monkeypatch.setattr(r2, "ensure_phase",
                        lambda r, ph, sub=None: seq.append(ph) or {"status": "committed"})
    monkeypatch.setattr(r2, "gate_with_repair",
                        lambda r, include_final: gates.append(include_final) or True)
    r2.auto(root)
    idx = {p: i for i, p in enumerate(seq)}
    assert idx["planner"] < idx["researcher-1"] < idx["architect"]
    assert idx["architect"] < idx["reviewer-1"] and idx["architect"] < idx["reviewer-2"]
    assert max(idx["reviewer-1"], idx["reviewer-2"]) < idx["finalizer"]
    assert gates == [False, True]


# ==== P1-10 stage_route staging ====
def test_stage_route_stages_inputs_and_tasks(tmp_path, monkeypatch):
    root = make_root(tmp_path, n=2)
    monkeypatch.setattr(r2, "cli", lambda *a, **k: {"todos": []})
    import loopx.control_plane.collaboration.peers as peers_mod
    monkeypatch.setattr(peers_mod, "request", lambda *a, **k: None)
    r2.stage_route(root, "architect")
    assert (root / "agents/architect/inputs/research-1.md").exists()
    op = (root / "agents/architect/OPERATING.md").read_text(encoding="utf-8")
    assert "outputs/architecture.md" in op
    task = (root / "agents/architect/tasks/architect.md").read_text(encoding="utf-8")
    assert "{deliverables}" not in task and "{title}" not in task


# ==== P2: reference 参数化 ====
def test_reference_section_lists_and_declares():
    s = r2.reference_section([("final-v5.md", False), ("snap.md", True)])
    assert "- final-v5.md(来自前场调研)" in s and "- snap.md(缺失)" in s
    assert "必须重新检索" in s  # 防污染声明在场


# ==== P3: 裁决收尾 + 引用双模式 ====
def test_verdict_ok_synthetic_matrix():
    ok = ["## 五、结论:**修改后采纳**\n\n附:独立复核记录\n来源A",
          "**裁决:采纳**！",
          "- 判定:重做。",
          "Verdict:修改后采纳"]
    bad = ["**Verdict:有条件通过(conditional pass)。**",
           "**判定:validated_progress(有条件通过)**。",
           "结论:无需重做",
           "结论:不采纳该建议",
           "正文提到修改。\n(无标签裁决行)"]
    for t in ok:
        assert r2.verdict_ok(t), t
    for t in bad:
        assert not r2.verdict_ok(t), t


def test_citation_modes():
    lit_brief = "引用规范: 本课题允许标准文献标识符(DOI/PMID/arXiv/ISO号)计入引用数"
    assert r2.citation_mode(lit_brief) == "lit"
    assert r2.citation_mode("普通任务书") == "strict"
    # strict: 3 URL 过, 2 URL 挂
    assert r2.citations_ok("https://a https://b https://c", "strict")
    assert not r2.citations_ok("https://a https://b", "strict")
    # lit: 1 URL + 2 良构标识符 过; 0 URL 挂(底线); 3裸提法不算标识符
    assert r2.citations_ok("https://a 以及 PMID:6541615 和 arXiv:2609.26532", "lit")
    assert not r2.citations_ok("PMID:6541615 arXiv:2609.26532 10.1234/abc", "lit")
    assert not r2.citations_ok("https://a 某Gartner报告 ISO手册 JAMA论文", "lit")


# ==== 竣工检验加固: 裁决对抗(V1非紧邻否定/V2引言标签/V3借尾巴) ====
def test_verdict_ok_adversarial_hardening():
    pad = "背景段落。\n" * 6  # 把裁决行垫到全文后2/3
    bad = [
        pad + "结论:不宜采纳\n",            # V1 非紧邻否定
        pad + "裁决:不建议采纳\n",
        pad + "判定:拒绝采纳\n",
        pad + "裁决:暂缓采纳\n",
        pad + "**判定:有条件通过(等同修改后采纳)**\n",   # V3 借尾巴
        "结论:本文将论证是否采纳\n" + "正文。\n" * 5 + "判定为:有条件通过\n",  # V2 引言标签顶替
    ]
    for t in bad:
        assert not r2.verdict_ok(t), t[:24]
    ok = [
        pad + "裁决:采纳\n",
        pad + "结论:建议修改后采纳。\n",      # "建议"不在否定窗
        pad + "五、判定:重做。\n附:复核记录\n",
    ]
    for t in ok:
        assert r2.verdict_ok(t), t[:24]


def test_citation_hardening_v7_v8():
    # V7: 1 URL + 两个无部号ISO营销提法 不再凑数
    assert not r2.citations_ok(
        "https://example.com/a 我们是通过ISO 9001与ISO 27001认证的服务商", "lit")
    # 带部号的ISO标准才算标识符
    assert r2.citations_ok("https://a.example ISO 2859-1:1999 与 PMID:6541615", "lit")
    # V8: doi.org链接不再双重计数(剥URL后无标识符) → lit不成立
    n_url, n_id = r2.cite_counts("https://doi.org/10.1234/abc.def 另一条 https://doi.org/10.5555/xyz")
    assert (n_url, n_id) == (2, 0)
    # URL去重: 同一URL重复3次算1个源,strict不满足3
    assert not r2.citations_ok("https://same.example/x " * 3, "strict")


# ==== 竣工检验乙席: 变异盲区补测(M1/M3/M6) ====
def test_verdict_last_label_line_wins():  # M1: 取第一条标签行会误放
    t = "背景。\n" * 4 + "裁决:待复核\n" + "正文。\n" * 3 + "结论:采纳\n"
    assert r2.verdict_ok(t)  # 最后一条标签行收尾
    t2 = "背景。\n" * 4 + "结论:采纳\n" + "正文。\n" * 3 + "裁决:无需重做\n"
    assert not r2.verdict_ok(t2)  # 首条收尾、末条否定 → 必须拒


def test_failing_phases_knows_verdict_check():  # M3: "裁决收尾"失败项必须能定位
    rep = {"checks": [{"check": "review-2.md 裁决收尾", "pass": False, "detail": ""}]}
    assert r2._failing_phases(rep) == ["reviewer-2"]


def test_gate_repair_bounded_call_count(tmp_path, monkeypatch):  # M6: 修复轮恰好max_rounds轮
    root = make_root(tmp_path, bad=("research-2",))
    called = []
    monkeypatch.setattr(r2, "run_phase", lambda r, p, *a, **k: called.append(p) or {})
    assert r2.gate_with_repair(root, include_final=True, max_rounds=2) is False
    assert len(called) == 2
