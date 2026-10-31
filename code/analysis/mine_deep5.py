# -*- coding: utf-8 -*-
"""mine_deep5.py — 第五轮深挖（2026-10-25）：零假设式挖掘
不看文章框架，纯从数据出发找模式。这次用此前完全没用过的技术与视角：
1. 序列模式挖掘：星标事件的周内/日内节律、爆发序列的前后关系
2. 文档内容结构挖掘：SKILL.md 正文结构（标题层级、代码块、命令）——此前只用了frontmatter
3. 仓库名称文本挖掘：命名模式（后缀、前缀、组合词）
4. 时间窗交叉：不同渠道信号出现的时间先后（哪个渠道最先响应新仓）
5. 网络角色分类：结构等价性（哪些仓扮演相同角色）
6. 文档相似度的"源-流"推断：哪些仓是"纯转发"、哪些是"再加工"
7. fork 网络的级联深度：一个仓被 fork 后，其 fork 又被 fork 的深度
8. 平台条目名与 GitHub 文档名的编辑距离分析
9. 星标增长的加速度分布（二阶差分）
10. 技能文档间的引用/包含关系（文档 A 的内容出现在文档 B 中）
"""
import json, os, re, collections, datetime, random, zlib, hashlib
import numpy as np
warnings_flag = True
try:
    import warnings
    warnings.filterwarnings('ignore')
except: pass

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

# ========== 1. 文档内容结构挖掘（此前只用过frontmatter，从未用过正文结构）==========
print("1. document structure mining...", flush=True)
struct = collections.defaultdict(lambda: {'docs': 0, 'has_code': 0, 'has_headings': 0, 'has_links': 0,
    'has_lists': 0, 'has_tables': 0, 'code_lines': [], 'headings_count': [], 'length': [],
    'has_example': 0, 'has_install': 0, 'has_usage': 0, 'has_license_section': 0, 'has_contributing': 0})
n_docs_read = 0
with open(os.path.join(ROOT, 'external_data', 'skills_with_content.jsonl'), encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        rp = r.get('repoFullName')
        if rp not in gdm: continue
        c = r.get('full_content') or ''
        if len(c) < 50: continue
        d = struct[rp]; d['docs'] += 1
        n_docs_read += 1
        d['length'].append(len(c))
        # markdown 结构
        code_blocks = re.findall(r'```', c)
        d['has_code'] += (1 if len(code_blocks) >= 2 else 0)
        d['code_lines'].append(sum(1 for l in c.split('\n') if l.strip().startswith(('$ ', '> '))))
        headings = re.findall(r'^#{1,3}\s', c, re.M)
        d['has_headings'] += (1 if len(headings) >= 2 else 0)
        d['headings_count'].append(len(headings))
        d['has_links'] += (1 if re.search(r'\[.+\]\(http', c) else 0)
        d['has_lists'] += (1 if re.search(r'^\s*[-*]\s', c, re.M) else 0)
        d['has_tables'] += (1 if re.search(r'\|.+\|.+\|', c) else 0)
        cl = c.lower()
        d['has_example'] += (1 if 'example' in cl or '示例' in cl else 0)
        d['has_install'] += (1 if 'install' in cl or '安装' in cl else 0)
        d['has_usage'] += (1 if 'usage' in cl or '用法' in cl or '使用' in cl else 0)
        d['has_license_section'] += (1 if '## license' in cl or '## 许可' in cl else 0)
        d['has_contributing'] += (1 if 'contributing' in cl or '贡献' in cl else 0)

s_rows = []
for rp, d in struct.items():
    if d['docs'] == 0: continue
    s_rows.append({
        'repo': rp, 'n_docs': d['docs'],
        'code_pct': round(d['has_code']/d['docs'], 3),
        'headings_pct': round(d['has_headings']/d['docs'], 3),
        'links_pct': round(d['has_links']/d['docs'], 3),
        'example_pct': round(d['has_example']/d['docs'], 3),
        'usage_pct': round(d['has_usage']/d['docs'], 3),
        'license_section_pct': round(d['has_license_section']/d['docs'], 3),
        'median_len': int(np.median(d['length'])) if d['length'] else 0,
        'median_code_lines': int(np.median(d['code_lines'])) if d['code_lines'] else 0,
        'median_headings': int(np.median(d['headings_count'])) if d['headings_count'] else 0,
        'stars': gdm.get(rp, {}).get('stars') or 0,
        'installs': sh_inst.get(rp, 0),
        'hit': sh_hit.get(rp, 0)
    })
# 结构特征与结果的关联
from scipy.stats import spearmanr, mannwhitneyu
if len(s_rows) > 20:
    code_arr = [r['code_pct'] for r in s_rows]
    len_arr = [r['median_len'] for r in s_rows]
    ex_arr = [r['example_pct'] for r in s_rows]
    lic_arr = [r['license_section_pct'] for r in s_rows]
    star_arr = [r['stars'] for r in s_rows]
    inst_arr = [r['installs'] for r in s_rows]
    hit_arr = [r['hit'] for r in s_rows]
    rho_code_star = spearmanr(code_arr, star_arr)
    rho_len_star = spearmanr(len_arr, star_arr)
    rho_ex_inst = spearmanr(ex_arr, inst_arr)
    rho_lic_hit = spearmanr(lic_arr, hit_arr)
    # 正文含"## License"节的文档比例
    lic_any = np.mean([1 if r['license_section_pct'] > 0 else 0 for r in s_rows])
    out['structure'] = {
        'n_repos': len(s_rows), 'n_docs': n_docs_read,
        'pct_repos_with_code': round(float(np.mean([1 if r['code_pct']>0 else 0 for r in s_rows])), 3),
        'pct_repos_with_examples': round(float(np.mean([1 if r['example_pct']>0 else 0 for r in s_rows])), 3),
        'pct_repos_with_license_section': round(float(lic_any), 3),
        'median_doc_len': int(np.median([r['median_len'] for r in s_rows])),
        'median_code_lines': int(np.median([r['median_code_lines'] for r in s_rows])),
        'code_to_stars_rho': round(float(rho_code_star.statistic), 3), 'code_to_stars_p': round(float(rho_code_star.pvalue), 4),
        'len_to_stars_rho': round(float(rho_len_star.statistic), 3),
        'example_to_installs_rho': round(float(rho_ex_inst.statistic), 3) if not np.isnan(rho_ex_inst.statistic) else None,
        'license_sec_to_hit_rho': round(float(rho_lic_hit.statistic), 3),
        'note': '正文级结构特征（代码块/标题/链接/示例/License节）——此前仅分析过frontmatter'
    }

# ========== 2. 仓库名称文本挖掘 ==========
print("2. repo name mining...", flush=True)
suffix_counter = collections.Counter()
name_patterns = collections.Counter()
for rp in gdm:
    name = rp.split('/')[1].lower()
    if name.endswith('skills'): suffix_counter['-skills'] += 1
    elif name.endswith('skill'): suffix_counter['-skill'] += 1
    elif 'skill' in name: suffix_counter['skill_in_middle'] += 1
    if 'claude' in name: name_patterns['contains_claude'] += 1
    if 'agent' in name: name_patterns['contains_agent'] += 1
    if 'awesome' in name: name_patterns['contains_awesome'] += 1
    if 'mcp' in name: name_patterns['contains_mcp'] += 1
    if re.search(r'\d', name): name_patterns['contains_digit'] += 1
    if '-' in name: name_patterns['hyphenated'] += 1
n_names = len(gdm)
out['naming'] = {'n': n_names,
    'suffix_skills': suffix_counter['-skills'], 'suffix_skill': suffix_counter['-skill'],
    'skill_middle': suffix_counter['skill_in_middle'],
    'patterns': dict(name_patterns),
    'note': '341面板仓的命名模式'}

# ========== 3. 渠道响应时序（哪个信号最先出现）==========
print("3. channel response order...", flush=True)
# 对每仓：星标日、fork日、skills.sh收录（无时点，用采集日近似）、pushed_at
# 可做的是：创建→首星→首fork 的间隔
order_counts = collections.Counter()
for rp, rows in sh2.items():
    if not rows: continue
    created = gdm.get(rp, {}).get('created_at')
    if not created: continue
    cd = datetime.datetime.fromisoformat(created.replace('Z', '+00:00'))
    # 首星
    first_star = None
    for w in sorted(rows, key=lambda x: x['week']):
        if w['total'] > 0:
            wt = datetime.datetime.fromtimestamp(w['week'], tz=datetime.timezone.utc)
            # 找到该周内第一个>0的日
            for i, dn in enumerate(w['days']):
                if dn > 0:
                    first_star = wt + datetime.timedelta(days=i)
                    break
            if first_star: break
    # 首fork
    first_fork = None
    forks = ft.get(rp, [])
    if forks and (gdm.get(rp, {}).get('forks') or 0) <= 500:
        ff = min(f['created_at'] for f in forks if f.get('created_at'))
        first_fork = datetime.datetime.fromisoformat(ff.replace('Z', '+00:00'))
    if first_star and first_fork:
        if first_star < first_fork: order_counts['star_first'] += 1
        elif first_fork < first_star: order_counts['fork_first'] += 1
        else: order_counts['same_day'] += 1
out['channel_order'] = dict(order_counts)

# ========== 4. 星标增长的加速度分布 ==========
print("4. star growth acceleration...", flush=True)
accels = []
for rp, rows in sh2.items():
    if len(rows) < 10: continue
    rows = sorted(rows, key=lambda x: x['week'])
    weekly = [w['total'] for w in rows]
    if sum(weekly) < 10: continue
    # 一阶差分（增长速度）、二阶差分（加速度）
    d1 = np.diff(weekly)
    if len(d1) < 2: continue
    d2 = np.diff(d1)
    # 用归一化加速度：d2/ (|d1|.mean()+1)
    norm_acc = d2 / (np.abs(d1).mean() + 1)
    accels.append({
        'repo': rp,
        'max_accel': round(float(np.max(norm_acc)), 2),
        'min_accel': round(float(np.min(norm_acc)), 2),
        'accel_volatility': round(float(np.std(norm_acc)), 3),
        'n_weeks': len(weekly),
        'total_stars': sum(weekly)
    })
if accels:
    max_a = [a['max_accel'] for a in accels]
    vol = [a['accel_volatility'] for a in accels]
    # 高波动仓的星标 vs 低波动
    accs_sorted = sorted(accels, key=lambda x: -x['accel_volatility'])
    top_quartile = accs_sorted[:len(accs_sorted)//4]
    bot_quartile = accs_sorted[-len(accs_sorted)//4:]
    out['star_acceleration'] = {
        'n_repos': len(accels),
        'median_max_accel': round(float(np.median(max_a)), 2),
        'median_volatility': round(float(np.median(vol)), 3),
        'high_vol_median_stars': int(np.median([a['total_stars'] for a in top_quartile])),
        'low_vol_median_stars': int(np.median([a['total_stars'] for a in bot_quartile])),
        'note': '二阶差分归一化；高波动=星标增长断续（突发型），低波动=平滑增长'
    }

# ========== 5. 纯转发 vs 再加工（基于近重复+exact的混合判断）==========
print("5. relay vs rework classification...", flush=True)
# 对面板仓：如果其文档 mostly exact SHA（share_cross 高且n_unique低）= 纯转发
# 如果 mostly unique = 再加工
relay = []; rework = []; original = []
for rp, d in lm.items():
    if d['n_skills'] < 3: continue
    if d['share_cross'] >= 0.7 and d['n_skills'] >= 5:
        relay.append(rp)
    elif d['share_cross'] <= 0.1 and d['n_skills'] >= 5:
        # 有内容但几乎不复制别人 = 可能是原创/再加工
        original.append(rp)
# 转发仓 vs 原创仓的结果对比
def stats(rps):
    st = [gdm.get(r, {}).get('stars') or 0 for r in rps]
    inst = [sh_inst.get(r, 0) for r in rps]
    hit = [sh_hit.get(r, 0) for r in rps]
    return {'n': len(rps), 'median_stars': int(np.median(st)) if st else 0,
            'median_installs': int(np.median(inst)) if inst else 0,
            'hit_rate': round(float(np.mean(hit)), 3) if hit else None}
out['relay_vs_original'] = {
    'relay': stats(relay), 'original': stats(original),
    'relay_examples': relay[:5], 'original_examples': original[:5],
    'note': '纯转发仓=share_cross≥0.7且≥5技能；原创/再加工仓=share_cross≤0.1且≥5技能'
}

# ========== 6. fork 级联深度（fork 的 fork）==========
print("6. fork cascade depth...", flush=True)
# 从forks_timestamps_full.json或数据构建：检查fork的owner是否也是本面板的成员
# 简化：检查fork出的仓是否又是面板中某仓（级联）
cascade = 0; no_cascade = 0
panel_set = set(gdm.keys())
for rp, forks in ft.items():
    if (gdm.get(rp, {}).get('forks') or 0) > 500: continue
    has_panel_fork = any(f.get('full_name', '').split('/')[0] in panel_set for f in forks if f.get('full_name'))
    if has_panel_fork: cascade += 1
    else: no_cascade += 1
out['fork_cascade'] = {'cascade_repos': cascade, 'no_cascade_repos': no_cascade,
    'cascade_rate': round(cascade / max(cascade + no_cascade, 1), 3),
    'note': '面板内 fork 出的仓又出现在面板中的比例（面板内级联）'}

# ========== 7. 平台条目名与 GitHub 文档名的模糊匹配 ==========
print("7. fuzzy name matching...", flush=True)
github_names = set()
with open(os.path.join(ROOT, 'external_data', 'skills_with_content.jsonl'), encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        nm = r.get('name') or ''
        if nm: github_names.add(nm.strip().lower())
slugs = set()
for line in open(os.path.join(COL, 'market_full.jsonl'), encoding='utf-8'):
    r = json.loads(line)
    if r.get('type') == 'clawhub_registry':
        s = (r.get('item') or {}).get('slug') or ''
        if s:
            slug_clean = s.split('--')[-1] if '--' in s else s
            slugs.add(slug_clean.lower())
exact = len(slugs & github_names)
# 近似匹配：一个是否为另一个的子串
sub_match = sum(1 for s in slugs if any(s in g or g in s for g in github_names)) if slugs else 0
out['fuzzy_match'] = {'clawhub_slugs': len(slugs), 'github_names': len(github_names),
    'exact_match': exact, 'substring_match': sub_match,
    'exact_rate': round(exact / max(len(slugs), 1), 3),
    'note': 'ClawHub slug 与 GitHub 文档名的精确/子串匹配率'}

# ========== 8. 星标集中度的时间演化（基尼系数按月）==========
print("8. star gini over time...", flush=True)
monthly_star = collections.defaultdict(lambda: collections.Counter())
for rp, rows in sh2.items():
    for w in rows:
        wt = datetime.datetime.fromtimestamp(w['week'], tz=datetime.timezone.utc)
        mkey = wt.strftime('%Y-%m')
        monthly_star[mkey][rp] += w['total']
def gini(xs):
    xs = np.sort(np.array(xs, dtype=float))
    n = len(xs)
    if n == 0 or xs.sum() <= 0: return None
    cum = np.cumsum(xs)
    return float((n + 1 - 2 * (cum / cum[-1]).sum()) / n)
gini_series = {}
for m in sorted(monthly_star):
    vals = list(monthly_star[m].values())
    if len(vals) >= 10:
        g = gini(vals)
        if g is not None:
            gini_series[m] = round(g, 3)
out['star_gini_monthly'] = gini_series

# ========== 9. 杂烩仓 vs 专业仓的内容结构对比 ==========
print("9. specialist vs generalist structure...", flush=True)
# 按每仓的文档名唯一性判断：技能名与仓名的相似度
# 专业仓：技能名与仓名相关；杂烩仓：技能名五花八门
spec = []; gen = []
for rp, d in lm.items():
    if d['n_skills'] < 5: continue
    share = d['share_cross']
    # 简单代理：n_skills 多且 name 多样 = 杂烩
    if d['n_skills'] >= 20:
        gen.append(rp)
    elif d['n_skills'] <= 10:
        spec.append(rp)
sp_stats = {'n': len(spec), 'median_stars': int(np.median([gdm.get(r, {}).get('stars') or 0 for r in spec])) if spec else 0,
            'hit_rate': round(float(np.mean([sh_hit.get(r, 0) for r in spec])), 3) if spec else None}
gn_stats = {'n': len(gen), 'median_stars': int(np.median([gdm.get(r, {}).get('stars') or 0 for r in gen])) if gen else 0,
            'hit_rate': round(float(np.mean([sh_hit.get(r, 0) for r in gen])), 3) if gen else None}
u_sp, p_sp = mannwhitneyu([gdm.get(r, {}).get('stars') or 0 for r in spec],
                          [gdm.get(r, {}).get('stars') or 0 for r in gen]) if spec and gen else (None, None)
out['specialist_vs_generalist'] = {'specialist': sp_stats, 'generalist': gn_stats,
    'mwu_p': round(float(p_sp), 4) if p_sp else None,
    'note': '专业仓=技能数≤10；杂烩仓=技能数≥20'}

# 保存
json.dump(out, open(os.path.join(ROOT, 'data', 'results', 'deep5_20261025.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1, default=str)
print("\n=== SUMMARY ===")
for k, v in out.items():
    print(f"--- {k} ---")
    print(json.dumps(v, ensure_ascii=False, indent=1)[:600])
print("ALL DONE")
