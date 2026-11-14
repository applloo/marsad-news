# -*- coding: utf-8 -*-
"""بحث شامل في كل المصادر على GitHub Actions (زر واحد في التطبيق).
بيقرا الاعدادات من الـGist (marsad_search_cfg.json) وبيبحث في كل قسم (اسرائيلية/امريكية/بريطانية/تركيا وايران واثيوبيا + الكتّاب)
بنفس طريقة التابات بالظبط، وبيحفظ كل نتيجة تحت اسم تابها في marsad_results.json، فتظهر في التاب زي ما هي وتدخل في الربط.
النتيجة بتفضل محفوظة لحد ما تشغّل بحث جديد. لا يستهلك رصيد Anthropic."""
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import core
import store
import writers as writers_mod
from sources import ARABIC, ISRAEL, REGION, UK, USA, source_country
from writers import WRITERS

CFG, STATUS, RES = "marsad_search_cfg.json", "marsad_search_job.json", "marsad_results.json"
# القسم: (المصادر، رمز بلد GDELT، رمز بلد أخبار Google)
SCOPES = {"il": (ISRAEL, "IS", "IL"), "us": (USA, "US", "US"), "uk": (UK, "UK", "UK"), "rg": (REGION, None, "US")}
WR_GROUPS = {"wr": ["US", "UK", "IL"], "wa": ["SA", "GCC", "EG", "AR"]}
LABELS = {}
for _g in (ISRAEL, USA, UK, REGION, ARABIC):
    for _entries in _g.values():
        for _label, _doms, _ in _entries:
            for _d in _doms.split("|"):
                LABELS.setdefault(_d, _label)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def source_name(domain):
    d = (domain or "").lower().replace("www.", "")
    for dom, label in LABELS.items():
        if d == dom or d.endswith("." + dom):
            return label
    return d


def update_meta(data, sel):
    counts, ctry = {}, {}
    for a in data["items"]:
        n = source_name(a.get("domain", ""))
        counts[n] = counts.get(n, 0) + 1
        ctry[n] = source_country(a.get("domain", ""))
    data["counts"], data["ctry"] = counts, ctry
    data["silent"] = [lbl for lbl, _, _ in (sel or []) if lbl not in counts]


def _hl(matchers):
    return sorted({s for alts in matchers for stems in alts for s in stems}, key=len, reverse=True)


def _by_url(items):
    out, seen = [], set()
    for a in items:
        k = (a.get("url") or "").split("?")[0].rstrip("/")
        if k and k not in seen:
            seen.add(k)
            out.append(a)
    return sorted(out, key=lambda a: a.get("seendate", ""), reverse=True)


def search_scope(key, groups, gd_country, gn_country, custom, terms, cfg, log):
    sel = [e for g in groups.values() for e in g] + [(x["label"], x["domain"], x["lang"]) for x in custom if x.get("group") == key]
    days = float(cfg.get("days") or 3)
    dcount = max(1, int(-(-days // 1)))
    joiner, match = cfg.get("joiner") or "OR", cfg.get("match") or core.MATCH_MODES[0]
    max_rec = int(cfg.get("max_rec") or 40)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    data = {"items": [], "errors": [], "used": [], "summaries": {}, "counts": {}, "silent": [], "hidden": 0, "hl": []}

    if not terms:  # من غير كلمات: اعرض كل ما نُشر (عناوين المواقع مباشرة + أخبار Google)
        d_items, d_notes = core.direct_headlines(sel, dcount)
        g_items, g_notes = core.gnews_site_search(sel, dcount, terms=None, joiner=joiner, country=gn_country, max_items=200)
        items = core.merge_items(d_items, g_items)
        core.translate_titles(items)
        data.update(items=_by_url(items), used=d_notes + g_notes)
        if not items:
            data["errors"] = ["لم تُرجع المصادر عناوين في الفترة دي."]
        update_meta(data, sel)
        return data

    seed, gnotes = [], []
    try:
        seed, gnotes = core.gnews_site_search(sel, dcount, terms=terms, joiner=joiner, country=gn_country)
        core.translate_titles(seed)
    except Exception as e:
        gnotes = [f"Google News تعذّر: {type(e).__name__}"]
    jobs = core.jobs_for_sources(sel, gd_country)
    matchers = core.make_matchers(terms, [j["code"] for j in jobs])
    hl = _hl(matchers)
    gd_items = []
    for ev in core.search_iter(terms, joiner, match, jobs, start, end, max_rec, "الكل"):
        data["errors"], data["used"] = ev["errors"], ev["used"]
        if ev["items"] is not None:
            gd_items = ev["items"]
    core.translate_titles([a for a in gd_items if "title_ar" not in a])
    items = _by_url(gd_items + seed)
    data["used"] = list(data["used"]) + gnotes
    # عناوين الخلاصات المباشرة
    try:
        d_items, d_notes = core.direct_headlines(sel, dcount)
        cm = core.make_matchers(terms, core.codes_for(sel))
        hits = [a for a in d_items if core.find_mentions(a.get("title", ""), cm, joiner)[0]]
        core.translate_titles(hits)
        have = {a["url"].split("?")[0].rstrip("/") for a in items}
        new = [a for a in hits if a["url"].split("?")[0].rstrip("/") not in have]
        items = _by_url(items + new)
        data["used"] += d_notes + [f"بحث العناوين المباشر ⟵ فُحص {len(d_items)} عنواناً ⟵ طابق {len(hits)} (جديد: {len(new)})"]
    except Exception as e:
        data["used"].append(f"الخلاصات المباشرة تعذّرت: {type(e).__name__}")
    # بحث داخل نص المقالات (اختياري، أبطأ)
    if cfg.get("use_body"):
        try:
            d2, n2 = core.direct_headlines(sel, dcount)
            g2, n3 = core.gnews_site_search(sel, dcount, terms=None, joiner=joiner, country=gn_country, max_items=200)
            pool = core.merge_items(d2, g2)[: int(cfg.get("body_n") or 60)]
            for i in range(0, len(pool), 8):
                core.enrich_items(pool[i:i + 8], matchers, joiner, limit=8)
            hits = [a for a in pool if a.get("found")]
            core.translate_titles(hits)
            have = {a["url"] for a in items}
            items = _by_url(items + [a for a in hits if a["url"] not in have])
            data["used"].append(f"بحث النص ⟵ قُرئ {len(pool)} مقالاً ⟵ وُجدت الكلمات في {len(hits)}")
        except Exception as e:
            data["used"].append(f"بحث النص تعذّر: {type(e).__name__}")
    # فحص نصوص المقالات وإخفاء اللي مفيهوش كلمتك
    if cfg.get("verify", True) and items:
        total = min(len(items), 80)
        for i in range(0, total, 8):
            core.enrich_items(items[i:i + 8], matchers, joiner, limit=8)
    if cfg.get("hide_nomatch", True):
        keep = [a for a in items if not (a.get("fetched") and not a.get("found"))]
        data["hidden"] = len(items) - len(keep)
        items = keep
    data.update(items=items, hl=hl)
    if items:
        data["errors"] = []
    update_meta(data, sel)
    return data


def search_writers(key, codes, terms, cfg, custom_writers, log):
    allw = WRITERS + [writers_mod.W(**dict(sp, default=True)) for sp in custom_writers]
    ws = [w for w in allw if w["country"] in codes and w.get("default")]
    days = float(cfg.get("days") or 3)
    items, notes = core.fetch_writers(ws, max(1, int(-(-days // 1))))
    core.translate_titles(items)
    joiner = cfg.get("joiner") or "OR"
    matchers = []
    if terms:
        matchers = core.make_matchers(terms, ["ar"] if key == "wa" else ["en", "iw"])
        if key == "wa":
            items = [a for a in items if core.find_mentions(a.get("title", ""), matchers, joiner)[0]]
        else:
            core.enrich_items(items, matchers, joiner, limit=60)
            items = [a for a in items if not (a.get("fetched") and not a.get("found"))]
    counts = {}
    for a in items:
        counts[a["writer"]] = counts.get(a["writer"], 0) + 1
    chosen = [w["name_ar"] for w in ws]
    return {"items": _by_url(items), "errors": [] if items else ["لم يُعثر على شيء في الفترة دي."], "used": notes,
            "summaries": {}, "counts": counts, "silent": [n for n in chosen if n not in counts], "hidden": 0, "hl": _hl(matchers)}


def main():
    tok, gid = os.getenv("GIST_TOKEN"), os.getenv("GIST_ID")
    if not (tok and gid):
        sys.exit("GIST_TOKEN و GIST_ID مطلوبان")
    cfg = store.load_file(tok, gid, CFG, {}) or {}
    terms = [t.strip() for t in re.split(r"[,،;\n]+", cfg.get("terms") or "") if t.strip()]
    keys = [k for k in (cfg.get("scopes") or list(SCOPES) + list(WR_GROUPS)) if k in SCOPES or k in WR_GROUPS]
    try:
        st = store.load(tok, gid)
        custom, custom_w = st.get("sources", []), st.get("writers", [])
    except Exception:
        custom, custom_w = [], []
    status = {"state": "running", "started": now_iso(), "updated": now_iso(), "terms": terms, "days": cfg.get("days"),
              "scopes": keys, "done": [], "counts": {}, "errors": {}}

    def put_status():
        status["updated"] = now_iso()
        try:
            store.save_file(tok, gid, STATUS, status)
        except Exception as e:
            print("status save failed", e, flush=True)

    def save_result(key, data):
        data = {**data, "partial": False, "saved_at": now_iso(), "job": True, "job_terms": terms}
        body = json.loads(json.dumps(data, ensure_ascii=False, default=str))
        body["items"] = body.get("items", [])[:200]
        for attempt in range(3):
            try:
                allres = store.load_file(tok, gid, RES, {}) or {}
                allres[key] = body
                store.save_file(tok, gid, RES, allres)
                return
            except Exception as e:
                print("save retry", e, flush=True)
                time.sleep(3)

    put_status()
    for key in keys:
        t0 = time.time()
        try:
            if key in SCOPES:
                groups, gd, gn = SCOPES[key]
                data = search_scope(key, groups, gd, gn, custom, terms, cfg, print)
            else:
                data = search_writers(key, WR_GROUPS[key], terms, cfg, custom_w, print)
            save_result(key, data)
            status["counts"][key] = len(data["items"])
            print(f"{key}: {len(data['items'])} نتيجة في {int(time.time() - t0)}ث", flush=True)
        except Exception as e:
            status["errors"][key] = f"{type(e).__name__}: {e}"
            print(f"{key} فشل: {e}", flush=True)
        status["done"].append(key)
        put_status()
    status["state"] = "done"
    status["finished"] = now_iso()
    put_status()
    print("تم", flush=True)


if __name__ == "__main__":
    main()
