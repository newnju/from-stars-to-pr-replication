# -*- coding: utf-8 -*-
"""botcheck.py — 机器人判定口径核对"""
import json
import re
import collections

SUB = re.compile("bot", re.I)
STRICT = re.compile(r"(\[bot\]$|-bot$|^dependabot|^renovate|^github-actions|^codecov|^greenkeeper|^mergify|^imgbot|^allcontributors)", re.I)

n = 0
sub_hit = 0
strict_hit = 0
sub_only = []
strict_authors = collections.Counter()
sub_authors = collections.Counter()

for line in open(r"E:/temp/opencode/pr_comments.jsonl", encoding="utf-8"):
    d = json.loads(line)
    if d.get("type") != "repo":
        continue
    for pr in d.get("prs") or []:
        for c in pr.get("comments") or []:
            a = c.get("author") or ""
            n += 1
            s1 = bool(SUB.search(a))
            s2 = bool(STRICT.match(a))
            if s1:
                sub_hit += 1
                sub_authors[a] += 1
            if s2:
                strict_hit += 1
                strict_authors[a] += 1
            if s2 and not s1:
                sub_only.append(a)

print("comments:", n)
print("substring 'bot':", sub_hit, round(100 * sub_hit / n, 2), "%")
print("strict:", strict_hit, round(100 * strict_hit / n, 2), "%")
print("strict-but-not-substring authors:", collections.Counter(sub_only).most_common(5))
print("top strict:", strict_authors.most_common(8))
print("top substring:", sub_authors.most_common(8))
