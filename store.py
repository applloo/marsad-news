# -*- coding: utf-8 -*-
"""تخزين دائم اختياري: المحفوظات + المصادر والكتّاب المضافون، داخل Gist خاص في GitHub.
بدون إعداد (GITHUB_TOKEN و GIST_ID في Secrets) يعمل التطبيق بالذاكرة المؤقتة فقط."""
import json

import requests

FILE = "marsad_store.json"
API = "https://api.github.com/gists/"


def empty():
    return {"saved": [], "sources": [], "writers": []}


def normalize(data):
    out = empty()
    if isinstance(data, dict):
        for k in out:
            if isinstance(data.get(k), list):
                out[k] = data[k]
    return out


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": "marsad-news"}


def load(token, gist_id):
    r = requests.get(API + gist_id, headers=_headers(token), timeout=20)
    r.raise_for_status()
    f = (r.json().get("files") or {}).get(FILE)
    if not f:
        return empty()
    content = f.get("content") or ""
    if f.get("truncated") and f.get("raw_url"):
        content = requests.get(f["raw_url"], headers=_headers(token), timeout=20).text
    try:
        return normalize(json.loads(content or "{}"))
    except ValueError:
        return empty()


def save(token, gist_id, data):
    body = {"files": {FILE: {"content": json.dumps(data, ensure_ascii=False)}}}
    r = requests.patch(API + gist_id, headers=_headers(token), json=body, timeout=25)
    r.raise_for_status()


def merge(base, extra):
    """يدمج نسخة احتياطية في البيانات الحالية دون تكرار"""
    base, extra = normalize(base), normalize(extra)
    seen = {x.get("url") for x in base["saved"]}
    base["saved"] += [x for x in extra["saved"] if x.get("url") not in seen]
    seen = {(x.get("domain"), x.get("group")) for x in base["sources"]}
    base["sources"] += [x for x in extra["sources"] if (x.get("domain"), x.get("group")) not in seen]
    seen = {x.get("id") for x in base["writers"]}
    base["writers"] += [x for x in extra["writers"] if x.get("id") not in seen]
    return base
