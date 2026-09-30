# -*- coding: utf-8 -*-
"""P2 采样原子主张核查(2026-10-01智囊团;依据FActScore原子主张分解+AVeriTeC
claim→evidence→verdict管线+Decomposition Dilemmas"不另搜,直接抓主张自引的URL")。

用法: python claim_audit.py --root .local/research7-run [--sample 5]
从终案随机均匀抽N条数字型主张→抓取该主张所在段落引用的URL→Flash模型
三分裁决(支持/不支持/无法判断)→落盘 claim-audit.md。

定位: 抽查信号,不是门禁(与P3同哲学: 只度量不拦截)。"不支持"≠报告错,
=该主张与其自引来源对不上,须人工复核;联网失败的"无法判断"同样是诚实结果。
"""
import argparse
import html as html_mod
import json
import random
import re
import sys
import time
import urllib.request
from pathlib import Path

API_URL = "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions"
MODEL = "glm-5.3-flash"
PROXY = "http://127.0.0.1:7890"
FETCH_TIMEOUT = 20
EXCERPT_CHARS = 40000   # 抓取保留量(长法条全文)
JUDGE_WINDOW = 4000     # 裁决摘录窗口(只给最相关段,不给开头)


def best_window(claim, txt, size=JUDGE_WINDOW):
    """按主张关键词定位最相关窗口。第四次实测教训: GDPR全文几十万字符,截开头
    =只给裁判看序言,条款在深处永远'摘录未提及'。关键词=条号/编号/数字/2字以上词,
    窗口按命中数取最高,平手取靠前;零命中退回首窗(诚实交裁判判'无法判断')。"""
    toks = set(re.findall(
        r"[§sS][.\s]?\d+(?:\(\w+\))*|reg\.\s?\d+(?:\(\d+\))?|Article\s?\d+|第\d+条"
        r"|\d{4}/\d{2}/[A-Z]{2}|UWG|GDPR|PECR|CASL|CAN-SPAM|ePrivacy|LIA|SCC", claim, re.I))
    toks |= {w for w in re.findall(r"[\u4e00-\u9fff]{2,6}|\d+(?:[.,]\d+)?", claim)}
    low = txt.lower()
    hits = [(t, low.count(t.lower())) for t in toks if low.count(t.lower()) > 0]
    if not hits:
        return txt[:size]
    step = 800
    best, best_score = 0, -1
    for pos in range(0, max(1, len(txt) - size + 1), step):
        win = txt[pos:pos + size].lower()
        score = sum(win.count(t.lower()) * (3 if re.match(r"\d|§|s\.|reg|Art", t, re.I) else 1)
                    for t, _ in hits)
        if score > best_score:
            best, best_score = pos, score
    return txt[best:best + size]

# 数字型主张特征: 百分比/金额/数量/日期/罚金等(FactScore式"可验证原子主张"的粗筛)
_CLAIM_PAT = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:%|％|元|万|亿|欧|美|镑|€|\$|英镑|美元|欧元|天|周|月|年|条|件|封|个|次|人|倍)"
    r"|\b(?:19|20)\d{2}\s*[年]"
    r"|(?:最高|至少|最多|超过|约|近)\s*\d+")
# URL只收ASCII可见字符: 第三次实测教训——\S+会把URL后的中文与第二个URL并吞成
# 一个"URL"(导致UnicodeEncodeError与错配),凡遇中文/全角即断。
_URL = re.compile(r"https?://[A-Za-z0-9:/\-._~?#\[\]@!$&+;,%=~]+")
# 参考文献条目行(如 "[2] https://… (ePrivacy第13条)"): 它是引用本身不是主张,
# 抽中它只会产出假裁决(第七场第三次实测的假"不支持"即源于此)。
_CITE_ENTRY = re.compile(r"^\s*[\[（(]?\s*\d{1,2}\s*[\]）)]?\s*https?://")


def split_units(text):
    """切成带行号的(行文本)列表——主张与其引用URL按'同段/邻近行'关联。"""
    return [(i, ln.strip()) for i, ln in enumerate(text.splitlines()) if ln.strip()]


def claim_candidates(lines):
    """含数字特征的行(15-300字,太短不成主张,太长不是原子主张)。
    排除表格行(以|开头)——第七场实测教训: 终案的处理清单/对比表里大量数字行
    是评审意见流水账,且邻近借URL机制在表格里全是错配(说s.10配s.6链接),
    抽样池里它们一出现就把真主张挤掉了。"""
    out = []
    for i, ln in lines:
        if ln.startswith("|") or ln.startswith("#") or _CITE_ENTRY.match(ln):
            continue
        if _CLAIM_PAT.search(ln) and 15 <= len(ln) <= 300:
            out.append((i, ln))
    return out


def spread_sample(cands, n):
    """确定性均匀抽样(固定种子仅用于打破并列): 全文档铺开,不扎堆。"""
    if len(cands) <= n:
        return cands
    idx = sorted({round(k * (len(cands) - 1) / (n - 1)) for k in range(n)})
    while len(idx) < n:  # 去重后不足时随机补,种子固定保证可复现
        extra = random.Random(20261001).randrange(len(cands))
        if extra not in idx:
            idx.append(extra)
    return [cands[j] for j in sorted(idx)]


def nearest_url(lines, target_i, window=3):
    """主张行先找本行URL;找不到按原始行号向上下window行扩散。
    必须按行号查邻居而非列表下标——split_units跳过空行后,列表下标≠行号,
    曾致系统性错配(说§7704配CNIL页,全部错位=空行偏移)。"""
    by_no = {i: ln for i, ln in lines}
    for d in range(0, window + 1):
        for j in ((target_i,) if d == 0 else (target_i - d, target_i + d)):
            if j in by_no:
                m = _URL.search(by_no[j].rstrip(").,;:、。"))
                if m:
                    return m.group(0)
    return None


def fetch(url):
    """直连→代理→(仅https)跳过证书验证三段降级。第三段是给boe.es这类
    官方官报站的:证书链在Windows Python信任库下验证失败,但作为只读的
    公开法条抓取,降级可接受——并在返回里带标记,报告如实呈现。"""
    import ssl
    unverified = ssl._create_unverified_context()
    attempts = [
        (None, None, ""),
        ({"http": PROXY, "https": PROXY}, None, ""),
    ]
    if url.startswith("https"):
        attempts.append((None, unverified, "证书跳过"))
        # JS渲染页兜底(eur-lex等官站直抓0字正文): r.jina.ai返回纯文本。国内直连
        # r.jina.ai会被重置,故reader走代理;公网法条页交给reader可接受,如实标注。
        attempts.append(({"http": PROXY, "https": PROXY}, None, "经reader服务"))
        url_for = [url, url, url, f"https://r.jina.ai/{url}"]
    else:
        url_for = [url] * len(attempts)
    last = ""
    for (proxies, ctx, mark), u in zip(attempts, url_for):
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT, context=ctx) as r:
                raw = r.read(400_000).decode("utf-8", errors="replace")
            raw = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", raw)
            txt = re.sub(r"(?s)<[^>]+>", " ", raw)
            txt = html_mod.unescape(txt)
            txt = re.sub(r"\s+", " ", txt).strip()
            if len(txt) >= 200:
                return txt[:EXCERPT_CHARS], mark
            last = f"正文过短({len(txt)}字,疑JS渲染页){mark}"
        except Exception as e:
            last = f"{type(e).__name__}: {str(e)[:80]}{mark}"
    return "", last


def judge(key, claim, excerpt):
    """Flash三分裁决: 支持该主张/不支持/摘录不足以判断。失败返回'核查失败'(诚实,不猜)。"""
    body = json.dumps({
        "model": MODEL, "max_tokens": 1024, "temperature": 0.1,
        "messages": [{"role": "user", "content":
            "你是事实核查员。一条从中文报告抽出的主张,及它所引网页的正文摘录。"
            "只依据摘录判断网页是否支持该主张——摘录没提到的就判'无法判断',不要用你的世界知识补。\n"
            f"主张: {claim}\n摘录: {excerpt[:4000]}\n"
            '只输出JSON: {"verdict":"支持|不支持|无法判断","reason":"一句话,尽量引摘录原词"}'}],
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        API_URL, data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        data = json.loads(r.read().decode("utf-8"))
    txt = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    m = re.search(r"\{[^{}]*\}", txt, re.S)
    if not m:
        return "核查失败", f"模型未按JSON回答: {txt[:60]}"
    try:
        j = json.loads(m.group(0))
        v = j.get("verdict", "")
        return (v if v in ("支持", "不支持", "无法判断") else "核查失败"), str(j.get("reason", ""))[:120]
    except Exception:
        return "核查失败", "JSON解析失败"


def load_corpus(root):
    """核查语料=全交付链(第二次实测教训: 执行终案的数字行多是我们自己的承诺,
    无从核也不该核;可核外部事实与引用都住在调研底稿与汇总稿里)。
    返回[(文档名, lines)],终案在前保证被抽到。"""
    docs = []
    fp = root / "agents/finalizer/outputs/final-plan.md"
    if fp.exists():
        docs.append(("final-plan.md", split_units(fp.read_text(encoding="utf-8"))))
    arch = root / "agents/architect/outputs/architecture.md"
    if arch.exists():
        docs.append(("architecture.md", split_units(arch.read_text(encoding="utf-8"))))
    try:
        n = json.loads((root / "agents/planner/outputs/plan.json")
                       .read_text(encoding="utf-8"))["N"]
    except Exception:
        n = MAX_FALLBACK_RESEARCHERS
    for k in range(1, n + 1):
        rp = root / "agents" / f"researcher-{k}" / f"outputs/research-{k}.md"
        if rp.exists():
            docs.append((f"research-{k}.md", split_units(rp.read_text(encoding="utf-8"))))
    return docs


MAX_FALLBACK_RESEARCHERS = 4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--sample", type=int, default=5)
    ap.add_argument("--key-env", default="DEEPSEEK_API_KEY",
                    help="智谱key所在环境变量名")
    a = ap.parse_args()
    root = Path(a.root)
    key = __import__("os").environ.get(a.key_env, "")
    assert key, f"缺{a.key_env}环境变量(智谱Coding Plan key)"

    corpus = load_corpus(root)
    cited, n_all = [], 0
    for doc, lines in corpus:
        n_all += len(claim_candidates(lines))
        for i, ln in claim_candidates(lines):
            cited.append((doc, i, ln, nearest_url(lines, i)))
    with_url = [c for c in cited if c[3]]
    # 配对可信度分档(第五次实测教训: 均匀抽样在混池里系统性错过真主张):
    # 同行URL=作者亲手把源挂在该主张上(强配对,优先抽);邻行URL=借来的(弱配对,
    # 只在强配对不足时补位,裁决如实暴露错配)。
    strong = [c for c in with_url if _URL.search(c[2])]
    weak = [c for c in with_url if not _URL.search(c[2])]
    no_url = [c for c in cited if not c[3]]
    take_s = min(a.sample, len(strong))
    picked = ([(d, i, ln, u) for d, i, ln, u in spread_sample(strong, take_s)]
              if take_s else [])
    for pool in (weak, no_url):
        need = a.sample - len(picked)
        if need <= 0:
            break
        for d, i, ln, u in spread_sample(pool, min(need, len(pool))):
            picked.append((d, i, ln, u))
    print(f"语料 {len(corpus)} 篇,候选 {n_all} 条(强配对同行URL {len(strong)}/"
          f"弱配对邻行 {len(weak)}/无URL {len(no_url)}),抽样 {len(picked)} 条", flush=True)

    rows, t0 = [], time.time()
    for no, (doc, i, ln, url) in enumerate(picked, 1):
        claim = ln if len(ln) <= 160 else ln[:157] + "..."
        if not url:
            rows.append((no, doc, claim, "", "无法判断", "主张行附近无URL可核"))
            continue
        excerpt, err = fetch(url)
        if not excerpt:
            rows.append((no, doc, claim, url, "无法判断", f"抓取失败: {err}"))
            continue
        win = best_window(claim, excerpt)
        v, why = judge(key, claim, win)
        if v == "核查失败":  # JSON偶发失败重试一次(gesetze实测)
            v, why = judge(key, claim, win)
        if err:  # 成功但降级抓取(如证书跳过)——如实标注
            why = f"{why}(抓取降级: {err})"
        rows.append((no, doc, claim, url, v, why))
        print(f"  [{no}/{len(picked)}] {v}({doc}): {claim[:36]}...", flush=True)

    n = {v: sum(1 for r in rows if r[4] == v) for v in ("支持", "不支持", "无法判断", "核查失败")}
    md = ["# 主张抽查报告(P2·抽查信号,不是门禁)", "",
          f"场次: `{root.name}` | 语料{len(corpus)}篇(终案+汇总+调研底稿) | 候选{n_all}条"
          f"带URL{len(with_url)}条抽{len(rows)}条 | 耗时{time.time() - t0:.0f}秒"
          f" | 裁决模型: {MODEL}(仅依据所引网页原文)", "",
          "| # | 文档 | 主张(节选) | 所引来源 | 裁决 | 依据 |",
          "|---|---|---|---|---|---|"]
    for no, doc, claim, url, v, why in rows:
        u = f"[链接]({url})" if url else "—"
        md.append(f"| {no} | {doc} | {claim.replace('|', '/')} | {u} | {v} | {why.replace('|', '/')} |")
    md += ["", f"**汇总: 支持 {n['支持']}/{len(rows)}"
           + (f",不支持 {n['不支持']}(须人工复核原文)" if n["不支持"] else "")
           + (f",无法判断 {n['无法判断']}" if n["无法判断"] else "") + "**", "",
          "口径: '不支持'=主张与其自引来源对不上,不是终审定罪;'无法判断'=网页抓不到或"
          "摘录未提及,同样是诚实结果。本报告不拦截交付,供老板抽查与下场迭代用。"]
    out = root / "claim-audit.md"
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\n==> {out}  支持{n['支持']} 不支持{n['不支持']} "
          f"无法判断{n['无法判断']} 核查失败{n['核查失败']}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
