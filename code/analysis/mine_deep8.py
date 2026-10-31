# -*- coding: utf-8 -*-
"""mine_deep8.py — 第八轮（2026-10-25）：四种新技术
1. DBSCAN 密度聚类：五渠道+星标+复制空间的异常群与核心群（替代 KMeans 的球形假设）
2. 互信息分析：离散化后各特征与结果的互信息（非单调关系也能捕捉）
3. 梯度提升重要度+部分依赖：安装量的非线性预测结构
4. 社区演化：复制网络两巨社区在时间上的成员增长曲线
5. 文本可读性：SKILL.md 正文的句长/段落长分布（Flesch 式简化指标）
6. 双序列 DTW 简化版：星标曲线与 fork 曲线的形态对齐（不要求时间点对齐）
7. 富集分析：高复制仓的特征富集（相对全体的超几何）
8. 词向量最近邻（PMI-PPMI 截断SVD）：技能描述的词聚类
"""
import json, os, re, collections, datetime, random
import numpy as np
from scipy.stats import hypergeom, spearmanr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COL = os.path.join(ROOT, 'external_data', 'collected_20261024')
TMP = r'E:\temp\opencode'
REF = datetime.datetime(2026, 10, 24, tzinfo=datetime.timezone.utc)
out = {}

print("loading...", flush=True)
gdm = json.load(open(os.path.join(ROOT, 'data', 'repos_meta.json'), encoding='utf-8'))
sh2 = json.load(open(os.path.join(TMP, 'star_history_v2.json'), encoding='utf-8'))
ft = json.load(open(os.path.join(ROOT, 'data', 'forks_timestamps.json'), encoding='utf-8'))
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
npm_hit = {}
for line in open(os.path.join(COL, 'npm_downloads.jsonl'), encoding='utf-8'):
    r = json.loads(line)
    if r.get('type') == 'repo':
        npm_hit[r['repo']] = 1 if r['npm']['status'] == 'matched' else 0
rel_hit = {}
for line in open(os.path.join(COL, 'release_downloads.jsonl'), encoding='utf-8'):
    r = json.loads(line)
    if r.get('type') == 'repo':
        rel_hit[r['repo']] = 1 if ((r.get('github') or {}).get('downloads') or 0) > 0 else 0

# ========== 1. DBSCAN 密度聚类 ==========
print("1. DBSCAN...", flush=True)
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import RobustScaler
rows = []; rps = []
for rp in gdm:
    if rp not in lm: continue
    m = gdm[rp]
    age = (REF - datetime.datetime.fromisoformat((m.get('created_at') or '2026-01-01').replace('Z', '+00:00'))).days / 30
    rows.append([np.log10((m.get('stars') or 0) + 1), np.log10((sh_inst.get(rp, 0)) + 1),
                 lm[rp]['share_cross'], np.log10((m.get('forks') or 0) + 1), age])
    rps.append(rp)
X = RobustScaler().fit_transform(np.array(rows))
db = DBSCAN(eps=0.9, min_samples=8).fit(X)
lab = collections.Counter(db.labels_)
groups = {}
for k, n in lab.most_common():
    idx = np.where(db.labels_ == k)[0]
    med = lambda arr: int(np.median([rows[i][arr] for i in idx])) if len(idx) else None
    groups[f'cluster_{k}'] = {'n': int(n),
        'median_log_stars': med(0), 'median_log_inst': med(1),
        'median_share_cross': round(float(np.median([rows[i][2] for i in idx])), 3),
        'example': rps[idx[0]] if len(idx) else None}
out['dbscan'] = {'n_clusters': len([k for k in lab if k != -1]), 'n_noise': lab.get(-1, 0), 'groups': groups,
    'note': 'DBSCAN eps=0.9 minPts=8 于 RobustScaler 后的5维空间（星/装/复制/ fork/年龄）'}

# ========== 2. 互信息 ==========
print("2. mutual information...", flush=True)
from sklearn.metrics import mutual_info_score
def disc(v, q=4):
    qs = np.quantile(v, [i / q for i in range(1, q)])
    return np.digitize(v, qs)
# 特征：星标分层/复制饱和/技能数/年龄；结果：平台命中
feats = {'star_tier': [], 'share_cross_q': [], 'n_skills_q': [], 'age_q': [], 'hit': [], 'hit_ch': []}
rps_m = []
for rp in gdm:
    if rp not in lm: continue
    m = gdm[rp]
    age = (REF - datetime.datetime.fromisoformat((m.get('created_at') or '2026-01-01').replace('Z', '+00:00'))).days / 30
    feats['star_tier'].append((m.get('stars') or 0))
    feats['share_cross_q'].append(lm[rp]['share_cross'])
    feats['n_skills_q'].append(lm[rp]['n_skills'])
    feats['age_q'].append(age)
    feats['hit'].append(sh_hit.get(rp, 0))
    feats['hit_ch'].append(ch_hit.get(rp, 0))
    rps_m.append(rp)
mi_out = {}
for f in ['star_tier', 'share_cross_q', 'n_skills_q', 'age_q']:
    a = disc(np.array(feats[f], dtype=float))
    h_s = mutual_info_score(a, np.array(feats['hit']))
    h_c = mutual_info_score(a, np.array(feats['hit_ch']))
    # 归一化（除以熵）
    Hs = mutual_info_score(a, a)
    mi_out[f] = {'MI_to_skillssh': round(float(h_s / Hs), 3) if Hs else 0,
                 'MI_to_clawhub': round(float(h_c / Hs), 3) if Hs else 0}
out['mutual_info'] = {'normalized_MI': mi_out,
    'note': '四分位离散化后的归一化互信息（0=无关，1=完全决定）'}

# ========== 3. 梯度提升重要度 + 部分依赖 ==========
print("3. gradient boosting importance...", flush=True)
from sklearn.ensemble import HistGradientBoostingRegressor
rows3 = []; y3 = []
for rp in sh_inst:
    if rp not in lm: continue
    m = gdm[rp]
    age = (REF - datetime.datetime.fromisoformat((m.get('created_at') or '2026-01-01').replace('Z', '+00:00'))).days / 30
    rows3.append([np.log10((m.get('stars') or 0) + 1), lm[rp]['share_cross'], lm[rp]['n_skills'],
                  np.log10((m.get('forks') or 0) + 1), age, ch_hit.get(rp, 0)])
    y3.append(np.log10(sh_inst[rp] + 1))
if len(rows3) > 50:
    X3 = np.array(rows3); y3 = np.array(y3)
    gb = HistGradientBoostingRegressor(max_iter=200, random_state=25).fit(X3, y3)
    # 置换重要度
    rng = np.random.default_rng(25)
    base = gb.score(X3, y3)
    imps = []
    for j in range(X3.shape[1]):
        Xp = X3.copy(); rng.shuffle(Xp[:, j])
        imps.append(base - gb.score(Xp, y3))
    fn = ['log_stars', 'share_cross', 'n_skills', 'log_forks', 'age', 'clawhub']
    order = np.argsort(-np.array(imps))
    # 部分依赖：share_cross 的 PDP（手算网格）
    grid = np.linspace(0, 1, 6)
    pd_vals = []
    for g in grid:
        Xp = X3.copy(); Xp[:, 1] = g
        pd_vals.append(round(float(gb.predict(Xp).mean()), 3))
    out['gb_importance'] = {'n': len(y3), 'r2': round(float(base), 3),
        'importance_order': [(fn[j], round(float(imps[j]), 4)) for j in order],
        'pdp_share_cross': [{'share_cross': round(float(g), 2), 'pred_log_inst': v} for g, v in zip(grid, pd_vals)],
        'note': '梯度提升 R² 与置换重要度；PDP 显示复制饱和度的非线性效应'}

# ========== 4. 社区演化：两巨社区的月度成员增长 ==========
print("4. community growth...", flush=True)
import networkx as nx, networkx.algorithms.community as nxcom
sha_repos = collections.defaultdict(set)
# 用 SHA→repos（重流 SWC 一次，仅取必要字段）
with open(os.path.join(ROOT, 'external_data', 'skills_with_content.jsonl'), encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        h = r.get('sha256_hash'); rp = r.get('repoFullName')
        if h: sha_repos[h].add(rp)
G = nx.Graph()
for h, rs in sha_repos.items():
    if len(rs) >= 2:
        rl = sorted(rs)
        for i in range(len(rl) - 1):
            for j in range(i + 1, min(i + 6, len(rl))):
                G.add_edge(rl[i], rl[j], w=1)
com = sorted(nxcom.greedy_modularity_communities(G, weight='w'), key=len, reverse=True)
growth = []
for ci, c0 in enumerate(com[:2]):
    mem_created = sorted([gdm.get(m, {}).get('created_at', '')[:7] for m in c0 if gdm.get(m, {}).get('created_at')])
    bym = collections.Counter(mem_created)
    cum = 0; curve = []
    for m in sorted(bym):
        cum += bym[m]; curve.append((m, cum))
    growth.append({'community': ci + 1, 'size': len(c0), 'first_member': curve[0] if curve else None,
                   'growth_by_month': curve[-12:]})
out['community_growth'] = growth

# ========== 5. 文本可读性 ==========
print("5. readability...", flush=True)
sent_lens = []; para_lens = []
with open(os.path.join(ROOT, 'external_data', 'skills_with_content.jsonl'), encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        if r.get('repoFullName') not in gdm: continue
        c = r.get('full_content') or ''
        body = re.sub(r'^---.*?---', '', c.strip(), flags=re.S)
        # 去代码块
        body = re.sub(r'```.*?```', '', body, flags=re.S)
        paras = [p for p in body.split('\n\n') if len(p.strip()) > 40]
        for p in paras[:3]:
            sents = re.split(r'[.!?。！？]', p)
            for s in sents:
                w = len(s.split())
                if 3 < w < 100: sent_lens.append(w)
        para_lens.extend([len(p.split()) for p in paras[:3]])
if sent_lens:
    out['readability'] = {'n_sents': len(sent_lens), 'median_sentence_words': int(np.median(sent_lens)),
        'p90_sentence_words': int(np.percentile(sent_lens, 90)),
        'median_para_words': int(np.median(para_lens)),
        'note': '去代码块后的句长/段长分布（简化可读性指标）'}

# ========== 6. 形态对齐（简化 DTW：最优点对距离）==========
print("6. shape alignment...", flush=True)
from scipy.spatial.distance import cdist
def norm_series(v):
    v = np.array(v, dtype=float)
    s = v.sum()
    return v / s if s > 0 else v
def dtw_dist(a, b):
    a, b = norm_series(a), norm_series(b)
    D = cdist(a.reshape(-1, 1), b.reshape(-1, 1), 'euclidean')
    n, m = len(a), len(b)
    acc = np.full((n + 1, m + 1), np.inf); acc[0, 0] = 0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            acc[i, j] = D[i - 1, j - 1] + min(acc[i - 1, j], acc[i, j - 1], acc[i - 1, j - 1])
    return acc[n, m] / (n + m)
pairs_shape = []
rps_s = [rp for rp in sh2 if len(sh2[rp]) >= 12]
random.seed(25)
sample_rps = random.sample(rps_s, min(60, len(rps_s)))
# 用月度聚合的星标曲线 vs 分叉曲线（可对齐不同长度）
for rp in sample_rps:
    rows = sorted(sh2[rp], key=lambda w: w['week'])
    sw = [w['total'] for w in rows]
    forks = ft.get(rp, [])
    if not forks or (gdm.get(rp, {}).get('forks') or 0) > 500: continue
    fmon = collections.Counter(f['created_at'][:7] for f in forks if f.get('created_at'))
    smon = collections.Counter()
    for w in rows:
        wt = datetime.datetime.fromtimestamp(w['week'], tz=datetime.timezone.utc)
        smon[wt.strftime('%Y-%m')] += w['total']
    months = sorted(set(smon) | set(fmon))
    sv = [smon.get(m, 0) for m in months]; fv = [fmon.get(m, 0) for m in months]
    if sum(sv) > 10 and sum(fv) > 3:
        pairs_shape.append(dtw_dist(sv, fv))
if pairs_shape:
    pa = np.array(pairs_shape)
    # 基线：随机两条星标曲线的 DTW
    base = []
    for _ in range(60):
        a, b = random.sample(sample_rps, 2)
        sa = sorted(sh2[a], key=lambda w: w['week']); sb = sorted(sh2[b], key=lambda w: w['week'])
        va = [w['total'] for w in sa]; vb = [w['total'] for w in sb]
        if sum(va) > 10 and sum(vb) > 10:
            L = min(len(va), len(vb))
            base.append(dtw_dist(va[:L], vb[:L]))
    out['dtw_shape'] = {'n_pairs': len(pa), 'median_dtw_star_vs_fork': round(float(np.median(pa)), 5),
        'baseline_dtw_random_star_pairs': round(float(np.median(base)), 5) if base else None,
        'note': 'DTW 越小形态越相似；对比组为随机两仓的星标曲线'}

# ========== 7. 高复制仓特征富集 ==========
print("7. enrichment...", flush=True)
high_copy = [rp for rp, d in lm.items() if d['share_cross'] >= 0.5 and d['n_skills'] >= 5]
all_r = list(lm.keys())
N = len(all_r); K = len(high_copy)
def enrich(pred):
    k = sum(1 for rp in high_copy if pred(rp))
    big_N = sum(1 for rp in all_r if pred(rp))
    if big_N == 0: return None
    p = hypergeom.sf(k - 1, N, big_N, K)
    return {'k': k, 'pool': big_N, 'fold': round((k / K) / (big_N / N), 2), 'p': round(float(p), 5)}
out['enrichment_highcopy'] = {
    'n_high_copy': K, 'n_all': N,
    'python': enrich(lambda rp: gdm.get(rp, {}).get('language') == 'Python'),
    'markdown_only': enrich(lambda rp: not gdm.get(rp, {}).get('language')),
    'created_2025': enrich(lambda rp: (gdm.get(rp, {}).get('created_at') or '')[:4] == '2025'),
    'on_skillssh': enrich(lambda rp: sh_hit.get(rp, 0) == 1),
    'note': '高复制仓（share≥0.5,≥5技能）的特征富集：fold>1 为富集，hypergeom 单侧'}

# ========== 8. PPMI 词向量最近邻 ==========
print("8. ppmi embeddings...", flush=True)
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.decomposition import TruncatedSVD
descs = []; seen = set()
with open(os.path.join(ROOT, 'external_data', 'skills_with_content.jsonl'), encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        rp = r.get('repoFullName')
        if rp in seen or rp not in gdm: continue
        c = r.get('full_content') or ''
        m = re.match(r'^---\s*\n(.*?)\n---', c.strip(), re.S)
        desc = ''
        if m:
            dm = re.search(r'description:\s*(.+)', m.group(1))
            desc = dm.group(1).strip() if dm else ''
        if len(desc) < 15: continue
        descs.append((rp, desc.lower())); seen.add(rp)
if len(descs) > 200:
    cv = CountVectorizer(max_features=800, min_df=5, max_df=0.5, stop_words='english')
    Xw = cv.fit_transform([d for _, d in descs])
    # PPMI
    tot = Xw.sum(); pw = np.asarray(Xw.sum(axis=0)).ravel() / tot
    pc = np.asarray(Xw.sum(axis=1)).ravel() / tot
    co = Xw.toarray() / tot
    ppmi = np.log((co + 1e-12) / (pc[:, None] * pw[None, :] + 1e-12))
    ppmi = np.maximum(ppmi, 0)
    svd = TruncatedSVD(n_components=30, random_state=25)
    W = svd.fit_transform(ppmi.T)
    terms = np.array(cv.get_feature_names_out())
    probes = ['security', 'install', 'scrape', 'write', 'data', 'design']
    nn = {}
    for p in probes:
        if p in terms:
            i = list(terms).index(p)
            sims = W @ W[i]
            nn[p] = [terms[j] for j in np.argsort(-sims)[1:7]]
    out['word_nn'] = {'n_docs': len(descs), 'probes': nn,
        'note': 'PPMI+SVD 词向量：探测词的最近邻（描述词语义空间）'}

json.dump(out, open(os.path.join(ROOT, 'data', 'results', 'deep8_20261025.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1, default=str)
print("\n=== SUMMARY ===")
for k, v in out.items():
    print(f"--- {k} ---")
    print(json.dumps(v, ensure_ascii=False, indent=1)[:750])
print("ALL DONE")
