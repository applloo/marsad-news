# -*- coding: utf-8 -*-
"""التقرير اليومي التلقائي. يعمل خارج Streamlit (GitHub Actions كل صباح) ويكتب النتيجة في الـGist
(ملف marsad_reports.json) فيعرضها التطبيق في تاب «التقرير اليومي».
الأسرار المطلوبة: GIST_TOKEN و GIST_ID. لا يستخدم أي ذكاء اصطناعي ولا يستهلك رصيد Anthropic."""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

import core
import intel
from sources import ARABIC, EGYPT_ARABIC, ISRAEL, REGION, UK, USA

REPORTS_FILE = "marsad_reports.json"
KEEP_DAYS = 7
PER_FILE = 30


def all_sources():
    """(قائمة البحث، خريطة الدومين ← (المنظور، النوع))"""
    meta, sel = {}, []
    for n, d, sd, k, _f in intel.SOURCES:
        sel.append((n, d, "en"))
        meta[d] = (sd, k)
    seen = {d for _, d, _ in sel}
    for sd, groups in (("il", ISRAEL), ("us", USA), ("uk", UK)):
        for entries in groups.values():
            for n, d, lg in entries:
                if "en" in core.entry_langs(lg) and d not in seen:
                    sel.append((n, d, "en"))
                    seen.add(d)
                    for x in d.split("|"):
                        meta.setdefault(x, (sd, "media"))
    for entries in ARABIC.values():
        for n, d, lg in entries:
            sel.append((n, d, "ar"))
            meta.setdefault(d, ("eg" if d in EGYPT_ARABIC else "ar", "media"))
    for entries in REGION.values():
        for n, d, lg in entries:
            sel.append((n, d, lg))
            meta.setdefault(d, ("reg", "media"))
    return sel, meta


def collect(file_name, sel, meta, days=1):
    f = intel.FILES[file_name]
    terms = f["terms"] + f["egypt"]
    items, _notes = core.gnews_site_search(sel, days, terms=terms, joiner="OR", country="US", max_items=80)
    if len(items) < 8 and days < 2:  # يوم هادئ: وسّع إلى يومين
        items, _notes = core.gnews_site_search(sel, 2, terms=terms, joiner="OR", country="US", max_items=80)
    for a in items:
        sd, k = next(((v[0], v[1]) for dd, v in meta.items() if core.domain_match(a["domain"], [dd])), ("osint", "think"))
        a["ctype"] = intel.classify_intel(a["title"], a["url"], k)
        a["side"], a["kind"] = sd, k
        a["egypt"] = bool(intel.EGYPT_RE.search(a["title"]))
    return items


def rank(a):
    # مصر أولاً ثم الجهات المتخصصة/الرسمية ثم الأحدث
    return (a["egypt"], a["kind"] in ("think", "official", "data"), a.get("seendate", ""))


def pick(items, n=PER_FILE):
    top = sorted(items, key=rank, reverse=True)[:n]
    core.translate_titles(top)
    keep = ("title_ar", "title", "url", "domain", "side", "ctype", "egypt", "seendate")
    return [{k: a.get(k, "") for k in keep} for a in sorted(top, key=lambda a: a.get("seendate", ""), reverse=True)]


def _row(a):
    d = a.get("domain", "")
    return f"- {a['title_ar']} ({d})"


def brief_for(file_name, items):
    """نشرة بلا ذكاء اصطناعي ولا تكلفة: ترتيب وتجميع للعناوين نفسها"""
    out = []
    top = [a for a in items if a["ctype"] != "تسريب غير مؤكد"][:6]
    if top:
        out += ["## أهم العناوين", *[_row(a) for a in top], ""]
    eg = [a for a in items if a["egypt"]][:8]
    out += ["## ما يخص مصر", *([_row(a) for a in eg] or ["- لا عناوين تخص مصر في هذا الملف اليوم."]), ""]
    sides = {}
    for a in items:
        sides.setdefault(a["side"], []).append(a)
    if len(sides) > 1:
        out.append("## تباين المنظورات (عنوان من كل منظور)")
        for sd, lst in sides.items():
            out.append(f"- **{intel.SIDES.get(sd, sd)}** ({len(lst)}): {lst[0]['title_ar']}")
        out.append("")
    leaks = [a for a in items if a["ctype"] == "تسريب غير مؤكد"][:4]
    if leaks:
        out += ["## يُنقل أن… (غير مؤكد)", *[_row(a) for a in leaks], ""]
    return "\n".join(out).strip()


def overview(files):
    out = ["## نشرة اليوم"]
    for n, f in files.items():
        if f.get("items"):
            out.append(f"- **{n}**: {f.get('total', len(f['items']))} عنواناً، منها {f.get('egypt', 0)} يخص مصر")
    eg = [a for f in files.values() for a in f.get("items", []) if a.get("egypt")][:6]
    if eg:
        out += ["", "## أبرز ما يخص مصر اليوم", *[_row(a) for a in eg]]
    return "\n".join(out)


def build(files, log=print):
    sel, meta = all_sources()
    out = {"files": {}, "overview": ""}
    for fn in files:
        try:
            raw = collect(fn, sel, meta)
            items = pick(raw)
        except Exception as e:  # ملف واحد لا يُسقط التقرير كله
            log(f"! {fn}: {type(e).__name__} {e}")
            out["files"][fn] = {"brief": "", "items": [], "error": f"{type(e).__name__}"}
            continue
        out["files"][fn] = {"brief": brief_for(fn, items) if items else "", "items": items, "total": len(raw),
                            "egypt": sum(1 for a in raw if a["egypt"])}
        log(f"{fn}: {len(raw)} عنواناً، اخترنا {len(items)}")
        time.sleep(1)
    out["overview"] = overview(out["files"])
    return out


def merge_into(existing, report, today, keep=KEEP_DAYS):
    arch = dict((existing or {}).get("archive") or {})
    arch[today] = report
    for d in sorted(arch)[:-keep]:
        arch.pop(d)
    return {"latest": today, "archive": arch}


def load_gist(token, gist_id):
    r = requests.get("https://api.github.com/gists/" + gist_id, headers={"Authorization": f"Bearer {token}", "User-Agent": "marsad-daily"}, timeout=30)
    r.raise_for_status()
    f = (r.json().get("files") or {}).get(REPORTS_FILE)
    if not f:
        return {}
    txt = f.get("content") or ""
    if f.get("truncated") and f.get("raw_url"):
        txt = requests.get(f["raw_url"], timeout=30).text
    try:
        return json.loads(txt or "{}")
    except ValueError:
        return {}


def save_gist(token, gist_id, data):
    r = requests.patch("https://api.github.com/gists/" + gist_id, headers={"Authorization": f"Bearer {token}", "User-Agent": "marsad-daily"},
                       json={"files": {REPORTS_FILE: {"content": json.dumps(data, ensure_ascii=False)}}}, timeout=40)
    r.raise_for_status()


def main():
    token, gid = os.getenv("GIST_TOKEN"), os.getenv("GIST_ID")
    if not (token and gid):
        sys.exit("GIST_TOKEN و GIST_ID مطلوبان")
    today = datetime.now(core.TZ).strftime("%Y-%m-%d")
    files = [f for f in os.getenv("DAILY_FILES", "").split("|") if f in intel.FILES] or list(intel.FILES)
    rep = build(files)
    rep["generated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not any(v.get("items") for v in rep["files"].values()):
        sys.exit("لم تُرجع أي مصادر نتائج؛ لن أكتب تقريراً فارغاً فوق السابق.")
    save_gist(token, gid, merge_into(load_gist(token, gid), rep, today))
    print("تم الحفظ:", today)


if __name__ == "__main__":
    main()
