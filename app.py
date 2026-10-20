# -*- coding: utf-8 -*-
import re
import time
import html
import json
import socket
import ipaddress
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote, urlparse
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import requests
import streamlit as st
import trafilatura
from deep_translator import GoogleTranslator

st.set_page_config(page_title="مرصد - بحث متعدد الكلمات", page_icon="📰", layout="centered")

TZ = ZoneInfo("Africa/Cairo")
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36"}

st.markdown("""
<style>
.stApp, .stMarkdown, label, [data-testid="stWidgetLabel"] {direction: rtl; text-align: right;}
.ar-title {font-size:1.15rem; font-weight:700; line-height:1.7; margin-bottom:4px;}
.ltr {direction:ltr; text-align:left; color:#6b7280; font-size:.9rem; margin-bottom:2px;}
.meta {color:#6b7280; font-size:.85rem; margin:6px 0;}
.badge {background:#eef2ff; color:#3730a3; padding:1px 8px; border-radius:10px; font-size:.78rem;}
a.btn {display:inline-block; background:#1d4ed8; color:#fff !important; padding:8px 18px; border-radius:8px; text-decoration:none; font-weight:600; margin-top:4px;}
.article-body p {line-height:2; font-size:1.05rem; margin-bottom:1rem;}
</style>
""", unsafe_allow_html=True)

@lru_cache(maxsize=4096)
def tr(text: str, src: str = "auto", dest: str = "ar") -> str:
    text = (text or "").strip()
    if not text: return ""
    for _ in range(2):
        try:
            return GoogleTranslator(source=src, target=dest).translate(text) or text
        except Exception:
            time.sleep(0.6)
    return text

def is_safe_url(url: str) -> bool:
    try:
        p = urlparse(url)
        if p.scheme not in ("http","https") or not p.hostname: return False
        for info in socket.getaddrinfo(p.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved: return False
        return True
    except Exception:
        return False

@lru_cache(maxsize=256)
def fetch_article(url: str):
    if not is_safe_url(url): return None
    try:
        r = requests.get(url, headers=UA, timeout=25)
        r.raise_for_status()
        data = trafilatura.extract(r.content, output_format="json", with_metadata=True, favor_recall=True, include_comments=False)
        if not data: return None
        d = json.loads(data)
        text = d.get("text") or ""
        if len(text) < 200: return None
        return {"title": d.get("title") or "", "date": d.get("date") or "", "text": text}
    except Exception:
        return None

OPINION_RE = re.compile(r"/(opinion|op-ed|editorial|commentary|column|blogs?)/", re.I)
ANALYSIS_RE = re.compile(r"/(analysis|explainer|insight|deep-dive|in-depth)/", re.I)

def classify(url: str, title: str) -> str:
    if OPINION_RE.search(url): return "رأي"
    if ANALYSIS_RE.search(url): return "تحليل"
    return "خبر"

def fmt_seen(seen: str) -> str:
    try:
        dt = datetime.strptime(seen, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone(TZ)
        return dt.strftime("%Y-%m-%d  %H:%M")
    except Exception:
        return seen or "-"

# === ترجمة سريعة للكلمات الشائعة عشان ما نستهلكش API ===
FAST_MAP = {
    "سيسي": "Sisi", "سيسى": "Sisi", "السيسي": "Sisi", "السيسى": "Sisi",
    "مصر": "Egypt", "المصرية": "Egypt", "الجيش المصري": "Egyptian army",
    "الرئيس المصري": "Egyptian president Sisi", "وزير الخارجية المصري": "Egyptian foreign minister",
    "وزير الخارجيه المصري": "Egyptian foreign minister", "وزير الخارجية": "foreign minister",
    "اليمن": "Yemen", "روسيا": "Russia", "السعودية": "Saudi Arabia",
    "مصر السعودية": "Egypt Saudi Arabia", "غزة": "Gaza", "إسرائيل": "Israel", "اسرائيل": "Israel",
    "ترامب": "Trump", "أمريكا": "America", "بايدن": "Biden", "سيناء": "Sinai", "سد النهضة": "GERD"
}

def fast_translate(term: str, target: str):
    term = term.strip()
    if target == "en":
        if term in FAST_MAP: return FAST_MAP[term]
        # جرب اطول عبارة اولا
        for k in sorted(FAST_MAP, key=len, reverse=True):
            if k in term: return term.replace(k, FAST_MAP[k])
    return None

def build_query(terms, lang_code, joiner, exact):
    parts = []
    for t in terms:
        t = t.strip()
        if not t: continue
        ft = fast_translate(t, "en") if lang_code == "en" else None
        x = ft if ft else tr(t, "ar", lang_code)
        words = [w for w in re.split(r"\s+", x) if len(w) >= 2]
        if not words: continue
        if len(words) == 1:
            parts.append(words[0])
        elif exact or joiner == "OR":
            parts.append('"' + " ".join(words) + '"')
        else:
            parts.append(" ".join(words))
    if not parts: return ""
    if len(parts) == 1: return parts[0]
    if joiner == "OR":
        return "(" + " OR ".join(parts) + ")"
    return " ".join(parts)

def gdelt_call(query, start_utc, end_utc, max_rec, country=None, lang=None):
    q = query
    if country: q += f" sourcecountry:{country}"
    if lang: q += f" sourcelang:{lang}"
    params = {"query": q, "mode": "ArtList", "format": "json", "maxrecords": max_rec, "sort": "DateDesc",
              "startdatetime": start_utc.strftime("%Y%m%d%H%M%S"), "enddatetime": end_utc.strftime("%Y%m%d%H%M%S")}
    last_err = ""
    for _ in range(3):
        try:
            r = requests.get(GDELT_URL, params=params, timeout=40)
            if r.status_code == 429 or "limit requests" in r.text.lower():
                time.sleep(6); continue
            try:
                return r.json().get("articles", []), ""
            except ValueError:
                last_err = r.text.strip()[:200] or f"HTTP {r.status_code}"
                if "too short" in last_err.lower() or "too common" in last_err.lower(): break
                time.sleep(3)
        except requests.RequestException as e:
            last_err = str(e); time.sleep(3)
    return [], last_err

SCOPES = {
    "جميع المصادر": [(None, "eng", "en"), (None, "heb", "iw")],
    "مصادر أمريكية فقط": [("US", "eng", "en")],
    "مصادر إسرائيلية فقط": [("IS", "eng", "en"), ("IS", "heb", "iw")],
    "مصادر بريطانية فقط": [("UK", "eng", "en")],
}

def run_search(terms, joiner, exact, scope, start_utc, end_utc, max_rec, ctype, status):
    jobs = SCOPES[scope]
    request_n = min(250, max_rec * 3) if ctype != "الكل" else min(250, max_rec)
    found, errors = {}, []
    for i, (country, lang, code) in enumerate(jobs):
        q = build_query(terms, code, joiner, exact)
        if not q: continue
        status.update(label=f"جارٍ البحث ({i+1}/{len(jobs)}): {q}")
        if i > 0: time.sleep(5.2)
        arts, err = gdelt_call(q, start_utc, end_utc, request_n, country, lang)
        if err: errors.append(f"{q}: {err}")
        for a in arts: found.setdefault(a.get("url"), a)
    items = []
    for a in found.values():
        a["ctype"] = classify(a.get("url",""), a.get("title",""))
        if ctype == "الكل" or a["ctype"] == ctype: items.append(a)
    items.sort(key=lambda a: a.get("seendate",""), reverse=True)
    return items[:max_rec], errors

def translate_titles(items):
    def work(a):
        title = a.get("title","")
        a["title_ar"] = tr(title, "auto", "ar")
        a["title_en"] = title if (a.get("language","").lower()=="english") else tr(title, "auto", "en")
        return a
    with ThreadPoolExecutor(6) as ex:
        return list(ex.map(work, items))

def summarize(url: str):
    art = fetch_article(url)
    if not art: return "تعذّر جلب النص (اشتراك أو حجب)."
    sents = re.split(r"(?<=[.!?])\s+", art["text"])[:5]
    return "ملخص أولي: " + tr(" ".join(sents), "auto", "ar")

# صفحة قراءة
def reader_page():
    url = unquote(st.query_params.get("view",""))
    seen = st.query_params.get("seen","")
    orig_title = unquote(st.query_params.get("t",""))
    st.markdown("## 📖 قراءة المقال مترجماً")
    if not url.startswith(("http://","https://")):
        st.error("رابط غير صالح."); return
    st.markdown(f"🔗 **الأصلي:** [{html.escape(url)}]({url})")
    with st.spinner("جارٍ الجلب والترجمة..."):
        art = fetch_article(url)
        if not art:
            st.warning("تعذّر الاستخراج - افتح الرابط الأصلي"); return
        title = art["title"] or orig_title
        title_ar = tr(title, "auto", "ar")
        # ترجمة طويلة
        chunks = [art["text"][i:i+4000] for i in range(0, len(art["text"]), 4000)]
        with ThreadPoolExecutor(4) as ex:
            parts = list(ex.map(lambda c: tr(c, "auto", "ar"), chunks))
        body_ar = "\n".join(parts)
    if art["date"]: st.markdown(f"🕒 **نشر:** {art['date']}")
    if seen: st.markdown(f"🛰️ **رصد:** {fmt_seen(seen)}")
    st.markdown(f"### {title_ar}")
    st.markdown(f"<div class='ltr' dir='ltr'>{html.escape(title)}</div>", unsafe_allow_html=True)
    st.divider()
    paras = "".join(f"<p>{html.escape(p)}</p>" for p in body_ar.split("\n") if p.strip())
    st.markdown(f"<div class='article-body'>{paras}</div>", unsafe_allow_html=True)

if "view" in st.query_params:
    reader_page(); st.stop()

# الواجهة الرئيسية
st.title("📰 مرصد - بحث متعدد الكلمات")
st.caption("اكتب كلمات مفصولة بفاصلة: مثال سيسي، مصر، اليمن، روسيا، وزير الخارجية المصري - أو كل كلمة في سطر")

query = st.text_input("🔎 كلمات البحث", placeholder="مثال: سيسي، مصر، اليمن، روسيا، وزير الخارجية المصري", value="سيسي، مصر")
c1, c2 = st.columns(2)
joiner_label = c1.radio("عند تعدد الكلمات", ["أيٌّ منها (OR) - يجيب كل المواضيع", "كلها معاً (AND) - أخبار تجمع المواضيع"], index=0, horizontal=False)
exact = c2.checkbox("مطابقة العبارة كما كُتبت (للأسماء المركبة)", value=True)
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
    # تقسيم ذكي: يدعم فاصلة، فاصلة عربية، سطر جديد، فاصلة منقوطة
    raw_terms = [t.strip() for t in re.split(r"[,،;\n]+", query) if t.strip()]
    # لو المستخدم كتب بدون فواصل: "سيسي مصر اليمن" -> حول المسافات لفاصلة إذا كانوا كلمات منفصلة قصيرة
    if len(raw_terms) == 1 and " " in raw_terms[0]:
        # لو فيه عبارات طويلة مثل وزير الخارجية المصري احتفظ بها
        tmp = raw_terms[0]
        # استبدل العبارات المعروفة بمكان مؤقت
        placeholders = {}
        for idx, phrase in enumerate(["وزير الخارجية المصري", "الرئيس المصري", "الجيش المصري", "مصر السعودية", "سد النهضة"]):
            if phrase in tmp:
                key = f"__PH{idx}__"
                placeholders[key] = phrase
                tmp = tmp.replace(phrase, key)
        # قسم الباقي بالمسافات
        parts = [p.strip() for p in tmp.split() if p.strip()]
        # رجع العبارات
        final_terms = []
        for p in parts:
            if p in placeholders: final_terms.append(placeholders[p])
            else: final_terms.append(p)
        terms = final_terms
    else:
        terms = raw_terms

    if not terms:
        st.warning("اكتب كلمة بحث أولاً.")
    else:
        st.info(f"🔍 تبحث عن: {' | '.join(terms)} - الوضع: {joiner}")
        with st.status("جارٍ البحث…", expanded=True) as status:
            items, errs = run_search(terms, joiner, exact, scope, start_utc, end_utc, max_rec, ctype, status)
            status.update(label="ترجمة العناوين…")
            items = translate_titles(items)
            status.update(label=f"تم — {len(items)} نتيجة", state="complete")
        st.session_state["results"] = items
        st.session_state["errors"] = errs
        st.session_state["summaries"] = {}

items = st.session_state.get("results")
if items is not None:
    for err in st.session_state.get("errors", []):
        st.warning(f"تنبيه: {err}")
    if not items:
        st.info("لا نتائج - جرب توسيع الوقت أو استخدم كلمات إنجليزية: Sisi Egypt Yemen Russia")
    summaries = st.session_state.setdefault("summaries", {})
    for i, a in enumerate(items):
        url = a.get("url","")
        link = f"?view={quote(url, safe='')}&seen={a.get('seendate','')}&t={quote(a.get('title','')[:200], safe='')}"
        orig = html.escape(a.get("title",""))
        en = a.get("title_en","")
        en_line = f"<div class='ltr' dir='ltr'>EN: {html.escape(en)}</div>" if en and en != a.get("title") else ""
        with st.container(border=True):
            st.markdown(f"<div class='ar-title'>{html.escape(a.get('title_ar',''))}</div><div class='ltr' dir='ltr'>{orig}</div>{en_line}<div class='meta'>🕒 {fmt_seen(a.get('seendate',''))} · 🌐 {html.escape(a.get('domain',''))} · {html.escape(a.get('sourcecountry',''))} · <span class='badge'>{a.get('ctype','')}</span></div><a class='btn' href='{html.escape(link)}' target='_blank' rel='noopener'>ترجم المقال</a>", unsafe_allow_html=True)
            if st.button("📝 تلخيص", key=f"sum{i}"):
                with st.spinner("يلخص…"): summaries[url] = summarize(url)
            if url in summaries: st.info(summaries[url])
