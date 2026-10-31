# -*- coding: utf-8 -*-
"""mine_deep3.py — 第三轮深挖（2026-10-25）：七项新分析
A 内容质量信号→结果（字段完整度×安装/星标/存活）
B fork-星标日级共时性（爆发日重叠）
C PR 贡献者集中度（平行于合并权垄断）
D 复制社区成员→存活率（巨社区 vs 小社区 vs 孤立仓）
E 复制中名称变更的方向（变短？变泛化？）
F 多渠道可见性预测（3+渠道 vs 1-2渠道）
G 冷启动时间（创建→首次星标/fork）
H fork→PR 转化率的仓级预测因子
"""
import json, os, re, collections, datetime, random
import numpy as np
from scipy.stats import mannwhitneyu, spearmanr, chi2_contingency
import statsmodels.api as sm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COL = os.path.join(ROOT, 'external_data', 'collected_20261024')
TMP = r'E:\temp\opencode'
REF = datetime.datetime(2026, 10, 24, tzinfo=datetime.timezone.utc)
out = {}

# ---------- 公共加载 ----------
FM = re.compile(r"^---\s*\n(.*?)\n---", re.S)
gdm = json.load(open(os.path.join(ROOT, 'data', 'repos_meta.json'), encoding='utf-8'))
lm_stars = {}
for line in open(os.path.join(COL, 'local_mining.jsonl'), encoding='utf-8'):
    r = json.loads(line)
    if r.get('type') == 'repo':
        lm_stars[r['repo']] = (r.get('stars') or 0, r.get('n_skills') or 0, r.get('share_cross') or 0)

sh2 = json.load(open(os.path.join(TMP, 'star_history_v2.json'), encoding='utf-8'))
ft = json.load(open(os.path.join(ROOT, 'data', 'forks_timestamps.json'), encoding='utf-8'))

# skills.sh 数据
sh_hit = {}; sh_inst = {}
for nmf in ('market_full.jsonl', 'market_retry.jsonl'):
    for line in open(os.path.join(COL, nmf), encoding='utf-8'):
        r = json.loads(line)
        if r.get('type') == 'skills_sh':
            sh_hit[r['repo']] = 1 if (r.get('n_hits') or 0) > 0 else 0
            if sh_hit[r['repo']]:
                sh_inst[r['repo']] = r.get('total_installs') or 0

# ClawHub search
ch_hit = {}
for line in open(os.path.join(COL, 'market_full.jsonl'), encoding='utf-8'):
    r = json.loads(line)
    if r.get('type') == 'clawhub_search':
        ch_hit[r['repo']] = 1 if (r.get('n_hits') or 0) > 0 else 0

# npm
npm = {}
for line in open(os.path.join(COL, 'npm_downloads.jsonl'), encoding='utf-8'):
    r = json.loads(line)
    if r.get('type') == 'repo':
        npm[r['repo']] = 1 if r['npm']['status'] == 'matched' else 0

# release
rel = {}
for line in open(os.path.join(COL, 'release_downloads.jsonl'), encoding='utf-8'):
    r = json.loads(line)
    if r.get('type') == 'repo':
        rel[r['repo']] = 1 if ((r.get('github') or {}).get('downloads') or 0) > 0 else 0

# 复制社区（用 sha 网络的连通分量标签——简化：用 local_mining 的 share_cross 是否>0 分组）
# 更精确：重建网络并取社区——但为速度用简版：share_cross>0 = 在复制网络中

# ---------- A) 内容质量信号→结果 ----------
# 对 341 面板仓：frontmatter 字段数（proxy for completeness）→ installs, stars, survival
repo_fields = collections.defaultdict(lambda: {'n': 0, 'total_fields': 0, 'has_desc': 0, 'has_tools': 0, 'desc_len': []})
with open(os.path.join(ROOT, 'external_data', 'skills_with_content.jsonl'), encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        rp = r.get('repoFullName')
        if rp not in gdm:
            continue
        c = r.get('full_content') or ''
        m = FM.match(c.strip('\ufeff \n'))
        if m:
            keys = set()
            for ln in m.group(1).splitlines():
                if ':' in ln:
                    k = ln.split(':', 1)[0].strip().lower()
                    keys.add(k)
            d = repo_fields[rp]
            d['n'] += 1
            d['total_fields'] += len(keys)
            if 'description' in keys:
                d['has_desc'] += 1
            if 'allowed-tools' in keys or 'allowed_tools' in keys:
                d['has_tools'] += 1
            # 提取描述长度
            dm = re.search(r'description:\s*(.+)', m.group(1))
            if dm:
                d['desc_len'].append(len(dm.group(1).strip()))
        else:
            repo_fields[rp]['n'] += 1

rows_a = []
for rp, d in repo_fields.items():
    if d['n'] == 0 or rp not in gdm:
        continue
    avg_fields = d['total_fields'] / d['n']
    desc_rate = d['has_desc'] / d['n']
    avg_desc_len = np.mean(d['desc_len']) if d['desc_len'] else 0
    stars = gdm[rp].get('stars') or 0
    installed = sh_inst.get(rp, 0)
    hit = sh_hit.get(rp, 0)
    # 存活
    pu = gdm[rp].get('pushed_at')
    active = 1 if pu and (REF - datetime.datetime.fromisoformat(pu.replace('Z', '+00:00'))).days <= 30 else 0
    rows_a.append((avg_fields, desc_rate, avg_desc_len, np.log10(stars + 1), np.log10(installed + 1), hit, active, rp))

arr = np.array([(r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in rows_a])
# 字段完整度→安装（在有命中的子集）
mask_hit = arr[:, 5] == 1
if mask_hit.sum() > 20:
    rho1, p1 = spearmanr(arr[mask_hit, 0], arr[mask_hit, 4])
    rho2, p2 = spearmanr(arr[mask_hit, 1], arr[mask_hit, 4])
else:
    rho1 = rho2 = p1 = p2 = None
# 字段完整度→星标
rho3, p3 = spearmanr(arr[:, 0], arr[:, 3])
# 字段完整度→存活
rho4, p4 = spearmanr(arr[:, 0], arr[:, 6])
# desc_len→安装
if mask_hit.sum() > 20:
    rho5, p5 = spearmanr(arr[mask_hit, 2], arr[mask_hit, 4])
else:
    rho5 = p5 = None

out['A_quality_signals'] = {
    'n_repos': len(rows_a),
    'avg_fields_range': [round(float(np.percentile(arr[:, 0], 10)), 1), round(float(np.percentile(arr[:, 0], 90)), 1)],
    'fields_to_installs_rho': round(float(rho1), 3) if rho1 else None,
    'desc_rate_to_installs_rho': round(float(rho2), 3) if rho2 else None,
    'fields_to_stars_rho': round(float(rho3), 3),
    'fields_to_survival_rho': round(float(rho4), 3),
    'desc_len_to_installs_rho': round(float(rho5), 3) if rho5 else None,
    'note': '字段完整度=frontmatter平均字段数；安装取log10；命中子集内的相关'
}

# ---------- B) fork-星标日级共时性 ----------
star_daily = collections.Counter()
fork_daily = collections.Counter()
for rp, rows in sh2.items():
    for w in rows:
        wt = datetime.datetime.fromtimestamp(w['week'], tz=datetime.timezone.utc)
        for i, dn in enumerate(w['days']):
            if dn:
                star_daily[(wt + datetime.timedelta(days=i)).strftime('%Y-%m-%d')] += dn
for rp, forks in ft.items():
    if (gdm.get(rp, {}).get('forks') or 0) > 500:
        continue
    for f in forks:
        if f.get('created_at'):
            fork_daily[f['created_at'][:10]] += 1
# 找共同的日级序列（取两序列都有值的日期）
common = sorted(set(star_daily) & set(fork_daily))
if len(common) > 30:
    sv = np.array([star_daily[d] for d in common])
    fv = np.array([fork_daily[d] for d in common])
    rho_b, p_b = spearmanr(sv, fv)
    # 日级增量相关（差分）
    ds = np.diff(sv); df = np.diff(fv)
    rho_bd, p_bd = spearmanr(ds, df)
    # 爆发日重叠：star top 20 天中有多少也是 fork top 20 天
    star_top = set(sorted(common, key=lambda d: -star_daily[d])[:20])
    fork_top = set(sorted(common, key=lambda d: -fork_daily[d])[:20])
    overlap = len(star_top & fork_top)
    # 期望重叠（超几何）
    from scipy.stats import hypergeom
    p_overlap = hypergeom.pmf(overlap, len(common), 20, 20)
else:
    rho_b = p_b = rho_bd = p_bd = overlap = p_overlap = None

out['B_fork_star_daily'] = {
    'n_common_days': len(common),
    'level_rho': round(float(rho_b), 3) if rho_b else None,
    'level_p': float(p_b) if p_b else None,
    'diff_rho': round(float(rho_bd), 3) if rho_bd else None,
    'diff_p': float(p_bd) if p_bd else None,
    'top20_overlap': overlap,
    'top20_expected': 20 * 20 / len(common) if len(common) else None,
    'hypergeom_p': float(p_overlap) if p_overlap else None
}

# ---------- C) PR 贡献者集中度 ----------
pr_author = collections.defaultdict(collections.Counter)
for nmf in ('pr_merged.jsonl', 'pr_merged_retry.jsonl', 'pr_merged_retry3.jsonl'):
    for line in open(os.path.join(COL, nmf), encoding='utf-8'):
        r = json.loads(line)
        if r.get('type') != 'repo' or not r.get('complete'):
            continue
        for pr in r.get('pulls', []):
            u = pr.get('user')
            if u:
                pr_author[r['repo']][u] += 1

author_shares = []
top_authors = collections.Counter()
for rp, ac in pr_author.items():
    tot = sum(ac.values())
    if tot >= 10:
        top_share = ac.most_common(1)[0][1] / tot
        author_shares.append(top_share)
        top_authors[ac.most_common(1)[0][0]] += ac.most_common(1)[0][1]
out['C_contributor_concentration'] = {
    'n_repos_ge10': len(author_shares),
    'median_top_author_share': round(float(np.median(author_shares)), 3) if author_shares else None,
    'mean_top_author_share': round(float(np.mean(author_shares)), 3) if author_shares else None,
    'top5_cross_repo_authors': top_authors.most_common(5),
    'note': '跨仓头部贡献者按其在各仓内的PR数合计'
}

# ---------- D) 复制社区成员→存活 ----------
# 用 share_cross 是否>0 作为"在复制网络中"的代理
in_copy = {}; no_copy = {}
for rp, (st, ns, sc) in lm_stars.items():
    if ns < 3:
        continue
    pu = gdm.get(rp, {}).get('pushed_at')
    if not pu:
        continue
    active = 1 if (REF - datetime.datetime.fromisoformat(pu.replace('Z', '+00:00'))).days <= 30 else 0
    if sc > 0.1:
        in_copy[rp] = (active, st)
    else:
        no_copy[rp] = (active, st)
act_copy = np.mean([v[0] for v in in_copy.values()]) if in_copy else None
act_nocopy = np.mean([v[0] for v in no_copy.values()]) if no_copy else None
u_d, p_d = mannwhitneyu([v[0] for v in in_copy.values()], [v[0] for v in no_copy.values()]) if len(in_copy) > 5 and len(no_copy) > 5 else (None, None)
star_copy = np.median([v[1] for v in in_copy.values()]) if in_copy else None
star_nocopy = np.median([v[1] for v in no_copy.values()]) if no_copy else None
out['D_copy_community_survival'] = {
    'n_in_copy': len(in_copy), 'n_no_copy': len(no_copy),
    'active_rate_in_copy': round(float(act_copy), 3) if act_copy else None,
    'active_rate_no_copy': round(float(act_nocopy), 3) if act_nocopy else None,
    'mwu_p': round(float(p_d), 4) if p_d else None,
    'median_stars_in_copy': int(star_copy) if star_copy else None,
    'median_stars_no_copy': int(star_nocopy) if star_nocopy else None
}

# ---------- E) 复制中名称变更的方向 ----------
pairs = []
for line in open(os.path.join(COL, 'near_duplicates.jsonl'), encoding='utf-8'):
    r = json.loads(line)
    if r.get('type') == 'pair' and not r.get('same_repo'):
        pairs.append(r)
random.seed(20261025)
samp = random.sample(pairs, min(3000, len(pairs)))
want = set()
for p in samp:
    want.add(p['a']['id']); want.add(p['b']['id'])
docs = {}
with open(os.path.join(ROOT, 'external_data', 'skills_with_content.jsonl'), encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        if r.get('id') in want:
            c = r.get('full_content') or ''
            m = FM.match(c.strip('\ufeff \n'))
            nm = r.get('name') or ''
            if m:
                dm = re.search(r'name:\s*(.+)', m.group(1))
                if dm:
                    nm = dm.group(1).strip()
            docs[r['id']] = nm
shorter = longer = same_len = total_changed = 0
generic_words = {'skill', 'tool', 'helper', 'agent', 'ai', 'assistant', 'master', 'pro', 'ultra', 'max'}
more_generic = less_generic = same_generic = 0
for p in samp:
    na, nb = docs.get(p['a']['id'], ''), docs.get(p['b']['id'], '')
    if not na or not nb or na == nb:
        continue
    total_changed += 1
    if len(nb) < len(na):
        shorter += 1
    elif len(nb) > len(na):
        longer += 1
    else:
        same_len += 1
    ga = sum(1 for w in generic_words if w in na.lower())
    gb = sum(1 for w in generic_words if w in nb.lower())
    if gb > ga:
        more_generic += 1
    elif gb < ga:
        less_generic += 1
    else:
        same_generic += 1
out['E_name_evolution'] = {
    'n_changed': total_changed,
    'shorter_pct': round(100 * shorter / total_changed, 1) if total_changed else None,
    'longer_pct': round(100 * longer / total_changed, 1) if total_changed else None,
    'more_generic_pct': round(100 * more_generic / total_changed, 1) if total_changed else None,
    'note': '方向以 b 相对 a 判定（b 为复制体或修改体）；泛化词表含 skill/tool/helper 等'
}

# ---------- F) 多渠道可见性预测 ----------
rows_f = []
for rp in gdm:
    channels = sum([1 if sh_hit.get(rp) else 0, 1 if ch_hit.get(rp) else 0,
                    1 if rel.get(rp) else 0, 1 if npm.get(rp) else 0])
    m = gdm[rp]
    created = m.get('created_at') or ''
    if not created:
        continue
    age_months = (REF - datetime.datetime.fromisoformat(created.replace('Z', '+00:00'))).days / 30
    is_awesome = 1 if 'awesome' in rp.lower() else 0
    ns, sc = lm_stars.get(rp, (0, 0, 0))[1], lm_stars.get(rp, (0, 0, 0))[2]
    rows_f.append((channels, np.log10((m.get('stars') or 0) + 1), age_months, is_awesome, ns >= 3, rp))

y_f = np.array([1 if r[0] >= 3 else 0 for r in rows_f])
X_f = np.array([[r[1], r[2], r[3]] for r in rows_f])
X_f = sm.add_constant(X_f)
try:
    res_f = sm.Logit(y_f, X_f).fit(disp=0)
    ci_f = res_f.conf_int()
    out['F_multichannel'] = {
        'n': len(y_f), 'pct_3plus': round(float(y_f.mean()), 3),
        'logstars_coef': round(float(res_f.params[1]), 3),
        'logstars_CI': [round(float(ci_f[0][1]), 3), round(float(ci_f[1][1]), 3)],
        'logstars_p': round(float(res_f.pvalues[1]), 4),
        'age_p': round(float(res_f.pvalues[2]), 4),
        'awesome_coef': round(float(res_f.params[3]), 3),
        'awesome_p': round(float(res_f.pvalues[3]), 4)
    }
except Exception as e:
    out['F_multichannel'] = {'error': str(e)[:100]}

# ---------- G) 冷启动时间 ----------
cold_star = []; cold_fork = []
for rp, rows in sh2.items():
    if not rows:
        continue
    rows = sorted(rows, key=lambda w: w['week'])
    created = gdm.get(rp, {}).get('created_at')
    if not created:
        continue
    cd = datetime.datetime.fromisoformat(created.replace('Z', '+00:00'))
    # 首次星标：第一个 total>0 的周
    for w in rows:
        if w['total'] > 0:
            wt = datetime.datetime.fromtimestamp(w['week'], tz=datetime.timezone.utc)
            cold_star.append(max(0, (wt - cd).days))
            break
    forks = ft.get(rp, [])
    if forks and (gdm.get(rp, {}).get('forks') or 0) <= 500:
        first_f = min(f['created_at'] for f in forks if f.get('created_at'))
        fd = datetime.datetime.fromisoformat(first_f.replace('Z', '+00:00'))
        cold_fork.append(max(0, (fd - cd).days))

out['G_cold_start'] = {
    'n_star': len(cold_star),
    'star_median_days': int(np.median(cold_star)) if cold_star else None,
    'star_pct_sameday': round(float(np.mean([d == 0 for d in cold_star])), 3) if cold_star else None,
    'star_pct_within_week': round(float(np.mean([d <= 7 for d in cold_star])), 3) if cold_star else None,
    'n_fork': len(cold_fork),
    'fork_median_days': int(np.median(cold_fork)) if cold_fork else None,
    'fork_pct_sameday': round(float(np.mean([d == 0 for d in cold_fork])), 3) if cold_fork else None,
    'note': '面板仓创建→首次星标/fork 的天数；fork≤500 仓'
}

# ---------- H) fork→PR 转化率的仓级预测因子 ----------
conv_data = []
for nmf in ('fork_prs.jsonl', 'fork_prs_retry1.jsonl', 'fork_prs_retry2.jsonl'):
    for line in open(os.path.join(COL, nmf), encoding='utf-8'):
        r = json.loads(line)
        if r.get('type') == 'parent' and r.get('complete') and r.get('n_forks', 0) > 50:
            rp = r['parent']
            head = sum(1 for l in r.get('links', []) if l.get('matched_by') == 'head_repo')
            conv = head / r['n_forks']
            stars_p = gdm.get(rp, {}).get('stars') or 0
            created_p = gdm.get(rp, {}).get('created_at') or ''
            age_m = (REF - datetime.datetime.fromisoformat(created_p.replace('Z', '+00:00'))).days / 30 if created_p else 18
            is_official = 1 if any(k in rp.lower() for k in ['anthropic', 'google/', 'microsoft/', 'github/']) else 0
            conv_data.append((conv, np.log10(stars_p + 1), age_m, is_official, rp))

if len(conv_data) > 20:
    y_h = np.array([r[0] for r in conv_data])
    X_h = sm.add_constant(np.array([[r[1], r[2], r[3]] for r in conv_data]))
    try:
        res_h = sm.OLS(y_h, X_h).fit()
        out['H_conversion_predictors'] = {
            'n_parents': len(conv_data),
            'r_squared': round(float(res_h.rsquared), 3),
            'logstars_coef': round(float(res_h.params[1]), 4),
            'logstars_p': round(float(res_h.pvalues[1]), 4),
            'age_coef': round(float(res_h.params[2]), 4),
            'age_p': round(float(res_h.pvalues[2]), 4),
            'official_coef': round(float(res_h.params[3]), 4),
            'official_p': round(float(res_h.pvalues[3]), 4)
        }
    except Exception as e:
        out['H_conversion_predictors'] = {'error': str(e)[:100], 'n': len(conv_data)}
else:
    out['H_conversion_predictors'] = {'n': len(conv_data), 'note': '样本不足'}

# 保存
json.dump(out, open(os.path.join(ROOT, 'data', 'results', 'newfindings3_20261025.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
