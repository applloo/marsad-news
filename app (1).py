# -*- coding: utf-8 -*-
"""
رادار الأخبار العالمية — بحث بالعربية في مصادر إسرائيلية وأمريكية وبريطانية + بحث عام عبر GDELT
"""
import hashlib
import html
import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote

import streamlit as st

import core
from core import fmt_seen, tr
import store
import writers as writers_mod
from sources import ISRAEL, UK, USA
from writers import WRITERS

DOMAIN_LABELS = {}
for _g in (ISRAEL, USA, UK):
    for _entries in _g.values():
        for _label, _doms, _ in _entries:
            for _d in _doms.split("|"):
                DOMAIN_LABELS[_d] = _label


def source_name(domain):
    domain = (domain or "").lower().replace("www.", "")
    for d, label in DOMAIN_LABELS.items():
        if domain == d or domain.endswith("." + d):
            return label
    return domain


st.set_page_config(page_title="رادار الأخبار العالمية", page_icon="📰", layout="centered")

st.markdown(
    """
<style>
.stApp, .stMarkdown, label, [data-testid="stWidgetLabel"] {direction: rtl; text-align: right;}
.ar-title {font-size:1.15rem; font-weight:700; line-height:1.7; margin-bottom:4px;}
.ltr {direction:ltr; text-align:left; color:#6b7280; font-size:.9rem; margin-bottom:2px;}
.meta {color:#6b7280; font-size:.85rem; margin:6px 0;}
.badge {background:#eef2ff; color:#3730a3; padding:1px 8px; border-radius:10px; font-size:.78rem;}
a.btn {display:inline-block; background:#1d4ed8; color:#fff !important; padding:8px 18px;
       border-radius:8px; text-decoration:none; font-weight:600; margin-top:4px;}
a.btn:hover {background:#1e40af;}
.card {border:1px solid rgba(128,128,128,.3); border-radius:10px; padding:12px 14px; margin-bottom:10px;}
.article-body p {line-height:2; font-size:1.05rem; margin-bottom:1rem;}
@media (max-width:640px){ .ar-title{font-size:1.05rem;} }
</style>
""",
    unsafe_allow_html=True,
)


def get_key():
    try:
        k = st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:
        k = None
    return k or os.getenv("ANTHROPIC_API_KEY")


# ───────────────────────── القراءة الصوتية ─────────────────────────

TTS_MODES = ["العنوان + المقال كاملاً", "العنوان + ملخص قصير", "العنوان فقط"]
ORDINALS = ["الأول", "الثاني", "الثالث", "الرابع", "الخامس", "السادس", "السابع", "الثامن", "التاسع", "العاشر"]


@st.cache_data(ttl=86400, max_entries=30, show_spinner=False)
def tts_cached(text, voice, rate):
    return core.tts(text, voice, rate)


def tts_settings(prefix):
    c1, c2 = st.columns(2)
    label = c1.selectbox("الصوت", list(core.VOICES), key=f"{prefix}_voice")
    rate = c2.slider("السرعة", -30, 40, 0, step=5, format="%d%%", key=f"{prefix}_rate")
    return core.VOICES[label], rate


def audio_block(entry, wk, name="marsad_news"):
    data, _engine, note = entry
    if note:
        st.caption("ℹ️ " + note)
    st.audio(data, format="audio/mpeg")
    st.download_button(
        "⬇️ تنزيل MP3 (للاستماع بدون إنترنت داخل المترو)", data=data, file_name=f"{name}.mp3", mime="audio/mpeg", key=f"dl_{wk}"
    )
    st.caption("⏸ للإيقاف المؤقت أو الإيقاف استخدم زر المشغّل. الصوت يستمر والشاشة مغلقة.")


def speech_text(url, title_ar, mode):
    """يجهّز النص العربي المراد نطقه حسب الوضع. يعيد (النص، ملاحظة)"""
    if mode == TTS_MODES[2]:
        return title_ar, ""
    art = core.fetch_article(url)
    if not art:
        return title_ar, "تعذّر جلب نص المقال (اشتراك أو حجب) فقُرئ العنوان فقط."
    if mode == TTS_MODES[1]:
        summ = core.summarize(url, get_key())
        summ = re.sub(r"^ملخص مبسّط[^\n]*\n+", "", summ)
        return f"{title_ar}. {summ}", ""
    return f"{title_ar}. {core.translate_long(art['text'])}", ""


def make_audio(text, voice, rate):
    try:
        return tts_cached(text, voice, rate)
    except Exception as e:
        st.error(f"تعذّر توليد الصوت ({type(e).__name__}): {e}")
        return None


def listen_widget(a, wk):
    aud = st.session_state.setdefault("audio", {})
    url = a.get("url", "")
    if st.button("🎧 استمع", key=f"ls_{wk}"):
        ss = st.session_state
        voice = core.VOICES[ss.get("tts_voice", list(core.VOICES)[0])]
        with st.spinner("جارٍ تجهيز الصوت (جلب النص وترجمته ثم النطق)… قد يستغرق دقيقة للمقالات الطويلة."):
            text, note0 = speech_text(url, a.get("title_ar", ""), ss.get("tts_mode", TTS_MODES[0]))
            res = make_audio(text, voice, ss.get("tts_rate", 0))
            if res:
                if len(aud) >= 6:
                    aud.pop(next(iter(aud)))
                aud[url] = (res[0], res[1], (note0 + " " + res[2]).strip())
    if url in aud:
        audio_block(aud[url], wk)


# ───────────────────────── صفحة قراءة المقال ─────────────────────────


def reader_page():
    url = unquote(st.query_params.get("view", ""))
    seen = st.query_params.get("seen", "")
    orig_title = unquote(st.query_params.get("t", ""))

    st.markdown("## 📖 قراءة المقال مترجماً")
    if not url.startswith(("http://", "https://")):
        st.error("رابط غير صالح.")
        return
    st.markdown(f"🔗 **الرابط الأصلي:** [{html.escape(url)}]({url})")

    with st.spinner("جارٍ جلب المقال وترجمته…"):
        art = core.fetch_article(url)
        if not art:
            st.warning("تعذّر استخراج نص المقال (جدار اشتراك أو حجب). افتح الرابط الأصلي مباشرة.")
            return
        title = art["title"] or orig_title
        title_ar = tr(title, "auto", "ar")
        body_ar = core.translate_long(art["text"])

    if art["date"]:
        st.markdown(f"🕒 **تاريخ النشر (حسب بيانات المصدر):** {art['date']}")
    if seen:
        st.markdown(f"🛰️ **وقت رصد المقال (توقيت القاهرة):** {fmt_seen(seen)}")

    st.markdown(f"### {title_ar}")
    st.markdown(f"<div class='ltr' dir='ltr'>{html.escape(title)}</div>", unsafe_allow_html=True)

    if st.button("📝 تلخيص المقال"):
        with st.spinner("جارٍ التلخيص…"):
            st.info(core.summarize(url, get_key()))

    with st.expander("🎧 استمع للمقال بصوت مسموع", expanded=False):
        voice, rate = tts_settings("rd")
        part = st.radio("ما الذي يُقرأ؟", ["المقال كاملاً", "أول فقرات فقط (حوالي دقيقتين)"], horizontal=True, key="rd_part")
        rd_aud = st.session_state.setdefault("rd_audio", {})
        if st.button("🔊 ولّد الصوت", key="rd_go", use_container_width=True):
            txt = f"{title_ar}. {body_ar}"
            if part != "المقال كاملاً":
                txt = txt[:1800].rsplit(".", 1)[0] + "."
            with st.spinner("جارٍ تجهيز الصوت…"):
                res = make_audio(txt, voice, rate)
            if res:
                rd_aud.clear()
                rd_aud[url] = res
        if url in rd_aud:
            audio_block(rd_aud[url], "rd")

    st.divider()
    paras = "".join(f"<p>{html.escape(p)}</p>" for p in body_ar.split("\n") if p.strip())
    st.markdown(f"<div class='article-body'>{paras}</div>", unsafe_allow_html=True)
    with st.expander("النص الأصلي"):
        st.text(art["text"])


if "view" in st.query_params:
    reader_page()
    st.stop()

# ───────────────────────── التخزين: المحفوظات + المصادر المضافة ─────────────────────────

DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9\-\.]*\.[a-z]{2,}$")


def _secret(name):
    try:
        v = st.secrets.get(name)
    except Exception:
        v = None
    return v or os.getenv(name)


GH_TOKEN, GH_GIST = _secret("GITHUB_TOKEN"), _secret("GIST_ID")
PERSIST = bool(GH_TOKEN and GH_GIST)

if "store" not in st.session_state:
    _data, _err = store.empty(), None
    if PERSIST:
        try:
            _data = store.load(GH_TOKEN, GH_GIST)
        except Exception as _e:
            _err = f"تعذّر تحميل التخزين الدائم ({type(_e).__name__})"
    st.session_state["store"] = _data
    st.session_state["store_err"] = _err


def S():
    return st.session_state["store"]


def persist():
    if not PERSIST:
        return
    try:
        store.save(GH_TOKEN, GH_GIST, S())
        st.session_state["store_err"] = None
    except Exception as e:
        st.session_state["store_err"] = f"تعذّر الحفظ الدائم ({type(e).__name__})"


for _s in S()["sources"]:
    DOMAIN_LABELS[_s["domain"]] = _s["label"]

SAVE_KEYS = [
    "url", "title", "title_ar", "title_en", "seendate", "domain", "sourcecountry", "country_ar", "language",
    "ctype", "ctype_sure", "writer", "outlet", "wsrc", "snips", "snip_ar", "found", "fetched", "checked",
]


def flash(msg):
    st.session_state["flash"] = msg


def clean_domain(x):
    return (x or "").strip().lower().replace("https://", "").replace("http://", "").replace("www.", "").strip("/").split("/")[0]


def save_item(a, tab=""):
    s = S()
    if any(x.get("url") == a.get("url") for x in s["saved"]):
        return
    it = {k: a[k] for k in SAVE_KEYS if k in a}
    it["saved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    it["note"], it["tab"] = "", tab
    s["saved"].insert(0, it)
    persist()


def delete_item(url):
    S()["saved"] = [x for x in S()["saved"] if x.get("url") != url]
    persist()


def set_note(url, wkey):
    for x in S()["saved"]:
        if x.get("url") == url:
            x["note"] = st.session_state.get(wkey, "")
    persist()


def add_source():
    ss = st.session_state
    dom = clean_domain(ss.get("ms_domain", ""))
    if not DOMAIN_RE.match(dom):
        return flash("⚠️ الدومين غير صالح (مثال: example.com).")
    name = (ss.get("ms_name", "") or "").strip() or dom
    gname = ss.get("ms_group", "أمريكية")
    group = {"إسرائيلية": "il", "أمريكية": "us", "بريطانية": "uk"}[gname]
    lang = {"عبري": "he", "إنجليزي": "en", "كلاهما": "both"}[ss.get("ms_lang", "إنجليزي")]
    if any(x["domain"] == dom and x["group"] == group for x in S()["sources"]):
        return flash("هذا المصدر مضاف مسبقاً.")
    S()["sources"].append({"label": name, "domain": dom, "lang": lang, "group": group})
    DOMAIN_LABELS[dom] = name
    persist()
    flash(f"✅ أُضيف «{name}» إلى مصادر التاب ({gname}) — يظهر هناك ضمن «مصادر أضفتَها».")


def add_writer():
    ss = st.session_state
    en = (ss.get("mw_en", "") or "").strip()
    sites = [d for d in (clean_domain(x) for x in re.split(r"[,\s]+", ss.get("mw_sites", ""))) if DOMAIN_RE.match(d)]
    if not en or not sites:
        return flash("⚠️ أدخل اسم الكاتب بالإنجليزية (للبحث) ودومين موقع واحداً على الأقل.")
    ar = (ss.get("mw_ar", "") or "").strip() or tr(en, "en", "ar")
    heb = (ss.get("mw_heb", "") or "").strip()
    country = {"أمريكي": "US", "بريطاني": "UK", "إسرائيلي": "IL"}[ss.get("mw_country", "أمريكي")]
    wid = "c_" + hashlib.md5((en + ",".join(sites)).encode()).hexdigest()[:8]
    if any(w["id"] == wid for w in S()["writers"]):
        return flash("هذا الكاتب مضاف مسبقاً.")
    S()["writers"].append(
        {"id": wid, "name_ar": ar, "name_en": en, "outlet": (ss.get("mw_outlet", "") or "").strip() or sites[0],
         "country": country, "kind": ss.get("mw_kind", "رأي"), "sites": sites, "aliases": [],
         "heb": [heb, sites] if heb else None}
    )
    persist()
    flash(f"✅ أُضيف الكاتب «{ar}» — يظهر في تاب «كتّاب ومحللون».")


def remove_source(dom, group):
    S()["sources"] = [x for x in S()["sources"] if not (x["domain"] == dom and x["group"] == group)]
    persist()


def remove_writer(wid):
    S()["writers"] = [x for x in S()["writers"] if x["id"] != wid]
    persist()


def fill_author(idx):
    ss = st.session_state
    a = (ss.get("analysis") or {}).get("authors", [])[idx]
    ss["mw_en"] = a.get("en") or a["raw"]
    ss["mw_ar"] = a.get("ar", "")
    ss["mw_heb"] = a["raw"] if a.get("heb") else ""


def pick_author():
    names = [a["raw"] for a in (st.session_state.get("analysis") or {}).get("authors", [])]
    if st.session_state.get("mw_pick") in names:
        fill_author(names.index(st.session_state["mw_pick"]))


def do_analyze():
    ss = st.session_state
    url = (ss.get("ms_url", "") or "").strip()
    if not url:
        return
    try:
        res = core.analyze_url(url)
    except Exception as e:
        res = {"error": f"تعذّر التحليل ({type(e).__name__})", "authors": []}
    ss["analysis"] = res
    if res.get("domain"):
        ss["ms_domain"] = res["domain"]
        ss["ms_name"] = res.get("site_name") or res["domain"]
        g = res.get("group", "us")
        ss["ms_group"] = {"il": "إسرائيلية", "uk": "بريطانية", "us": "أمريكية"}[g]
        ss["ms_lang"] = "عبري" if res.get("lang") == "he" else "إنجليزي"
        ss["mw_sites"], ss["mw_outlet"] = res["domain"], ss["ms_name"]
        ss["mw_country"] = {"il": "إسرائيلي", "uk": "بريطاني", "us": "أمريكي"}[g]
    if res.get("authors"):
        ss["mw_pick"] = res["authors"][0]["raw"]
        fill_author(0)


# ───────────────────────── الواجهة الرئيسية ─────────────────────────

st.title("📰 رادار الأخبار العالمية")
st.caption("اكتب بالعربية كلمة أو عدة كلمات أو جملة مركّبة — تُترجم تلقائياً إلى العبرية والإنجليزية وتُترجم النتائج للعربية.")

query = st.text_input(
    "🔎 كلمات البحث",
    placeholder="مثال: وزير الخارجية المصري   —   أو عدة مواضيع بفاصلة: اليمن، الحوثيين، مصر السعودية",
    help="كل ما بين فاصلتين (، أو ,) يُعامل كموضوع/عبارة مستقلة. بدون فاصلة تُعتبر الجملة كلها عبارة واحدة.",
)
c1, c2 = st.columns(2)
match = c1.radio(
    "طريقة مطابقة كل عبارة",
    core.MATCH_MODES,
    help="Near: الكلمات متقاربة بأي ترتيب (الأنسب للجمل). Exact: العبارة بنصّها المترجم حرفياً. AND: الكلمات موجودة في المقال في أي موضع.",
)
joiner_label = c2.radio("عند وجود أكثر من عبارة (بفاصلة)", ["كلها معاً (AND)", "أيٌّ منها (OR)"])
joiner = "OR" if "OR" in joiner_label else "AND"

with st.expander("⚙️ الوقت ونوع المحتوى", expanded=True):
    ctype = st.selectbox("نوع المحتوى", ["الكل", "خبر", "تحليل", "رأي"])
    mode = st.radio("النطاق الزمني", ["آخر ساعات", "آخر أيام", "تواريخ محددة"], horizontal=True)
    now_utc = datetime.now(timezone.utc)
    if mode == "آخر ساعات":
        h = st.slider("عدد الساعات", 1, 72, 24)
        start_utc, end_utc = now_utc - timedelta(hours=h), now_utc
    elif mode == "آخر أيام":
        d = st.slider("عدد الأيام", 1, 90, 7)
        start_utc, end_utc = now_utc - timedelta(days=d), now_utc
    else:
        today = datetime.now(core.TZ).date()
        rng = st.date_input("من – إلى", value=(today - timedelta(days=3), today), max_value=today)
        if isinstance(rng, (list, tuple)) and len(rng) == 2:
            s, e = rng
        else:
            s = e = rng[0] if isinstance(rng, (list, tuple)) else rng
        start_utc = datetime(s.year, s.month, s.day, tzinfo=core.TZ).astimezone(timezone.utc)
        end_utc = datetime(e.year, e.month, e.day, 23, 59, 59, tzinfo=core.TZ).astimezone(timezone.utc)
    max_rec = st.slider("عدد النتائج الأقصى", 10, 100, 30, step=10)
    verify = st.checkbox("🔍 افحص نص كل مقال واعرض جملة ذُكرت فيها كلمتك (أبطأ)", value=True)
    hide_nomatch = st.checkbox("🚫 أخفِ المقالات التي لا تظهر كلمتك في نصها", value=False)

with st.expander("🎧 إعدادات القراءة الصوتية (للمترو والسماعات)"):
    tts_settings("tts")
    st.radio("ما الذي يُقرأ عند الضغط على «🎧 استمع»؟", TTS_MODES, key="tts_mode")
    st.caption("تُجهَّز القراءة بصوت عربي عصبي، ويمكن تنزيلها MP3 قبل نزول المترو للاستماع بلا إنترنت.")

def pick_sources(key, groups, allow_custom=True):
    """يعرض اختيار المصادر ويعيد قائمة (label, domains, lang)"""
    chosen = []
    extra_src = [(x["label"], x["domain"], x["lang"]) for x in S()["sources"] if x["group"] == key]
    if extra_src:
        groups = {**groups, "➕ مصادر أضفتَها": extra_src}
    for gname, entries in groups.items():
        labels = [e[0] for e in entries]
        sel = st.multiselect(gname, labels, default=labels, key=f"{key}_{gname}")
        chosen += [e for e in entries if e[0] in sel]
    if allow_custom:
        extra = st.text_input(
            "➕ مواقع إضافية (دومين واحد أو أكثر، بفاصلة)", placeholder="example.com, another.org", key=f"{key}_extra"
        )
        for dmn in re.split(r"[,\s]+", extra.strip().lower()):
            dmn = dmn.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
            if dmn and DOMAIN_RE.match(dmn):
                chosen.append((dmn, dmn, "both"))
    return chosen


def update_meta(data, sel):
    counts = {}
    for a in data["items"]:
        n = source_name(a.get("domain", ""))
        counts[n] = counts.get(n, 0) + 1
    data["counts"] = counts
    data["silent"] = [lbl for lbl, _, _ in (sel or []) if lbl not in counts]


def do_search(key, jobs, sel=None, terms=None, pre=False):
    terms = terms or [t.strip() for t in re.split(r"[,،;\n]+", query) if t.strip()]
    if not terms:
        st.warning("اكتب كلمة بحث أولاً (في الخانة أعلى الصفحة).")
        return
    if not jobs:
        st.warning("اختر مصدراً واحداً على الأقل.")
        return
    # زر الإيقاف: الضغط عليه يقطع التنفيذ الجاري، وما ظهر حتى الآن محفوظ في session_state ويُعرض كاملاً
    st.button("⏹ إيقاف البحث والاكتفاء بالنتائج الظاهرة", key=f"stop_{key}")
    status_ph, live_ph = st.empty(), st.empty()
    status_ph.info("⏳ جارٍ التحضير والترجمة…")
    matchers = core.make_matchers_pre(jobs) if pre else core.make_matchers(terms, [j["code"] for j in jobs])
    hl = sorted({st_ for alts in matchers for stems in alts for st_ in stems}, key=len, reverse=True)
    data = {
        "items": [], "errors": [], "used": [], "summaries": {}, "counts": {}, "silent": [],
        "hidden": 0, "hl": hl, "partial": True,
    }
    st.session_state[f"res_{key}"] = data
    for ev in core.search_iter(terms, joiner, match, jobs, start_utc, end_utc, max_rec, ctype):
        status_ph.info(f"⏳ {ev['msg']}")
        data["errors"], data["used"] = ev["errors"], ev["used"]
        if ev["items"] is not None:
            core.translate_titles([a for a in ev["items"] if "title_ar" not in a])
            data["items"] = ev["items"]
            update_meta(data, sel)
            live_ph.markdown(live_html(data["items"], hl), unsafe_allow_html=True)
    if verify and data["items"]:
        items = data["items"]
        total = min(len(items), 40)
        for i in range(0, total, 8):
            status_ph.info(f"🔍 جارٍ فحص نصوص المقالات… ({i}/{total})")
            core.enrich_items(items[i:i + 8], matchers, joiner, limit=8)
            live_ph.markdown(live_html(items, hl), unsafe_allow_html=True)
    update_meta(data, sel)
    if hide_nomatch:
        raw = data["items"]
        data["items"] = [a for a in raw if not (a.get("fetched") and not a.get("found"))]
        data["hidden"] = len(raw) - len(data["items"])
    data["partial"] = False
    status_ph.success(f"✅ تم — {len(data['items'])} نتيجة")
    live_ph.empty()


def highlight(text, stems):
    out = html.escape(text)
    for st_ in stems:
        out = re.sub(f"({re.escape(html.escape(st_))})", r"<b>\1</b>", out, flags=re.I)
    return out


def card_html(a):
    url = a.get("url", "")
    link = f"?view={quote(url, safe='')}&seen={a.get('seendate', '')}&t={quote(a.get('title', '')[:200], safe='')}"
    orig = html.escape(a.get("title", ""))
    en = a.get("title_en", "")
    en_line = f"<div class='ltr' dir='ltr'>EN: {html.escape(en)}</div>" if en and en != a.get("title") else ""
    dom = a.get("domain", "")
    sname = source_name(dom)
    src = html.escape(sname) + (f" ({html.escape(dom)})" if sname != dom else "")
    ctag = a.get("ctype", "") + ("" if a.get("ctype_sure") else " (تقدير)")
    wline = (
        f"✍️ الكاتب: <b>{html.escape(a['writer'])}</b> — {html.escape(a.get('outlet', ''))} "
        + ("· 📌 من صفحة الكاتب" if a.get("wsrc") == "feed" else "· 🔎 بحث باسم الكاتب")
        + "<br>"
        if a.get("writer")
        else ""
    )
    return (
        f"<div class='ar-title'>{html.escape(a.get('title_ar', ''))}</div>"
        f"<div class='ltr' dir='ltr'>{orig}</div>{en_line}"
        f"<div class='meta'>🕒 {fmt_seen(a.get('seendate', ''))} (القاهرة)<br>{wline}"
        f"🌐 المصدر: {src} · 🏳️ الدولة: {html.escape(a.get('country_ar', '') or a.get('sourcecountry', ''))}"
        f" · <span class='badge'>{html.escape(ctag)}</span></div>"
        f"<a class='btn' href='{html.escape(link)}' target='_blank' rel='noopener'>ترجم المقال</a>"
    )


def snippet_html(a, hl):
    if not a.get("checked"):
        return ""
    if not a.get("fetched"):
        return "<div class='meta'>ℹ️ تعذّر فحص نص المقال (قد يكون خلف اشتراك أو يحجب الزحف).</div>"
    if a.get("found"):
        out = f"<div class='meta'>✅ ذُكرت كلمتك في نص المقال:</div><div>{html.escape(a.get('snip_ar', ''))}</div>"
        for sn in a.get("snips", []):
            out += f"<div class='ltr' dir='ltr'>{highlight(sn, hl)}</div>"
        return out
    return "<div class='meta'>⚠️ كلمتك لم تظهر في نص هذا المقال.</div>"


def live_html(items, hl):
    """عرض خفيف (بدون أزرار) أثناء البحث؛ تُرسم الأزرار الكاملة بعد الانتهاء أو الإيقاف"""
    return "".join(f"<div class='card'>{card_html(a)}{snippet_html(a, hl)}</div>" for a in items)


def render_results(key):
    data = st.session_state.get(f"res_{key}")
    if data is None:
        return
    if data.get("partial"):
        st.warning("⏹ توقّف البحث قبل اكتماله — هذه هي النتائج التي وُجدت حتى الآن (وقد لا تشمل فحص النصوص كاملاً).")
    for err in data["errors"]:
        st.warning(f"تنبيه من مصدر البيانات: {err}")
    with st.expander("الاستعلام المُرسل فعلياً (بعد الترجمة)"):
        for u in data["used"]:
            st.code(u, language=None)
    with st.expander("📊 توزيع النتائج على المصادر"):
        if data["counts"]:
            st.markdown("  \n".join(f"- **{n}**: {c}" for n, c in sorted(data["counts"].items(), key=lambda x: -x[1])))
        if data["silent"]:
            st.markdown("**مصادر مختارة لم تُرجع نتائج:** " + "، ".join(data["silent"]))
            st.caption("غياب مصدر يعني أن GDELT لم يرصد له مقالات مطابقة في هذه الفترة، وليس أنه غير مدعوم في التطبيق.")
    if data.get("hidden"):
        st.caption(f"تم إخفاء {data['hidden']} مقالاً لم تظهر كلمتك في نصّه.")
    if not data["items"]:
        st.info("لا نتائج ضمن هذه الفلاتر. جرّب «كل الكلمات (AND)» أو وسّع النطاق الزمني أو زِد المصادر.")
    for i, a in enumerate(data["items"]):
        url = a.get("url", "")
        with st.container(border=True):
            st.markdown(card_html(a), unsafe_allow_html=True)
            if a.get("checked"):
                if not a.get("fetched"):
                    st.caption("ℹ️ تعذّر فحص نص المقال (قد يكون خلف اشتراك أو يحجب الزحف).")
                elif a.get("found"):
                    st.success("✅ ذُكرت كلمتك في نص المقال:")
                    st.markdown(a.get("snip_ar", ""))
                    for sn in a.get("snips", []):
                        st.markdown(f"<div class='ltr' dir='ltr'>{highlight(sn, data['hl'])}</div>", unsafe_allow_html=True)
                else:
                    st.warning("⚠️ كلمتك لم تظهر في نص هذا المقال — ربما تطابق GDELT مع الصفحة أو الروابط الجانبية.")
            if st.button("📝 تلخيص المقال", key=f"sum_{key}_{i}"):
                with st.spinner("جارٍ التلخيص…"):
                    data["summaries"][url] = core.summarize(url, get_key())
            if url in data["summaries"]:
                st.info(data["summaries"][url])
            listen_widget(a, f"{key}_{i}")
            if any(x.get("url") == url for x in S()["saved"]):
                st.caption("✅ محفوظ — تجده في تاب «المحفوظات»")
            else:
                st.button("💾 حفظ للقراءة لاحقاً", key=f"save_{key}_{i}", on_click=save_item, args=(a, key))


tab_wr, tab_ml, tab_il, tab_us, tab_uk, tab_gd, tab_sv, tab_ms = st.tabs(
    ["✍️ كتّاب ومحللون", "🔤 ترجمة ثم بحث", "🇮🇱 إسرائيلية (عبري)", "🇺🇸 أمريكية", "🇬🇧 بريطانية", "🌐 بحث عام GDELT",
     "📌 المحفوظات", "⚙️ مصادري"]
)

with tab_il:
    st.caption("يُترجم بحثك إلى العبرية للمصادر العبرية، وإلى الإنجليزية للنسخ الإنجليزية.")
    sel = pick_sources("il", ISRAEL)
    if st.button("ابحث في المصادر الإسرائيلية", type="primary", use_container_width=True, key="go_il"):
        do_search("il", core.jobs_for_sources(sel, "IS"), sel)
    render_results("il")

with tab_us:
    st.caption("مصادر أمريكية مهتمة بالشرق الأوسط (Axios وغيرها) ومراكز أبحاث.")
    sel = pick_sources("us", USA)
    if st.button("ابحث في المصادر الأمريكية", type="primary", use_container_width=True, key="go_us"):
        do_search("us", core.jobs_for_sources(sel, "US"), sel)
    render_results("us")

with tab_uk:
    st.caption("صحف وقنوات بريطانية ومصادر متخصصة بالشرق الأوسط.")
    sel = pick_sources("uk", UK)
    if st.button("ابحث في المصادر البريطانية", type="primary", use_container_width=True, key="go_uk"):
        do_search("uk", core.jobs_for_sources(sel, "UK"), sel)
    render_results("uk")

with tab_gd:
    st.caption("بحث واسع في كل ما يرصده GDELT حسب بلد المصدر، دون تحديد مواقع بعينها.")
    scope = st.selectbox("المصادر", list(core.GLOBAL_SCOPES.keys()), key="gd_scope")
    if st.button("ابحث (GDELT عام)", type="primary", use_container_width=True, key="go_gd"):
        do_search("gd", core.GLOBAL_SCOPES[scope])
    render_results("gd")

COUNTRIES = {"كل الدول": None, "الولايات المتحدة": "US", "بريطانيا": "UK", "إسرائيل": "IS", "البرازيل": "BR", "البرتغال": "PO", "فرنسا": "FR", "إسبانيا": "SP"}

with tab_ml:
    st.caption(
        "ترجم كلماتك إلى عدة لغات، **عدّل أي ترجمة بيدك أو اكتبها بنفسك**، ثم ابحث بها. "
        "كل لغة تُبحث في المقالات المنشورة بها."
    )
    src_txt = st.text_input(
        "العبارة بالعربية (اتركها فارغة لاستخدام خانة البحث أعلى الصفحة)", key="ml_src",
        help="افصل بين المواضيع بفاصلة.",
    )
    base_terms = [x.strip() for x in re.split(r"[,،;\n]+", src_txt or query) if x.strip()]
    if st.button("🔤 ترجم إلى اللغات المختارة", use_container_width=True, key="ml_tr"):
        if not base_terms:
            st.warning("اكتب كلمة أو جملة بالعربية أولاً.")
        else:
            with st.spinner("جارٍ الترجمة…"):
                for code, _, _, _ in core.LANGS:
                    if st.session_state.get(f"ml_use_{code}", dict((c, d) for c, _, _, d in core.LANGS)[code]):
                        out, ok = core.translate_terms(base_terms, code)
                        st.session_state[f"ml_txt_{code}"] = "، ".join(out) if ok else ""
                        st.session_state[f"ml_fail_{code}"] = not ok
    chosen = []
    for code, name, gl, default in core.LANGS:
        c1_, c2_ = st.columns([1, 3])
        use = c1_.checkbox(name, value=default, key=f"ml_use_{code}")
        txt = c2_.text_input(f"الترجمة إلى {name}", key=f"ml_txt_{code}", label_visibility="collapsed",
                             placeholder=f"اكتب أو عدّل الترجمة ({name})")
        if st.session_state.get(f"ml_fail_{code}"):
            c2_.caption("⚠️ فشلت الترجمة الآلية — اكتبها بنفسك.")
        if use and txt.strip():
            chosen.append((code, gl, [x.strip() for x in re.split(r"[,،;\n]+", txt) if x.strip()]))
    country_label = st.selectbox("حصر في مصادر بلد معيّن (اختياري)", list(COUNTRIES.keys()), key="ml_country")
    if st.button("ابحث بهذه الترجمات", type="primary", use_container_width=True, key="go_ml"):
        cc = COUNTRIES[country_label]
        jobs = [
            {"code": code, "extra": f"sourcelang:{gl}" + (f" sourcecountry:{cc}" if cc else ""), "terms": terms_}
            for code, gl, terms_ in chosen
        ]
        if not jobs:
            st.warning("اختر لغة واحدة على الأقل واكتب ترجمتها (اضغط «ترجم» أولاً).")
        else:
            do_search("ml", jobs, None, terms=base_terms or ["x"], pre=True)
    render_results("ml")

DAY_OPTS = {"آخر 24 ساعة": 1, "آخر 3 أيام": 3, "آخر 7 أيام": 7, "آخر 14 يوماً": 14, "آخر 30 يوماً": 30}


GROUP_LABELS = {"US": "🇺🇸 أمريكيون", "UK": "🇬🇧 بريطانيون", "IL": "🇮🇱 إسرائيليون"}


def current_writers():
    return WRITERS + [writers_mod.W(**dict(sp, default=True)) for sp in S()["writers"]]


@st.cache_data(ttl=1800, show_spinner=False)
def cached_writers(ids, days, extra_json="[]"):
    allw = WRITERS + [writers_mod.W(**dict(sp, default=True)) for sp in json.loads(extra_json)]
    ws = [w for w in allw if w["id"] in ids]
    items, notes = core.fetch_writers(ws, days)
    return core.translate_titles(items), notes


with tab_wr:
    st.caption(
        "أحدث مقالات الرأي والتحليل لكتّاب ومراسلين مهتمين بالشرق الأوسط، بعناوين مترجمة، وزر «ترجم المقال» لقراءة النص مترجماً. "
        "النتائج تُحفظ نصف ساعة، فالفتح المتكرر سريع."
    )
    days_label = st.selectbox("الفترة", list(DAY_OPTS.keys()), index=2, key="wr_days")
    sel_ids = []
    all_w = current_writers()
    for gcode, gname in GROUP_LABELS.items():
        ws_ = [w for w in all_w if w["country"] == gcode]
        if not ws_:
            continue
        label_to_id = {f"{w['name_ar']} — {w['outlet']}": w["id"] for w in ws_}
        picked = st.multiselect(
            gname, list(label_to_id), default=[l for l, i in label_to_id.items() if next(w for w in ws_ if w["id"] == i)["default"]],
            key=f"wr_{gname}",
        )
        sel_ids += [label_to_id[p] for p in picked]
    use_ctype = st.checkbox("طبّق فلتر «نوع المحتوى» أعلاه", value=False, key="wr_ct")
    use_kw = st.checkbox("اقتصر على المقالات التي تذكر كلمات البحث أعلاه (يفحص النص — أبطأ)", value=False, key="wr_kw")
    if st.button("اعرض أحدث مقالاتهم", type="primary", use_container_width=True, key="go_wr"):
        if not sel_ids:
            st.warning("اختر كاتباً واحداً على الأقل.")
        else:
            with st.spinner("جارٍ جلب المقالات وترجمة العناوين…"):
                items, notes = cached_writers(
                    tuple(sorted(sel_ids)), DAY_OPTS[days_label], json.dumps(S()["writers"], ensure_ascii=False, sort_keys=True)
                )
                items = [dict(a) for a in items]
            kw_terms = [t_.strip() for t_ in re.split(r"[,،;\n]+", query) if t_.strip()]
            if use_ctype and ctype != "الكل":
                items = [a for a in items if a.get("ctype") == ctype]
            matchers = []
            if use_kw and kw_terms and items:
                with st.spinner("جارٍ فحص نصوص المقالات…"):
                    matchers = core.make_matchers(kw_terms, ["en", "iw"])
                    core.enrich_items(items, matchers, joiner, limit=60)
                    items = [a for a in items if not (a.get("fetched") and not a.get("found"))]
            counts = {}
            for a in items:
                counts[a["writer"]] = counts.get(a["writer"], 0) + 1
            chosen = [w["name_ar"] for w in all_w if w["id"] in sel_ids]
            hl = sorted({s_ for alts in matchers for stems in alts for s_ in stems}, key=len, reverse=True)
            st.session_state["res_wr"] = {
                "items": items, "errors": [] if items else ["لم يُعثر على مقالات — راجع «الاستعلام المُرسل فعلياً» لمعرفة ما جُرّب."],
                "used": notes, "summaries": {}, "counts": counts,
                "silent": [n for n in chosen if n not in counts], "hidden": 0, "hl": hl,
            }
    st.caption("ℹ️ مواقع مثل نيويورك تايمز وواشنطن بوست وفاينانشال تايمز وهآرتس مدفوعة: يظهر عنوانها مترجماً، وقد يتعذّر عرض نصها الكامل.")
    render_results("wr")


def render_saved():
    s = S()
    if not PERSIST:
        st.warning(
            "💡 التخزين الدائم غير مفعّل: ما تحفظه هنا يضيع عند تحديث الصفحة أو إعادة تشغيل التطبيق. "
            "فعّله بخطوتين (الشرح في README: GITHUB_TOKEN و GIST_ID) أو نزّل نسخة احتياطية من الأسفل."
        )
    if st.session_state.get("store_err"):
        st.error(st.session_state["store_err"])
    c1, c2 = st.columns([2, 1])
    q = c1.text_input("🔎 ابحث داخل المحفوظات (عنوان، كاتب، موقع، ملاحظة)", key="sv_q")
    order = c2.selectbox("الترتيب", ["الأحدث حفظاً", "الأحدث نشراً", "الأقدم نشراً (خط زمني)"], key="sv_order")
    items = list(s["saved"])
    if q.strip():
        ql = q.strip().lower()
        items = [
            x for x in items
            if ql in " ".join(str(x.get(k, "")) for k in ("title_ar", "title", "writer", "domain", "note", "outlet")).lower()
        ]
    if order == "الأحدث نشراً":
        items.sort(key=lambda x: x.get("seendate", ""), reverse=True)
    elif order.startswith("الأقدم"):
        items.sort(key=lambda x: x.get("seendate", ""))
    with st.expander("🎙️ نشرة صوتية من المحفوظات (مثالية للمترو)"):
        labels = {f"{n + 1}. {x.get('title_ar', '')[:70]}": x for n, x in enumerate(s["saved"])}
        picked = st.multiselect("اختر المقالات (بالترتيب الذي تُقرأ به)", list(labels), default=list(labels)[:5], key="bl_pick")
        st.caption("تُقرأ حسب إعدادات «🎧 إعدادات القراءة الصوتية» أعلى الصفحة (الصوت والسرعة وما يُقرأ).")
        if st.button("🎙️ اصنع النشرة", key="bl_go", use_container_width=True):
            if not picked:
                st.warning("اختر مقالاً واحداً على الأقل.")
            else:
                ss = st.session_state
                prog = st.progress(0.0, text="جارٍ تجهيز النصوص…")
                parts = []
                for n, lab in enumerate(picked):
                    x = labels[lab]
                    txt, _ = speech_text(x["url"], x.get("title_ar", ""), ss.get("tts_mode", TTS_MODES[0]))
                    num = ORDINALS[n] if n < len(ORDINALS) else str(n + 1)
                    parts.append(f"الخبر {num}. من {source_name(x.get('domain', ''))}. {txt}")
                    prog.progress((n + 1) / (len(picked) + 1), text=f"جُهّز {n + 1} من {len(picked)}")
                full = "نشرة رادار الأخبار. " + " ... ".join(parts) + " ... انتهت النشرة."
                prog.progress(0.95, text=f"جارٍ النطق (حوالي {len(full) / 13 / 60:.0f} دقيقة صوت)…")
                res = make_audio(full, core.VOICES[ss.get("tts_voice", list(core.VOICES)[0])], ss.get("tts_rate", 0))
                prog.empty()
                if res:
                    ss["bulletin"] = res
        if st.session_state.get("bulletin"):
            audio_block(st.session_state["bulletin"], "bulletin", "marsad_bulletin")
    st.caption(f"عدد المحفوظات: {len(s['saved'])}" + (f" — المعروض: {len(items)}" if q.strip() else ""))
    sums = st.session_state.setdefault("sv_sum", {})
    for it in items:
        h = hashlib.md5(it["url"].encode()).hexdigest()[:10]
        with st.container(border=True):
            st.markdown(card_html(it) + snippet_html(it, []), unsafe_allow_html=True)
            try:
                when = datetime.fromisoformat(it.get("saved_at", "")).astimezone(core.TZ).strftime("%Y-%m-%d %H:%M")
                st.caption(f"📌 حُفظ: {when}")
            except Exception:
                pass
            st.text_area(
                "📝 ملاحظتي (لربط الأحداث ببعضها)", value=it.get("note", ""), key=f"note_{h}", height=80,
                on_change=set_note, args=(it["url"], f"note_{h}"),
            )
            b1, b2 = st.columns(2)
            if b1.button("📝 تلخيص المقال", key=f"svsum_{h}"):
                with st.spinner("جارٍ التلخيص…"):
                    sums[it["url"]] = core.summarize(it["url"], get_key())
            b2.button("🗑️ حذف من المحفوظات", key=f"del_{h}", on_click=delete_item, args=(it["url"],))
            listen_widget(it, f"sv_{h}")
            if it["url"] in sums:
                st.info(sums[it["url"]])
    with st.expander("💾 نسخة احتياطية (تنزيل / استيراد) — تشمل المحفوظات والمصادر والكتّاب المضافين"):
        st.download_button(
            "⬇️ تنزيل كل بياناتي (JSON)", data=json.dumps(s, ensure_ascii=False, indent=1),
            file_name="marsad_backup.json", mime="application/json",
        )
        up = st.file_uploader("⬆️ استيراد نسخة احتياطية", type=["json"], key="sv_up")
        if up is not None and st.session_state.get("sv_up_done") != (up.name, up.size):
            try:
                st.session_state["store"] = store.merge(s, json.loads(up.getvalue().decode("utf-8")))
                persist()
                st.session_state["sv_up_done"] = (up.name, up.size)
                st.rerun()
            except ValueError:
                st.error("الملف ليس نسخة احتياطية صالحة.")
        if PERSIST and st.button("🔄 تحديث من التخزين الدائم (لو حفظت من جهاز آخر)", key="sv_reload"):
            try:
                st.session_state["store"] = store.load(GH_TOKEN, GH_GIST)
                st.rerun()
            except Exception as e:
                st.error(f"تعذّر التحديث ({type(e).__name__})")


def render_manage():
    if st.session_state.get("flash"):
        st.success(st.session_state.pop("flash"))
    st.markdown("### 🔗 أضف مصدراً أو كاتباً من رابط")
    st.caption(
        "الصق رابط خبر، أو رابط تغريدة (تويتر/X) تحوي رابط مقال، وسيستخرج التطبيق الموقع والكاتب لتضيفهما بضغطة. "
        "يمكنك أيضاً تعبئة الخانات يدوياً."
    )
    st.text_input("رابط الخبر أو التغريدة", key="ms_url", placeholder="https://...")
    st.button("🔍 حلّل الرابط", on_click=do_analyze, use_container_width=True, key="ms_an")
    an = st.session_state.get("analysis")
    if an:
        if an.get("error"):
            st.warning(an["error"])
        tw = an.get("tweet")
        if tw:
            st.info(f"🐦 تغريدة {tw.get('author', '')} (@{tw.get('handle', '')}): {tw.get('text', '')}")
        if an.get("domain"):
            st.markdown(f"**الموقع:** {an.get('site_name')} (`{an['domain']}`)  \n**العنوان:** {an.get('title', '')}")
        if an.get("authors"):
            st.selectbox("الكتّاب المكتشفون (اختر لتعبئة بياناته)", [a["raw"] for a in an["authors"]], key="mw_pick", on_change=pick_author)
    st.markdown("#### ➕ إضافة كمصدر إخباري")
    st.text_input("اسم المصدر", key="ms_name")
    st.text_input("الدومين (مثال: example.com)", key="ms_domain")
    st.radio("يُضاف إلى تاب", ["إسرائيلية", "أمريكية", "بريطانية"], key="ms_group", horizontal=True)
    st.radio("لغة المصدر", ["إنجليزي", "عبري", "كلاهما"], key="ms_lang", horizontal=True)
    st.button("➕ أضف المصدر", on_click=add_source, use_container_width=True, key="ms_add")
    st.markdown("#### ➕ إضافة ككاتب")
    st.text_input("اسم الكاتب بالإنجليزية (يُستخدم في البحث)", key="mw_en")
    st.text_input("الاسم بالعربية (للعرض)", key="mw_ar")
    st.text_input("الاسم بالعبرية (اختياري — لمواقع عبرية)", key="mw_heb")
    st.text_input("المنفذ / الصحيفة", key="mw_outlet")
    st.text_input("مواقع نشره (دومين أو أكثر بفاصلة)", key="mw_sites")
    st.radio("جنسية المنفذ", ["أمريكي", "بريطاني", "إسرائيلي"], key="mw_country", horizontal=True)
    st.radio("نوع كتاباته", ["رأي", "تحليل", "خبر"], key="mw_kind", horizontal=True)
    st.button("➕ أضف الكاتب", on_click=add_writer, use_container_width=True, key="mw_add")
    st.markdown("#### ما أضفتَه")
    if not S()["sources"] and not S()["writers"]:
        st.caption("لم تضف شيئاً بعد.")
    for x in S()["sources"]:
        r1, r2 = st.columns([4, 1])
        r1.markdown(f"🌐 **{x['label']}** — `{x['domain']}` — تاب: {x['group']} — لغة: {x['lang']}")
        r2.button("حذف", key=f"rs_{x['domain']}_{x['group']}", on_click=remove_source, args=(x["domain"], x["group"]))
    for w in S()["writers"]:
        r1, r2 = st.columns([4, 1])
        r1.markdown(f"✍️ **{w['name_ar']}** ({w['name_en']}) — {w['outlet']} — `{', '.join(w['sites'])}`")
        r2.button("حذف", key=f"rw_{w['id']}", on_click=remove_writer, args=(w["id"],))
    if not PERSIST:
        st.caption("⚠️ بدون التخزين الدائم تضيع هذه الإضافات عند تحديث الصفحة؛ نزّل نسخة احتياطية من تاب «المحفوظات».")


with tab_sv:
    render_saved()

with tab_ms:
    render_manage()
