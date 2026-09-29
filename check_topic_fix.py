# -*- coding: utf-8 -*-
"""第8缺陷修复的离线验证: 模板渲染(双任务书)+新门禁(正/负样本)。不动旧运行根证据。"""
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, ".")
import research_run2 as r2

OUT = {}


def j(tag, v):
    OUT[tag] = v
    print(tag, "=", json.dumps(v, ensure_ascii=True)[:400])


eu = r2.BRIEF
saas = Path("brief-saas-review.md").read_text(encoding="utf-8")

# 1) helpers
j("eu_title", r2.brief_title(eu))
j("saas_title", r2.brief_title(saas))
j("eu_terms", r2.topic_terms(eu))
j("saas_terms", r2.topic_terms(saas))
j("eu_deliverables", r2.deliverables_of(eu))
j("saas_deliverables", r2.deliverables_of(saas))

# 2) 全模板渲染(两任务书×全phase),不留未替换占位符
for name, brief in (("eu", eu), ("saas", saas)):
    fill = {"deliverables": r2.deliverables_of(brief), "title": r2.brief_title(brief)}
    for phase, tpl in r2.TASKS.items():
        out = tpl.format(**fill)
        assert "{" + "deliverables" + "}" not in out and "{" + "title" + "}" not in out
        assert "{{" not in out, (name, phase, "leftover doubled braces")
    rt = r2.RESEARCHER_TASK.format(k="1", scope="测试范围")
    assert "EUR-Lex" not in rt and "GDPR" not in rt and "义务" not in rt
j("render_both_briefs", "ok")

# 3) planner JSON示例坍缩为单括号
fill = {"deliverables": "x", "title": "y"}
pl = r2.TASKS["planner"].format(**fill)
frag = re.search(r'\{"N": <int 1-4>.*?一段话>"\}', pl)
j("planner_json_example_single_brace", bool(frag))

# 4) 旧运行根(证据不动,拷最小子集)过新门禁
def mini_copy(src, dst):
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    (dst / "project").mkdir(parents=True)
    shutil.copy(src / "project" / "REQUIREMENTS.md", dst / "project" / "REQUIREMENTS.md")
    for p in list((src / "agents").glob("*/outputs/*")):
        if p.is_file():
            d = dst / p.relative_to(src)
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(p, d)


for tag, srcp in (("gate_eu_run", Path(".local/research2-run")),
                  ("gate_saas_run", Path(".local/research2-b"))):
    dst = Path(".local/tmp-topic-check") / tag
    mini_copy(srcp, dst)
    ok = r2.gate(dst, include_final=True)
    rep = json.loads((dst / "gate-report.json").read_text(encoding="utf-8"))
    j(tag, {"ok": ok,
            "topic_checks": [c for c in rep["checks"] if "主题匹配" in c["check"]]})

# 5) 负样本: SaaS任务书 + AI-Act骨架终稿(其他文件照抄真实SaaS产物) → 主题匹配必须红
neg = Path(".local/tmp-topic-check/neg")
mini_copy(Path(".local/research2-b"), neg)
stale = ("# 合规终案\n## 分渠道义务清单\n邮件/官网挂件/WhatsApp逐条义务(带条款号)。\n"
         "## GDPR交叉动作\n数据出境与个人数据处理动作若干。\n"
         "## 最小留档与举证要求\n文档与留存集。\n## 模板披露话术(中英对照)\nAI披露模板。\n"
         "## 行动检查表\n可打勾条目。" + "义务义务义务GDPR GDPR 披露话术。" * 40)
(neg / "agents/finalizer/outputs/final-plan.md").write_text(stale, encoding="utf-8")
ok = r2.gate(neg, include_final=True)
rep = json.loads((neg / "gate-report.json").read_text(encoding="utf-8"))
j("gate_negative", {"ok": ok,
                    "failed": [c["check"] for c in rep["checks"] if not c["pass"]]})

# 6) 形状稳健性: 各种标题/结构不退化(不为阈值定制,只验不崩不空)
shapes = [
    "# 研究委托: WhatsApp收费新政应对方案\n\n## 本次研究要回答\n1. 成本冲击多大?\n",
    "# 研究委托: 大促期间客服弹性扩容\n\n## 本次研究要回答\n1. 怎么扩?\n",
    "# Research: API cost benchmark 2026\n\n1. what changed?\n",
    "# 无冒号标题的一次研究\n\n产出: 一份对照表\n",
    "# 研究委托\n\n只有正文没有问题清单。\n",
    "没有一级标题的任务书\n\n## 本次研究要回答\n1. 问题A?\n2. 产出: 简报一份\n",
]
shape_res = []
for s in shapes:
    t = r2.topic_terms(s)
    d = r2.deliverables_of(s)
    assert isinstance(t, list) and isinstance(d, str) and d, "helper退化"
    shape_res.append({"title": r2.brief_title(s), "n_terms": len(t),
                      "terms_head": t[:4], "deliverables": d[:30]})
j("shape_robustness", shape_res)

shutil.rmtree(Path(".local/tmp-topic-check"))
print("DONE")
