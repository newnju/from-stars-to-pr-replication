# -*- coding: utf-8 -*-
"""fetch_pr_bodytext.py — 批量获取 PR 正文（bodyText）（2026-10-25）
对已完成仓的 PR 逐仓拉取 GraphQL bodyText，按 GraphQL rate limit 自动等待。
输出 E:/temp/opencode/pr_bodytext.jsonl: {"type":"repo","repo":...,"prs":[{n,body_len,body[:200],classified}]}
"""
import json, os, time, re, urllib.request, urllib.error, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = open(os.path.join(ROOT, 'external_data', '_cache', 'gh_token.txt')).read().strip()
COL = os.path.join(ROOT, 'external_data', 'collected_20261024')
TMP = r'E:\temp\opencode'
OUT = os.path.join(TMP, 'pr_bodytext.jsonl')

HEAD = {'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json',
        'User-Agent': 'skill-diffusion-repro'}


def gql(query, variables, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request('https://api.github.com/graphql',
                data=json.dumps({'query': query, 'variables': variables}).encode(),
                headers=HEAD)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode()), r.headers.get('X-RateLimit-Remaining')
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                reset = e.headers.get('X-RateLimit-Reset')
                w = max(5, int(reset) - int(time.time()) + 5) if reset else 60
                print(f"ratelimited; sleep {w}s", flush=True)
                time.sleep(min(w, 3700))
            else:
                raise
        except Exception as e:
            time.sleep(3 * (i + 1))
    return None, None


QUERY = '''query($owner:String!, $name:String!, $first:Int!, $after:String) {
  repository(owner:$owner, name:$name) {
    pullRequests(first:$first, after:$after, orderBy:{field:CREATED_AT, direction:ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes { number bodyText }
    }
  }
}'''


def classify(title, body):
    """按标题+正文分类 PR"""
    t = (title or '').lower()
    b = (body or '').lower()[:500]
    if re.match(r'^(bump|update.*(dep|depend|version|package)|chore\(deps?\)|dependabot|renovate)', t):
        return 'dep_update'
    if re.match(r'^(sync|mirror|fetch|pull|import|upstream|update.*(fork|remote))', t):
        return 'sync'
    if re.match(r'^(docs?|readme|comment|typo|spell)', t):
        return 'docs'
    if re.match(r'^(fix|bug|hotfix|patch)', t):
        return 'fix'
    if re.match(r'^(feat|add|new|implement|create|introduce)', t):
        return 'feature'
    if re.match(r'^(refactor|clean|remove|delete|deprecate)', t):
        return 'refactor'
    if re.match(r'^(test|spec|coverage)', t):
        return 'test'
    if re.match(r'^(ci|build|docker|deploy|release|publish)', t):
        return 'ci_release'
    if re.match(r'^(style|format|lint|prettier)', t):
        return 'style'
    # 正文补充
    if 'dependabot' in b or 'renovate' in b:
        return 'dep_update'
    if 'sync' in t and ('fork' in b or 'upstream' in b or 'mirror' in b):
        return 'sync'
    return 'other'


def fetch_repo_bodytext(full_name):
    owner, name = full_name.split('/', 1)
    prs = []
    cursor = None
    while True:
        v = {'owner': owner, 'name': name, 'first': 100, 'after': cursor}
        data, rem = gql(QUERY, v)
        if data is None or 'errors' in data:
            return None
        nodes = data['data']['repository']['pullRequests']['nodes']
        pi = data['data']['repository']['pullRequests']['pageInfo']
        for n in nodes:
            body = n.get('bodyText') or ''
            prs.append({'n': n['number'], 'body_len': len(body), 'body': body[:300],
                        'class': classify(None, body)})
        if not pi['hasNextPage']:
            break
        cursor = pi['endCursor']
        time.sleep(0.2)
    return prs


def main():
    # 已完成仓列表
    done_repos = set()
    for nmf in ('pr_merged.jsonl', 'pr_merged_retry.jsonl', 'pr_merged_retry3.jsonl'):
        fp = os.path.join(COL, nmf)
        if not os.path.exists(fp):
            continue
        for line in open(fp, encoding='utf-8'):
            r = json.loads(line)
            if r.get('type') == 'repo' and r.get('complete'):
                done_repos.add(r['repo'])
    # retry4 在 TMP
    fp4 = os.path.join(TMP, 'pr_merged_retry4.jsonl')
    if os.path.exists(fp4):
        for line in open(fp4, encoding='utf-8'):
            r = json.loads(line)
            if r.get('type') == 'repo' and r.get('complete'):
                done_repos.add(r['repo'])
    # 已获取的仓跳过
    already = set()
    if os.path.exists(OUT):
        for line in open(OUT, encoding='utf-8'):
            try:
                r = json.loads(line)
                if r.get('type') == 'repo':
                    already.add(r['repo'])
            except Exception:
                pass
    todo = sorted(done_repos - already)
    print(f"repos: {len(done_repos)} | already: {len(already)} | todo: {len(todo)}", flush=True)

    with open(OUT, 'a', encoding='utf-8') as f:
        for i, rp in enumerate(todo):
            try:
                prs = fetch_repo_bodytext(rp)
                if prs is None:
                    f.write(json.dumps({'type': 'error', 'repo': rp}) + '\n')
                    print(f"FAIL {rp}", flush=True)
                else:
                    f.write(json.dumps({'type': 'repo', 'repo': rp, 'n_prs': len(prs), 'prs': prs}, ensure_ascii=False) + '\n')
                    f.flush()
            except Exception as e:
                f.write(json.dumps({'type': 'error', 'repo': rp, 'error': str(e)[:120]}) + '\n')
            if (i + 1) % 20 == 0:
                print(f"[{i+1}/{len(todo)}]", flush=True)
            time.sleep(0.3)
    print("DONE")


if __name__ == '__main__':
    main()
