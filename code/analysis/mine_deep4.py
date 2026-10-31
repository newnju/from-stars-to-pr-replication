# -*- coding: utf-8 -*-
"""mine_deep4.py — 第四轮深挖（2026-10-25）：多技术组合挖掘
使用聚类、降维、序列分析、网络分析、关联规则、异常检测、文本挖掘、生存分析等
十余种技术，从多角度挖掘数据中的潜在模式。

A. 文档嵌入聚类（TF-IDF + SVD + KMeans）：发现技能文档的潜在主题
B. 异常检测（IsolationForest）：识别星标/安装/复制率异常的仓库
C. 生存分析（Kaplan-Meier）：仓库从创建到首次fork的存活时间
D. 关联规则挖掘（复制的仓库对的特征模式）
E. 主成分分析（PCA）：五渠道可见性的降维解读
F. 时序分解：星标时序的趋势/周期/突发成分
G. 复制网络加权中心性（PageRank, betweenness）
H. 协同过滤视角：平台收录的协同信号
I. 多维标度分析（MDS）：仓库在复制空间的相似度结构
J. 文本特征→结果的多变量模型（L1正则化）
K. PR title 的主题提取（LDA）
L. 复制对的时间差分布拟合（对数正态 vs 指数）
M. 仓库"生命周期阶段"的隐马尔可夫模型（HMM）
N. 安装量-星标比率的回归分析（自然对数）
"""
import json, os, re, collections, datetime, random, warnings
import numpy as np
warnings.filterwarnings('ignore')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COL = os.path.join(ROOT, 'external_data', 'collected_20261024')
TMP = r'E:\temp\opencode'
REF = datetime.datetime(2026, 10, 24, tzinfo=datetime.timezone.utc)
out = {}

print("Loading data...", flush=True)
FM = re.compile(r"^---\s*\n(.*?)\n---", re.S)
gdm = json.load(open(os.path.join(ROOT, 'data', 'repos_meta.json'), encoding='utf-8'))
sh2 = json.load(open(os.path.join(TMP, 'star_history_v2.json'), encoding='utf-8'))
ft = json.load(open(os.path.join(ROOT, 'data', 'forks_timestamps.json'), encoding='utf-8'))
lm = {}
for line in open(os.path.join(COL, 'local_mining.jsonl'), encoding='utf-8'):
    r = json.loads(line)
    if r.get('type') == 'repo':
        lm[r['repo']] = {'stars': r.get('stars') or 0, 'n_skills': r.get('n_skills') or 0,
                         'share_cross': r.get('share_cross') or 0, 'n_unique': r.get('n_unique_sha') or 0,
                         'n_shared': r.get('n_shared_sha') or 0, 'fm_valid': r.get('fm_valid'),
                         'fm_rate': r.get('fm_rate'), 'fm_fields': r.get('fm_fields_mean')}
sh_hit = {}; sh_inst = {}
for nmf in ('market_full.jsonl', 'market_retry.jsonl'):
    for line in open(os.path.join(COL, nmf), encoding='utf-8'):
        r = json.loads(line)
        if r.get('type') == 'skills_sh':
            sh_hit[r['repo']] = 1 if (r.get('n_hits') or 0) > 0 else 0
            if sh_hit[r['repo']]:
                sh_inst[r['repo']] = r.get('total_installs') or 0
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

# ========== A) 文档嵌入聚类（TF-IDF + TruncatedSVD + KMeans）==========
print("A: document embedding clustering...", flush=True)
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD
from sklearn.cluster import MiniBatchKMeans
from sklearn.metrics import silhouette_score

descs = []; repos_a = []; names_a = []
seen_rp = set()
with open(os.path.join(ROOT, 'external_data', 'skills_with_content.jsonl'), encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        rp = r.get('repoFullName')
        if rp in seen_rp or rp not in gdm:
            continue
        c = r.get('full_content') or ''
        m = FM.match(c.strip('\ufeff \n'))
        if m:
            dm = re.search(r'description:\s*(.+)', m.group(1))
            desc = dm.group(1).strip()[:300] if dm else ''
        else:
            desc = (r.get('description') or '')[:300]
        if len(desc) < 15:
            continue
        descs.append(desc); repos_a.append(rp); seen_rp.add(rp)

if len(descs) > 100:
    vec = TfidfVectorizer(max_features=3000, stop_words='english', min_df=3, max_df=0.8)
    X = vec.fit_transform(descs)
    svd = TruncatedSVD(n_components=50, random_state=25)
    Xr = svd.fit_transform(X)
    ev = svd.explained_variance_ratio_.sum()
    best_k, best_s = 4, -1
    for k in [3, 4, 5, 6, 8]:
        km = MiniBatchKMeans(k, n_init=5, random_state=25).fit(Xr)
        s = silhouette_score(Xr[:3000], km.labels_[:3000])
        if s > best_s: best_k, best_s = k, s
    km = MiniBatchKMeans(best_k, n_init=10, random_state=25).fit(Xr)
    terms = np.array(vec.get_feature_names_out())
    clusters = []
    for c in range(best_k):
        mask = km.labels_ == c
        if mask.sum() < 3: continue
        cen = Xr[mask].mean(axis=0)
        top_idx = np.argsort(-np.abs(cen))[:8]
        # 转换回原空间取词
        comp = svd.components_[:, top_idx].mean(axis=1)
        top_terms = terms[np.argsort(-np.abs(comp))[:10]].tolist()
        stars_c = [gdm.get(repos_a[i], {}).get('stars') or 0 for i in np.where(mask)[0]]
        clusters.append({'k': c, 'n': int(mask.sum()), 'terms': top_terms,
                        'median_stars': int(np.median(stars_c)),
                        'platform_hit': round(float(np.mean([sh_hit.get(repos_a[i], 0) for i in np.where(mask)[0]])), 3)})
    out['A'] = {'n_docs': len(descs), 'svd_var_explained': round(float(ev), 3),
                'best_k': best_k, 'silhouette': round(float(best_s), 3), 'clusters': clusters,
                'note': '每仓取首份文档的描述做向量；silhouette 在3000样本上估计'}

# ========== B) 异常检测（IsolationForest）==========
print("B: anomaly detection...", flush=True)
from sklearn.ensemble import IsolationForest
rows_b = []; rps_b = []
for rp in gdm:
    m = gdm[rp]
    if not m.get('created_at'): continue
    age = (REF - datetime.datetime.fromisoformat(m['created_at'].replace('Z', '+00:00'))).days / 30
    d = lm.get(rp, {})
    rows_b.append([
        np.log10((m.get('stars') or 0) + 1),
        np.log10((m.get('forks') or 0) + 1),
        np.log10((sh_inst.get(rp, 0)) + 1),
        d.get('share_cross', 0),
        d.get('n_skills', 0),
        age,
        1 if sh_hit.get(rp) else 0,
        1 if ch_hit.get(rp) else 0,
        1 if npm_hit.get(rp) else 0
    ])
    rps_b.append(rp)
if len(rows_b) > 50:
    Xb = np.array(rows_b)
    iso = IsolationForest(contamination=0.05, random_state=25).fit(Xb)
    labels_b = iso.predict(Xb)
    anomalies = [(rps_b[i], float(iso.score_samples(Xb[i:i+1])[0])) for i in range(len(rps_b)) if labels_b[i] == -1]
    anomalies.sort(key=lambda x: x[1])
    anom_info = []
    for rp, sc in anomalies[:15]:
        m = gdm[rp]; d = lm.get(rp, {})
        anom_info.append({'repo': rp, 'anomaly_score': round(sc, 3),
                         'stars': m.get('stars'), 'forks': m.get('forks'),
                         'installs': sh_inst.get(rp, 0), 'share_cross': round(d.get('share_cross', 0), 3),
                         'n_skills': d.get('n_skills', 0)})
    out['B'] = {'n_anomalies': len(anomalies), 'top15': anom_info,
               'note': 'contamination=5%；异常=星标/安装/复制率的极端组合'}

# ========== C) 生存分析（Kaplan-Meier）==========
print("C: survival analysis...", flush=True)
durations = []; events = []
for rp, rows in sh2.items():
    if not rows: continue
    created = gdm.get(rp, {}).get('created_at')
    if not created: continue
    cd = datetime.datetime.fromisoformat(created.replace('Z', '+00:00'))
    forks = ft.get(rp, [])
    if forks and (gdm.get(rp, {}).get('forks') or 0) <= 500:
        first_f = min(f['created_at'] for f in forks if f.get('created_at'))
        fd = datetime.datetime.fromisoformat(first_f.replace('Z', '+00:00'))
        dur = (fd - cd).days
        events.append(1)
    else:
        dur = (REF - cd).days  # censored at observation end
        events.append(0)
    durations.append(max(0, dur))

# 手写 KM 估计
if durations:
    T = np.array(durations); E = np.array(events)
    times = np.sort(np.unique(T[E == 1]))
    km_est = []
    n_at_risk = len(T)
    surv = 1.0
    for t in times:
        d = np.sum((T == t) & (E == 1))
        c = np.sum((T == t) & (E == 0))
        if n_at_risk > 0:
            surv *= (1 - d / n_at_risk)
        km_est.append((int(t), round(float(surv), 4)))
        n_at_risk -= (d + c)
    # 分位数
    med_t = next((t for t, s in km_est if s <= 0.5), None)
    q25_t = next((t for t, s in km_est if s <= 0.25), None)
    # 前 N 天的存活率
    surv_1 = next((s for t, s in km_est if t >= 1), None)
    surv_7 = next((s for t, s in km_est if t >= 7), None)
    surv_30 = next((s for t, s in km_est if t >= 30), None)
    surv_90 = next((s for t, s in km_est if t >= 90), None)
    out['C'] = {'n': len(durations), 'n_events': int(E.sum()),
               'median_days_to_first_fork': med_t, 'q25_days': q25_t,
               'km_surv_at_1d': surv_1, 'at_7d': surv_7, 'at_30d': surv_30, 'at_90d': surv_90,
               'km_curve_first20': km_est[:20],
               'note': 'KM 估计：仓库创建→首次fork；fork>500 仓以观测终点为删失'}

# ========== D) 关联规则：复制的仓库对特征模式 ==========
print("D: association rules on copied pairs...", flush=True)
# 找共享SHA的仓库对，提取特征
sha_repos = collections.defaultdict(set)
with open(os.path.join(ROOT, 'external_data', 'skills_with_content.jsonl'), encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        h = r.get('sha256_hash')
        if h:
            sha_repos[h].add(r.get('repoFullName'))
# 提取每仓的离散特征
def discretize(rp):
    m = gdm.get(rp, {})
    d = lm.get(rp, {})
    stars = m.get('stars') or 0
    return {
        'high_star': stars >= 10000,
        'mid_star': 100 <= stars < 10000,
        'low_star': stars < 100,
        'has_skills_platform': bool(sh_hit.get(rp)),
        'has_clawhub': bool(ch_hit.get(rp)),
        'high_copy': d.get('share_cross', 0) >= 0.5,
        'many_skills': d.get('n_skills', 0) >= 10,
        'is_python': m.get('language') == 'Python',
        'is_ts': m.get('language') == 'TypeScript',
        'old_repo': m.get('created_at', '9999')[:4] in ('2025',),
    }
pair_features = collections.Counter()
seen_pairs = set()
for h, rs in sha_repos.items():
    if len(rs) < 2: continue
    rl = sorted(rs)
    for i in range(len(rl)):
        for j in range(i+1, len(rl)):
            pk = (rl[i], rl[j])
            if pk in seen_pairs: continue
            seen_pairs.add(pk)
            fa = discretize(rl[i]); fb = discretize(rl[j])
            # 记录特征共现模式
            for feat in ['high_star', 'mid_star', 'low_star', 'has_skills_platform', 'has_clawhub',
                         'high_copy', 'many_skills', 'is_python', 'is_ts', 'old_repo']:
                if fa[feat] and fb[feat]:
                    pair_features[f'both_{feat}'] += 1
                elif fa[feat] or fb[feat]:
                    pair_features[f'one_{feat}'] += 1
            if fa['high_star'] != fb['high_star']:
                pair_features['star_mismatch'] += 1
            if fa['has_skills_platform'] != fb['has_skills_platform']:
                pair_features['platform_mismatch'] += 1
n_pairs = len(seen_pairs)
if n_pairs > 0:
    out['D'] = {'n_pairs': n_pairs,
               'top_patterns': {k: {'n': v, 'pct': round(100 * v / n_pairs, 1)}
                               for k, v in pair_features.most_common(15)},
               'note': '共享SHA的仓库对的二元特征共现模式'}

# ========== E) PCA：五渠道可见性降维 ==========
print("E: PCA on channels...", flush=True)
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
rows_e = []; rps_e = []
for rp in gdm:
    if rp not in lm: continue
    rows_e.append([1 if (gdm[rp].get('stars') or 0) > 0 else 0,
                   sh_hit.get(rp, 0), ch_hit.get(rp, 0), rel_hit.get(rp, 0), npm_hit.get(rp, 0)])
    rps_e.append(rp)
if len(rows_e) > 30:
    Xe = StandardScaler().fit_transform(np.array(rows_e))
    pca = PCA(n_components=5, random_state=25)
    Xp = pca.fit_transform(Xe)
    ev = pca.explained_variance_ratio_
    out['E'] = {'explained_variance': [round(float(x), 3) for x in ev],
               'cumulative_2pc': round(float(ev[0] + ev[1]), 3),
               'loadings_pc1': [round(float(x), 3) for x in pca.components_[0]],
               'loadings_pc2': [round(float(x), 3) for x in pca.components_[1]],
               'channels': ['star>0', 'skills_sh', 'clawhub', 'release', 'npm'],
               'note': 'PC1/PC2 载荷揭示渠道间的结构关系'}

# ========== F) 时序分解（趋势/突发）==========
print("F: time series decomposition...", flush=True)
agg = collections.Counter()
for rp, rows in sh2.items():
    for w in sorted(rows, key=lambda x: x['week']):
        wt = datetime.datetime.fromtimestamp(w['week'], tz=datetime.timezone.utc)
        for i, dn in enumerate(w['days']):
            agg[(wt + datetime.timedelta(days=i)).strftime('%Y-%m-%d')] += dn
days = sorted(agg)
if len(days) > 60:
    vals = np.array([agg[d] for d in days], dtype=float)
    # 简单移动平均作为趋势
    win = 7
    trend = np.convolve(vals, np.ones(win) / win, mode='same')
    resid = vals - trend
    # 突发日：resid > 3*MAD
    mad = np.median(np.abs(resid - np.median(resid)))
    burst_days = [(days[i], int(vals[i])) for i in range(len(vals)) if resid[i] > 3 * mad]
    # 周内模式
    dow = collections.Counter()
    for i, d in enumerate(days):
        dt = datetime.datetime.strptime(d, '%Y-%m-%d')
        dow[dt.weekday()] += int(vals[i])
    dow_mean = {k: int(v / len(days) * 7 / 7) for k, v in dow.items()}
    out['F'] = {'n_days': len(days), 'mean_daily': round(float(vals.mean()), 1),
               'trend_first_last': [round(float(trend[:14].mean()), 1), round(float(trend[-14:].mean()), 1)],
               'trend_change_pct': round(100 * (trend[-14:].mean() - trend[:14].mean()) / max(trend[:14].mean(), 1), 1),
               'n_burst_days_3mad': len(burst_days), 'burst_days': burst_days[:10],
               'day_of_week_sum': dict(sorted(dow.items())),
               'note': '7日移动平均为趋势；resid>3×MAD 为突发日；dow 0=周一'}

# ========== G) 复制网络加权中心性 ==========
print("G: network centrality...", flush=True)
import networkx as nx
Gw = nx.Graph()
for h, rs in sha_repos.items():
    if len(rs) >= 2:
        rl = sorted(rs)
        for i in range(len(rl) - 1):
            for j in range(i + 1, min(i + 6, len(rl))):
                if Gw.has_edge(rl[i], rl[j]):
                    Gw[rl[i]][rl[j]]['w'] += 1
                else:
                    Gw.add_edge(rl[i], rl[j], w=1)
if Gw.number_of_nodes() > 100:
    pr = nx.pagerank(Gw, weight='w', alpha=0.85)
    top_pr = sorted(pr.items(), key=lambda x: -x[1])[:10]
    # Betweenness（对大图采样计算）
    btw = nx.betweenness_centrality(Gw, k=min(500, Gw.number_of_nodes()), weight='w')
    top_btw = sorted(btw.items(), key=lambda x: -x[1])[:10]
    out['G'] = {'n_nodes': Gw.number_of_nodes(), 'n_edges': Gw.number_of_edges(),
               'top_pagerank': [(r, round(v, 5), lm.get(r, {}).get('stars', 0)) for r, v in top_pr],
               'top_betweenness': [(r, round(v, 4), lm.get(r, {}).get('stars', 0)) for r, v in top_btw],
               'note': 'PageRank α=0.85；Betweenness 采样500节点'}

# ========== H) 平台收录协同信号 ==========
print("H: platform co-listing...", flush=True)
both_platforms = sum(1 for rp in gdm if sh_hit.get(rp) and ch_hit.get(rp))
only_sh = sum(1 for rp in gdm if sh_hit.get(rp) and not ch_hit.get(rp))
only_ch = sum(1 for rp in gdm if ch_hit.get(rp) and not sh_hit.get(rp))
neither = sum(1 for rp in gdm if not sh_hit.get(rp) and not ch_hit.get(rp))
tbl_h = [[both_platforms, only_sh], [only_ch, neither]]
chi2_h, p_h, _, _ = __import__('scipy.stats', fromlist=['chi2_contingency']).chi2_contingency(tbl_h)
out['H'] = {'both': both_platforms, 'only_skillssh': only_sh, 'only_clawhub': only_ch, 'neither': neither,
           'jaccard': round(both_platforms / max(both_platforms + only_sh + only_ch, 1), 3),
           'chi2': round(float(chi2_h), 2), 'p': round(float(p_h), 4),
           'note': '两平台收录的2×2列联表与Jaccard系数'}

# ========== I) 文本特征→结果（L1正则化）==========
print("I: L1 text features to outcomes...", flush=True)
from sklearn.linear_model import LassoCV
from sklearn.preprocessing import StandardScaler
# 对有安装数据的仓：特征=[n_skills, share_cross, avg_fields, desc_len, is_python, is_ts, age_months]
rows_i = []; y_i = []
for rp in sh_inst:
    d = lm.get(rp, {})
    m = gdm.get(rp, {})
    if not m.get('created_at'): continue
    age = (REF - datetime.datetime.fromisoformat(m['created_at'].replace('Z', '+00:00'))).days / 30
    rows_i.append([d.get('n_skills', 0), d.get('share_cross', 0), d.get('fm_fields_mean', 0) or 0,
                   1 if m.get('language') == 'Python' else 0,
                   1 if m.get('language') == 'TypeScript' else 0, age])
    y_i.append(np.log10(sh_inst[rp] + 1))
if len(rows_i) > 30:
    Xi = StandardScaler().fit_transform(np.array(rows_i))
    yi = np.array(y_i)
    lasso = LassoCV(cv=5, random_state=25).fit(Xi, yi)
    feats = ['n_skills', 'share_cross', 'fm_fields', 'is_python', 'is_ts', 'age_months']
    out['I'] = {'n': len(y_i), 'r2_cv': round(float(lasso.score(Xi, yi)), 3),
               'alpha': round(float(lasso.alpha_), 4),
               'coefs': {f: round(float(c), 4) for f, c in zip(feats, lasso.coef_)},
               'note': 'LassoCV 5折；因变量=log10(installs+1)；特征标准化'}

# ========== J) PR title 的主题提取（简化 LDA）==========
print("J: PR title topics...", flush=True)
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.decomposition import LatentDirichletAllocation
titles = []
for nmf in ('pr_merged.jsonl', 'pr_merged_retry.jsonl'):
    for line in open(os.path.join(COL, nmf), encoding='utf-8'):
        r = json.loads(line)
        if r.get('type') != 'repo' or not r.get('complete'): continue
        for pr in r.get('pulls', []):
            t = pr.get('title') or ''
            if len(t) > 5:
                titles.append(t)
if len(titles) > 500:
    cv = CountVectorizer(max_features=500, stop_words='english', min_df=5, max_df=0.5)
    Xt = cv.fit_transform(titles[:20000])
    lda = LatentDirichletAllocation(n_components=6, random_state=25, max_iter=15).fit(Xt)
    terms_t = np.array(cv.get_feature_names_out())
    topics = []
    for c in range(6):
        top = terms_t[np.argsort(-lda.components_[c])[:8]].tolist()
        topics.append({'topic': c, 'terms': top})
    out['J'] = {'n_titles': min(len(titles), 20000), 'topics': topics}

# ========== K) 复制时间差的分布拟合 ==========
print("K: time-lag distribution...", flush=True)
lags = []
pairs_k = []
for line in open(os.path.join(COL, 'direction_sample.jsonl'), encoding='utf-8'):
    r = json.loads(line)
    if r.get('type') == 'pair' and isinstance(r.get('abs_lag_days'), (int, float)):
        lags.append(r['abs_lag_days'])
if len(lags) > 30:
    la = np.array(lags)
    la_pos = la[la > 0]
    # 对数正态拟合检验
    from scipy.stats import kstest, lognorm, expon
    if len(la_pos) > 20:
        shape, loc, scale = lognorm.fit(la_pos, floc=0)
        ks_ln, p_ln = kstest(la_pos, 'lognorm', args=(shape, loc, scale))
        lam = 1 / la_pos.mean()
        ks_ex, p_ex = kstest(la_pos, 'expon', args=(0, 1/lam))
        out['K'] = {'n_pairs': len(la), 'n_positive_lag': len(la_pos),
                   'median_lag': float(np.median(la)),
                   'lognorm_ks_p': round(float(p_ln), 4), 'expon_ks_p': round(float(p_ex), 4),
                   'lognorm_params': {'shape': round(float(shape), 3), 'scale': round(float(scale), 1)},
                   'best_fit': 'lognorm' if p_ln > p_ex else 'expon',
                   'note': '方向样本对的|时间差|分布拟合'}

# ========== 汇总输出 ==========
json.dump(out, open(os.path.join(ROOT, 'data', 'results', 'deep4_20261025.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1, default=str)
print("\n=== SUMMARY ===", flush=True)
for k, v in out.items():
    print(f"--- {k} ---")
    print(json.dumps(v, ensure_ascii=False, indent=1)[:500])
print("ALL DONE")
