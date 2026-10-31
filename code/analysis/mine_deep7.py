# -*- coding: utf-8 -*-
"""mine_deep7.py — 第七轮零假设挖掘（2026-10-25）
完全未触的切面：
1. 文档正文首段的"召唤结构"：多少文档以命令句/疑问句/列表开头（文风挖掘）
2. frontmatter license 字段的"值"分布：写了 license 的都写的什么
3. 技能文档的"命令密度"：正文含 shell 命令行的文档占比——与安全标记交叉
4. 双平台收录仓 vs 单平台仓的星标差（条件层二分）
5. 文档名长度分布与星标（命名长度经济学）
6. fork 仓库的命名保留率：fork 后改名的比例（用 fork_prs links 的 head_repo 名 vs parent 名）
7. ClawHub 条目名前缀分析：scope 前缀（@xxx/）与平台品牌化
8. PR 标题中的语言混杂度：中英混排/emoji/版本号
9. 复制簇的"半径"：同一簇内文档所在仓的星标跨度
10. star_history v2 的周内自相关：上周星标能否预测本周（含滞后1-4周）
"""
import json, os, re, collections, datetime, random
import numpy as np
from scipy.stats import spearmanr, mannwhitneyu

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
ch_hit = {}
for line in open(os.path.join(COL, 'market_full.jsonl'), encoding='utf-8'):
    r = json.loads(line)
    if r.get('type') == 'clawhub_search':
        ch_hit[r['repo']] = 1 if (r.get('n_hits') or 0) > 0 else 0

# ========== 1. license 字段的值分布 ==========
print("1. license values...", flush=True)
FM = re.compile(r"^---\s*\n(.*?)\n---", re.S)
lic_vals = collections.Counter(); n_lic = 0
with open(os.path.join(ROOT, 'external_data', 'skills_with_content.jsonl'), encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        c = r.get('full_content') or ''
        m = FM.match(c.strip('\ufeff \n'))
        if not m: continue
        for ln in m.group(1).splitlines():
            mm = re.match(r'^license\s*:\s*(.+)$', ln.strip(), re.I)
            if mm:
                v = mm.group(1).strip().strip('"\'')[:40]
                lic_vals[v] += 1; n_lic += 1
out['license_values'] = {'n_licenses': n_lic, 'top_values': lic_vals.most_common(12),
    'note': '写了 license 字段的文档的值分布'}

# ========== 2. 文档首段召唤结构 + 命令密度 ==========
print("2. document style...", flush=True)
style = {'starts_with_heading': 0, 'starts_with_list': 0, 'starts_with_code': 0, 'starts_with_prose': 0}
cmd_docs = 0; n_doc = 0; emoji_docs = 0
with open(os.path.join(ROOT, 'external_data', 'skills_with_content.jsonl'), encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        rp = r.get('repoFullName')
        if rp not in gdm: continue
        c = r.get('full_content') or ''
        body = re.sub(r'^---.*?---', '', c.strip(), flags=re.S).strip()
        if len(body) < 50: continue
        n_doc += 1
        first = body.split('\n')[0].strip()
        if first.startswith('#'): style['starts_with_heading'] += 1
        elif re.match(r'^[-*\d]', first): style['starts_with_list'] += 1
        elif first.startswith('```'): style['starts_with_code'] += 1
        else: style['starts_with_prose'] += 1
        if re.search(r'\$\s+\w|npm install|pip install|git clone|cd\s', body): cmd_docs += 1
        if re.search(r'[\U0001F300-\U0001FAFF\u2600-\u27BF]', body): emoji_docs += 1
out['doc_style'] = {'n_docs': n_doc,
    'opening_structure': {k: round(v / max(n_doc, 1), 3) for k, v in style.items()},
    'shell_command_doc_pct': round(cmd_docs / max(n_doc, 1), 3),
    'emoji_doc_pct': round(emoji_docs / max(n_doc, 1), 3),
    'note': '正文首段结构与命令/emoji密度（面板仓文档）'}

# ========== 3. fork 改名率 ==========
print("3. fork rename rate...", flush=True)
rename = kept = 0
for nmf in ('fork_prs.jsonl', 'fork_prs_retry1.jsonl', 'fork_prs_retry2.jsonl'):
    for line in open(os.path.join(COL, nmf), encoding='utf-8'):
        r = json.loads(line)
        if r.get('type') != 'parent' or not r.get('complete'): continue
        pshort = r['parent'].split('/')[1].lower()
        for l in r.get('links', []):
            if l.get('matched_by') == 'head_repo' and l.get('fork'):
                hshort = l['fork'].split('/')[1].lower()
                # fork 默认同名；改名=短名不同
                if hshort == pshort: kept += 1
                else: rename += 1
out['fork_rename'] = {'kept_same_name': kept, 'renamed': rename,
    'rename_rate': round(rename / max(kept + rename, 1), 3),
    'note': '回流 fork 的仓名保留率（fork 默认同名，改名=有意区分）'}

# ========== 4. 双平台 vs 单平台的星标差 ==========
print("4. dual vs single platform...", flush=True)
dual = [gdm[rp].get('stars') or 0 for rp in gdm if sh_hit.get(rp) and ch_hit.get(rp)]
only_sh = [gdm[rp].get('stars') or 0 for rp in gdm if sh_hit.get(rp) and not ch_hit.get(rp)]
if dual and only_sh:
    u, p = mannwhitneyu(dual, only_sh)
    out['dual_vs_single'] = {'n_dual': len(dual), 'n_only_sh': len(only_sh),
        'median_stars_dual': int(np.median(dual)), 'median_stars_only_sh': int(np.median(only_sh)),
        'mwu_p': round(float(p), 4),
        'note': '双平台收录仓与仅skills.sh收录仓的星标差'}
else:
    out['dual_vs_single'] = {'n_dual': len(dual), 'n_only_sh': len(only_sh)}

# ========== 5. 文档名长度与结果 ==========
print("5. name length economics...", flush=True)
nm_len_star = []
with open(os.path.join(ROOT, 'external_data', 'skills_with_content.jsonl'), encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        rp = r.get('repoFullName')
        if rp not in gdm: continue
        nm = (r.get('name') or '').strip()
        if nm and rp not in [x[1] for x in nm_len_star[-1:]] if nm_len_star else True:
            nm_len_star.append((len(nm), gdm[rp].get('stars') or 0))
# 去重仓级：每仓取首文档名长
seen = set(); nl = []
with open(os.path.join(ROOT, 'external_data', 'skills_with_content.jsonl'), encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        rp = r.get('repoFullName')
        if rp in seen or rp not in gdm: continue
        nm = (r.get('name') or '').strip()
        if nm:
            seen.add(rp); nl.append((len(nm), gdm[rp].get('stars') or 0, sh_inst.get(rp, 0)))
if len(nl) > 50:
    lens = [x[0] for x in nl]; stars = [x[1] for x in nl]; inst = [x[2] for x in nl]
    r1 = spearmanr(lens, stars); r2 = spearmanr(lens, inst)
    out['name_length'] = {'n_repos': len(nl), 'median_len': int(np.median(lens)),
        'len_to_stars_rho': round(float(r1.statistic), 3), 'len_to_stars_p': round(float(r1.pvalue), 4),
        'len_to_installs_rho': round(float(r2.statistic), 3),
        'note': '每仓首文档名长度→星标/安装'}

# ========== 6. ClawHub slug 前缀品牌化 ==========
print("6. slug branding...", flush=True)
pref = collections.Counter()
n_slug = 0
for line in open(os.path.join(COL, 'market_full.jsonl'), encoding='utf-8'):
    r = json.loads(line)
    if r.get('type') == 'clawhub_registry':
        s = (r.get('item') or {}).get('slug') or ''
        if s:
            n_slug += 1
            head = s.split('--')[0] if '--' in s else s
            pref[head[:12]] += 1
out['slug_prefix'] = {'n_slugs': n_slug, 'top_prefixes': pref.most_common(10),
    'note': 'ClawHub slug 首段前缀——平台品牌化命名'}

# ========== 7. star 周序列自相关（滞后1-4周）==========
print("7. star autocorrelation...", flush=True)
ac = collections.defaultdict(list)
for rp, rows in sh2.items():
    rows = sorted(rows, key=lambda w: w['week'])
    wk = [w['total'] for w in rows]
    if len(wk) < 20 or sum(wk) < 20: continue
    for lag in (1, 2, 4):
        a = np.array(wk[:-lag]); b = np.array(wk[lag:])
        if a.std() > 0 and b.std() > 0:
            r_ = spearmanr(a, b).statistic
            if not np.isnan(r_): ac[lag].append(r_)
out['star_autocorr'] = {f'lag{lag}_weeks_median_rho': round(float(np.median(v)), 3)
    for lag, v in sorted(ac.items()) if len(v) >= 30},
out['star_autocorr_n'] = {f'lag{lag}': len(v) for lag, v in sorted(ac.items())}

# ========== 8. 复制簇的星标跨度 ==========
print("8. cluster star span...", flush=True)
sha_star = collections.defaultdict(list)
with open(os.path.join(ROOT, 'external_data', 'skills_with_content.jsonl'), encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        h = r.get('sha256_hash'); rp = r.get('repoFullName')
        if h and rp in gdm:
            sha_star[h].append(gdm[rp].get('stars') or 0)
spans = []
for h, ss in sha_star.items():
    if len(ss) >= 3:
        spans.append(max(ss) - min(ss))
if spans:
    spa = np.array(spans)
    out['cluster_star_span'] = {'n_hashes_ge3': len(spans),
        'median_span': int(np.median(spa)), 'p90_span': int(np.percentile(spa, 90)),
        'pct_zero_span': round(float(np.mean(spa == 0)), 3),
        'note': '同SHA≥3仓的星标跨度（同内容在注意力上的离散度）'}

# ========== 9. frontmatter 与正文的 meta 一致性 ==========
print("9. fm-body consistency...", flush=True)
name_match = 0; name_mismatch = 0
with open(os.path.join(ROOT, 'external_data', 'skills_with_content.jsonl'), encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        rp = r.get('repoFullName')
        if rp not in gdm: continue
        c = r.get('full_content') or ''
        m = FM.match(c.strip('\ufeff \n'))
        if not m: continue
        fmnm = ''
        dm = re.search(r'^name\s*:\s*(.+)$', m.group(1), re.M)
        if dm: fmnm = dm.group(1).strip().strip('"\'').lower()
        # 正文首个标题
        hm = re.search(r'^#\s+(.+)$', re.sub(r'^---.*?---', '', c, flags=re.S), re.M)
        if hm and fmnm:
            h1 = hm.group(1).strip().lower()
            if fmnm[:10] and (fmnm[:10] in h1 or h1[:10] in fmnm): name_match += 1
            else: name_mismatch += 1
out['fm_body_name'] = {'name_vs_h1_match': name_match, 'mismatch': name_mismatch,
    'match_rate': round(name_match / max(name_match + name_mismatch, 1), 3),
    'note': 'frontmatter name 与正文首个 H1 的一致率'}

json.dump(out, open(os.path.join(ROOT, 'data', 'results', 'deep7_20261025.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1, default=str)
print("\n=== SUMMARY ===")
for k, v in out.items():
    print(f"--- {k} ---")
    print(json.dumps(v, ensure_ascii=False, indent=1)[:650])
print("ALL DONE")
