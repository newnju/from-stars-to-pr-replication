# -*- coding: utf-8 -*-
"""mine_deep6.py — 第六轮零假设挖掘（2026-10-25）
完全未动过的数据层：
1. SHA 考古：跨仓相同 SHA 的"首次出现时间"分布——内容首次诞生的时间结构
2. 文档正文语义相似度的极端对（同一文档的最不像副本）
3. 平台条目生命周期画像：ClawHub 条目的创建时间分布与版本演化
4. 技能名冲突图谱：同名技能在不同仓的星标差异（谁借谁的光）
5. PR 标题与正文的情感/紧急度（fix/urgent/breaking 等紧急词）
6. 仓库描述文本的情感与主题词（比技能名更深一层）
7. 星标事件的周内节律按仓分层（官方 vs 转发 vs 原创）
8. 安装量的"帕累托截断"：每渠道的 top-N 份额曲线对比
9. frontmatter 字段组合的频繁项集（哪些字段一起出现）
"""
import json, os, re, collections, datetime, random
import numpy as np
from scipy.stats import mannwhitneyu, spearmanr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COL = os.path.join(ROOT, 'external_data', 'collected_20261024')
TMP = r'E:\temp\opencode'
REF = datetime.datetime(2026, 10, 24, tzinfo=datetime.timezone.utc)
out = {}

print("loading...", flush=True)
gdm = json.load(open(os.path.join(ROOT, 'data', 'repos_meta.json'), encoding='utf-8'))
sh2 = json.load(open(os.path.join(TMP, 'star_history_v2.json'), encoding='utf-8'))
lm = {}
for line in open(os.path.join(COL, 'local_mining.jsonl'), encoding='utf-8'):
    r = json.loads(line)
    if r.get('type') == 'repo':
        lm[r['repo']] = {'stars': r.get('stars') or 0, 'n_skills': r.get('n_skills') or 0,
                         'share_cross': r.get('share_cross') or 0}
sh_hit = {}; sh_inst = {}
for nmf in ('market_full.jsonl', 'market_retry.jsonl'):
    for line in open(os.path.join(COL, nmf), encoding='utf-8'):
        r = json.loads(line)
        if r.get('type') == 'skills_sh':
            sh_hit[r['repo']] = 1 if (r.get('n_hits') or 0) > 0 else 0
            if sh_hit[r['repo']]: sh_inst[r['repo']] = r.get('total_installs') or 0

# ========== 1. SHA 考古：内容首次出现的时间结构 ==========
print("1. SHA archaeology...", flush=True)
# 每仓的文档最早出现时间=仓创建时间；跨仓 SHA 的最早仓创建时间=内容诞生时间
sha_created = collections.defaultdict(list)  # sha -> [created_at of repos containing it]
n_read = 0
with open(os.path.join(ROOT, 'external_data', 'skills_with_content.jsonl'), encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        h = r.get('sha256_hash'); rp = r.get('repoFullName')
        if h and rp in gdm:
            ca = gdm[rp].get('created_at')
            if ca: sha_created[h].append(ca)
            n_read += 1
# 多仓 SHA：内容诞生时间=最早仓创建
birth = collections.Counter()
birth_month = collections.Counter()
for h, cas in sha_created.items():
    if len(cas) < 2: continue
    first = min(cas)[:7]
    birth[first[:4]] += 1
    birth_month[first] += 1
out['sha_archaeology'] = {
    'n_multi_sha': len([h for h, c in sha_created.items() if len(c) >= 2]),
    'birth_by_year': dict(sorted(birth.items())),
    'top_birth_months': sorted(birth_month.items(), key=lambda x: -x[1])[:8],
    'note': '多仓SHA的内容"诞生月"（最早含它的仓创建月）；n_read=%d' % n_read}

# ========== 2. 同名技能的星标差异（谁借谁的光）==========
print("2. name collision stars...", flush=True)
name_repos = collections.defaultdict(list)
with open(os.path.join(ROOT, 'external_data', 'skills_with_content.jsonl'), encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        nm = (r.get('name') or '').strip().lower()
        rp = r.get('repoFullName')
        if nm and len(nm) > 2 and rp in gdm:
            name_repos[nm].append(rp)
coll = []
for nm, rps in name_repos.items():
    if len(set(rps)) >= 3:
        stars = sorted([gdm.get(r, {}).get('stars') or 0 for r in set(rps)], reverse=True)
        coll.append({'name': nm, 'n_repos': len(set(rps)), 'max_star': stars[0],
                     'median_star': int(np.median(stars)), 'star_ratio': round(stars[0] / max(stars[-1], 1), 1)})
coll.sort(key=lambda x: -x['n_repos'])
out['name_collision'] = {
    'n_names_ge3': len(coll),
    'top10': coll[:10],
    'median_max_over_median_ratio': round(float(np.median([c['star_ratio'] for c in coll])), 1) if coll else None,
    'note': '同名技能≥3仓的星标差异'}

# ========== 3. PR 紧急度词汇 ==========
print("3. PR urgency...", flush=True)
urgency_words = {'urgent': 0, 'asap': 0, 'breaking': 0, 'critical': 0, 'hotfix': 0,
                 'security': 0, 'vulnerab': 0, 'cve': 0, 'malicious': 0}
n_title = 0
for nmf in ('pr_merged.jsonl', 'pr_merged_retry.jsonl', 'pr_merged_retry3.jsonl'):
    for line in open(os.path.join(COL, nmf), encoding='utf-8'):
        r = json.loads(line)
        if r.get('type') != 'repo' or not r.get('complete'): continue
        for pr in r.get('pulls', []):
            t = (pr.get('title') or '').lower()
            n_title += 1
            for w in urgency_words:
                if w in t: urgency_words[w] += 1
out['pr_urgency'] = {'n_titles': n_title,
    'urgency_counts': {k: v for k, v in urgency_words.items()},
    'urgency_share': {k: round(v / max(n_title, 1), 4) for k, v in urgency_words.items()},
    'note': 'PR标题中的紧急/安全词汇占比'}

# ========== 4. 星标周内节律按仓类型分层 ==========
print("4. day-of-week by repo type...", flush=True)
dow_by_type = collections.defaultdict(lambda: collections.Counter())
relay_set = {rp for rp, d in lm.items() if d['share_cross'] >= 0.7 and d['n_skills'] >= 5}
orig_set = {rp for rp, d in lm.items() if d['share_cross'] <= 0.1 and d['n_skills'] >= 5}
official_set = {rp for rp in gdm if any(k in rp.lower() for k in ['anthropic', 'google/', 'microsoft/', 'github/'])}
for rp, rows in sh2.items():
    tp = 'official' if rp in official_set else ('relay' if rp in relay_set else ('original' if rp in orig_set else None))
    if not tp: continue
    for w in rows:
        wt = datetime.datetime.fromtimestamp(w['week'], tz=datetime.timezone.utc)
        for i, dn in enumerate(w['days']):
            if dn: dow_by_type[tp][(wt + datetime.timedelta(days=i)).weekday()] += dn
dow_out = {}
for tp, c in dow_by_type.items():
    tot = sum(c.values())
    if tot < 100: continue
    # 周末（五六）占比
    weekend_share = (c.get(5, 0) + c.get(6, 0)) / tot
    dow_out[tp] = {'total': tot, 'weekend_share': round(float(weekend_share), 3),
                   'peak_day': max(c, key=c.get)}
out['dow_by_type'] = {'types': dow_out,
    'note': '官方/转发/原创仓的星标周内节律（weekend_share 越高越像个人行为）'}

# ========== 5. 渠道 top-N 份额曲线（帕累托截断对比）==========
print("5. pareto curves...", flush=True)
def topn_share(vals, ns=(1, 5, 10, 50)):
    s = sorted(vals, reverse=True)
    tot = sum(s)
    return {f'top{n}': round(sum(s[:n]) / max(tot, 1), 3) for n in ns}
sh_vals = list(sh_inst.values())
ch_vals = []
for line in open(os.path.join(COL, 'market_full.jsonl'), encoding='utf-8'):
    r = json.loads(line)
    if r.get('type') == 'clawhub_registry':
        st = (r.get('item') or {}).get('stats') or {}
        if st.get('downloads'): ch_vals.append(st['downloads'])
npm_m = []
for line in open(os.path.join(COL, 'npm_downloads.jsonl'), encoding='utf-8'):
    r = json.loads(line)
    if r.get('type') == 'repo' and r['npm']['status'] == 'matched':
        m = sum(p.get('downloads_last_month') or 0 for p in r['npm'].get('packages', []))
        if m: npm_m.append(m)
rel_v = []
for line in open(os.path.join(COL, 'release_downloads.jsonl'), encoding='utf-8'):
    r = json.loads(line)
    if r.get('type') == 'repo':
        d = (r.get('github') or {}).get('downloads') or 0
        if d: rel_v.append(d)
stars_v = [gdm[rp].get('stars') or 0 for rp in gdm if (gdm[rp].get('stars') or 0) > 0]
out['pareto'] = {
    'skillssh_installs': {'n': len(sh_vals), **topn_share(sh_vals)},
    'clawhub_downloads': {'n': len(ch_vals), **topn_share(ch_vals)},
    'npm_monthly': {'n': len(npm_m), **topn_share(npm_m)},
    'release': {'n': len(rel_v), **topn_share(rel_v)},
    'github_stars': {'n': len(stars_v), **topn_share(stars_v)},
    'note': '各渠道 top1/5/10/50 份额——帕累托陡峭度对比'}

# ========== 6. frontmatter 字段组合频繁项集 ==========
print("6. frontmatter field combos...", flush=True)
FM = re.compile(r"^---\s*\n(.*?)\n---", re.S)
combos = collections.Counter(); single = collections.Counter(); n_fm = 0
with open(os.path.join(ROOT, 'external_data', 'skills_with_content.jsonl'), encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        c = r.get('full_content') or ''
        m = FM.match(c.strip('\ufeff \n'))
        if not m: continue
        keys = set()
        for ln in m.group(1).splitlines():
            if ':' in ln:
                k = ln.split(':', 1)[0].strip().lower()
                if k and not k.startswith('#'): keys.add(k)
        if not keys: continue
        n_fm += 1
        for k in keys: single[k] += 1
        for a in keys:
            for b in keys:
                if a < b: combos[frozenset([a, b])] += 1
top_combos = [(sorted(k), v) for k, v in combos.most_common(12)]
top_singles = single.most_common(15)
out['frontmatter_combos'] = {
    'n_with_fm': n_fm,
    'top_fields': top_singles,
    'top_pairs': [{'pair': k, 'n': v, 'support': round(v / max(n_fm, 1), 3)} for k, v in top_combos],
    'note': 'frontmatter 字段的单频与二元共现支持度'}

# ========== 7. 安装/星标比率的分布（把"代理差异"参数化）==========
print("7. installs-per-star distribution...", flush=True)
ratios = []
for rp, v in sh_inst.items():
    st = gdm.get(rp, {}).get('stars') or 0
    if st >= 100:
        ratios.append(v / st)
if ratios:
    ra = np.array(ratios)
    out['install_per_star'] = {
        'n': len(ra), 'median': round(float(np.median(ra)), 2),
        'p10': round(float(np.percentile(ra, 10)), 3), 'p90': round(float(np.percentile(ra, 90)), 2),
        'pct_above_10': round(float(np.mean(ra >= 10)), 3), 'pct_below_1': round(float(np.mean(ra < 1)), 3),
        'note': '星标≥100仓的每星安装数分布——代理换算的离散度'}

# ========== 8. 平台条目版本数分布 ==========
print("8. version depth...", flush=True)
vers = []
vers_zero = 0
for line in open(os.path.join(COL, 'market_full.jsonl'), encoding='utf-8'):
    r = json.loads(line)
    if r.get('type') == 'clawhub_registry':
        st = (r.get('item') or {}).get('stats') or {}
        v = st.get('versions') or 0
        if v: vers.append(v)
        else: vers_zero += 1
if vers:
    va = np.array(vers)
    out['version_depth'] = {'n_items_with_versions': len(vers), 'zero_version_items': vers_zero,
        'median': float(np.median(va)), 'pct_single_version': round(float(np.mean(va == 1)), 3),
        'pct_ge5': round(float(np.mean(va >= 5)), 3),
        'note': 'ClawHub 条目的版本数分布——单版本即弃置的比例'}

# ========== 9. 仓库描述的主题词（超越技能名）==========
print("9. repo description themes...", flush=True)
theme_words = collections.Counter()
stop = {'the','a','an','for','of','and','to','in','with','on','by','is','it','this','that','your','you','from','or','as','be','can','use','using','based','all','any','into','when','new','more','also','best','top','github','repo','repository','set','llm','llms','model','models','agent','agents','ai','claude','code','claudecode','gpt','openai','anthropic','mcp','skill','skills','tool','tools'}
desc_texts = []
for rp, m in gdm.items():
    d = (m.get('description') or '').lower()
    if len(d) < 20: continue
    desc_texts.append(d)
    for w in re.findall(r'[a-z]{4,}', d):
        if w not in stop: theme_words[w] += 1
out['desc_themes'] = {'n_desc': len(desc_texts), 'top30': theme_words.most_common(30),
    'note': '35,947普查仓描述的词频（去除通用停用词与领域专名）'}

json.dump(out, open(os.path.join(ROOT, 'data', 'results', 'deep6_20261025.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1, default=str)
print("\n=== SUMMARY ===")
for k, v in out.items():
    print(f"--- {k} ---")
    print(json.dumps(v, ensure_ascii=False, indent=1)[:700])
print("ALL DONE")
