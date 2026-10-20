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

st.set_page_config(page_title="مرصد - ترجمة ديناميكية", page_icon="📰", layout="centered")

TZ = ZoneInfo("Africa/Cairo")
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

st.markdown("""
<style>
.stApp, .stMarkdown, label, [data-testid="stWidgetLabel"] {direction: rtl; text-align: right;}
.ar-title {font-size:1.15rem; font-weight:700; line-height:1.7; margin-bottom:4px;}
.ltr {direction:ltr; text-align:left; color:#6b7280; font-size:.9rem; margin-bottom:2px;}
.meta {color:#6b7280; font-size:.85rem; margin:6px 0;}
.badge {background:#eef2ff; color:#3730a3; padding:1px 8px; border-radius:10px; font-size:.78rem;}
</style>
""", unsafe_allow_html=True)

# ترجمة ديناميكية لأي جملة عربية - بدون قاموس ثابت - باستخدام Google Translate API المجاني
@lru_cache(maxsize=1024)
def tr_dynamic(text: str, src="ar", dest="en") -> str:
    text = text.strip()
    if not text: return ""
    # لو النص أصلا إنجليزي، رجعه
    if not any('\u0600' <= c <= '\u06FF' for c in text):
        return text
    try:
        # Google Translate free endpoint
        url = "https://translate.googleapis.com/translate_a/single"
        params = {"client":"gtx","sl":src,"tl":dest,"dt":"t","q":text}
        r = requests.get(url, params=params, timeout=10, headers={"User-Agent":"Mozilla/5.0"})
        data = r.json()
        # data[0] is list of translations
        translated = "".join([seg[0] for seg in data[0] if seg[0]])
        return translated if translated else text
    except Exception as e:
        # fallback: رجع النص الأصلي لو فشلت الترجمة
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
    try:
        r = requests.get(GDELT_URL, params=params, timeout=30)
        if r.status_code != 200: return [], f"HTTP {r.status_code}"
        try:
            return r.json().get("articles", []), ""
        except:
            return [], r.text[:200]
    except Exception as e:
        return [], str(e)

SCOPES = {
    "جميع المصادر": [(None, "eng"), (None, "heb")],
    "مصادر أمريكية فقط": [("US", "eng")],
    "مصادر إسرائيلية فقط": [("IS", "eng"), ("IS", "heb")],
    "مصادر بريطانية فقط": [("UK", "eng")],
}

def run_search(terms, joiner, scope, start_utc, end_utc, max_rec, ctype):
    jobs = SCOPES[scope]
    request_n = min(250, max_rec * 3)
    found, errors, all_queries = {}, [], []
    for i, (country, lang) in enumerate(jobs):
        parts = []
        for t in terms:
            en = tr_dynamic(t, "ar", "en")
            if not en: continue
            if " " in en:
                parts.append(f'"{en}"')
            else:
                parts.append(en)
        if not parts: continue
        if joiner == "OR":
            q = "(" + " OR ".join(parts) + ")"
        else:
            q = " ".join(parts)
        all_queries.append(q)
        if i > 0: time.sleep(5.2)
        arts, err = gdelt_call(q, start_utc, end_utc, request_n, country, lang)
        if err: errors.append(f"{q}: {err}")
        for a in arts: found.setdefault(a.get("url"), a)
    items = list(found.values())
    def classify(url, title):
        url=url.lower(); title=title.lower()
        if "/opinion" in url or "/editorial" in url: return "رأي"
        if "/analysis" in url: return "تحليل"
        return "خبر"
    for a in items: a["ctype"]=classify(a.get("url",""), a.get("title",""))
    if ctype != "الكل":
        items=[a for a in items if a["ctype"]==ctype]
    items.sort(key=lambda a: a.get("seendate",""), reverse=True)
    return items[:max_rec], errors, " | ".join(all_queries)

# UI
st.title("📰 مرصد - ترجمة ديناميكية لأي خبر")
st.caption("اكتب أي شيء بالعربية - سيتم ترجمته فورا للإنجليزية والعبرية والبحث في آلاف المواقع. مثال: وزير خارجية إيران، زلزال تركيا، لقاء السيسي وترامب")

query = st.text_input("🔎 كلمات البحث", placeholder="مثال: لقاء وزير الخارجية المصري مع وزير خارجية إيران، أو: روسيا أوكرانيا، زلزال تركيا", value="وزير الخارجية المصري مع وزير خارجية إيران")

c1, c2 = st.columns(2)
joiner_label = c1.radio("عند تعدد الكلمات", ["أيٌّ منها (OR) - كل المواضيع", "كلها معاً (AND) - أخبار تجمع المواضيع"], index=1)
exact = c2.checkbox("مطابقة العبارة", value=True)
joiner = "OR" if "OR" in joiner_label else "AND"

with st.expander("⚙️ الفلاتر المتقدمة", expanded=True):
    scope = st.selectbox("المصادر", list(SCOPES.keys()))
    ctype = st.selectbox("نوع المحتوى", ["الكل", "خبر", "تحليل", "رأي"])
    mode = st.radio("النطاق الزمني", ["آخر أيام", "آخر ساعات", "تواريخ محددة"], horizontal=True, index=0)
    now_utc = datetime.now(timezone.utc)
    if mode == "آخر ساعات":
        h = st.slider("عدد الساعات", 1, 72, 24)
        start_utc, end_utc = now_utc - timedelta(hours=h), now_utc
    elif mode == "آخر أيام":
        d = st.slider("عدد الأيام", 1, 90, 7)
        start_utc, end_utc = now_utc - timedelta(days=d), now_utc
    else:
        today = datetime.now(TZ).date()
        rng = st.date_input("من – إلى", value=(today - timedelta(days=3), today), max_value=today)
        if isinstance(rng, (list, tuple)) and len(rng) == 2: s, e = rng
        else: s = e = rng[0] if isinstance(rng, (list, tuple)) else rng
        start_utc = datetime(s.year, s.month, s.day, tzinfo=TZ).astimezone(timezone.utc)
        end_utc = datetime(e.year, e.month, e.day, 23, 59, 59, tzinfo=TZ).astimezone(timezone.utc)
    max_rec = st.slider("عدد النتائج", 10, 100, 30, step=10)

if st.button("ابحث", type="primary", use_container_width=True):
    raw_terms = [t.strip() for t in re.split(r"[,،;\n]+", query) if t.strip()]
    if len(raw_terms) == 1 and " " not in raw_terms[0]:
        terms = raw_terms
    elif len(raw_terms) == 1:
        # لو كتب جملة طويلة واحدة مثل "وزير الخارجية المصري مع وزير خارجية إيران" اعتبرها مصطلح واحد
        # لكن لو كتب "روسيا أوكرانيا" بدون فاصلة، قسمها إذا كانت كلمات قصيرة
        if len(raw_terms[0].split()) <= 3 and "مع" not in raw_terms[0] and "وزير" not in raw_terms[0]:
            terms = [p for p in raw_terms[0].split() if p]
        else:
            terms = raw_terms
    else:
        terms = raw_terms

    if not terms:
        st.warning("اكتب كلمة بحث")
    else:
        with st.spinner("يترجم و يبحث..."):
            translated = []
            for t in terms:
                en = tr_dynamic(t, "ar", "en")
                he = tr_dynamic(t, "ar", "iw")
                translated.append(f"{t} → EN:{en} | HE:{he}")
        st.info(" | ".join(translated))
        with st.status("يبحث في GDELT...", expanded=True) as status:
            items, errs, used_q = run_search(terms, joiner, scope, start_utc, end_utc, max_rec, ctype)
            status.update(label=f"تم — {len(items)} نتيجة | {used_q[:200]}", state="complete")
        st.session_state["results"]=items
        st.session_state["errors"]=errs
        st.session_state["used_q"]=used_q

items = st.session_state.get("results")
if items is not None:
    for err in st.session_state.get("errors", []):
        st.warning(f"تنبيه: {err}")
    if not items:
        st.info("لا نتائج - جرب توسيع الوقت")
    for i, a in enumerate(items):
        url=a.get("url",""); title=a.get("title",""); domain=a.get("domain",""); country=a.get("sourcecountry",""); seen=a.get("seendate","")
        with st.container(border=True):
            # ترجم العنوان للعربية ديناميكيا
            title_ar = tr_dynamic(title, "auto", "ar")
            st.markdown(f"<div class='ar-title'>{html.escape(title_ar)}</div><div class='ltr' dir='ltr'>{html.escape(title)}</div><div class='meta'>🕒 {fmt_seen(seen)} · 🌐 {html.escape(domain)} · {html.escape(country)} · <span class='badge'>{a.get('ctype','')}</span></div>", unsafe_allow_html=True)
            c1,c2=st.columns(2)
            with c1: st.link_button("🔗 المصدر", url, use_container_width=True)
            with c2: st.link_button("🌐 ترجم", f"https://translate.google.com/translate?sl=auto&tl=ar&u={quote(url, safe='')}", use_container_width=True)
