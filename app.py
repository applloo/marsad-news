# -*- coding: utf-8 -*-
"""
رادار الأخبار العالمية — بحث بالعربية في مصادر إسرائيلية وأمريكية وبريطانية + بحث عام عبر GDELT
"""
import html
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote

import streamlit as st

import core
from core import fmt_seen, tr
from sources import ISRAEL, UK, USA

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

    st.divider()
    paras = "".join(f"<p>{html.escape(p)}</p>" for p in body_ar.split("\n") if p.strip())
    st.markdown(f"<div class='article-body'>{paras}</div>", unsafe_allow_html=True)
    with st.expander("النص الأصلي"):
        st.text(art["text"])


if "view" in st.query_params:
    reader_page()
    st.stop()

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

DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9\-\.]*\.[a-z]{2,}$")


def pick_sources(key, groups, allow_custom=True):
    """يعرض اختيار المصادر ويعيد قائمة (label, domains, lang)"""
    chosen = []
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


def do_search(key, jobs, sel=None, terms=None, pre=False):
    terms = terms or [t.strip() for t in re.split(r"[,،;\n]+", query) if t.strip()]
    if not terms:
        st.warning("اكتب كلمة بحث أولاً (في الخانة أعلى الصفحة).")
        return
    if not jobs:
        st.warning("اختر مصدراً واحداً على الأقل.")
        return
    hidden = 0
    with st.status("جارٍ البحث…", expanded=True) as status:
        items, errs, used = core.run_search(
            terms, joiner, match, jobs, start_utc, end_utc, max_rec, ctype, progress=lambda m: status.update(label=m)
        )
        status.update(label="جارٍ ترجمة العناوين…")
        items = core.translate_titles(items)
        matchers = core.make_matchers_pre(jobs) if pre else core.make_matchers(terms, [j["code"] for j in jobs])
        if verify and items:
            status.update(label="جارٍ فحص نصوص المقالات…")
            core.enrich_items(items, matchers, joiner)
        raw = list(items)
        if hide_nomatch:
            items = [a for a in items if not (a.get("fetched") and not a.get("found"))]
            hidden = len(raw) - len(items)
        status.update(label=f"تم — {len(items)} نتيجة", state="complete")
    counts = {}
    for a in raw:
        n = source_name(a.get("domain", ""))
        counts[n] = counts.get(n, 0) + 1
    silent = [lbl for lbl, _, _ in (sel or []) if lbl not in counts]
    hl = sorted({st_ for alts in matchers for stems in alts for st_ in stems}, key=len, reverse=True)
    st.session_state[f"res_{key}"] = {
        "items": items, "errors": errs, "used": used, "summaries": {},
        "counts": counts, "silent": silent, "hidden": hidden, "hl": hl,
    }


def highlight(text, stems):
    out = html.escape(text)
    for st_ in stems:
        out = re.sub(f"({re.escape(html.escape(st_))})", r"<b>\1</b>", out, flags=re.I)
    return out


def render_results(key):
    data = st.session_state.get(f"res_{key}")
    if data is None:
        return
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
        link = f"?view={quote(url, safe='')}&seen={a.get('seendate', '')}&t={quote(a.get('title', '')[:200], safe='')}"
        orig = html.escape(a.get("title", ""))
        en = a.get("title_en", "")
        en_line = f"<div class='ltr' dir='ltr'>EN: {html.escape(en)}</div>" if en and en != a.get("title") else ""
        dom = a.get("domain", "")
        sname = source_name(dom)
        src = html.escape(sname) + (f" ({html.escape(dom)})" if sname != dom else "")
        ctag = a.get("ctype", "") + ("" if a.get("ctype_sure") else " (تقدير)")
        with st.container(border=True):
            st.markdown(
                f"<div class='ar-title'>{html.escape(a.get('title_ar', ''))}</div>"
                f"<div class='ltr' dir='ltr'>{orig}</div>{en_line}"
                f"<div class='meta'>🕒 {fmt_seen(a.get('seendate', ''))} (القاهرة)<br>"
                f"🌐 المصدر: {src} · 🏳️ الدولة: {html.escape(a.get('country_ar', '') or a.get('sourcecountry', ''))}"
                f" · <span class='badge'>{html.escape(ctag)}</span></div>"
                f"<a class='btn' href='{html.escape(link)}' target='_blank' rel='noopener'>ترجم المقال</a>",
                unsafe_allow_html=True,
            )
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


tab_ml, tab_il, tab_us, tab_uk, tab_gd = st.tabs(
    ["🔤 ترجمة ثم بحث", "🇮🇱 إسرائيلية (عبري)", "🇺🇸 أمريكية", "🇬🇧 بريطانية", "🌐 بحث عام GDELT"]
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

COUNTRIES = {"كل الدول": None, "الولايات المتحدة": "US", "بريطانيا": "UK", "إسرائيل": "IS"}

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
