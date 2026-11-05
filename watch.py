# -*- coding: utf-8 -*-
"""تقرير مخصص بالكلمات والعلاقات: كل سطر موضوع (مثل «اثيوبيا + مصر»)، يُبحث عنه في عناوين خلاصات المصادر المباشرة وفي اخبار Google
(بلغات المصادر)، ثم تُقرأ نصوص اهم الاخبار لحساب عدد ذكر الكلمات وتلخيصها في نقاط. بلا ذكاء اصطناعي وبلا مفاتيح.
صيغة الاسطر: «+» = كلمتان لازم تجتمعان في الخبر، «|» = بدائل لنفس الموضوع (سيناء | سينا)، وسطر يبدأ بـ # تعليق."""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import core

DEFAULT_TOPICS = """# كل سطر موضوع. + تعني اجتماع كلمتين في الخبر، و | تعني بدائل لنفس الموضوع
مصر
الجيش المصري | القوات المصرية
تحركات مصرية
السعودية
ايران
الحوثيين
اليمن
سيناء | سينا
اثيوبيا + مصر
السعودية + مصر
الصومال + مصر
اريتريا + مصر
السودان + مصر
البحر الاحمر + مصر
اسرائيل + مصر
تركيا + مصر
امريكا + مصر
روسيا + مصر
الصين + مصر
تركيا + السعودية
باكستان + السعودية
تحالف مكة
سد النهضة
"""


def parse_topics(text):
    """يحوّل النص الى مواضيع: [{title, alts: [[كلمات تجتمع], ...]}]"""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        alts = []
        for alt in re.split(r"\s*\|\s*", line):
            terms = [t.strip() for t in re.split(r"\s*\+\s*", alt) if t.strip()]
            if terms:
                alts.append(terms)
        if alts:
            out.append({"title": " + ".join(alts[0]) if len(alts) == 1 else line, "alts": alts})
    return out


def _hosts(sel):
    return {d.split("/")[0] for _l, doms, _g in sel for d in core._split_domains([doms])}


def _lang_codes(sel):
    ls = [l for l in core.LANG_ORDER if any(l in core.entry_langs(lg) for _a, _b, lg in sel)]
    return ls or ["en", "he"]


def _group(t_ar, code):
    """مجموعة بحث لكلمة واحدة بلغة الكود (مع صيغها البديلة مثل Su-35)؛ None لو تعذرت الترجمة"""
    x = t_ar if code == "ar" else core.tr(t_ar, "ar", core.GT_CODE.get(code, code))
    if code != "ar" and core._HAS_AR.search(x):
        return None
    parts = [core._quoted(x)] + [core._quoted(v) for v in core.term_extras(t_ar, code) if v != x]
    return "(" + " OR ".join(parts) + ")" if len(parts) > 1 else parts[0]


def _gn_search(task, days, allowed):
    ti, ai, lang, terms = task
    code = core.LANG_MAP[lang][0]
    groups = [_group(t, code) for t in terms]
    if not all(groups):
        return ti, ai, [], f"تعذّرت ترجمة «{' + '.join(terms)}» الى {core.LANG_NAME_AR.get(code, code)}"
    q = " ".join(groups) + f" when:{max(1, days)}d"
    if lang == "he":
        loc = core._GN_LOC["he"]["IL"]
    elif lang == "en":
        loc = core._GN_LOC["en"]["US"]
    else:
        loc = next(iter(core._GN_LOC[lang].values()))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        got = core._get_feed(core.gnews_url(q, *loc))
    except Exception as ex:
        return ti, ai, [], f"اخبار Google تعذّر ({type(ex).__name__}): {q[:80]}"
    items = []
    for e in got:
        if not e["link"] or not e["title"] or not e["date"] or e["date"] < cutoff:
            continue
        host = core._host(e["source_url"]) or ""
        if not host or not core.domain_match(host, list(allowed)):
            continue
        title = e["title"]
        if e["source_name"] and title.endswith(" - " + e["source_name"]):
            title = title[: -len(e["source_name"]) - 3]
        items.append({"url": e["link"], "title": title, "seendate": e["date"].strftime("%Y%m%dT%H%M%SZ"), "domain": host,
                      "sourcecountry": "", "language": {"he": "Hebrew", "ar": "Arabic", "tr": "Turkish", "fa": "Persian", "am": "Amharic"}.get(lang, "English"),
                      "alt": ai})
    return ti, ai, items, f"اخبار Google ⟵ {q[:90]} ⟵ {len(items)}"


def _tr_all(texts):
    """ترجمة نقاط الملخص بإصرار: دفعات ثم محاولات فردية متباعدة لما بقي غير عربي (جوجل يبطّئنا على خوادم GitHub)"""
    out = core._batch_tr(texts, "ar", size=6)
    for wait in (2, 5, 10):
        bad = [i for i, t in enumerate(out) if not core._HAS_AR.search(t) and texts[i].strip()]
        if not bad:
            break
        core.time.sleep(wait)
        for i in bad:
            try:
                r = core.tr(" ".join(texts[i].split()), "auto", "ar")
                if core._HAS_AR.search(r):
                    out[i] = r
            except Exception:
                pass
    return out


def build_report(topics, sel, days, per_topic=8, deep=3, progress=None, scopes=None, fulltext=False, checkpoint=None):
    """يبني التقرير. يعيد dict(topics=[{title, total, items}], overlap, notes, meta)"""
    prog = progress or (lambda f, m: None)
    notes, allowed = [], _hosts(sel)
    codes = [core.LANG_MAP[l][0] for l in _lang_codes(sel)]
    langs = _lang_codes(sel)

    prog(0.02, "جارٍ قراءة عناوين خلاصات المصادر من مواقعها…")
    pool, dn = core.direct_headlines(sel, days)
    ok_sites = sum(1 for n in dn if "تعذّر" not in n)
    notes.append(f"خلاصات المصادر المباشرة: {ok_sites} موقع من {len(dn)} فتحت، وبها {len(pool)} عنواناً")

    prog(0.15, "جارٍ تجهيز كلمات البحث وترجمتها…")
    matchers = {}
    for ti, tp in enumerate(topics):
        for ai, terms in enumerate(tp["alts"]):
            matchers[(ti, ai)] = core.make_matchers(terms, codes)

    hits = {ti: [] for ti in range(len(topics))}
    for ti, tp in enumerate(topics):
        for ai in range(len(tp["alts"])):
            m = matchers[(ti, ai)]
            for a in pool:
                if m and core.find_mentions(a.get("title", ""), m, "AND")[0]:
                    hits[ti].append({**a, "alt": ai})

    tasks = [(ti, ai, lg, terms) for ti, tp in enumerate(topics) for ai, terms in enumerate(tp["alts"]) for lg in langs]
    done = 0
    with ThreadPoolExecutor(5) as ex:
        futs = [ex.submit(_gn_search, t, days, allowed) for t in tasks]
        for f in futs:
            ti, ai, items, note = f.result()
            hits[ti] += items
            if "تعذّر" in note:
                notes.append(note)
            done += 1
            prog(0.15 + 0.35 * done / max(1, len(tasks)), f"اخبار Google: {done}/{len(tasks)}")

    rep_topics = []
    for ti, tp in enumerate(topics):
        items = core.merge_items(hits[ti])
        rep_topics.append({"title": tp["title"], "total": len(items), "items": items[:per_topic]})

    prog(0.52, "جارٍ فك الروابط وترجمة العناوين…")
    flat_items = [a for t in rep_topics for a in t["items"]]
    cache_dec = {}

    def dec(a):
        u = a["url"]
        if "news.google.com" in u:
            if u not in cache_dec:
                cache_dec[u] = core.decode_gnews(u)
            real = cache_dec[u]
            if real != u:
                a["url"], a["domain"] = real, core._host(real)

    with ThreadPoolExecutor(6) as ex:
        list(ex.map(dec, flat_items))
    for t in rep_topics:  # بعد فك الروابط قد تتكرر اخبار
        t["items"] = core.merge_items(t["items"])
    uniq = {}
    for t in rep_topics:
        for a in t["items"]:
            uniq.setdefault(a["url"], a)
    core.translate_titles(list(uniq.values()))
    for t in rep_topics:
        for a in t["items"]:
            src = uniq[a["url"]]
            if src is not a:
                a["title_ar"], a["title_en"], a["country_ar"] = src.get("title_ar"), src.get("title_en"), src.get("country_ar", "")
            a["ctype"], a["ctype_sure"] = core.classify(a["url"], a["title"])
    seen = uniq
    for t in rep_topics:
        for a in t["items"]:
            a["scopes"] = [n for n, doms in (scopes or {}).items() if core.domain_match(a.get("domain", ""), doms)]
    if checkpoint:
        checkpoint(_pack(rep_topics, [], notes, days, allowed, pool, done=False))

    if deep > 0:
        prog(0.62, "جارٍ قراءة نصوص اهم الاخبار وحساب ذكر الكلمات…")
        todo = []
        for ti, t in enumerate(rep_topics):
            for a in t["items"][:deep]:
                if "news.google.com" not in a["url"]:
                    todo.append((ti, a))

        def read(p):
            ti, a = p
            try:
                art = core.fetch_article(a["url"])
            except Exception:
                art = None
            a["fetched"] = bool(art)
            if not art:
                return
            a["via"] = art.get("via", "")
            m = matchers[(ti, a.get("alt", 0))]
            a["mcount"], a["words"] = core.count_mentions(art["text"], m)
            a["mlevel"] = core.mention_level(a["mcount"], a["words"], core.find_mentions(a.get("title", ""), m, "OR")[0])
            a["_pts"] = core.summary_points(art["text"], 3)
            if fulltext:
                try:
                    a["full_ar"] = core.translate_long(art["text"][:6000])
                except Exception:
                    a["full_ar"] = ""

        total = max(1, len(todo))
        for i in range(0, len(todo), 8):
            with ThreadPoolExecutor(8) as ex:
                list(ex.map(read, todo[i:i + 8]))
            prog(0.62 + 0.25 * min(1, (i + 8) / total), f"قراءة النصوص: {min(i + 8, len(todo))}/{len(todo)}")
        prog(0.9, "جارٍ ترجمة النقاط…")
        flat = [(a, p) for _t, a in todo for p in a.get("_pts", [])]
        if flat:
            trd = _tr_all([p for _a, p in flat])
            for a, _p in flat:
                a["points_ar"] = []
            for (a, _p), t in zip(flat, trd):
                a["points_ar"].append(t)
        for _t, a in todo:
            a.pop("_pts", None)

    topics_of = {}
    for t in rep_topics:
        for a in t["items"]:
            topics_of.setdefault(a["url"], []).append(t["title"])
    overlap = [(seen[u], ts) for u, ts in topics_of.items() if len(ts) >= 2]
    overlap.sort(key=lambda x: -len(x[1]))
    prog(1.0, "تم")
    return _pack(rep_topics, overlap[:15], notes, days, allowed, pool, done=True)


def _pack(rep_topics, overlap, notes, days, allowed, pool, done):
    return {"topics": rep_topics, "overlap": overlap, "notes": notes, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "days": days, "n_sources": len(allowed), "n_pool": len(pool), "done": done}


def to_markdown(rep, label_fn, fmt_date):
    """نسخة نصية للنسخ او التنزيل (تصلح للصق عند اي ذكاء اصطناعي)"""
    out = [f"# تقرير مخصص بالكلمات — اخر {rep['days']} يوم", f"المصادر المفحوصة: {rep['n_sources']} موقعاً · العناوين المقروءة مباشرة: {rep['n_pool']}", ""]
    for t in rep["topics"]:
        out.append(f"## {t['title']} ({t['total']} خبر)")
        for a in t["items"]:
            out.append(f"- {a.get('title_ar', a.get('title', ''))} — {label_fn(a.get('domain', ''))} — {fmt_date(a.get('seendate', ''))}")
            out.append(f"  الرابط: {a['url']}")
            if a.get("mcount") is not None and a.get("fetched"):
                out.append(f"  ذُكرت الكلمات {a['mcount']} مرة في مقال حوالي {a.get('words', 0)} كلمة ({a.get('mlevel', '')})")
            for p in a.get("points_ar", []):
                out.append(f"  * {p}")
        out.append("")
    if rep["overlap"]:
        out.append("## اخبار تتقاطع فيها اكثر من قضية")
        for a, ts in rep["overlap"]:
            out.append(f"- {a.get('title_ar', a.get('title', ''))} ⟵ {' | '.join(ts)}")
    return "\n".join(out)
