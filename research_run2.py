# -*- coding: utf-8 -*-
"""LoopX × dsh 自适应DAG研究编队 v2: 难度路由驱动并行展开。

架构: planner(难度评估→plan.json定N) -> N×researcher并行(互斥子课题)
      -> architect(合流) -> reviewer-1 ∥ reviewer-2(双盲评) -> 门禁 -> finalizer(终稿)
质量阀门(恒定,不随N变): effort=max / 每工件非空+引用检查 / 双盲互相不可见 / 门禁fail-closed。
速度: 并行段墙钟≈最慢一支;各阶段耗时实测落盘 stage-timing.json。

用法:
  export GLM_API_KEY=xxx  (或 DEEPSEEK_API_KEY)
  uv run --extra test --extra deepseek-harness python research_run2.py prepare --root .local/r2
  uv run ... research_run2.py auto --root .local/r2 --execute     # 全链(含并行段)
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from loopx.capabilities.manager_context import deliver
from loopx.chat_store import ChatSessionStore

HERE = Path(__file__).parent
GOAL = "adaptive-research"
ROOT = Path(".local/research2-run")
MAXN = 4
ACTORS = ("planner", "architect", "reviewer-1", "reviewer-2", "finalizer") + tuple(
    f"researcher-{k}" for k in range(1, MAXN + 1))

DSH_MODEL = os.environ.get("DSH_MODEL", "glm-5.3-flash")
DSH_EFFORT = os.environ.get("DSH_EFFORT", "max")
DSH_MAX_TOKENS = "131072"

BRIEF = """# 研究委托: EU AI Act 第50条实操合规清单(家具出口工厂AI客服)

## 我们是谁(真实约束,评审以此为据)
- 中国家具出口工厂,B2B,客户在欧盟;AI客服按自建方案v5.0落地中
  (FastGPT+国内VPS+邮件/WhatsApp渠道;AI只起草不自动发送的放权阶梯)
- 老板是唯一审批人;无专职法务;预算敏感
- 参考既有方案: reference/final-v5.md(中文终案,含红线与放权阶梯)

## 本次研究要回答
1. EU AI Act 第50条(透明度义务,2025-02起适用)对我们这种"AI起草+人审批"的客服模式,
   具体触发哪些告知/标识/文档义务? 分渠道(邮件/官网挂件/WhatsApp)逐条列。
2. 与 GDPR(数据出境、个人数据)的交叉要求,实操上怎么一起满足?
3. 罚则风险分级与最小合规动作集: 小工厂花最少力气做到"够用且可举证"。
4. 产出: 老板可直接照做的合规清单(检查表+模板话术+留档要求)。

## 硬性红线(不可协商)
AI 不得自行: 报价折扣/交期承诺/认证合规声明/合同性确认等(继承v5.0十五条);
合规建议必须给出来源(条款号或官方URL),不得凭空编造义务。
"""

# ---- 任务书派生层(第8缺陷修复): 任务文本与门禁都从任务书取主题,不硬编码任何课题 ----

_GENERIC_BIGRAMS = {"研究", "委托", "本次", "我们", "以及", "怎么", "如何", "什么", "实操", "落地"}
_GENERIC_LATIN = {"vs", "the", "of", "and", "for", "or"}


def brief_title(brief):
    """任务书首行'# '标题,去掉'研究委托:'类前缀。"""
    for line in brief.splitlines():
        s = line.strip()
        if s.startswith("# "):
            body = s[2:]
            if ":" in body or "：" in body:
                body = re.split(r"[:：]", body, maxsplit=1)[1]
            return body.strip()
    return ""


def topic_terms(brief, limit=10):
    """标题里的拉丁词+CJK二元组(去通用词)——门禁'主题匹配'的判据。"""
    title = brief_title(brief)
    terms = []
    for w in re.findall(r"[A-Za-z][A-Za-z0-9.+-]*", title):
        if len(w) >= 2 and w.lower() not in _GENERIC_LATIN and w not in terms:
            terms.append(w)
    cjk = re.sub(r"[^\u4e00-\u9fff]", "", title)
    for a, b in zip(cjk, cjk[1:]):
        t = a + b
        if t not in _GENERIC_BIGRAMS and t not in terms:
            terms.append(t)
    return terms[:limit]


def deliverables_of(brief):
    """交付要求唯一来源: '产出:'行 → 否则'本次研究要回答'末条 → 否则通用兜底。"""
    m = re.search(r"^\s*(?:\d+[.、)]\s*)?产出[:：]\s*(.+)$", brief, re.M)
    if m:
        return m.group(1).strip()
    sec = re.search(r"^##\s*本次研究要回答[^\n]*\n(.*?)(?=^##\s|\Z)", brief, re.M | re.S)
    if sec:
        items = re.findall(r"^\s*\d+[.、)]\s*(.+)$", sec.group(1), re.M)
        if items:
            return items[-1].strip()
    return "按任务书'本次研究要回答'逐条回答,并给出老板可直接照做的交付物"


# ---- 裁决收尾门禁(第9坑家族: 结构词全文命中曾3/8假阴性;竣工检验甲席对抗加固) ----
VERDICT_LABEL = re.compile(  # 标签式裁决行: 行首(允许#/列表/序号/粗体)即 裁决|判定|结论|Verdict + 冒号
    r"^\s{0,3}(?:#{1,6}\s*)?(?:[-*•]|\d{1,2}[.、)])?\s*"
    r"(?:[一二三四五六七八九十]{1,3}|\d{1,2})?[、.．]?\s*\**\s*"
    r"(裁决|判定|结论|[Vv]erdict)\s*[:：]")
VERDICT_TAIL = re.compile(  # 三词收尾;尾部容粗体/全角标点;否定式(无需重做/不采纳)不算
    r"(?<!无需)(?<!不需)(?<!不再)(?<!不)(?<!无)(?<!勿)(?<!莫)"
    r"(修改后采纳|重做|采纳)[\s。.，！!？?…*)）)」』’”】\[\]]{0,8}$")
# 竣工检验V1: lookbehind只查紧邻1字,"不宜/不建议/拒绝/无法/暂缓采纳"曾全放行 → 前置窗口否定
VERDICT_NEG_NEAR = re.compile(r"[不宜勿莫拒难暂缓无未非]")  # 门四#1: "非"系(并非/绝非/远非)曾放行
# 竣工检验V3: "有条件通过(等同修改后采纳)"借括号尾巴过验 → 收尾词前窗口出现"通过/pass"即拒
VERDICT_BORROW = re.compile(r"通过|pass", re.I)


def verdict_ok(txt):
    """最后一条标签式裁决行必须以三词之一收尾,且该行须位于全文后2/3(竣工检验V2:
    引言里唯一的标签行恰以三词收尾曾顶替真裁决);自创词不放行,否定式不放行,
    借尾巴不放行。容忍裁决行后置附录(历史4/5真裁决带附录,V1严格末段会误拦)。"""
    all_lines = txt.splitlines()
    # 附录后的标签行不算裁决(门四#2: 真否定裁决+附录编号行"1. 结论:采纳"曾顶替成假阳性);
    # 规则本就要求裁决置于附录之前,附录里的历史/引用裁决行一律排除。
    appendix_at = next((i for i, ln in enumerate(all_lines)
                        if re.match(r"^\s{0,3}#{1,6}\s*附\s*录|^\s{0,3}附\s*录", ln)), len(all_lines))
    hits = [(i, ln) for i, ln in enumerate(all_lines)
            if VERDICT_LABEL.match(ln) and i < appendix_at]
    if not hits:
        return False
    i, last = hits[-1]
    # 竣工检验V2: 引言区标签行曾顶替真裁决。仅对足够长的文档执行位置规则
    # (短评审<6行无"引言+正文"结构可言;8份历史稿命中行全部在后2/3,零伤害)。
    if len(all_lines) >= 6 and i < len(all_lines) // 3:
        return False
    m = VERDICT_TAIL.search(last)
    if not m:
        return False
    prefix = last[:m.start()]
    if VERDICT_NEG_NEAR.search(prefix[-4:]):
        return False
    if VERDICT_BORROW.search(prefix[-12:]):
        return False
    return True


def verdict_diagnose(txt):
    """三段式诊断(P1,2026-10-01智囊团;VeriHarness: 位置+实际值+改法把修复成功率28%→72%):
    告诉失败者"实际是什么"而非只重复规则——与verdict_ok子规则一一对应,供门禁detail。
    全程用原始行匹配(门四#4: 曾先strip再匹配,行尾≥9空格时ok=False而诊断报"好行",自相矛盾)。"""
    lines = txt.splitlines()
    appendix_at = next((i for i, ln in enumerate(lines)
                        if re.match(r"^\s{0,3}#{1,6}\s*附\s*录|^\s{0,3}附\s*录", ln)), len(lines))
    hits = [(i, ln) for i, ln in enumerate(lines)
            if VERDICT_LABEL.match(ln) and i < appendix_at]
    if not hits:
        if any(VERDICT_LABEL.match(ln) for ln in lines):
            return "实际状态: 标签行只出现在附录区(附录里的裁决不算数),正文没有 裁决:/判定:/结论: 行"
        return "实际状态: 全文没有 裁决:/判定:/结论: 开头的标签行(扫描了全文所有行)"
    i, raw = hits[-1]
    disp = raw.strip()
    where = f"最后一条标签行在第{i + 1}行(全文{len(lines)}行)"
    if len(lines) >= 6 and i < len(lines) // 3:
        return f"实际状态: {where},落在全文前1/3(引言区标签行顶替真裁决的位置规则): {disp[:40]}"
    m = VERDICT_TAIL.search(raw)
    if not m:
        return f"实际状态: {where},行尾不是三词之一(含行尾多余空白也会拦): {disp[:60]}"
    prefix = raw[:m.start()]
    if VERDICT_NEG_NEAR.search(prefix[-4:]):
        return f"实际状态: {where},收尾词前4字含否定字'{prefix[-4:]}'(否定式裁决不放行): {disp[:60]}"
    if VERDICT_BORROW.search(prefix[-12:]):
        return f"实际状态: {where},收尾词前12字含'通过/pass'借词'{prefix[-12:]}'(借尾巴不放行): {disp[:60]}"
    return f"实际状态: {where}: {disp[:60]}"


# ---- 引用双模式(课题自适应: 文献型课题的PMID/ISO源不再被URL规则误杀) ----
# 竣工检验V7/V8加固: ISO须带部号(ISO 2859-1:1999)——无部号的"ISO 9001认证"营销提法不计数;
_CITE_ID_PATTERNS = [
    re.compile(r"10\.\d{4,9}/\S+"),
    re.compile(r"PMID[:：]?\s?\d{5,9}", re.I),
    re.compile(r"arXiv:\d{4}\.\d{4,5}(v\d+)?", re.I),
    re.compile(r"ISO\s?\d{3,5}(?:[:\-]\d+)+"),
    re.compile(r"NIST SP \d{3,4}(-\d+)?", re.I),
]


def citation_mode(brief_text):
    """任务书声明制(人授权,模型不能自授): 出现文献规范行→lit,否则strict。
    否定句不放行(门四#5: "不允许标准文献标识符"曾照样切lit,弱化引用门禁)。"""
    return "lit" if re.search(r"(?<![不未非])允许标准文献标识符", brief_text) else "strict"


def cite_counts(txt):
    """URL按归一化去重(url_set同源: 同一URL的粘尾/大小写/末斜杠变体曾计3源骗过门禁——
    乙席#2/门三#2实锤);标识符在剥除URL后的文本上计数
    (竣工检验V8: https://doi.org/... 曾被URL与DOI正则双重计数)。"""
    urls = url_set(txt)
    txt_no_url = URL_ASCII.sub("", txt)
    n_id = sum(len(pat.findall(txt_no_url)) for pat in _CITE_ID_PATTERNS)
    return len(urls), n_id


def citations_ok(txt, mode):
    n_url, n_id = cite_counts(txt)
    if mode == "lit":
        return n_url >= 1 and (n_url + n_id) >= 3
    return n_url >= 3


# ---- 同质化防御(P3,2026-10-01智囊团;趋势席依据Anthropic蜂群实验:45 agent里18/30用
# 同一分支名=从众病,并行调研员引同一批源、给同质结论是未设防的失效面) ----
_URL_TAIL_PUNCT = ".,;:、。)】」』\"'，；！？：·"
# URL只收ASCII可见字符(门三#2附注/门四#11: \S+会吞URL后无空格CJK,粘尾归一化做不干净)
URL_ASCII = re.compile(r"https?://[A-Za-z0-9:/\-._~?#\[\]@!$&+;,%=~]+")


def url_set(txt):
    """URL集合归一: 去尾部标点+小写+去末斜杠,让 [x](url) 与 url。 归并为同一源。"""
    return {u.rstrip(_URL_TAIL_PUNCT).lower().rstrip("/")
            for u in URL_ASCII.findall(txt)}


def homog_report(root, n):
    """调研员来源集两两Jaccard,降序。只度量不拦截——官方监管页被多调研员同引是
    正常现象,真质量权威是评审+穷举门禁;这里给的是架构师须知的偏见放大风险信号。"""
    sets = []
    for k in range(1, n + 1):
        p = root / "agents" / f"researcher-{k}" / f"outputs/research-{k}.md"
        if p.exists():
            sets.append((k, url_set(p.read_text(encoding="utf-8", errors="replace"))))
    pairs = []
    for a in range(len(sets)):
        for b in range(a + 1, len(sets)):
            (ka, sa), (kb, sb) = sets[a], sets[b]
            union = sa | sb
            j = round(len(sa & sb) / len(union), 3) if union else 0.0
            pairs.append({"pair": [ka, kb], "jaccard": j, "shared": len(sa & sb)})
    pairs.sort(key=lambda x: (-x["jaccard"], x["pair"]))
    return pairs


def attempts_ledger(root, n):
    """pass^k台账(P4,2026-10-01智囊团;业界已证单次75%→3次全过仅42%,"最终全绿"
    可能掩盖"重试才绿"): 每棒实际起跑次数=home-*目录计数(与next_instance同源)。
    attempts==1即首试通过;>1即经重试/修复环才绿。"""
    phases = (["planner", "architect", "reviewer-1", "reviewer-2", "finalizer"]
              + [f"researcher-{k}" for k in range(1, n + 1)])
    ledger = {}
    for ph in phases:
        names = {p.name for p in root.glob(f"home-{ph}*")}
        exact = {x for x in names if x == f"home-{ph}" or re.fullmatch(rf"home-{ph}-r\d+", x)}
        ledger[ph] = len(exact)
    return ledger


# 同质化告警阈值(单一常量,门禁打印与告警共用——审计批三#1: 曾两处0.7脱钩)
HOMOG_THRESHOLD = 0.7


def homog_warning(root, n, threshold=HOMOG_THRESHOLD):
    """超阈值→写给架构师任务书的告警段;未超→空串(不注入)。"""
    hot = [p for p in homog_report(root, n) if p["jaccard"] > threshold]
    if not hot:
        return ""
    desc = "; ".join(f"research-{p['pair'][0]}×research-{p['pair'][1]} "
                     f"J={p['jaccard']}(共享{p['shared']}个URL)" for p in hot)
    return ("同质化告警(来源重叠检测): " + desc + "。\n"
            "多份调研的来源集高度重叠,汇总时须警惕同质结论与单一信源的偏见放大:\n"
            "1. 各调研员对同一来源的结论若雷同,须用独立来源交叉验证后再写入汇总;\n"
            "2. 互相矛盾的发现优先保留并标注分歧,不得为表面一致性抹平;\n"
            "3. 汇总文档中说明哪些关键结论仅依赖单一来源。")


def read_brief(root):
    return (root / "project" / "REQUIREMENTS.md").read_text(encoding="utf-8")


RESEARCHER_TASK = (
    "You are researcher-{k}, ONE member of a parallel research squad. Your scope is ONLY: {scope} "
    "Other squad members cover the other scopes; do NOT stray into theirs. "
    "Use web_search and web_fetch (bounded: at most 10 searches, 6 fetches) for 2025-2026 primary "
    "sources (official regulator/vendor pages outrank blogs; the brief's domain decides which). "
    "Read REQUIREMENTS.md and reference/ background materials (see the 背景资料清单 section of REQUIREMENTS.md) for our real context first. "
    "Write outputs/research-{k}.md IN CHINESE: findings each with source (official URL or article "
    "number), what it means for OUR operation as described in the brief, and a short 'if we do nothing' "
    "risk note. 1500-3000 chars. Cite every claim: by default with at least 3 full URLs "
    "(complete addresses starting with https://, never bare domains or partial paths); "
    "cite the SPECIFIC page that contains the fact (the statute section, the case, the pricing "
    "page), never a portal/search/index/homepage page (P2抽查实测: 门户页引用=核查必盲); "
    "put the source URL ON THE SAME LINE as the fact it supports (第八场实测: 主张列条+"
    "来源集中列节尾的写法,让抽查工具配不上对——同行引用才可核); "
    "IF the brief's 引用规范 line allows standard literature identifiers, then 1 full URL "
    "plus well-formed identifiers (DOI/PMID/arXiv/ISO) totaling 3 is acceptable. "
    "Mark uncertain items as 待核实 explicitly. "
    "Finish by writing the file; it is your only deliverable."
)

TASKS = {
    "planner": (
        "You are the planning lead of an adaptive research squad. Read REQUIREMENTS.md and "
        "reference/ background materials. Decide how many parallel researchers this task needs (1 to 4) by "
        "assessing: (a) breadth = how many genuinely disjoint subtopic blocks exist, (b) depth = "
        "whether each block needs independent multi-source digging. More researchers = narrower, "
        "faster, deeper per block, but the architect must read them all — do not exceed the natural "
        "block count. Write outputs/plan.json with EXACTLY this schema: "
        '{{"N": <int 1-4>, "subtopics": [{{"id": 1, "scope": "<互斥子课题中文描述,含关键问题>"}}], '
        '"difficulty_reasoning": "<为什么是这个N,一段话>"}} '
        "and ALSO outputs/plan.md (human-readable Chinese summary of the split). JSON must parse; "
        "len(subtopics) must equal N. Then write both files and stop."
    ),
    "architect": (
        "You are the solution architect. Read REQUIREMENTS.md, reference/ background materials, and EVERY "
        "inputs/research-*.md staged for you (they come from parallel researchers with disjoint "
        "scopes). Synthesize them into ONE coherent plan that answers the brief's numbered "
        "questions under 本次研究要回答; where two researchers conflict, resolve it and say so. "
        "Write outputs/architecture.md IN CHINESE structured around THIS brief's topic "
        "(\"{title}\") and its stated deliverable requirements: {deliverables} "
        "Do NOT reuse chapter skeletons from any other topic. 3000-6000 chars. Every material "
        "claim cites its source (inherited from research). When you aggregate or compute "
        "figures across researcher inputs (totals, ratios, conversions), verify the "
        "arithmetic with pwsh — do not do mental math on numbers that reach the owner."
    ),
    "reviewer-1": (
        "You are independent reviewer A. Read REQUIREMENTS.md, inputs/research-*.md and "
        "inputs/architecture.md. You CANNOT see the other reviewer and must not try. Re-derive "
        "the key facts YOURSELF from the cited sources before judging. MECHANICAL CHECK FIRST "
        "(shell works on this runtime): use grep/pwsh to count the https:// URLs in each "
        "research input, and confirm the architecture's claims that cite them actually "
        "reference sources present in the inputs — machine counts beat eyeballing. "
        "Write outputs/review-1.md IN CHINESE: (1) factual errors with evidence, (2) missing "
        "questions or angles the brief asked for, (3) over-engineering a small factory "
        "does not need, (4) the three highest-value fixes, (5) the verdict as its OWN last line before any appendix, "
        "in EXACTLY this format: 裁决:采纳 / 裁决:修改后采纳 / 裁决:重做 — the 裁决: label prefix is REQUIRED "
        "(a bare verdict word without the label fails the gate; sample compliant line: 裁决:修改后采纳). "
        "Judge against our real constraints, not generic best practice."
    ),
    "reviewer-2": (
        "You are independent reviewer B. Read REQUIREMENTS.md, inputs/research-*.md and "
        "inputs/architecture.md. You CANNOT see the other reviewer and must not try. Attack "
        "DIFFERENTLY from a generic checklist pass: hunt for hallucinated claims (verify "
        "each cited source actually says what is claimed via web_fetch, bounded 8 "
        "fetches), over-broad interpretation, and silent gaps on the brief's own topic "
        "(\"{title}\"). NUMBER-PROVENANCE CHECK (shell works on this runtime): extract the "
        "5 largest figures in architecture.md and grep each in inputs/research-*.md — a "
        "number the researchers never reported is an architect hallucination until proven "
        "otherwise. Write outputs/review-2.md IN CHINESE with this 5-part structure: "
        "(1) factual errors with evidence, (2) missing questions or angles the brief "
        "asked for, (3) over-engineering a small factory does not need, (4) the three "
        "highest-value fixes, (5) the verdict as its OWN last line before any appendix, in EXACTLY this format: "
        "裁决:采纳 / 裁决:修改后采纳 / 裁决:重做 — the 裁决: label prefix is REQUIRED (a bare verdict word "
        "without the label fails the gate; sample compliant line: 裁决:修改后采纳). Do not invent other verdict "
        "words (English status words do not count)."
    ),
    "finalizer": (
        "You are the finalizing architect. Read REQUIREMENTS.md, inputs/research-*.md, "
        "inputs/architecture.md, inputs/review-1.md AND inputs/review-2.md (two independent "
        "reviews). Address EVERY review point: incorporate it, or reject it with a stated "
        "reason. Write outputs/final-plan.md IN CHINESE, owner-executable, for THIS brief's "
        "topic (\"{title}\"): 决策摘要(10行内) / 按任务书交付要求逐项产出({deliverables}) / "
        "行动检查表(可打勾) / 两轮评审处理说明(采纳与驳回逐条). "
        "Do NOT reuse chapter skeletons from any other topic. "
        "This document will be used by the factory owner directly."
    ),
}
ARTIFACT = {
    "planner": ("planner", "outputs/plan.json"),
    "architect": ("architect", "outputs/architecture.md"),
    "reviewer-1": ("reviewer-1", "outputs/review-1.md"),
    "reviewer-2": ("reviewer-2", "outputs/review-2.md"),
    "finalizer": ("finalizer", "outputs/final-plan.md"),
}


def phase_actor(phase):
    """phase → agent id: researcher-* 原名;ARTIFACT里的复合名(reviewer-1)查表;其余取首段。"""
    if phase.startswith("researcher"):
        return phase
    if phase in ARTIFACT:
        return ARTIFACT[phase][0]
    return phase.split("-")[0]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def git(repo, *args):
    return subprocess.check_output(
        ["git", "-C", str(repo), "-c", "user.name=Research Controller",
         "-c", "user.email=research@example.invalid", *args], text=True).strip()


def cli(root, *args, cwd=None):
    env = {k: v for k, v in os.environ.items()
           if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    result = subprocess.run(
        [sys.executable, "-m", "loopx.cli", "--registry", str(root / "registry.json"),
         "--runtime-root", str(root / "runtime"), "--format", "json", *args],
        capture_output=True, text=True, check=False, cwd=cwd, env=env,
        timeout=1500)  # 内核--timeout-seconds 1200是传参不是子进程超时(乙席#16);1500=1200+余量
    if result.returncode:
        # 并发失败互覆只剩最后一份(乙席#11):至少让每份日志自述是哪条命令
        (root / "last-cli-failure.log").write_text(
            f"args: {args}\n{result.stdout}\n{result.stderr}", encoding="utf-8")
        raise SystemExit("CLI failed; inspect last-cli-failure.log")
    return json.loads(result.stdout)


DEFAULT_REFERENCE = ("final-v5.md",
                     Path(r"C:/Users/Administrator/ZCodeProject/电商客服研究-AI团队产出/4-终案v5.0-老板版.md"))


def reference_section(refs):
    """REQUIREMENTS.md 追加的背景资料清单(纯函数,可测)。
    refs: [(dest名, 是否缺失)] —— 防污染: 声明数字须当期重核(借鉴issue_fix记忆的
    advisory原则: 前场结论只作线索,影响决策须当期验证)。"""
    lines = ["", "## 背景资料清单(reference/)", ""]
    for name, missing in refs:
        lines.append(f"- {name}" + ("(缺失)" if missing else "(来自前场调研)"))
    lines += ["", "> **防污染声明**: 以上为背景与线索。其中所有数字(价格/额度/费率/法规版本)"
              "本场必须重新检索并给当期来源,直接沿用=评审否决项。", ""]
    return "\n".join(lines)


def prepare(root, brief_text=None, references=None):
    brief = brief_text or BRIEF
    root.mkdir(parents=True, exist_ok=False)
    (root / ".gitignore").write_text("*\n")
    project = root / "project"
    (project / "inputs").mkdir(parents=True)
    (project / "reference").mkdir(parents=True)
    (project / ".gitignore").write_text(".local/\nACTIVE_GOAL_STATE.md\n__pycache__/\n")
    # v5终案恒在(所有任务书的基线方案); --reference 追加。
    # 竣工检验加固: dest强制basename(拒路径穿越/绝对路径)、按dest去重(后到覆盖有记录)、
    # 显式传final-v5.md=覆盖默认源、复制失败清干净半成品根再报错(否则重跑卡死)。
    refs = {DEFAULT_REFERENCE[0]: DEFAULT_REFERENCE[1]}
    for raw_dest, src in (references or []):
        dest = Path(raw_dest).name
        if dest != raw_dest:
            print(f">>> --reference 目标名含路径段,已收敛为: {dest}")
        refs[dest] = src
    staged = []
    try:
        for dest, src in refs.items():
            if Path(src).exists():
                shutil.copy(src, project / "reference" / dest)
                staged.append((dest, False))
            else:
                (project / "reference" / dest).write_text("(资料缺失)\n", encoding="utf-8")
                staged.append((dest, True))
    except (OSError, shutil.SameFileError) as exc:
        shutil.rmtree(root, ignore_errors=True)
        raise SystemExit(f"--reference 复制失败({exc});半成品根已清理,修正参数后重跑: {root}")
    (project / "REQUIREMENTS.md").write_text(brief + reference_section(staged), encoding="utf-8")
    (project / "ACTIVE_GOAL_STATE.md").write_text(
        "---\nstatus: active\n---\n# " + (brief_title(brief) or "研究任务") + "\n\n## User Todo\n\n"
        "## Agent Todo\n\n## Next Action\n\n- Run the assigned bounded research phase.\n",
        encoding="utf-8")
    git(project, "init", "-b", "main")
    git(project, "add", ".")
    git(project, "commit", "-s", "-m", "Initialize adaptive research brief and references")
    # Identity only: never contacted. 结算判据要求worktree带credential-free origin
    # (v1漏此行导致peer delivery守卫永远红——demo.py同位置有这行)
    git(project, "remote", "add", "origin", "https://example.invalid/research/adaptive-r2.git")
    registry = {
        "schema_version": 1,
        "common_runtime_root": str(root / "runtime"),
        "goals": [{
            "id": GOAL, "domain": "adaptive-research", "status": "active",
            "repo": str(project), "state_file": "ACTIVE_GOAL_STATE.md",
            "adapter": {"kind": "fixture_v0", "status": "connected-delivery"},
            "quota": {"compute": 1.0, "window_hours": 24},
            "coordination": {"agent_model": "peer_v1", "registered_agents": list(ACTORS),
                             "write_scope": ["**"]},
        }],
    }
    write(root / "registry.json", registry)
    for actor in ACTORS:
        workspace = root / "agents" / actor
        workspace.parent.mkdir(exist_ok=True)
        git(project, "worktree", "add", "-b", actor.replace("-", ""), str(workspace))
        (workspace / "outputs").mkdir()
        (workspace / "tasks").mkdir()
        args = ["-m", "loopx.collaboration_mcp", "--registry", str(root / "registry.json"),
                "--runtime-root", str(root / "runtime"), "--goal-id", GOAL,
                "--agent-id", actor, "--workspace", str(workspace)]
        write(root / f"{actor}-cordis.yml", [{
            "insert": [{
                "id": "loopx-collaboration", "name": "@deepseek-ai/dsh-mcp-client",
                "config": {"transport": "stdio", "serverName": "loopx_collaboration",
                           "command": sys.executable, "args": args, "cwd": str(workspace),
                           "failOnStartupError": True},
            }]
        }])
    store = ChatSessionStore(root / "runtime")
    session = store.create_session(goal_id="loopx-manager", agent_id="codex",
                                   adapter_kind="codex_app_server", upstream_thread_id="r2-owner",
                                   channel_id="manager")
    turn, _ = store.create_turn(session["session_id"], client_turn_id="initial",
                                message="产出研究终案: " + (brief_title(brief) or "(见REQUIREMENTS.md)"),
                                origin="web")
    brief = {
        "schema_version": "collaboration_brief_v0",
        "purpose": "Adaptive-squad research: produce the owner-executable deliverable for: "
                   + (brief_title(brief) or "see REQUIREMENTS.md"),
        "context": brief[:1500],
        "constraints": ["Chinese deliverables", "Every material claim cites its source",
                        "Judge against our real constraints"],
        "inputs": [{"ref": "REQUIREMENTS.md", "description": "Research brief with real constraints"}],
        "acceptance": ["plan.json + N research docs with sources", "architecture.md",
                       "two independent blind reviews", "final-plan.md owner-executable"],
        "return_requirement": "Return actual documents and remaining gaps",
    }
    receipt = deliver(root / "runtime", root / "registry.json", session=session, turn=turn,
                      request={"goal_id": GOAL, "agent_id": "planner", "brief": brief})
    store.update_turn(session["session_id"], turn["turn_id"], status="completing",
                      response={"message": "Delegation saved.", "context_handoff_receipt": receipt})
    store.finalize_managed_turn_completion(session["session_id"], turn["turn_id"])
    write(root / "demo.json", {"schema": "research_run2_v1", "session_id": session["session_id"],
                               "requests": [receipt["request_id"]]})
    print("Prepared adaptive research fixture; no model call has run.")


def stage_route(root, phase, subtopics=None):
    """串行段: 工件staging + peer请求 + todo绑定。并行turn启动前全部完成。"""
    actor = phase_actor(phase)
    ws = root / "agents" / actor
    (ws / "inputs").mkdir(exist_ok=True)
    routing = {
        "architect": [(f"researcher-{k}", f"outputs/research-{k}.md", f"inputs/research-{k}.md")
                      for k in range(1, MAXN + 1)],
        "reviewer-1": None, "reviewer-2": None, "finalizer": None,
    }
    brief = read_brief(root)
    fill = {"deliverables": deliverables_of(brief), "title": brief_title(brief)}
    if phase.startswith("researcher"):
        if subtopics is None:  # 门禁修复环/CLI单棒只传(root,ph)——从plan.json回读子课题
            subtopics = [s["scope"] for s in json.loads(
                (root / "agents/planner/outputs/plan.json").read_text(encoding="utf-8"))["subtopics"]]
        task = RESEARCHER_TASK.format(k=phase.split("-")[1], scope=subtopics[int(phase.split("-")[1]) - 1])
    else:
        task = TASKS[phase].format(**fill)
    if phase == "architect":
        plan = json.loads((root / "agents/planner/outputs/plan.json").read_text(encoding="utf-8"))
        routing["architect"] = [(f"researcher-{k}", f"outputs/research-{k}.md", f"inputs/research-{k}.md")
                                for k in range(1, plan["N"] + 1)]
        # P3同质化防御: 汇总者进场前先量来源重叠,超阈值把告警写进任务书
        warn = homog_warning(root, plan["N"])
        if warn:
            task += "\n\n" + warn
            print(f">>> 同质化告警已注入architect任务书: {warn.splitlines()[0][12:60]}", flush=True)
        plan_md = (root / "agents/planner/outputs/plan.md")
        if plan_md.exists():
            routing["architect"].append(("planner", "outputs/plan.md", "inputs/plan.md"))
    research_files = [(f"researcher-{k}", f"outputs/research-{k}.md", f"inputs/research-{k}.md")
                      for k in range(1, MAXN + 1)]
    if phase in ("reviewer-1", "reviewer-2", "finalizer"):
        plan = json.loads((root / "agents/planner/outputs/plan.json").read_text(encoding="utf-8"))
        research_files = research_files[:plan["N"]]
        base = [("planner", "outputs/plan.md", "inputs/plan.md"),
                ("architect", "outputs/architecture.md", "inputs/architecture.md")] + research_files
        if phase == "finalizer":
            base += [("reviewer-1", "outputs/review-1.md", "inputs/review-1.md"),
                     ("reviewer-2", "outputs/review-2.md", "inputs/review-2.md")]
        routing[phase] = base
    for src_actor, src_ref, dst_ref in (routing.get(phase) or []):
        if dst_ref is None:
            continue
        src = root / "agents" / src_actor / src_ref
        if src.exists():
            shutil.copy(src, ws / dst_ref)
    # peer请求(协作协议痕迹); 链条起点planner无上游,不发
    from loopx.control_plane.collaboration import peers as _peers
    if phase.startswith("researcher"):
        source = "planner"
    elif actor in ("reviewer-1", "reviewer-2", "finalizer", "architect"):
        source = "planner" if actor == "architect" else "architect"
    else:
        source = None
    if source:
        _peers.request(
            root / "runtime", root / "registry.json", GOAL,
            source_agent_id=source, target_agent_id=actor,
            operation_id=f"{phase}-handoff",
            brief={
                "schema_version": "collaboration_brief_v0",
                "purpose": f"Phase handoff: perform {phase}. See tasks/{phase}.md and staged inputs/.",
                "context": "Controller-routed adaptive research DAG; artifacts staged under inputs/.",
                "constraints": ["Chinese deliverables", "Cite sources"],
                "inputs": [{"ref": "REQUIREMENTS.md", "description": "Research brief"}],
                "acceptance": ["The phase output file named in tasks/"],
                "return_requirement": "Return actual documents and remaining gaps",
            })
    # OPERATING.md + 任务书 + todo
    meta = json.loads((root / "demo.json").read_text(encoding="utf-8"))
    deliverable = (f"outputs/research-{phase.split('-')[1]}.md" if phase.startswith("researcher")
                   else ARTIFACT[phase][1])
    (ws / "OPERATING.md").write_text(
        f"Your identity is {actor}. Scoped loopx_collaboration MCP tools are available. "
        "DELIVERABLE (validator checks this exact path; missing/empty = phase fails): "
        f"{deliverable}. Write it FIRST-complete, then stop. "
        "Runtime note: shell (pwsh) WORKS on the current runtime (0.1.5's '--profile' bug is fixed); "
        "prefer read/write/edit/glob for file edits, use pwsh for commands and Get-FileHash digests. "
        f"Owner request ids: {', '.join(meta['requests'])}.\n", encoding="utf-8")
    if actor.startswith("reviewer"):
        # 裁决契约双通道教学(r9复活轮反例: 任务书教了仍首试白词——同份合同在
        # 工人第一眼读的OPERATING.md里再教一遍)
        (ws / "OPERATING.md").write_text(
            (ws / "OPERATING.md").read_text(encoding="utf-8")
            + "\nVERDICT FORMAT (gate-checked): your review's LAST standalone line before any "
            "appendix MUST be exactly `裁决:采纳` / `裁决:修改后采纳` / `裁决:重做` — the 裁决: "
            "label prefix is REQUIRED; a bare verdict word without the label FAILS the gate.\n",
            encoding="utf-8")
    fb = ws / "outputs" / "repair-feedback.md"
    art = ws / deliverable
    # 陈旧反馈不附(乙席#17): 反馈早于工件=已修好,再附"先读反馈"误导无关重跑的方向
    if fb.exists() and (not art.exists() or fb.stat().st_mtime >= art.stat().st_mtime):
        task += ("\n\nREPAIR ATTEMPT: FIRST read outputs/repair-feedback.md and follow its "
                 "针对性修复要求 exactly (previous attempt failed validation; do not repeat it).")
    (ws / "tasks" / f"{phase}.md").write_text(task + "\n", encoding="utf-8")
    text = f"Read OPERATING.md and tasks/{phase}.md and perform that bounded research phase."
    todos = cli(root, "todo", "list", "--goal-id", GOAL)["todos"]
    owned = next((t for t in todos if t.get("claimed_by") == actor and t.get("status") == "open"), None)
    if owned:
        cli(root, "todo", "update", "--goal-id", GOAL, "--todo-id", owned["todo_id"],
            "--agent-id", actor, "--text", text)
    else:
        cli(root, "todo", "add", "--goal-id", GOAL, "--role", "agent", "--claimed-by", actor,
            "--text", text, "--action-kind", "implement")


def next_instance(root, phase):
    """跨运行全局新鲜的instance id: 同名旧turn会触发resume语义而非新回合。"""
    n = len(list(root.glob(f"home-{phase}*")))
    return phase if n == 0 else f"{phase}-r{n}"


def execute_turn(root, phase):
    """并行段: 只跑 turn run-once(异agent=异lane,内核允许并行)。instance全局新鲜。"""
    actor = phase_actor(phase)
    instance = next_instance(root, phase)
    workspace = root / "agents" / actor
    validator = [sys.executable, str(HERE / "research_run2.py"), "validate",
                 "--root", str(root), "--phase", phase]
    turn_args = (
        "turn", "run-once",
        "--goal-id", GOAL, "--agent-id", actor, "--turn-instance-id", instance,
        "--host", "dsh", "--execution-mode", "isolated-headless",
        "--project", str(workspace),
        "--dsh-home", str(root / f"home-{instance}"),
        "--dsh-cordis", str(root / f"{actor}-cordis.yml"),
        "--dsh-model", DSH_MODEL, "--dsh-reasoning-effort", DSH_EFFORT,
        "--dsh-max-tokens", DSH_MAX_TOKENS,
        "--validation-command-json", json.dumps(validator),
        "--validation-failure-kind", "repair_required",
        "--scan-root", str(workspace), "--no-global-sync",
        "--timeout-seconds", "1200", "--execute",
    )
    result = cli(root, *turn_args, cwd=str(workspace))
    write(root / f"{instance}.json", result)
    return result


def validate(root, phase):
    if phase.startswith("researcher"):
        actor, ref = phase, f"outputs/research-{phase.split('-')[1]}.md"
    else:
        actor, ref = ARTIFACT[phase]
    p = root / "agents" / actor / ref
    assert p.stat().st_size > 200, f"{ref} 太小或缺失"
    if phase.startswith("researcher"):
        txt = p.read_text(encoding="utf-8", errors="replace")
        n_url, n_id = cite_counts(txt)
        if citation_mode(read_brief(root)) == "lit":
            assert n_url >= 1 and (n_url + n_id) >= 3,                 f"{ref} 引用源不足(lit模式: URL={n_url},URL+标识符={n_url + n_id})"
        else:
            assert n_url >= 3, f"{ref} 引用源不足({n_url}<3)"
    print(f"validated: {ref} ({p.stat().st_size} bytes)")


def read_plan(root):
    plan = json.loads((root / "agents/planner/outputs/plan.json").read_text(encoding="utf-8"))
    assert isinstance(plan.get("N"), int) and 1 <= plan["N"] <= MAXN, "plan.json N 非法"
    assert len(plan.get("subtopics", [])) == plan["N"], "subtopics 数与 N 不符"
    return plan


def gate(root, include_final=True):
    """穷举门禁: 全工件齐+引用足+双盲评在场+(可选)终稿结构词。中检不含终稿。"""
    plan = read_plan(root)
    cite_mode = citation_mode(read_brief(root))
    checks = []
    ok = True
    def chk(name, cond, detail=""):
        nonlocal ok
        checks.append({"check": name, "pass": bool(cond), "detail": detail})
        ok = ok and bool(cond)
    for k in range(1, plan["N"] + 1):
        p = root / "agents" / f"researcher-{k}" / f"outputs/research-{k}.md"
        if p.exists():
            txt = p.read_text(encoding="utf-8", errors="replace")
            chk(f"research-{k} 非空", p.stat().st_size > 200, f"{p.stat().st_size}B")
            n_url, n_id = cite_counts(txt)
            if cite_mode == "lit":
                need = f"实际URL={n_url},标识符={n_id};要求URL≥1且合计≥3,还差{max(0, 3 - n_url - n_id)}条"
            else:
                need = f"实际完整URL={n_url};要求≥3,还差{max(0, 3 - n_url)}条"
            chk(f"research-{k} 引用>=3", citations_ok(txt, cite_mode), need)
        else:
            chk(f"research-{k} 存在", False, "缺失")
    checks_pool = [
        ("agents/architect/outputs/architecture.md", 1500, None),
        ("agents/reviewer-1/outputs/review-1.md", 400, "verdict"),
        ("agents/reviewer-2/outputs/review-2.md", 400, "verdict"),
    ] + ([("agents/finalizer/outputs/final-plan.md", 2000, ("清单", "检查表"))]
         if include_final else [])
    for ref, min_size, kw in checks_pool:
        p = root / ref
        if p.exists():
            txt = p.read_text(encoding="utf-8", errors="replace")
            chk(f"{ref.split('/')[-1]} 非空", p.stat().st_size > min_size, f"{p.stat().st_size}B")
            if kw == "verdict":
                chk(f"{ref.split('/')[-1]} 裁决收尾", verdict_ok(txt),
                    verdict_diagnose(txt))
            elif kw:
                hit_words = [w for w in kw if w in txt]
                chk(f"{ref.split('/')[-1]} 结构词", bool(hit_words),
                    f"实际命中{hit_words or '无'};要求含任一: {list(kw)}")
        else:
            chk(f"{ref.split('/')[-1]} 存在", False, "缺失")
    # 主题匹配(第8缺陷防线): 只当"灾难性错题绊线"用——拦整体课题替换(旧骨架任务书
    # 场景,特征=命中趋近零),不对好文档做精细打分。阈值故意压低(约1/3+下限2):
    # 启发式检查的假阳性代价是模型级返工,而边界伪影(跨词二元组如"规清")会天然
    # 拉低好文档命中,真质量权威始终是评审+穷举门禁,不是这条代理指标。
    terms = topic_terms(read_brief(root))
    topic_refs = ["agents/architect/outputs/architecture.md"]
    if include_final:
        topic_refs.append("agents/finalizer/outputs/final-plan.md")
    if terms:
        need = max(2, len(terms) // 3) if len(terms) >= 2 else len(terms)
        for ref in topic_refs:
            p = root / ref
            if p.exists():
                txt = p.read_text(encoding="utf-8", errors="replace")
                missing = [t for t in terms if t not in txt]
                hit = len(terms) - len(missing)
                chk(f"{ref.split('/')[-1]} 主题匹配({hit}/{len(terms)},绊线{need})",
                    hit >= need, f"缺: {missing}")
            else:
                chk(f"{ref.split('/')[-1]} 主题匹配", False, "文件缺失")
    # 双盲评互不可见: reviewer工作区不得包含对方review(结构保证+显式复查)
    for a, b in (("reviewer-1", "reviewer-2"), ("reviewer-2", "reviewer-1")):
        leaked = list((root / "agents" / a / "inputs").glob(f"review-{b[-1]}.md"))
        chk(f"盲评隔离({a}不见{b})", not leaked)
    led = attempts_ledger(root, plan["N"])
    first = sorted(p for p, a in led.items() if a == 1)
    report = {"ok": ok, "N": plan["N"], "checks": checks,
              "homogenization": homog_report(root, plan["N"]),
              "attempts": led, "first_pass": first,
              "digests": {str(pp.relative_to(root)): hashlib.sha256(pp.read_bytes()).hexdigest()
                          for pp in set(root.glob("agents/*/outputs/*.md"))
                          | set(root.glob("agents/planner/outputs/plan.json"))}}
    write(root / "gate-report.json", report)
    live = {p: a for p, a in led.items() if a > 0}  # 0次棒不进首试率分母(门六#4)
    print(f"pass^k: 首试通过 {len(first)}/{len(live)} 棒"
          + ("" if len(first) == len(live) else f"(重试棒: { {p: a for p, a in live.items() if a > 1} })"),
          flush=True)
    top = next((p for p in report["homogenization"]
                if p["jaccard"] > HOMOG_THRESHOLD), None)  # 与homog_warning同参(审计批三#1:曾两处硬编码脱钩)
    if top:
        print(f"!! 同质化信号(非拦截): research-{top['pair'][0]}×research-{top['pair'][1]} "
              f"J={top['jaccard']}(共享{top['shared']}个URL) > {HOMOG_THRESHOLD}", flush=True)
    print(json.dumps({"ok": ok, "failed": [c["check"] for c in checks if not c["pass"]]},
                     ensure_ascii=False))
    return ok


def run_phase(root, phase, subtopics=None, attempt=1):
    # 注: instance新鲜度由next_instance按home-*计数保证,execute_turn不收attempt
    # (run_phase曾是死代码,门禁修复环成为首个调用者时暴露签名漂移——第10坑)
    stage_route(root, phase, subtopics)
    return execute_turn(root, phase)


def _artifact_ok(root, phase):
    try:
        validate(root, phase)
        return True
    except Exception:
        return False


def ensure_phase(root, phase, subtopics=None, max_tries=3):
    """幂等+修复重试: 工件已过验直接跳过; 否则同根重试(新instance id),带修复反馈。"""
    if _artifact_ok(root, phase):
        print(f">>> 跳过(已过验): {phase}", flush=True)
        return {"status": "committed", "skipped": True}
    actor = phase_actor(phase)
    last = None
    for t in range(1, max_tries + 1):
        if t > 1:
            verr = ""
            try:
                validate(root, phase)
            except (Exception, SystemExit) as ve:
                verr = str(ve)
            fb = root / "agents" / actor / "outputs" / "repair-feedback.md"
            fb.parent.mkdir(parents=True, exist_ok=True)
            fb.write_text(
                f"# Repair feedback for {phase}\n\n"
                f"上一次尝试失败: {last or 'validation'}。\n"
                f"验证器原话: {verr or '(turn未commit,工件层请自查)'}\n\n"
                "针对性修复要求:\n"
                "- 交付物必须非空且完整覆盖任务书的子课题范围。\n"
                "- 引用源: 至少3个**完整URL(以https://开头)**,不要只写域名或续路径"
                "(如'...eu/article/50'要写成完整'https://...'地址);官方源优先。\n"
                "- 写完文件后重读一遍确认上述两点,再结束回合。\n",
                encoding="utf-8")
        stage_route(root, phase, subtopics)
        try:
            r = execute_turn(root, phase)
            if r.get("status") == "committed" and _artifact_ok(root, phase):
                return r
            last = f"turn status={r.get('status')}"
        except (Exception, SystemExit) as exc:  # cli()抛SystemExit,必须显式接住
            last = f"{type(exc).__name__}: {str(exc)[:200]}"
        if _artifact_ok(root, phase):
            # 工件优先: turn结算可能挂,但交付物已过验证器——门禁才是权威,不重跑模型
            print(f">>> {phase} 工件已过验(turn结算异常,采信工件)", flush=True)
            return {"status": "committed", "artifact_first": True}
        print(f">>> {phase} 第{t}次未过({last[:100]}), 重试", flush=True)
    raise SystemExit(f"{phase} {max_tries}次未过: {last}")


def _failing_phases(report):
    """门禁失败项 → 负责phase(按检查名里的工件名反查)。结构性失败(盲评隔离等)无负责phase→[]。"""
    name_to_phase = {ref.split("/")[-1]: ph for ph, (_, ref) in ARTIFACT.items()}
    for k in range(1, MAXN + 1):
        name_to_phase[f"research-{k}"] = f"researcher-{k}"
    out = []
    for c in report["checks"]:
        if c["pass"]:
            continue
        name = re.split(r" (非空|结构词|裁决收尾|存在|引用|主题匹配)", c["check"])[0].strip()
        ph = name_to_phase.get(name) or name_to_phase.get(name + ".md")
        if ph and ph not in out:
            out.append(ph)
    return out


def gate_with_repair(root, include_final, max_rounds=2):
    """门禁失败不再死刑(第9坑): 定位负责phase→写修复反馈→强制重跑→重验;有限轮后仍败才真败。"""
    for rnd in range(max_rounds + 1):
        if gate(root, include_final=include_final):
            return True
        if rnd == max_rounds:
            return False
        rep = json.loads((root / "gate-report.json").read_text(encoding="utf-8"))
        bad = _failing_phases(rep)
        if not bad:
            return False
        for ph in bad:
            stem = (f"research-{ph.split('-')[1]}" if ph.startswith("researcher")
                    else ARTIFACT[ph][1].split("/")[-1])
            det = "; ".join(f"{c['check']} — {str(c['detail'])[:80]}"
                            for c in rep["checks"] if not c["pass"] and stem in c["check"])
            fb = root / "agents" / phase_actor(ph) / "outputs" / "repair-feedback.md"
            fb.parent.mkdir(parents=True, exist_ok=True)
            fb.write_text(
                f"# Gate repair feedback for {ph}\n\n"
                f"终验门禁失败项(含实际状态与差距): {det}\n\n"
                "针对性修复要求:\n"
                "- 按原任务书(tasks/同名.md)重写完整交付物,逐项消除上述失败点;不要只补一句话。\n"
                "- 若失败项是'裁决收尾': 以 裁决:/判定:/结论: 单独成行(置于附录之前)、以三词之一收尾,\n"
                "  不得自创裁决词(英文状态词不算)。对照上面'实际状态'里指认的那一行改。\n"
                "- 若失败项是'引用': 从你调研时实际使用的来源中,把完整 https:// 地址以 [标题](https://…)\n"
                "  或行内 https:// 形式插入对应结论处;默认须≥3个完整URL。若任务书'引用规范'行允许\n"
                "  文献标识符,则保证≥1个完整URL且URL+良构标识符(DOI/PMID/arXiv/ISO号)合计≥3。\n"
                "- 写完后重读全文,确认门禁失败点已消除再结束回合。\n",
                encoding="utf-8")
            print(f">>> 门禁修复(round {rnd + 1}): 重跑 {ph}: {det[:100]}", flush=True)
            try:
                run_phase(root, ph)
            except (Exception, SystemExit) as exc:
                # 修复轮内CLI失败不再SystemExit直穿控制器(第五场事故:宿主杀shell后
                # cli()报错让整个auto死亡)——落账后继续下一轮,由门禁自然重验。
                print(f">>> 修复轮 {ph} 执行异常(已落账,继续): "
                      f"{type(exc).__name__}: {str(exc)[:120]}", flush=True)
    return False


def expected_endpoint(sdk_version: str) -> str:
    """端点与SDK版本的强配对(端点打架事故: 模板export旧端点+守卫只认旧端点,
    0.2.0运行时会在首个模型调用404——守卫必须按版本认端点,不放行必死的组合)。
    0.2.x走Anthropic Messages(api/anthropic); 0.1.5x走OpenAI兼容(coding/paas/v4)。"""
    if sdk_version.startswith("0.2"):
        return "https://open.bigmodel.cn/api/anthropic"
    return "https://open.bigmodel.cn/api/coding/paas/v4"


def live_pipeline_processes():
    """一场一管的机械牙(r9事故: 首例中途死亡源于宿主与管线并发拉起effect runtime)。
    扫描本机是否已有 research_run2.py auto 在跑(排除自身)。"""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Where-Object {$_.CommandLine -like '*research_run2.py*' -and $_.CommandLine -notlike '*Get-CimInstance*'} | "
             "Select-Object -ExpandProperty ProcessId"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if r.returncode != 0:
            return None  # 探针失败: fail-closed由调用方决定
        pids = {int(x) for x in (r.stdout or "").split() if x.isdigit()}
        pids.discard(os.getpid())
        pids.discard(os.getppid())
        return pids or None
    except Exception:
        return None


def auto(root):
    # 并发防撞闸(r9事故机械牙): 已有编队管线在跑→拒绝启动,提示一场一管。
    # 探针失败也拒绝(fail-closed)——宁可误拦一次,不再并发互杀一场。
    live = live_pipeline_processes()
    if live is not None:
        raise SystemExit(f"已有编队管线在运行(pid={sorted(live)[:3]}): 一场一管——"
                         "先收上一场(或确认其已死并清理),再启动新场")
    # 端点快查(丙席#14+端点打架加固): 端点必须与所装SDK版本配对——
    # 错配组合(0.2.0+旧端点)此处在发射前拦住,不烧到第一个模型调用才发现404
    from importlib.metadata import version as _pkg_version
    try:
        sdk_ver = _pkg_version("deepseek-harness-sdk")
    except Exception:
        sdk_ver = "未知"
    want = expected_endpoint(sdk_ver) if sdk_ver != "未知" else None
    base = os.environ.get("DEEPSEEK_BASE_URL", "")
    if want and base and base.rstrip("/") != want:
        raise SystemExit(f"DEEPSEEK_BASE_URL={base} 与SDK {sdk_ver} 不配对"
                         f"(该版本要求 {want});检查launch模板端点行")
    timing = {}
    t_all = time.time()

    def stamp(stage):
        timing[stage] = round(time.time() - t_all, 1)
        print(f"[{timing[stage]:>7.1f}s] {stage} 完成", flush=True)

    r1 = ensure_phase(root, "planner")
    plan = read_plan(root)
    print(f">>> 难度路由: N={plan['N']}")
    for s in plan["subtopics"]:
        print(f"    子课题{s['id']}: {s['scope'][:60]}")
    stamp(f"planner(N={plan['N']})")

    scopes = [s["scope"] for s in plan["subtopics"]]
    phases = [f"researcher-{k}" for k in range(1, plan["N"] + 1)]
    with cf.ThreadPoolExecutor(max_workers=plan["N"]) as ex:
        futs = {ex.submit(ensure_phase, root, ph, scopes): ph for ph in phases}
        results = {}
        for fu in cf.as_completed(futs):
            ph = futs[fu]
            try:
                results[ph] = fu.result().get("status")
            except (Exception, SystemExit) as exc:
                results[ph] = f"FAILED: {str(exc)[:80]}"
    print(f">>> 并行调研: {results}")
    assert all(v == "committed" for v in results.values()), "有调研员未committed"
    stamp("research(N路并行)")

    r = ensure_phase(root, "architect")
    stamp("architect")

    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        futs = {ex.submit(ensure_phase, root, ph): ph for ph in ("reviewer-1", "reviewer-2")}
        results = {}
        for fu in cf.as_completed(futs):
            ph = futs[fu]
            try:  # 与调研员池对称(乙席#6): 单评审失败落账不裸穿,另一路结果不丢
                results[ph] = fu.result().get("status")
            except (Exception, SystemExit) as exc:
                results[ph] = f"FAILED: {str(exc)[:80]}"
    print(f">>> 双盲评: {results}")
    assert all(v == "committed" for v in results.values()), "有评审未committed"
    stamp("双盲评(2路并行)")

    if not gate_with_repair(root, include_final=False):
        raise SystemExit("中间门禁 FAIL(修复轮耗尽,见 gate-report.json)")
    stamp("门禁(中间,不含终稿)")

    r = ensure_phase(root, "finalizer")
    if not gate_with_repair(root, include_final=True):
        raise SystemExit("终局门禁 FAIL(修复轮耗尽)")
    stamp("finalizer+终局门禁")

    write(root / "stage-timing.json", timing)
    print(json.dumps({"一路绿灯": True, "总耗时秒": round(time.time() - t_all, 1),
                      "N": plan["N"], "timing": timing}, ensure_ascii=False))


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, default=ROOT)
    parser = argparse.ArgumentParser(parents=[common])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_prep = sub.add_parser("prepare", parents=[common])
    p_prep.add_argument("--brief-file", type=Path, default=None)
    p_prep.add_argument("--reference", action="append", nargs=2,
                        metavar=("DEST", "SRC"), default=[],
                        help="额外背景资料: 目标名 源路径(可重复,如 snapshot-meta.md ../产出/final-plan.md); "
                             "v5终案恒为基线,同名可覆盖")
    sub.add_parser("gate", parents=[common])
    sub.add_parser("auto", parents=[common])
    p_run = sub.add_parser("run", parents=[common])
    p_run.add_argument("--phase", required=True)
    p_run.add_argument("--model", default=DSH_MODEL)
    p_run.add_argument("--execute", action="store_true")
    p_run.add_argument("--attempt", type=int, default=1)
    p_val = sub.add_parser("validate", parents=[common])
    p_val.add_argument("--phase", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.cmd == "prepare":
        bt = args.brief_file.read_text(encoding="utf-8") if args.brief_file else None
        refs = [(dest, Path(src)) for dest, src in args.reference] or None
        prepare(root, bt, references=refs)
    elif args.cmd == "run":
        os.environ.setdefault("DSH_MODEL", args.model)
        run_phase(root, args.phase)
    elif args.cmd == "validate":
        validate(root, args.phase)
    elif args.cmd == "gate":
        gate(root)
    elif args.cmd == "auto":
        if not os.environ.get("DEEPSEEK_API_KEY"):
            raise SystemExit("auto 需要 DEEPSEEK_API_KEY(或GLM key映射)")
        auto(root)


if __name__ == "__main__":
    main()
