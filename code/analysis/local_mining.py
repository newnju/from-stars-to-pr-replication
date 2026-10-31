# -*- coding: utf-8 -*-
"""
local_mining.py — 本地补 RQ1/RQ2：exact SHA、仓库类型、frontmatter、静态安全标记。

环境限制：Python 不能直接写文件。结果 JSONL 打到 stdout：
  python analysis\\local_mining.py > E:\\temp\\opencode\\local_mining.jsonl

输出行：
  {"type":"repo", ...}        每个 repo 的复制画像/类型
  {"type":"flag", ...}        被静态规则标记的 skill（最多 50k）
  {"type":"summary", ...}     总体比例
"""
import json
import os
import re
import sys
import time
import datetime
import collections

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "external_data", "skills_with_content.jsonl")
LOCAL_LIMIT = int(os.environ.get("LOCAL_LIMIT", "0") or "0")

SECRET = [
    ("aws_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA|OPENSSH|EC|DSA) PRIVATE KEY-----")),
    ("generic_secret", re.compile(
        r"(?:api[_-]?key|secret|password|access[_-]?token|auth[_-]?token)"
        r"\s*[:=]\s*['\"][A-Za-z0-9_\-]{20,}['\"]", re.I)),
]
DANGER = [
    ("pipe_shell", re.compile(r"(?:curl|wget)[^\n]{0,240}\|\s*(?:bash|sh|zsh)", re.I)),
    ("rm_rf_root", re.compile(r"rm\s+-rf\s+/(?:\s|$)")),
    ("eval_exec", re.compile(r"\b(?:eval|exec)\s*\(")),
    ("os_system", re.compile(r"os\.system|subprocess\.(?:run|Popen|call)")),
    ("sudo", re.compile(r"\bsudo\b")),
    ("chmod_777", re.compile(r"chmod\s+777")),
    ("netcat_exec", re.compile(r"\bnc\s+-e|\bncat\s+.*-e")),
    ("dev_tcp", re.compile(r"/dev/tcp/")),
]

REGISTRY_KW = ("registry", "marketplace", "catalog", "index", "aggregator", "feed", "hub")
MIRROR_KW = ("mirror", "backup", "archive", "snapshot", "clone")
COLLECTION_KW = ("awesome", "collection", "curated", "resources", "links", "list")


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def log(msg):
    print(f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}",
          file=sys.stderr, flush=True)


def frontmatter(content):
    if not content.startswith("---"):
        return 0, False, False, False, False
    end = content.find("\n---", 3)
    if end < 0:
        return 0, False, False, False, False
    fm = content[3:end]
    keys = re.findall(r"^([A-Za-z0-9_-]+)\s*:", fm, re.M)
    kset = {k.lower() for k in keys}
    return len(keys), ("license" in kset), ("allowed-tools" in kset or "allowed_tools" in kset), \
        ("version" in kset), ("author" in kset)


def main():
    t0 = time.time()
    sha_repos = collections.defaultdict(set)
    repo_hashes = collections.defaultdict(set)
    repo_n = collections.Counter()
    repo_stars = {}
    repo_paths = collections.defaultdict(set)
    repo_fm_valid = collections.Counter()
    repo_fm_fields = collections.Counter()
    repo_fm_license = collections.Counter()
    repo_fm_tools = collections.Counter()
    repo_fm_version = collections.Counter()
    repo_fm_author = collections.Counter()
    repo_flags = collections.Counter()
    flag_counts = collections.Counter()
    flags_out = 0
    n = 0
    bad = 0
    doc_shas = []

    with open(SRC, encoding="utf-8") as f:
        for line in f:
            n += 1
            if LOCAL_LIMIT and n > LOCAL_LIMIT:
                break
            try:
                o = json.loads(line)
            except Exception:
                bad += 1
                continue
            repo = o.get("repoFullName") or "?"
            sha = o.get("sha256_hash")
            content = o.get("full_content") or ""
            repo_n[repo] += 1
            if repo not in repo_stars:
                try:
                    repo_stars[repo] = int(o.get("stars") or 0)
                except Exception:
                    repo_stars[repo] = 0
            if sha:
                sha_repos[sha].add(repo)
                repo_hashes[repo].add(sha)
                doc_shas.append(sha)
            p = o.get("path") or ""
            if p:
                repo_paths[repo].add(p.split("/")[0])
            nf, lic, tools, ver, auth = frontmatter(content)
            if nf:
                repo_fm_valid[repo] += 1
                repo_fm_fields[repo] += nf
                repo_fm_license[repo] += int(lic)
                repo_fm_tools[repo] += int(tools)
                repo_fm_version[repo] += int(ver)
                repo_fm_author[repo] += int(auth)

            flags = []
            for name, pat in SECRET:
                if pat.search(content):
                    flags.append(name)
            for name, pat in DANGER:
                if pat.search(content):
                    flags.append(name)
            if flags:
                for x in flags:
                    flag_counts[x] += 1
                repo_flags[repo] += 1
                if flags_out < 50000:
                    emit({"type": "flag", "repo": repo, "name": o.get("name"),
                          "path": o.get("path"), "sha": sha, "flags": flags})
                    flags_out += 1
            if n % 20000 == 0:
                log(f"read {n}, repos {len(repo_n)}, elapsed {time.time()-t0:.0f}s")

    log(f"read done n={n} repos={len(repo_n)} bad={bad}")

    n_docs = sum(repo_n.values())
    n_shared_docs = sum(1 for h in doc_shas if h and len(sha_repos[h]) > 1)
    n_cross = 0
    for h, rs in sha_repos.items():
        if len(rs) > 1:
            n_cross += 1
    repo_rows = []
    for repo, ns in repo_n.items():
        hs = repo_hashes.get(repo, set())
        nu = len(hs)
        shared = sum(1 for h in hs if len(sha_repos[h]) > 1)
        share = shared / nu if nu else None
        name = repo.lower()
        ev = []
        typ = "unknown"
        if nu == 0:
            typ = "unknown"
        elif any(k in name for k in REGISTRY_KW) and (share or 0) >= 0.3:
            typ = "registry"
            ev.append("name_registry")
        elif any(k in name for k in MIRROR_KW) and (share or 0) >= 0.3:
            typ = "mirror"
            ev.append("name_mirror")
        elif any(k in name for k in COLLECTION_KW) and ns >= 20:
            typ = "collection"
            ev.append("name_collection")
        elif (share or 0) >= 0.9 and ns >= 5:
            typ = "mirror"
            ev.append("share>=0.9")
        elif (share or 0) >= 0.1:
            typ = "mixed"
            ev.append("share>=0.1")
        else:
            typ = "original"
            ev.append("share<0.1")
        repo_rows.append({
            "type": "repo", "repo": repo, "stars": repo_stars.get(repo, 0),
            "n_skills": ns, "n_unique_sha": nu, "n_shared_sha": shared,
            "share_cross": share, "n_dirs": len(repo_paths.get(repo, set())),
            "repo_type": typ, "evidence": ev,
            "fm_valid": repo_fm_valid.get(repo, 0),
            "fm_rate": repo_fm_valid.get(repo, 0) / ns if ns else None,
            "fm_fields_mean": repo_fm_fields.get(repo, 0) / ns if ns else None,
            "fm_license": repo_fm_license.get(repo, 0),
            "fm_allowed_tools": repo_fm_tools.get(repo, 0),
            "fm_version": repo_fm_version.get(repo, 0),
            "fm_author": repo_fm_author.get(repo, 0),
            "n_flagged": repo_flags.get(repo, 0),
        })

    repo_rows.sort(key=lambda r: (-r["n_skills"], r["repo"]))
    for r in repo_rows:
        emit(r)

    # 精确按行统计：每行 sha 出现在 >=2 个 repo
    # 这里用 repo_hashes 无法还原行数，重新算一个近似下界：
    # n_shared_docs 已按 sha 的 repo 行数求和，可能重复；保留为 upper bound。
    by_type = collections.Counter(r["repo_type"] for r in repo_rows)
    by_type_stars = collections.Counter()
    for r in repo_rows:
        by_type_stars[r["repo_type"]] += r["stars"]
    total_stars = sum(repo_stars.values())
    emit({"type": "summary",
          "generated": datetime.datetime.now().isoformat(timespec="seconds"),
          "n_docs": n_docs, "n_repos": len(repo_rows), "bad_json": bad,
          "n_sha": len(sha_repos), "n_cross_sha": n_cross,
          "cross_sha_share": n_cross / len(sha_repos) if sha_repos else None,
          "shared_docs_exact": n_shared_docs,
          "shared_docs_share": n_shared_docs / n_docs if n_docs else None,
          "by_type_repos": dict(by_type),
          "by_type_stars": dict(by_type_stars),
          "total_stars": total_stars,
          "security_flag_counts": dict(flag_counts),
          "n_flagged_skills": flags_out,
          "elapsed_sec": round(time.time() - t0, 1)})
    log(f"done repos={len(repo_rows)} elapsed={time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
