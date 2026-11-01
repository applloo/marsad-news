# -*- coding: utf-8 -*-
"""التقرير اليومي التلقائي. يعمل خارج Streamlit (GitHub Actions كل صباح) ويكتب النتيجة في الـGist
(ملف marsad_reports.json) فيعرضها التطبيق في تاب «التقرير اليومي».
الأسرار المطلوبة: GIST_TOKEN و GIST_ID. لا يستخدم أي ذكاء اصطناعي ولا يستهلك رصيد Anthropic."""
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests

import core
import intel
import links
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


STOP = {"news", "with", "from", "that", "this", "attacks", "military", "assessment"}


def term_stems(terms):
    """جذور كلمات الملف بالإنجليزية والعربية، لحذف العناوين التي لا علاقة لها بالملف"""
    en, ar = set(), set()
    for t in terms:
        for w in re.findall(r"[A-Za-z]{4,}", t):
            if w.lower() not in STOP:
                en.add(w.lower()[:5])
        try:
            t_ar = core.tr(t, "en", "ar")
        except Exception:
            t_ar = ""
        for w in re.findall(r"[\u0600-\u06FF]{3,}", t_ar):
            w = w[2:] if w.startswith("ال") and len(w) > 4 else w
            ar.add(w[:4])
    return en, ar


def relevant(a, en, ar):
    if a["egypt"] or a["kind"] in ("think", "official", "data"):
        return True  # المؤسسات المتخصصة وما يخص مصر نبقيه دائماً
    t = a["title"].lower()
    return any(x in t for x in en) or any(x in a.get("title_ar", "") for x in ar)


def snippet(a):
    """جملتان من أول المقال مترجمتان للعربية (إن أمكن فتح المقال)"""
    try:
        if "news.google.com" in a["url"]:
            return
        art = core.fetch_article(a["url"])
        if not art:
            return
        sents = [x.strip() for x in re.split(r"(?<=[.!?؟])\s+|\n+", art["text"]) if len(x.strip()) > 50]
        sents = [x for x in sents if not re.search(r"cookie|subscribe|sign in|javascript|©|newsletter", x, re.I)][:2]
        if sents:
            a["snip_ar"] = core.tr(" ".join(sents)[:600], "auto", "ar")
    except Exception:
        pass


def pick(items, terms, n=PER_FILE, snip_n=5):
    en, ar = term_stems(terms)
    cand = sorted(items, key=rank, reverse=True)[: n * 3]
    core.translate_titles(cand)
    ok = [a for a in cand if relevant(a, en, ar)]
    if len(ok) < 8:  # يوم هادئ: لا نُفرط في الحذف
        ok = cand
    top = ok[:n]
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(snippet, [a for a in top if a["ctype"] != "تسريب غير مؤكد"][:snip_n]))
    keep = ("title_ar", "title", "url", "domain", "side", "ctype", "egypt", "seendate", "snip_ar")
    return [{k: a.get(k, "") for k in keep} for a in sorted(top, key=lambda a: a.get("seendate", ""), reverse=True)]


def _row(a):
    d = a.get("domain", "")
    out = f"- {a['title_ar']} ({d})"
    if a.get("snip_ar"):
        out += f"\n  > {a['snip_ar']}"
    return out


def brief_for(file_name, items):
    """نشرة بلا ذكاء اصطناعي ولا تكلفة: ترتيب وتجميع للعناوين نفسها"""
    out = []
    top = sorted([a for a in items if a["ctype"] != "تسريب غير مؤكد"], key=lambda a: bool(a.get("snip_ar")), reverse=True)[:6]
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


def link_threads(pool, log=print):
    """خيوط الربط السياسي: تجمع من كل الملفات ما يتصل بكل خيط (بالأسماء والكلمات المشتركة)"""
    out = {}
    links.tag_pool(pool)
    for t in links.THREADS:
        name = "🔗 " + t
        its = links.thread_items(pool, t)
        if not its:
            out[name] = {"brief": "", "items": [], "total": 0, "egypt": 0}
            continue
        info = links.analyse(its, t, pool)
        top = sorted(its, key=lambda a: links._score(a, t), reverse=True)[:PER_FILE]
        core.translate_titles([a for a in top if not a.get("title_ar")])
        with ThreadPoolExecutor(4) as ex:
            list(ex.map(snippet, [a for a in top if a["ctype"] != "تسريب غير مؤكد" and not a.get("snip_ar")][:4]))

        def row(a, t=t):
            tags = "، ".join(a["threads"][t][:3])
            return _row(a) + f" — 🏷️ {tags}"

        shown = sorted([a for a in top if a["ctype"] != "تسريب غير مؤكد"], key=lambda a: (bool(a.get("snip_ar")), links._score(a, t)), reverse=True)[:6]
        keep = ("title_ar", "title", "url", "domain", "side", "ctype", "egypt", "seendate", "snip_ar")
        items = []
        for a in sorted(top, key=lambda a: a.get("seendate", ""), reverse=True):
            d = {k: a.get(k, "") for k in keep}
            d["ents"] = a["threads"][t]
            items.append(d)
        out[name] = {"brief": links.brief(t, its, info, shown, row, extra=top), "items": items, "total": len(its),
                     "egypt": sum(1 for a in its if a.get("egypt"))}
        log(f"{name}: {len(its)} عنواناً")
    return out


def build(files, log=print):
    sel, meta = all_sources()
    out = {"files": {}, "overview": ""}
    pool = {}
    for fn in files:
        try:
            raw = collect(fn, sel, meta)
            for a in raw:
                pool.setdefault(a["url"], a)
            items = pick(raw, intel.FILES[fn]["terms"] + intel.FILES[fn]["egypt"])
        except Exception as e:  # ملف واحد لا يُسقط التقرير كله
            log(f"! {fn}: {type(e).__name__} {e}")
            out["files"][fn] = {"brief": "", "items": [], "error": f"{type(e).__name__}"}
            continue
        out["files"][fn] = {"brief": brief_for(fn, items) if items else "", "items": items, "total": len(raw),
                            "egypt": sum(1 for a in raw if a["egypt"])}
        log(f"{fn}: {len(raw)} عنواناً، اخترنا {len(items)}")
        time.sleep(1)
    try:
        out["files"].update(link_threads(list(pool.values()), log))
    except Exception as e:  # الربط لا يُسقط التقرير
        log(f"! الربط: {type(e).__name__} {e}")
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
