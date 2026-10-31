# -*- coding: utf-8 -*-
"""
near_duplicate.py — 对 155,547 条 skill 全文做近重复检测（SimHash + banding）。

环境限制：Python 不能直接写文件。结果 JSONL 打到 stdout：
  python analysis\\near_duplicate.py > E:\\temp\\opencode\\near_duplicates.jsonl

方法：
  - 去 YAML frontmatter，转小写，按非字母数字/汉字切词；
  - 5-gram shingles，长文最多均匀抽 256 个；
  - 64-bit SimHash（crc32 两段拼成 64 位）；
  - 4 bands × 16 bits 分桶，候选对算 Hamming；
  - Hamming <= 3 且 sha256 不同 => 近重复对（exact SHA 另算）。
输出：meta / pair / cluster / repo_summary。
"""
import json
import os
import re
import sys
import time
import zlib
import datetime
import collections

import numpy as np

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "external_data", "skills_with_content.jsonl")
BANDS = 4
BAND_BITS = 16
HAMMING_MAX = 3
MAX_BUCKET = 400
MAX_PAIRS = 300000
MAX_SHINGLES = 256
LIMIT = int(os.environ.get("NEAR_LIMIT", "0") or "0")


def log(msg):
    print(f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}",
          file=sys.stderr, flush=True)


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def normalize(s):
    if not s:
        return []
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    if s.startswith("---"):
        parts = s.split("---", 2)
        if len(parts) >= 3:
            s = parts[2]
    s = s.lower()
    s = re.sub(r"[^0-9a-z\u4e00-\u9fff_]+", " ", s)
    return s.split()


def shingles(tokens, k=5, cap=MAX_SHINGLES):
    n = len(tokens) - k + 1
    if n <= 0:
        return [tuple(tokens)] if tokens else []
    if n > cap:
        idx = np.linspace(0, n - 1, cap).astype(int)
        return [tuple(tokens[i:i + k]) for i in idx]
    return [tuple(tokens[i:i + k]) for i in range(n)]


def simhash64(tokens):
    sh = shingles(tokens)
    if not sh:
        return 0
    hs = np.empty(len(sh), dtype=np.uint64)
    for i, t in enumerate(sh):
        b = " ".join(t).encode("utf-8", "ignore")
        a = zlib.crc32(b) & 0xFFFFFFFF
        c = zlib.crc32(b + b"\x01") & 0xFFFFFFFF
        hs[i] = (a << 32) | c
    bits = ((hs[:, None] >> np.arange(64, dtype=np.uint64)) & np.uint64(1)).astype(np.int16)
    sums = bits.sum(axis=0)
    sig = 0
    half = len(sh) / 2.0
    for i, v in enumerate(sums):
        if v >= half:
            sig |= (1 << i)
    return sig


def main():
    t0 = time.time()
    sigs = []
    meta = []
    n = 0
    skipped = 0
    exact = collections.Counter()
    with open(SRC, encoding="utf-8") as f:
        for line in f:
            n += 1
            if LIMIT and n > LIMIT:
                break
            try:
                o = json.loads(line)
            except Exception:
                skipped += 1
                continue
            content = o.get("full_content") or ""
            toks = normalize(content)
            if len(toks) < 20:
                skipped += 1
                continue
            sig = simhash64(toks)
            sigs.append(sig)
            meta.append({
                "id": o.get("id"),
                "repo": o.get("repoFullName"),
                "name": o.get("name"),
                "path": o.get("path"),
                "sha": o.get("sha256_hash"),
                "stars": o.get("stars"),
                "len": o.get("content_length"),
                "sig": sig,
            })
            exact[o.get("sha256_hash")] += 1
            if n % 20000 == 0:
                log(f"read {n}, kept {len(sigs)}, elapsed {time.time()-t0:.0f}s")

    log(f"read done n={n} kept={len(sigs)} skipped={skipped}")
    buckets = [collections.defaultdict(list) for _ in range(BANDS)]
    for i, m in enumerate(meta):
        s = m["sig"]
        for b in range(BANDS):
            v = (s >> (b * BAND_BITS)) & ((1 << BAND_BITS) - 1)
            buckets[b][v].append(i)

    cand = set()
    for b in range(BANDS):
        for v, ids in buckets[b].items():
            if len(ids) < 2:
                continue
            if len(ids) > MAX_BUCKET:
                ids = ids[:MAX_BUCKET]
            for x in range(len(ids)):
                for y in range(x + 1, len(ids)):
                    cand.add((ids[x], ids[y]) if ids[x] < ids[y] else (ids[y], ids[x]))
    log(f"candidates={len(cand)}")

    parent = list(range(len(meta)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    pairs = 0
    emitted = 0
    near_by_doc = collections.Counter()
    for i, j in cand:
        if pairs >= MAX_PAIRS:
            break
        a, b = meta[i], meta[j]
        if a["sha"] and a["sha"] == b["sha"]:
            continue
        d = (a["sig"] ^ b["sig"]).bit_count()
        if d > HAMMING_MAX:
            continue
        pairs += 1
        union(i, j)
        near_by_doc[i] += 1
        near_by_doc[j] += 1
        if emitted < MAX_PAIRS:
            emit({"type": "pair", "a": a, "b": b, "hamming": d,
                  "same_repo": a["repo"] == b["repo"]})
            emitted += 1

    clusters = collections.defaultdict(list)
    for i in range(len(meta)):
        clusters[find(i)].append(i)
    cluster_sizes = sorted((len(v) for v in clusters.values() if len(v) > 1), reverse=True)
    n_clusters = len(cluster_sizes)
    n_in_clusters = sum(cluster_sizes)
    log(f"pairs={pairs} clusters={n_clusters} docs_in_clusters={n_in_clusters}")

    # repo summary
    repo_n = collections.Counter()
    repo_hit = collections.Counter()
    for i, m in enumerate(meta):
        r = m["repo"]
        repo_n[r] += 1
        if near_by_doc.get(i):
            repo_hit[r] += 1
    top_repos = []
    for r, c in repo_hit.most_common(50):
        top_repos.append({"repo": r, "n_skills": repo_n[r], "n_near": c,
                          "share": c / repo_n[r] if repo_n[r] else None})

    # exact duplicate summary
    exact_multi = {h: c for h, c in exact.items() if h and c > 1}
    emit({"type": "meta",
          "generated": datetime.datetime.now().isoformat(timespec="seconds"),
          "n_read": n, "n_kept": len(meta), "n_skipped": skipped,
          "n_candidates": len(cand), "n_near_pairs": pairs,
          "n_clusters": n_clusters, "n_docs_in_clusters": n_in_clusters,
          "max_cluster": cluster_sizes[0] if cluster_sizes else 0,
          "n_exact_hashes": len(exact_multi),
          "n_exact_docs": sum(exact_multi.values()),
          "hamming_max": HAMMING_MAX,
          "elapsed_sec": round(time.time() - t0, 1)})
    emit({"type": "repo_summary", "top": top_repos})
    # top clusters with sample members
    for root, ids in sorted(clusters.items(), key=lambda kv: len(kv[1]), reverse=True)[:200]:
        if len(ids) < 2:
            continue
        members = [{"repo": meta[i]["repo"], "name": meta[i]["name"],
                    "path": meta[i]["path"], "sha": meta[i]["sha"],
                    "stars": meta[i]["stars"], "len": meta[i]["len"]} for i in ids[:20]]
        emit({"type": "cluster", "size": len(ids), "members": members})
    log(f"done elapsed={time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
