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
    for k in range(1, n + 1):  # 调研员也要tasks目录(生产由prepare建,夹具须对齐)
        (root / "agents" / f"researcher-{k}" / "tasks").mkdir(parents=True, exist_ok=True)
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
        "# 测试课题终案\n决策摘要\n" + FILLER * 10 + "\n决策与行动清单(可打勾)\n", encoding="utf-8")  # 只含'清单'不含'检查表'(门三#3: 双关键词曾致any-of回归测试恒真)
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


# ==== v2批次1: 修复轮异常保护(第五场事故回归) ====
def test_gate_repair_survives_cli_failure(tmp_path, monkeypatch):
    """修复轮内 run_phase 抛异常不再直穿 auto——落账后继续,最终 False 而非 SystemExit。"""
    root = make_root(tmp_path, bad=("research-2",))
    def boom(r, p, *a, **k):
        raise SystemExit("CLI failed; inspect last-cli-failure.log")
    monkeypatch.setattr(r2, "run_phase", boom)
    try:
        ok = r2.gate_with_repair(root, include_final=True, max_rounds=2)
        assert ok is False  # 正常耗尽返回False,不抛
    except SystemExit:
        pytest.fail("修复轮异常直穿控制器(第五场事故回归)")


# ==== P1批次(2026-10-01智囊团): 三段式报错——位置+实际值+改法 ====
def test_verdict_diagnose_names_actual_state():
    """诊断必须说'实际是什么'而非复述规则: 无标签行/错收尾词/好文档三种。"""
    no_label = FILLER + "\n" + GOOD_URLS  # 无裁决标签行
    assert "没有" in r2.verdict_diagnose(no_label)
    wrong_tail = FILLER + "\n裁决:基本合格\n"  # 标签行在,但不以三词收尾
    d = r2.verdict_diagnose(wrong_tail)
    assert "行尾不是三词之一" in d and "裁决:基本合格" in d
    good = FILLER * 2 + "\n裁决:采纳\n"
    assert r2.verdict_ok(good)  # 诊断只服务失败路径,但同输入verdict_ok必须真过


def test_gate_report_carries_citation_gap_detail(tmp_path):
    """引用失败项的detail必须带'实际X条/还差Y条',不再空串。"""
    root = make_root(tmp_path, n=2)
    # 做坏research-1的引用: 保留体积但URL清零
    p = root / "agents/researcher-1/outputs/research-1.md"
    p.write_text("# 测试课题研究1\n" + FILLER + "\n", encoding="utf-8")
    ok = r2.gate(root, include_final=True)
    assert not ok
    rep = json.loads((root / "gate-report.json").read_text(encoding="utf-8"))
    cite = next(c for c in rep["checks"] if c["check"] == "research-1 引用>=3")
    assert not cite["pass"] and "实际完整URL=0" in cite["detail"] and "还差3条" in cite["detail"]


def test_structure_word_check_keeps_any_of_semantics(tmp_path):
    """结构词检查维持'任一命中即过'(曾险改成全命中);detail带实际命中的词。"""
    root = make_root(tmp_path)  # final-plan含'清单'不含'检查表'
    ok = r2.gate(root, include_final=True)
    assert ok  # 只含'清单'也必须过
    rep = json.loads((root / "gate-report.json").read_text(encoding="utf-8"))
    sw = next(c for c in rep["checks"] if c["check"] == "final-plan.md 结构词")
    assert sw["pass"] and "清单" in sw["detail"]


# ==== P3批次(2026-10-01智囊团): 同质化防御——来源重叠度量+架构师告警注入 ====
def test_url_set_normalizes_tail_punctuation():
    s = r2.url_set("见 https://a.example/x/。 与 [t](https://A.example/x) 及 http://b.io/y,")
    assert s == {"https://a.example/x", "http://b.io/y"}


def test_homog_report_orders_and_warns_only_above_threshold(tmp_path):
    root = make_root(tmp_path, n=2)
    # 两个调研员给完全相同的来源集 → J=1.0 触发告警
    same = "# x\n" + FILLER + GOOD_URLS * 3 + "\n"
    for k in (1, 2):
        (root / "agents" / f"researcher-{k}" / "outputs" / f"research-{k}.md").write_text(
            same, encoding="utf-8")
    pairs = r2.homog_report(root, 2)
    assert pairs[0]["jaccard"] == 1.0 and pairs[0]["shared"] == 3
    w = r2.homog_warning(root, 2)
    assert "同质化告警" in w and "research-1×research-2" in w


def test_homog_warning_silent_when_distinct(tmp_path):
    root = make_root(tmp_path, n=2)  # make_root两调研员URL本就相同…
    # 改成不相交来源集 → 无告警
    (root / "agents/researcher-1/outputs/research-1.md").write_text(
        "# x\n" + FILLER + " https://r1.only/a https://r1.only/b https://r1.only/c\n", encoding="utf-8")
    (root / "agents/researcher-2/outputs/research-2.md").write_text(
        "# y\n" + FILLER + " https://r2.only/a https://r2.only/b https://r2.only/c\n", encoding="utf-8")
    assert r2.homog_warning(root, 2) == ""


def test_gate_report_records_homogenization_ledger(tmp_path):
    root = make_root(tmp_path, n=2)
    r2.gate(root, include_final=True)
    rep = json.loads((root / "gate-report.json").read_text(encoding="utf-8"))
    assert rep["homogenization"] and rep["homogenization"][0]["pair"] == [1, 2]


def test_architect_task_injects_homog_warning(tmp_path, monkeypatch):
    """来源重叠超阈值时,architect任务书必须带告警段(汇总者是唯一的化解位置)。"""
    root = make_root(tmp_path, n=2)  # make_root两调研员同一批GOOD_URLS=高重叠
    monkeypatch.setattr(r2, "cli", lambda *a, **k: {"todos": []})
    import loopx.control_plane.collaboration.peers as peers_mod
    monkeypatch.setattr(peers_mod, "request", lambda *a, **k: None)
    r2.stage_route(root, "architect")
    task = (root / "agents/architect/tasks/architect.md").read_text(encoding="utf-8")
    assert "同质化告警" in task and "research-1×research-2" in task
    # 来源不相交时不注入(告警是信号不是仪式)
    (root / "agents/researcher-2/outputs/research-2.md").write_text(
        "# y\n" + FILLER + " https://r2.only/a https://r2.only/b https://r2.only/c\n", encoding="utf-8")
    r2.stage_route(root, "architect")
    task2 = (root / "agents/architect/tasks/architect.md").read_text(encoding="utf-8")
    assert "同质化告警" not in task2


# ==== P4批次(2026-10-01智囊团): pass^k双轨指标——"最终全绿"须能拆出"首试绿" ====
def test_attempts_ledger_counts_exact_home_dirs(tmp_path):
    """与next_instance同源计数: home-x 与 home-x-rN 都算;不误吞别棒目录。"""
    for d in ("home-planner", "home-planner-r1", "home-architect",
              "home-researcher-1", "home-researcher-1-r1", "home-researcher-1-r2",
              "home-reviewer-2"):
        (tmp_path / d).mkdir()
    led = r2.attempts_ledger(tmp_path, 2)
    assert led["planner"] == 2 and led["architect"] == 1
    assert led["researcher-1"] == 3 and led["researcher-2"] == 0
    assert led["reviewer-1"] == 0 and led["reviewer-2"] == 1


def test_gate_report_carries_passk_ledger(tmp_path):
    """gate-report必须带attempts台账+first_pass清单: 全绿也要能拆出首试绿。"""
    root = make_root(tmp_path, n=2)
    (root / "home-planner").mkdir()      # planner首试
    (root / "home-researcher-1").mkdir()  # r1首试
    (root / "home-researcher-1-r1").mkdir()  # r2重试过
    r2.gate(root, include_final=True)
    rep = json.loads((root / "gate-report.json").read_text(encoding="utf-8"))
    assert rep["attempts"]["researcher-1"] == 2
    assert "researcher-1" not in rep["first_pass"]
    # 独立断言(审计批三#1: 原or写法两侧同条件恒真,first_pass改坏也拦不住)
    assert rep["first_pass"] == ["planner"] and rep["attempts"]["planner"] == 1


def test_homog_threshold_boundary_strict_above():  # 审计批三#1: J=0.7边界行为零覆盖
    """严格大于: J恰=0.7不告警,>0.7告警(阈值曾两处硬编码,现单一常量)。"""
    assert r2.HOMOG_THRESHOLD == 0.7
    sa = {f"https://a.io/{i}" for i in range(10)}        # 10个
    sb = {f"https://a.io/{i}" for i in range(7)}          # 7个全共享→交7/并10=0.7
    t1 = "# x\n" + FILLER + " " + " ".join(sorted(sa)) + "\n"
    t2 = "# y\n" + FILLER + " " + " ".join(sorted(sb)) + "\n"
    assert abs(len(sa & sb) / len(sa | sb) - 0.7) < 1e-9  # 交7/并10恰=0.7
    assert "同质化" not in _warn_with_texts(t1, t2)  # J=0.7恰不告警(严格大于)
    sb2 = {f"https://a.io/{i}" for i in range(8)}    # 交8/并10=0.8>0.7
    assert len(sa & sb2) / len(sa | sb2) > 0.7
    t2b = "# y\n" + FILLER + " " + " ".join(sorted(sb2)) + "\n"
    assert "同质化" in _warn_with_texts(t1, t2b)


def _warn_with_texts(t1, t2, n=2):
    import tempfile
    from pathlib import Path as P
    root = P(tempfile.mkdtemp())
    for k, t in ((1, t1), (2, t2)):
        d = root / "agents" / f"researcher-{k}" / "outputs"
        d.mkdir(parents=True)
        (d / f"research-{k}.md").write_text(t, encoding="utf-8")
    return r2.homog_warning(root, n)


# ==== 六门复审整改批次(2026-10-01): 逐条钉死审计实锤项 ====
def test_spread_sample_n1_takes_middle_no_crash():  # 门一#2: n=1曾除零
    import claim_audit as ca
    c = [(i, f"行{i}") for i in range(5)]
    assert ca.spread_sample(c, 1) == [c[2]]
    assert ca.spread_sample([], 1) == []


def test_cite_counts_sticky_tail_single_url_counts_once():  # 乙席#2: 同URL三种粘尾曾计3源骗过门禁
    t = "见 https://a.example/x。其次 https://a.example/x，见下。三处 https://a.example/x)"
    n_url, _ = r2.cite_counts(t)
    assert n_url == 1, f"粘尾变体应归一为1源,实得{n_url}"
    assert not r2.citations_ok(t + FILLER, "strict")


def test_verdict_neg_near_catches_fei_compounds():  # 门四#1: 并非/绝不曾放行
    body = FILLER * 3 + "\n"
    for bad in ("结论:并非重做", "裁决:绝不采纳", "判定:远非重做"):
        assert not r2.verdict_ok(body + bad), bad


def test_verdict_appendix_numbered_line_cannot_override():  # 门四#2: 附录编号行曾顶替真否定裁决
    t = FILLER * 3 + "\n裁决:无需重做\n## 附录 处理记录\n1. 结论:采纳。\n"
    assert not r2.verdict_ok(t)
    # 正例: 附录之后的合法裁决不再算,但正文裁决仍在附录前且合法→过
    t2 = FILLER * 3 + "\n裁决:修改后采纳\n## 附录\n1. 结论:采纳。\n"
    assert r2.verdict_ok(t2)


def test_citation_mode_negative_sentence_stays_strict():  # 门四#5: "不允许"曾照样切lit
    assert r2.citation_mode("本课题不允许标准文献标识符") == "strict"
    assert r2.citation_mode("本课题允许标准文献标识符") == "lit"


def test_verdict_diagnose_agrees_with_ok_on_trailing_ws():  # 门四#4: 行尾空白曾致诊断与门禁分叉
    t = FILLER * 3 + "\n裁决:采纳         \n"  # 9个尾随空格:TAIL{0,8}放不过
    assert not r2.verdict_ok(t)
    d = r2.verdict_diagnose(t)
    assert "行尾不是三词" in d, d  # 诊断必须指出真实死因,不得报"好行"


def test_stage_route_researcher_none_subtopics_falls_back_to_plan(tmp_path, monkeypatch):
    """乙席#1: 修复环对researcher曾传None→TypeError→修复死路。现从plan.json回读。"""
    root = make_root(tmp_path, n=2)
    monkeypatch.setattr(r2, "cli", lambda *a, **k: {"todos": []})
    import loopx.control_plane.collaboration.peers as peers_mod
    monkeypatch.setattr(peers_mod, "request", lambda *a, **k: None)
    r2.stage_route(root, "researcher-2", None)  # 修复环的真实调用形态
    task = (root / "agents/researcher-2/tasks/researcher-2.md").read_text(encoding="utf-8")
    assert "子课题2" in task


def test_stale_repair_feedback_not_appended(tmp_path, monkeypatch):  # 乙席#17: 陈旧反馈误导无关重跑
    import os
    root = make_root(tmp_path, n=2)
    monkeypatch.setattr(r2, "cli", lambda *a, **k: {"todos": []})
    import loopx.control_plane.collaboration.peers as peers_mod
    monkeypatch.setattr(peers_mod, "request", lambda *a, **k: None)
    fb = root / "agents/researcher-1/outputs/repair-feedback.md"
    art = root / "agents/researcher-1/outputs/research-1.md"
    fb.write_text("# 旧反馈", encoding="utf-8")
    os.utime(fb, (1000, 1000))          # 反馈很旧
    os.utime(art, (2000, 2000))         # 工件更新=已修好
    r2.stage_route(root, "researcher-1", ["s1", "s2"])
    t1 = (root / "agents/researcher-1/tasks/researcher-1.md").read_text(encoding="utf-8")
    assert "REPAIR ATTEMPT" not in t1
    os.utime(art, (500, 500))           # 工件比反馈旧=真未修
    r2.stage_route(root, "researcher-1", ["s1", "s2"])
    t2 = (root / "agents/researcher-1/tasks/researcher-1.md").read_text(encoding="utf-8")
    assert "REPAIR ATTEMPT" in t2


def test_claim_audit_ssrf_and_anchor_window():  # 门二#6 + 窗口四件套直锚
    import claim_audit as ca
    assert ca._ssrf_blocked("http://127.0.0.1:9090/x")
    assert ca._ssrf_blocked("http://169.254.169.254/latest/meta-data")
    assert ca._ssrf_blocked("http://192.168.1.5/admin")
    assert not ca._ssrf_blocked("https://eur-lex.europa.eu/x")
    gdpr = open('.local/gdpr-fulltext.txt', encoding='utf-8').read() if Path('.local/gdpr-fulltext.txt').exists() else ("序言" * 100 + "Article 13 位置标记 " + "正文" * 100000 + "Article 13 个人数据透明义务条款" + "尾" * 5000)
    w = ca.best_window("GDPR第13条规定透明义务,参考Article 13", gdpr)
    assert "透明义务" in w or "Article 13" in w  # 直锚落在条款正文而非序言
    w2 = ca.best_window("guard规则含退订链接与物理地址", gdpr)  # 无锚+零命中→首窗(诚实)
    assert w2 == gdpr[:ca.JUDGE_WINDOW]


def test_claim_audit_json_regex_nested_and_escape():
    import re as _re
    import claim_audit as ca
    m = _re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}",
                   'x {"verdict":"支持","reason":"引{Art. 13}原文"} y')
    assert json.loads(m.group(0))["verdict"] == "支持"
    assert ca.esc("a|b") == "a\\|b"  # 管道符真转义,引文逐字


# ==== 整改批二测试钉(2026-10-01): 乙席测试盲区两项 ====
def test_mid_gate_excludes_finalizer_checks_and_repair_target(tmp_path):
    """include_final=False: finalizer检查不进报告,_failing_phases拉不到finalizer(乙席#14)。"""
    root = make_root(tmp_path, n=2)
    ok_mid = r2.gate(root, include_final=False)
    rep = json.loads((root / "gate-report.json").read_text(encoding="utf-8"))
    names = [c["check"] for c in rep["checks"]]
    assert ok_mid and not any("final-plan" in n for n in names), names
    # 做坏finalizer也不该被中检报告点名(它不在中检范围)
    (root / "agents/finalizer/outputs/final-plan.md").write_text("空", encoding="utf-8")
    ok_mid2 = r2.gate(root, include_final=False)
    rep2 = json.loads((root / "gate-report.json").read_text(encoding="utf-8"))
    assert ok_mid2 and "finalizer" not in r2._failing_phases(rep2)


def test_verdict_diagnose_covers_position_and_borrow_branches():
    """diagnose六分支钉全(乙席#13): 位置规则分支与借词分支此前零覆盖。"""
    long_doc = "\n".join(f"第{i}行填充内容。" for i in range(12))
    d_pos = r2.verdict_diagnose("裁决:采纳\n" + long_doc)  # 标签行在第0行<1/3
    assert "前1/3" in d_pos, d_pos
    body = long_doc + "\n结论:有条件通过(等同修改后采纳)\n"
    d_borrow = r2.verdict_diagnose(body)
    assert "借词" in d_borrow, d_borrow
