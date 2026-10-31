# -*- coding: utf-8 -*-
"""near_recall_bound.py — 用更宽 Hamming 阈值重扫，给出近重复召回的阈上界估计

与 analysis/near_duplicate.py 同一套 simhash/分桶，仅把 HAMMING_MAX 从 3 放宽到 6，
并输出按汉明距离分档的对数。d<=3 的结果应与既有 121,127 对吻合（自检），
d<=6 的对数即为"放宽阈值后近重复宇宙"的上界。
"""
import json, os, re, sys, time, zlib, collections
import numpy as np

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "external_data", "skills_with_content.jsonl")
BANDS, BAND_BITS = 4, 16
HAMMING_MAX = 6
MAX_BUCKET = 400
MAX_SHINGLES = 256


def log(m):
    print(m, file=sys.stderr, flush=True)


def normalize(s):
    if not s:
        return []
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    if s.startswith("---"):
        p = s.split("---", 2)
        if len(p) >= 3:
            s = p[2]
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
    sigs, shas, repos = [], [], []
    n = 0
    with open(SRC, encoding="utf-8") as f:
        for line in f:
            n += 1
            try:
                o = json.loads(line)
            except Exception:
                continue
            toks = normalize(o.get("full_content") or "")
            if len(toks) < 20:
                continue
            sigs.append(simhash64(toks))
            shas.append(o.get("sha256_hash"))
            repos.append(o.get("repoFullName"))
            if n % 30000 == 0:
                log(f"read {n} kept {len(sigs)} {time.time()-t0:.0f}s")
    log(f"read done n={n} kept={len(sigs)}")

    buckets = [collections.defaultdict(list) for _ in range(BANDS)]
    for i, s in enumerate(sigs):
        for b in range(BANDS):
            buckets[b][(s >> (b * BAND_BITS)) & ((1 << BAND_BITS) - 1)].append(i)

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
    log(f"candidates={len(cand)} {time.time()-t0:.0f}s")

    hist = collections.Counter()
    cross = collections.Counter()
    for i, j in cand:
        if shas[i] and shas[i] == shas[j]:
            continue
        d = (sigs[i] ^ sigs[j]).bit_count()
        if d > HAMMING_MAX:
            continue
        hist[d] += 1
        if repos[i] != repos[j]:
            cross[d] += 1

    print(json.dumps({
        "docs": len(sigs),
        "candidates": len(cand),
        "pairs_by_hamming": dict(sorted(hist.items())),
        "pairs_le3": sum(v for k, v in hist.items() if k <= 3),
        "pairs_le6": sum(hist.values()),
        "cross_by_hamming": dict(sorted(cross.items())),
        "cross_le3": sum(v for k, v in cross.items() if k <= 3),
        "cross_le6": sum(cross.values()),
        "elapsed_s": round(time.time() - t0, 1),
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
