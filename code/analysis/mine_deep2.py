# -*- coding: utf-8 -*-
"""mine_deep2.py — 第二轮深挖（2026-10-25）：七项新分析
A 复制社区谱系（官方扇出+两巨社区构成） B 轨迹类型×渠道 C PR标题模式
D 跨平台内容匹配 E 注意力突发日历 F 仓库策略类型学 G 回流流向
输出 data/results/newfindings2_20261025.json
"""
import json, os, re, collections, datetime
import numpy as np
from scipy.stats import mannwhitneyu

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COL = os.path.join(ROOT, 'external_data', 'collected_20261024')
TMP = r'E:\temp\opencode'
out = {}

CATS = [("bangong", "pdf docx pptx xlsx word excel powerpoint spreadsheet"),
        ("web", "web frontend react vue html css tailwind ui landing design figma"),
        ("test", "test testing e2e coverage qa lint debug"),
        ("pachong", "scrape scraper crawling spider dataset csv parse extract"),
        ("xiezuo", "write writing copy blog article seo essay humanize content"),
        ("anquan", "security audit vuln secret token credential pentest"),
        ("sousuo", "search research deep fact paper literature"),
        ("devops", "deploy docker kubernetes ci terraform cli shell bash git"),
        ("shuju", "database sql postgres mysql mongo api graphql"),
        ("ai", "agent llm prompt gpt model embedding rag mcp")]

def cat_of(t):
    t = t.lower()
    for n, kw in CATS:
        if any(k in t for k in kw.split()):
            return n
    return 'tongyong'

sha_repos = {}
repo_cats = collections.defaultdict(collections.Counter)
names = set()
anth_sha = set()
anth_docs = 0
FM = re.compile(r"^---\s*\n(.*?)\n---", re.S)
with open(os.path.join(ROOT, 'external_data', 'skills_with_content.jsonl'), encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        h = r.get('sha256_hash'); rp = r.get('repoFullName')
        if h:
            sha_repos.setdefault(h, set()).add(rp)
            if rp == 'anthropics/skills':
                anth_sha.add(h); anth_docs += 1
        c = r.get('full_content') or ''
        m = FM.match(c.strip('\ufeff \n'))
        desc = (r.get('description') or '')[:150]; nm = r.get('name') or ''
        if m:
            fm = {}
            for ln in m.group(1).splitlines():
                if ':' in ln:
                    k, v = ln.split(':', 1); fm[k.strip().lower()] = v.strip()
            desc = fm.get('description') or desc; nm = fm.get('name') or nm
        if nm:
            names.add(nm.strip().lower())
        repo_cats[rp][cat_of(desc)] += 1

import networkx as nx
import networkx.algorithms.community as nxcom
G = nx.Graph()
for h, rs in sha_repos.items():
    if len(rs) >= 2:
        rl = sorted(rs)
        for i in range(len(rl) - 1):
            for j in range(i + 1, min(i + 6, len(rl))):
                if G.has_edge(rl[i], rl[j]):
                    G[rl[i]][rl[j]]['w'] += 1
                else:
                    G.add_edge(rl[i], rl[j], w=1)
com = sorted(nxcom.greedy_modularity_communities(G, weight='w'), key=len, reverse=True)
lm = {}
for line in open(os.path.join(COL, 'local_mining.jsonl'), encoding='utf-8'):
    r = json.loads(line)
    if r.get('type') == 'repo':
        lm[r['repo']] = r.get('stars') or 0

def reg(rp):
    return any(k in rp.lower() for k in ['registry', 'feed', 'marketplace', 'awesome', 'skills', 'templates'])

ci = []
for c0 in com[:2]:
    mem = list(c0); stars = [lm.get(m, 0) for m in mem]
    td = sorted(mem, key=lambda m: -G.degree(m))[:3]
    ci.append({'size': len(mem), 'median_stars': int(np.median(stars)),
               'registry_like_share': round(float(np.mean([reg(m) for m in mem])), 3),
               'top_degree': [(m, G.degree(m), lm.get(m, 0)) for m in td]})
af = [len(sha_repos[h]) for h in anth_sha]
out['A_genealogy'] = {'anthropic_docs': anth_docs, 'anthropic_shas': len(anth_sha),
                      'anth_fanout_max': int(max(af)) if af else 0,
                      'anth_fanout_mean': round(float(np.mean(af)), 2),
                      'top2_communities': ci}

sh2 = json.load(open(os.path.join(TMP, 'star_history_v2.json'), encoding='utf-8'))
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
feats = []; rps = []
for rp, rows in sh2.items():
    rows = sorted(rows, key=lambda w: w['week']); tot = [w['total'] for w in rows]
    if len(tot) < 12 or sum(tot) <= 0:
        continue
    cum = np.cumsum(tot)
    feats.append([max(tot) / sum(tot), (np.argmax(cum >= .9 * cum[-1]) + 1) / len(cum), np.log1p(cum[-1])])
    rps.append(rp)
km = KMeans(4, n_init=10, random_state=25).fit(StandardScaler().fit_transform(np.array(feats)))
hit = {}; inst = {}
for nmf in ('market_full.jsonl', 'market_retry.jsonl'):
    for line in open(os.path.join(COL, nmf), encoding='utf-8'):
        r = json.loads(line)
        if r.get('type') == 'skills_sh' and r.get('repo') in sh2:
            hit[r['repo']] = 1 if (r.get('n_hits') or 0) > 0 else 0
            if hit[r['repo']]:
                inst[r['repo']] = r.get('total_installs') or 0
byt = collections.defaultdict(lambda: [0, 0, []])
for rp, l in zip(rps, km.labels_):
    k = int(l); byt[k][0] += 1; byt[k][1] += hit.get(rp, 0)
    if hit.get(rp):
        byt[k][2].append(inst.get(rp, 0))
out['B_traj_channels'] = {'type%d' % (k + 1): {'n': v[0], 'hit_share': round(v[1] / v[0], 3),
                        'med_inst': int(np.median(v[2])) if v[2] else None} for k, v in sorted(byt.items())}

pref = ai = n = zh = 0
for nmf in ('pr_merged.jsonl', 'pr_merged_retry.jsonl', 'pr_merged_retry3.jsonl'):
    for line in open(os.path.join(COL, nmf), encoding='utf-8'):
        r = json.loads(line)
        if r.get('type') != 'repo' or not r.get('complete'):
            continue
        for pr in r.get('pulls', []):
            t = pr.get('title') or ''
            if not t:
                continue
            n += 1; tt = t.lower()
            if re.match(r'^(feat|fix|chore|docs|update|bump|refactor|test|style)', tt):
                pref += 1
            if any(k in tt for k in ['ai', 'agent', 'claude', 'gpt', 'llm']):
                ai += 1
            if any('\u4e00' <= ch <= '\u9fff' for ch in t):
                zh += 1
p4 = os.path.join(TMP, 'pr_merged_retry4.jsonl')
if os.path.exists(p4):
    for line in open(p4, encoding='utf-8'):
        r = json.loads(line)
        if r.get('type') != 'repo' or not r.get('complete'):
            continue
        for pr in r.get('pulls', []):
            t = pr.get('title') or ''
            if not t:
                continue
            n += 1; tt = t.lower()
            if re.match(r'^(feat|fix|chore|docs|update|bump|refactor|test|style)', tt):
                pref += 1
            if any(k in tt for k in ['ai', 'agent', 'claude', 'gpt', 'llm']):
                ai += 1
            if any('\u4e00' <= ch <= '\u9fff' for ch in t):
                zh += 1
out['C_pr_titles'] = {'n': n, 'convention': round(pref / n, 3), 'ai_mention': round(ai / n, 3), 'chinese': round(zh / n, 3)}

slugs = set(); reg_n = 0
for line in open(os.path.join(COL, 'market_full.jsonl'), encoding='utf-8'):
    r = json.loads(line)
    if r.get('type') == 'clawhub_registry':
        reg_n += 1
        s = (r.get('item') or {}).get('slug') or ''
        if s:
            slugs.add(s.split('--')[-1] if '--' in s else s)
out['D_match'] = {'clawhub': reg_n, 'github_names': len(names),
                  'matched': len(slugs & names), 'rate': round(len(slugs & names) / reg_n, 3)}

daily = collections.Counter()
for rp, rows in sh2.items():
    for w in rows:
        wt = datetime.datetime.fromtimestamp(w['week'], tz=datetime.timezone.utc)
        for i, dn in enumerate(w['days']):
            if dn:
                daily[(wt + datetime.timedelta(days=i)).strftime('%m-%d')] += dn
out['E_burst'] = sorted(daily.items(), key=lambda x: -x[1])[:8]

divs = []; single = 0; nrep = 0
db = {0: [], 1: [], 2: [], 3: []}
for rp, c in repo_cats.items():
    major = {k for k in c if k != 'tongyong' and c[k] >= 2}
    ns = sum(c.values())
    if ns >= 5:
        nrep += 1; nd = len(major); divs.append(nd)
        if nd == 1:
            single += 1
        db[min(nd, 3)].append(lm.get(rp, 0))
out['F_strategy'] = {'n': nrep, 'single_type_share': round(single / nrep, 3),
                     'med_types': float(np.median(divs)),
                     'med_stars_by_nd': {str(k if k < 3 else '3+'): int(np.median(v)) for k, v in db.items() if v}}
if db[3]:
    out['F_strategy']['p_div1_vs_3plus'] = round(float(mannwhitneyu(db[0], db[3]).pvalue), 4)

tgt = collections.Counter()
for nmf in ('fork_prs.jsonl', 'fork_prs_retry1.jsonl', 'fork_prs_retry2.jsonl'):
    for line in open(os.path.join(COL, nmf), encoding='utf-8'):
        r = json.loads(line)
        if r.get('type') == 'parent' and r.get('complete'):
            tgt[r['parent']] += sum(1 for l in r.get('links', []) if l.get('matched_by') == 'head_repo')
p3 = os.path.join(TMP, 'fork_prs_retry3.jsonl')
if os.path.exists(p3):
    for line in open(p3, encoding='utf-8'):
        r = json.loads(line)
        if r.get('type') == 'parent' and r.get('complete'):
            tgt[r['parent']] += sum(1 for l in r.get('links', []) if l.get('matched_by') == 'head_repo')
top = tgt.most_common(15)
cls = collections.Counter('official' if any(k in p for k in ['anthropics', 'google', 'microsoft', 'github', 'openclaw'])
                          else 'registry' if reg(p) else 'app' for p, _ in top)
out['G_targets'] = {'top15': [(p, c) for p, c in top], 'class': dict(cls),
                    'top5_share': round(sum(c for _, c in top[:5]) / max(sum(tgt.values()), 1), 3)}

json.dump(out, open(os.path.join(ROOT, 'data', 'results', 'newfindings2_20261025.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
