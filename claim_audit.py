# -*- coding: utf-8 -*-
"""P2 采样原子主张核查(2026-10-01智囊团;依据FActScore原子主张分解+AVeriTeC
claim→evidence→verdict管线+Decomposition Dilemmas"不另搜,直接抓主张自引的URL")。

用法: python claim_audit.py --root .local/research8-run [--sample 5]
从交付链(终案+汇总+调研底稿)抽N条带引用的数字主张→抓取该主张自引的URL→
Flash模型三分裁决(支持/不支持/无法判断)→落盘 claim-audit.md。

定位: 抽查信号,不是门禁(与P3同哲学: 只度量不拦截)。"不支持"≠报告错,
=该主张与其自引来源对不上,须人工复核;联网失败/反爬墙/JS页的"无法判断"
同样是诚实结果。

六门复审整改(2026-10-01,门一/门二实锤项):
- 传输层显式代理(死代理根修:urlopen不收proxies参数,必须build_opener;
  直连段用ProxyHandler({})强制绕开Windows注册表代理,行为不再押在Clash开关上)
- SSRF拦截(环回/内网/链路本地/元数据地址一律拒抓)
- 页面编码按Content-Type回退GBK(UTF-8硬解曾把GBK页变U+FFFD垃圾静默进裁决)
- 行级异常隔离(一行崩不再整场作废)+judge重试保留
- spread_sample n=1除零根修
- 报告带时间戳+旧报告转存claim-audit-prev.md(不再静默覆盖证据)
- 主张全行送窗口定位与裁决(展示才截断,行尾关键词曾两头漏)
- best_window四件套: 搜索全文/条号直锚优先/噪声词降权/无锚退回首窗
- JSON正则容一层嵌套(reason含{Art.13}曾误配致合法裁决记核查失败)
- 管道符真转义(报告引文逐字)
"""
import argparse
import datetime
import html as html_mod
import ipaddress
import json
import random
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

API_URL = "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions"
MODEL = "glm-5.3-flash"
PROXY = "http://127.0.0.1:7890"
FETCH_TIMEOUT = 20
FETCH_BYTES = 900_000   # 长法条全文(GDPR实测35.5万字符)须整体进窗口定位
JUDGE_WINDOW = 4000     # 裁决摘录窗口(只给最相关段,不给开头)

# 三opener各司其职(opener.open不收context参数,跳证书必须焊进HTTPSHandler)
_DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 强制无代理
_PROXY_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
_UNVERIFIED_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))

# 数字型主张特征: 百分比/金额/数量/日期/罚金等(FactScore式"可验证原子主张"的粗筛)
_CLAIM_PAT = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:%|％|元|万|亿|欧|美|镑|€|\$|英镑|美元|欧元|天|周|月|年|条|件|封|个|次|人|倍)"
    r"|\b(?:19|20)\d{2}\s*[年]"
    r"|(?:最高|至少|最多|超过|约|近)\s*\d+")
_URL = re.compile(r"https?://[A-Za-z0-9:/\-._~?#\[\]@!$&+;,%=~]+")
# 参考文献条目行(如 "[2] https://…"): 它是引用本身不是主张,抽中只产出假裁决
_CITE_ENTRY = re.compile(r"^\s*[-*•]?\s*[\[（(]?\s*\d{1,2}\s*[\]）)]?\s*https?://")
# 条号锚(直锚定位用): §7 / s.10(9) / Article 13 / reg.22 / 第13条 / 2002/58/EC
# 不用\b: \w含CJK,"参考Article 13"/"见s.10"的中英接界处没有词边界,\b会让锚全部漏配(测试实锤)
_ANCHOR_PAT = re.compile(
    r"[§]\s?\d+(?:\s?(?:Abs|abs|Nr)\.?\s?\d+)*"
    r"|[sa]\.\s?\d+(?:\(\d+\))*"
    r"|Article\s+\d+(?:\(\d+\))*"
    r"|reg\.\s?\d+(?:\(\d+\))?"
    r"|第\s?\d+\s?条"
    r"|\d{4}/\d{2}/[A-Z]{2}")


def split_units(text):
    """切成(原始行号, 行文本)——行号用于按行号邻居配对URL(下标≠行号的错位已根修)。"""
    return [(i, ln.strip()) for i, ln in enumerate(text.splitlines()) if ln.strip()]


def claim_candidates(lines):
    """含数字特征的行(15-300字)。排除表格行(处理清单流水账+邻格借URL全是错配)
    与参考文献条目行(门一#4: "- [1] https://…(罚2000万欧)"形态曾绕过进强池)。"""
    out = []
    for i, ln in lines:
        if ln.startswith("|") or ln.startswith("#") or _CITE_ENTRY.match(ln):
            continue
        if _CLAIM_PAT.search(ln) and 15 <= len(ln) <= 300:
            out.append((i, ln))
    return out


def spread_sample(cands, n):
    """确定性均匀抽样: 全文档铺开不扎堆。n==1取中位(门一#2: 曾除零崩)。"""
    if n <= 0 or not cands:
        return []
    if len(cands) <= n:
        return cands
    if n == 1:
        return [cands[(len(cands) - 1) // 2]]
    idx = sorted({round(k * (len(cands) - 1) / (n - 1)) for k in range(n)})
    while len(idx) < n:  # 去重后不足时随机补,种子固定保证可复现
        extra = random.Random(20261001).randrange(len(cands))
        if extra not in idx:
            idx.append(extra)
    return [cands[j] for j in sorted(idx)]


def nearest_url(lines, target_i, window=3):
    """主张行先找本行URL;找不到按原始行号向上下window行扩散(按行号查邻居非下标)。"""
    by_no = {i: ln for i, ln in lines}
    for d in range(0, window + 1):
        for j in ((target_i,) if d == 0 else (target_i - d, target_i + d)):
            if j in by_no:
                m = _URL.search(by_no[j].rstrip(").,;:、。"))
                if m:
                    return m.group(0)
    return None


def _ssrf_blocked(url):
    """环回/内网/链路本地/元数据地址一律拒抓(门二#6)。"""
    try:
        host = urllib.parse.urlsplit(url).hostname or ""
    except ValueError:
        return True
    if not host:
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except ValueError:
        return host.lower() in ("localhost", "metadata.google.internal")


def _decode_page(raw):
    """UTF-8优先,U+FFFD占比高再试GBK(GBK中文官网页曾整页变替换符静默进裁决)。"""
    for enc in ("utf-8", "gbk"):
        txt = raw.decode(enc, errors="replace")
        if txt.count("\ufffd") <= len(txt) * 0.02:
            return txt, enc
    return raw.decode("utf-8", errors="replace"), "utf-8(损坏)"


def best_window(claim, txt, size=JUDGE_WINDOW):
    """定位最相关窗口。四件套(GDPR标本实测驱动):
    1) 条号直锚优先——引用写条号是法条引用常态,锚最后一次出现处开窗
       (首次出现常在目录;GDPR Article 13实测在52%处,单字符数字打分曾把
       窗口送去99%处的文末引用区);
    2) 无锚才打分,噪声词出局——裸短数字(6/2/0在法条里以百计)、全文高频词
       (法名每条标题都出现)不参与;
    3) 打分零命中退回首窗,诚实交裁判判'无法判断';
    4) 中文主张对英文原文零命中是方法边界,不硬修。"""
    for a in _ANCHOR_PAT.findall(claim):
        pos = txt.rfind(a)
        if pos >= 0:
            start = max(0, pos - 400)
            return txt[start:start + size]
    toks = set(re.findall(
        r"UWG|GDPR|PECR|CASL|CAN-SPAM|ePrivacy|LIA|SCC|CRTC|FTC|ICO", claim, re.I))
    toks |= {w for w in re.findall(r"[\u4e00-\u9fff]{2,6}|\d+(?:[.,]\d{3,})+|\d{4,}", claim)}
    low = txt.lower()
    freq_cap = max(8, len(low) // 800)  # 全文出现率过高=目录/页眉词,不参与定位
    hits = [t for t in toks if 0 < low.count(t.lower()) <= freq_cap]
    if not hits:
        return txt[:size]
    step = 800
    best, best_score = 0, -1
    for pos in range(0, max(1, len(txt) - size + 1), step):
        win = txt[pos:pos + size].lower()
        score = sum(win.count(t.lower()) for t in hits)
        if score > best_score:
            best, best_score = pos, score
    return txt[best:best + size]


def fetch(url):
    """直连(强制无代理)→代理→(仅https)跳证书→代理reader,四段降级。
    每段用显式opener: urlopen不收proxies参数,默认opener还会静默吃
    Windows注册表代理——行为曾随Clash系统代理开关漂移(同机不同时刻两种结果)。
    返回(文本, 降级标记);四段全败返回("", 各段错误合并,不再只剩末段)。"""
    if _ssrf_blocked(url):
        return "", "SSRF拦截(内网/环回/元数据地址不抓)"
    attempts = [
        (_DIRECT_OPENER, url, ""),
        (_PROXY_OPENER, url, ""),
    ]
    if url.startswith("https"):
        attempts.append((_UNVERIFIED_OPENER, url, "证书跳过"))
    attempts.append((_PROXY_OPENER, f"https://r.jina.ai/{url}", "经reader服务"))
    errs = []
    for opener, u, mark in attempts:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            with opener.open(req, timeout=FETCH_TIMEOUT) as r:
                raw = r.read(FETCH_BYTES)
            txt, enc = _decode_page(raw)
            raw_md = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", txt)
            plain = re.sub(r"(?s)<[^>]+>", " ", raw_md)
            plain = html_mod.unescape(plain)
            plain = re.sub(r"\s+", " ", plain).strip()
            if len(plain) >= 200:
                note = mark or (f"编码={enc}" if enc != "utf-8" else "")
                return plain, note
            errs.append(f"正文过短({len(plain)}字,疑JS渲染页){mark}")
        except Exception as e:
            errs.append(f"{type(e).__name__}:{str(e)[:60]}{mark}")
    return "", "四段全败[" + "; ".join(errs) + "]"


def judge(key, claim, excerpt):
    """Flash三分裁决: 只依据摘录判断,摘录没提到的判'无法判断',不用世界知识补。"""
    body = json.dumps({
        "model": MODEL, "max_tokens": 2048, "temperature": 0.1,
        "messages": [{"role": "user", "content":
            "你是事实核查员。一条从中文报告抽出的主张,及它所引网页的正文摘录。"
            "只依据摘录判断网页是否支持该主张——摘录没提到的就判'无法判断',不要用你的世界知识补。\n"
            f"主张: {claim}\n摘录: {excerpt[:JUDGE_WINDOW]}\n"
            '只输出JSON: {"verdict":"支持|不支持|无法判断","reason":"一句话,尽量引摘录原词"}'}],
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        API_URL, data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        data = json.loads(r.read().decode("utf-8"))
    txt = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    # 容一层嵌套(门二#2: reason含{Art. 13}曾被平的正则误配,合法裁决记核查失败)
    m = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", txt, re.S)
    if not m:
        return "核查失败", f"模型未按JSON回答: {txt[:60]}"
    try:
        j = json.loads(m.group(0))
        v = j.get("verdict", "")
        return (v if v in ("支持", "不支持", "无法判断") else "核查失败"), str(j.get("reason", ""))[:120]
    except Exception:
        return "核查失败", "JSON解析失败"


def load_corpus(root):
    """核查语料=全交付链(终案数字行多是自己的承诺无从核;可核外部事实住在底稿)。"""
    docs = []
    for name, rel in (("final-plan.md", "agents/finalizer/outputs/final-plan.md"),
                      ("architecture.md", "agents/architect/outputs/architecture.md")):
        p = root / rel
        if p.exists():
            docs.append((name, split_units(p.read_text(encoding="utf-8"))))
    try:
        n = json.loads((root / "agents/planner/outputs/plan.json")
                       .read_text(encoding="utf-8"))["N"]
    except Exception:
        n = 4
    for k in range(1, n + 1):
        rp = root / "agents" / f"researcher-{k}" / f"outputs/research-{k}.md"
        if rp.exists():
            docs.append((f"research-{k}.md", split_units(rp.read_text(encoding="utf-8"))))
    return docs


def esc(cell):
    """表格单元格真转义(门二#9: replace改写破坏逐字引文)。"""
    return cell.replace("|", "\\|").replace("\n", " ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--sample", type=int, default=5)
    ap.add_argument("--key-env", default="DEEPSEEK_API_KEY")
    ap.add_argument("--force", action="store_true",
                    help="跳过运行根完整性前置(默认要求demo.json在且门禁ok)")
    a = ap.parse_args()
    root = Path(a.root)
    key = __import__("os").environ.get(a.key_env, "")
    assert key, f"缺{a.key_env}环境变量(智谱Coding Plan key)"
    # 前置校验(门六#3): 不是运行根/门禁未过/交付链为空时不出误导报告
    if not a.force:
        assert root.is_dir(), f"{root} 不存在"
        assert (root / "demo.json").exists(), f"{root} 不是运行根(缺demo.json);确要跑加 --force"
        gr = root / "gate-report.json"
        if gr.exists():
            assert json.loads(gr.read_text(encoding="utf-8")).get("ok"), \
                "gate-report.ok=false(门禁未过,终案不可信,先跑完编队)"
        else:
            print("警告: 无gate-report.json(半程运行根?)", flush=True)
        assert any((root / "agents" / w / f"outputs/{f}").exists()
                   for w, f in [("finalizer", "final-plan.md"),
                                ("architect", "architecture.md")]), "交付链为空"

    corpus = load_corpus(root)
    cited, n_all = [], 0
    for doc, lines in corpus:
        n_all += len(claim_candidates(lines))
        for i, ln in claim_candidates(lines):
            cited.append((doc, i, ln, nearest_url(lines, i)))
    strong = [c for c in cited if c[3] and _URL.search(c[2])]
    weak = [c for c in cited if c[3] and not _URL.search(c[2])]
    take_s = min(a.sample, len(strong))
    picked = ([(d, i, ln, u) for d, i, ln, u in spread_sample(strong, take_s)]
              if take_s else [])
    if len(picked) < a.sample:  # 只用弱配对补位;无URL候选不烧抽样席位(门二#8)
        for d, i, ln, u in spread_sample(weak, min(a.sample - len(picked), len(weak))):
            picked.append((d, i, ln, u))
    print(f"语料 {len(corpus)} 篇,候选 {n_all} 条(强配对 {len(strong)}/弱配对 {len(weak)}/"
          f"无URL {n_all - len(strong) - len(weak)}),抽样 {len(picked)} 条", flush=True)

    rows, t0 = [], time.time()
    for no, (doc, i, ln, url) in enumerate(picked, 1):
        try:  # 行级隔离(门一#3): 一行异常不再作废整场,已花的fetch+API成本全保留
            if not url:
                rows.append((no, doc, ln, "", "无法判断", "主张行附近无URL可核"))
                continue
            excerpt, err = fetch(url)
            if not excerpt:
                rows.append((no, doc, ln, url, "无法判断", f"抓取失败: {err[:180]}"))
                continue
            v, why = judge(key, ln, best_window(ln, excerpt))  # 全行送定位与裁决(门二#1)
            if v == "核查失败":
                v, why = judge(key, ln, best_window(ln, excerpt))
            if err:
                why = f"{why}({err})"
            rows.append((no, doc, ln, url, v, why))
            print(f"  [{no}/{len(picked)}] {v}({doc}): {ln[:36]}...", flush=True)
        except Exception as e:  # 隔离层: API崩/编码炸只损失本行
            rows.append((no, doc, ln, url or "", "核查失败",
                         f"{type(e).__name__}: {str(e)[:100]}"))
            print(f"  [{no}/{len(picked)}] 核查失败({doc}): {type(e).__name__}", flush=True)

    n = {v: sum(1 for r in rows if r[4] == v)
         for v in ("支持", "不支持", "无法判断", "核查失败")}
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    md = ["# 主张抽查报告(P2·抽查信号,不是门禁)",
          "",
          f"时间: {ts} | 场次: `{root.name}` | 语料{len(corpus)}篇(终案+汇总+调研底稿) | "
          f"候选{n_all}条(强配对{len(strong)}/弱配对{len(weak)})抽{len(rows)}条 | "
          f"耗时{time.time() - t0:.0f}秒 | 裁决模型: {MODEL}(仅依据所引网页原文)", "",
          "| # | 文档 | 主张(节选) | 所引来源 | 裁决 | 依据 |",
          "|---|---|---|---|---|---|"]
    for no, doc, ln, url, v, why in rows:
        disp = ln if len(ln) <= 120 else ln[:117] + "..."
        u = f"[链接]({url})" if url else "—"
        md.append(f"| {no} | {doc} | {esc(disp)} | {u} | {v} | {esc(why)} |")
    md += ["", f"**汇总: 支持 {n['支持']}/{len(rows)}"
           + (f",不支持 {n['不支持']}(须人工复核原文)" if n["不支持"] else "")
           + (f",无法判断 {n['无法判断']}" if n["无法判断"] else "")
           + (f",核查失败 {n['核查失败']}" if n["核查失败"] else "") + "**", "",
          "口径: '不支持'=主张与其自引来源对不上,不是终审定罪;'无法判断'=网页抓不到"
          "(含反爬墙/JS渲染页)或摘录未提及,同样是诚实结果。本报告不拦截交付。"]
    out = root / "claim-audit.md"
    if out.exists():  # 旧报告转存(门二#5: 曾静默覆盖销毁证据)
        (root / "claim-audit-prev.md").write_text(
            out.read_text(encoding="utf-8"), encoding="utf-8")
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\n==> {out}  支持{n['支持']} 不支持{n['不支持']} "
          f"无法判断{n['无法判断']} 核查失败{n['核查失败']}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
