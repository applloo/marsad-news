# -*- coding: utf-8 -*-
import re
import time
import html
import requests
import streamlit as st
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor

st.set_page_config(page_title="مرصد - فلتر دقيق", page_icon="🎯", layout="centered")

TZ = ZoneInfo("Africa/Cairo")
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

st.markdown("""
<style>
.stApp, .stMarkdown, label, [data-testid="stWidgetLabel"] {direction: rtl; text-align: right;}
.ar-title {font-size:1.25rem; font-weight:800; line-height:1.6; margin-bottom:6px; color:#1e3a8a;}
.en-title {direction:ltr; text-align:left; color:#6b7280; font-size:.88rem; margin-bottom:2px;}
.he-title {direction:rtl; text-align:right; color:#7c3aed; font-size:.88rem; margin-bottom:4px;}
.meta {color:#6b7280; font-size:.85rem; margin:6px 0;}
.badge {background:#eef2ff; color:#3730a3; padding:2px 8px; border-radius:10px; font-size:.78rem;}
.badge-il {background:#fef3c7; color:#92400e; padding:2px 8px; border-radius:10px; font-size:.78rem;}
.relevance {background:#ecfdf5; color:#065f46; padding:2px 8px; border-radius:10px; font-size:.75rem; margin-right:6px;}
</style>
""", unsafe_allow_html=True)

@lru_cache(maxsize=2048)
def tr_dynamic(text: str, src="auto", dest="en") -> str:
    text = text.strip()
    if not text: return ""
    if len(text) < 2: return text
    if src == dest: return text
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {"client":"gtx","sl":src,"tl":dest,"dt":"t","q":text}
        r = requests.get(url, params=params, timeout=6, headers={"User-Agent":"Mozilla/5.0"})
        data = r.json()
        translated = "".join([seg[0] for seg in data[0] if seg[0]])
        return translated if translated else text
    except Exception:
        return text

def fmt_seen(seen: str) -> str:
    try:
        dt = datetime.strptime(seen, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone(TZ)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return seen or "-"

def gdelt_call(query, start_utc, end_utc, max_rec, country=None, lang=None):
    q = query
    if country: q += f" sourcecountry:{country}"
    if lang: q += f" sourcelang:{lang}"
    params = {"query": q, "mode": "ArtList", "format": "json", "maxrecords": max_rec, "sort": "DateDesc",
              "startdatetime": start_utc.strftime("%Y%m%d%H%M%S"), "enddatetime": end_utc.strftime("%Y%m%d%H%M%S")}
    for _ in range(3):
        try:
            r = requests.get(GDELT_URL, params=params, timeout=12)
            if r.status_code == 429:
                time.sleep(6); continue
            if r.status_code != 200:
                time.sleep(1); continue
            data = r.json()
            return data.get("articles", [])
        except Exception:
            time.sleep(1); continue
    return []

SCOPES = {
    "جميع المصادر (EN+HE) - الأفضل": [(None, "eng", "en"), (None, "heb", "iw")],
    "مصادر إسرائيلية فقط (EN+HE)": [("IS", "eng", "en"), ("IS", "heb", "iw")],
    "مصادر أمريكية فقط": [("US", "eng", "en")],
    "مصادر بريطانية فقط": [("UK", "eng", "en")],
    "إنجليزي فقط (أسرع)": [(None, "eng", "en")],
}

def is_relevant(title, search_terms_en, search_terms_he):
    title_low = title.lower()
    for term in search_terms_en + search_terms_he:
        term_low = term.lower().strip('"')
        if len(term_low) < 2: continue
        # كلمة واحدة
        if " " not in term_low:
            if term_low in title_low:
                return True, term
        else:
            # عبارة مركبة - لازم كل الكلمات موجودة
            words = [w for w in term_low.split() if len(w) > 2]
            if words and all(w in title_low for w in words):
                return True, term
            # أو 70% من الكلمات
            if words and sum(1 for w in words if w in title_low) >= len(words)*0.7:
                return True, term
    return False, ""

def run_search(terms, joiner, scope, start_utc, end_utc, max_rec, ctype):
    jobs = SCOPES[scope]
    found = {}
    all_queries = []
    search_terms_en = []
    search_terms_he = []
    for t in terms:
        en = tr_dynamic(t, "ar", "en")
        he = tr_dynamic(t, "ar", "iw")
        if en: search_terms_en.append(en)
        if he: search_terms_he.append(he)

    for i, (country, gdelt_lang, trans_lang) in enumerate(jobs):
        parts = []
        if trans_lang == "iw":
            for t in search_terms_he:
                parts.append(f'"{t}"' if " " in t else t)
        else:
            for t in search_terms_en:
                parts.append(f'"{t}"' if " " in t else t)
        if not parts: continue
        q = "(" + " OR ".join(parts) + ")" if joiner == "OR" else " ".join(parts)
        all_queries.append(f"[{trans_lang}:{q}]")
        if i > 0: time.sleep(5.2)
        arts = gdelt_call(q, start_utc, end_utc, min(250, max_rec*3), country, gdelt_lang)
        for a in arts:
            a["_q_lang"] = trans_lang
            found.setdefault(a.get("url"), a)

    items = list(found.values())
    # فلتر دقيق: احتفظ فقط بالأخبار اللي عنوانها فيه كلمة البحث
    filtered = []
    for a in items:
        title = a.get("title","")
        rel, matched = is_relevant(title, search_terms_en, search_terms_he)
        if rel:
            a["_matched"] = matched
            filtered.append(a)
    
    # لو الفلتر شال كل حاجة، رجع أول 10 بدون فلتر (عشان ميطلعش فاضي)
    if not filtered and items:
        filtered = items[:10]
        for a in filtered: a["_matched"] = "عام"

    def classify(url):
        u=url.lower()
        if "/opinion" in u or "/editorial" in u or "/op-ed" in u: return "رأي"
        if "/analysis" in u or "/explainer" in u: return "تحليل"
        return "خبر"
    for a in filtered: a["ctype"]=classify(a.get("url",""))
    if ctype != "الكل": filtered=[a for a in filtered if a["ctype"]==ctype]
    filtered.sort(key=lambda a: a.get("seendate",""), reverse=True)
    return filtered[:max_rec], " | ".join(all_queries), len(items), len(filtered)

def translate_titles_batch(items):
    def work(a):
        title = a.get("title","")
        lang = a.get("language","").lower()
        q_lang = a.get("_q_lang","en")
        if "hebrew" in lang or q_lang == "iw":
            ar = tr_dynamic(title, "iw", "ar")
            he = title
            en = tr_dynamic(title, "iw", "en")
        else:
            ar = tr_dynamic(title, "en", "ar")
            en = title
            he = tr_dynamic(title, "en", "iw")
        a["title_ar"] = ar
        a["title_en"] = en
        a["title_he"] = he
        return a
    with ThreadPoolExecutor(max_workers=5) as ex:
        return list(ex.map(work, items))

# UI
st.title("مرصد - نتائج دقيقة 100%")
st.caption("العبري مهم جدا - يبحث في Haaretz, Ynet, Times of Israel ويترجم للعربية - مع فلتر ذكي للعلاقة")

query = st.text_input("🔎 كلمات البحث", placeholder="مثال: السيسي، مصر، اليمن، غزة", value="السيسي، مصر")
c1, c2 = st.columns(2)
joiner_label = c1.radio("عند تعدد الكلمات", ["أيٌّ منها (OR) - كل المواضيع", "كلها معاً (AND)"], index=0)
joiner = "OR" if "OR" in joiner_label else "AND"

with st.expander("⚙️ الفلاتر - العبري مهم", expanded=True):
    scope = st.selectbox("المصادر", list(SCOPES.keys()), index=0)
    ctype = st.selectbox("نوع المحتوى", ["الكل", "خبر", "تحليل", "رأي"])
    mode = st.radio("النطاق", ["آخر أيام", "آخر ساعات"], horizontal=True, index=0)
    now_utc = datetime.now(timezone.utc)
    if mode == "آخر ساعات":
        h = st.slider("ساعات", 1, 72, 24)
        start_utc, end_utc = now_utc - timedelta(hours=h), now_utc
    else:
        d = st.slider("أيام", 1, 90, 7)
        start_utc, end_utc = now_utc - timedelta(days=d), now_utc
    max_rec = st.slider("عدد النتائج", 10, 100, 40, step=10)
    strict = st.checkbox("فلتر دقيق (العنوان يجب أن يحتوي كلمة البحث)", value=True, help="لو مفعل، يشيل أخبار جنوب السودان اللي ملهاش علاقة")

if st.button("ابحث", type="primary", use_container_width=True):
    raw_terms = [t.strip() for t in re.split(r"[,،;\n]+", query) if t.strip()]
    if len(raw_terms)==1 and " " in raw_terms[0] and "," not in query and "،" not in query:
        if len(raw_terms[0].split()) <= 3:
            terms=[p for p in raw_terms[0].split() if p]
        else:
            terms=raw_terms
    else:
        terms=raw_terms
    if not terms:
        st.warning("اكتب كلمة بحث")
    else:
        with st.spinner("يترجم عربي → إنجليزي + عبري..."):
            for t in terms:
                en=tr_dynamic(t,"ar","en")
                he=tr_dynamic(t,"ar","iw")
                st.info(f"{t} → EN: {en} | HE: {he}")
        with st.status("يبحث ويترجم...", expanded=True) as status:
            items, used_q, total, filtered_count = run_search(terms, joiner, scope, start_utc, end_utc, max_rec, ctype)
            if strict and total > filtered_count:
                status.update(label=f"فلتر: من {total} خبر، {filtered_count} فقط لهم علاقة مباشرة | {used_q[:150]}")
            else:
                status.update(label=f"يترجم {len(items)} عنوان...")
            items = translate_titles_batch(items)
            status.update(label=f"تم — {len(items)} نتيجة دقيقة | {used_q[:200]}", state="complete")
        st.session_state["results"]=items
        st.session_state["stats"]=(total, filtered_count)

items = st.session_state.get("results")
if items is not None:
    total, filtered_count = st.session_state.get("stats", (0,0))
    if total != filtered_count and total > 0:
        st.success(f"✅ فلتر ذكي: من {total} خبر عشوائي، وجدنا {filtered_count} خبر له علاقة مباشرة بـ '{query}'")
    if not items:
        st.info("لا نتائج مطابقة - جرب توسيع الوقت أو إلغاء الفلتر الدقيق")
    for a in items:
        url=a.get("url",""); domain=a.get("domain",""); country=a.get("sourcecountry",""); seen=a.get("seendate",""); lang=a.get("language","")
        title_en=a.get("title_en","") or a.get("title","")
        title_ar=a.get("title_ar","") or title_en
        title_he=a.get("title_he","")
        is_hebrew = "hebrew" in lang.lower() or a.get("_q_lang")=="iw"
        matched = a.get("_matched","")
        with st.container(border=True):
            st.markdown(f"<div class='ar-title'>{html.escape(title_ar)}</div>", unsafe_allow_html=True)
            if is_hebrew and title_he:
                st.markdown(f"<div class='he-title'>HE: {html.escape(title_he)}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='en-title'>EN: {html.escape(title_en)}</div>", unsafe_allow_html=True)
            badge_class = "badge-il" if country=="IS" or is_hebrew else "badge"
            flag = "🇮🇱" if country=="IS" or is_hebrew else "🌐"
            rel_badge = f"<span class='relevance'>مطابق: {html.escape(matched)}</span>" if matched and matched != "عام" else ""
            st.markdown(f"<div class='meta'>🕒 {fmt_seen(seen)} · {flag} {html.escape(domain)} · {html.escape(country)} · {html.escape(lang)} · <span class='{badge_class}'>{a.get('ctype','')}</span> {rel_badge}</div>", unsafe_allow_html=True)
            c1,c2=st.columns(2)
            with c1: st.link_button("🔗 المصدر", url, use_container_width=True)
            with c2: st.link_button("🌐 ترجم المقال كامل", f"https://translate.google.com/translate?sl=auto&tl=ar&u={quote(url, safe='')}", use_container_width=True)
