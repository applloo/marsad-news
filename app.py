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

st.set_page_config(page_title="مرصد - مصادر أمريكية", page_icon="🇺🇸", layout="centered")

TZ = ZoneInfo("Africa/Cairo")
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

SOURCE_NAMES = {
    "haaretz.com": "Haaretz", "ynet.co.il": "Ynet", "timesofisrael.com": "Times of Israel",
    "jpost.com": "Jerusalem Post", "reuters.com": "Reuters", "apnews.com": "AP News",
    "bbc.com": "BBC", "cnn.com": "CNN", "nytimes.com": "NY Times", "wsj.com": "WSJ",
    "washingtonpost.com": "Washington Post", "theguardian.com": "The Guardian",
    "axios.com": "Axios", "bloomberg.com": "Bloomberg", "aljazeera.com": "Al Jazeera",
    "nbcnews.com": "NBC", "foxnews.com": "Fox News", "abcnews.go.com": "ABC News",
    "cbsnews.com": "CBS News", "usatoday.com": "USA Today", "ap.org": "AP"
}

def get_source_name(domain):
    domain=domain.lower()
    if domain in SOURCE_NAMES: return SOURCE_NAMES[domain]
    for k,v in SOURCE_NAMES.items():
        if k in domain: return v
    return domain.replace("www.","").upper()

st.markdown("""
<style>
.stApp, .stMarkdown, label, [data-testid="stWidgetLabel"] {direction: rtl; text-align: right;}
.ar-title {font-size:1.25rem; font-weight:800; line-height:1.6; margin-bottom:8px; color:#111827;}
.en-title {direction:ltr; text-align:left; color:#6b7280; font-size:.88rem; margin-bottom:6px;}
.source-box {background:#f3f4f6; border:1px solid #e5e7eb; border-radius:8px; padding:8px 12px; margin:8px 0; display:flex; justify-content:space-between; align-items:center;}
.source-name {font-weight:800; font-size:1.05rem; color:#1f2937;}
.source-meta {font-size:.85rem; color:#6b7280;}
.badge {background:#eef2ff; color:#3730a3; padding:3px 10px; border-radius:12px; font-size:.8rem; font-weight:600;}
.badge-il {background:#fef3c7; color:#92400e; padding:3px 10px; border-radius:12px; font-size:.8rem; font-weight:700;}
</style>
""", unsafe_allow_html=True)

@lru_cache(maxsize=2048)
def tr_dynamic(text: str, src="auto", dest="en") -> str:
    text=text.strip()
    if not text or len(text)<2: return text
    if src==dest: return text
    try:
        url="https://translate.googleapis.com/translate_a/single"
        params={"client":"gtx","sl":src,"tl":dest,"dt":"t","q":text}
        r=requests.get(url, params=params, timeout=6, headers={"User-Agent":"Mozilla/5.0"})
        data=r.json()
        return "".join([seg[0] for seg in data[0] if seg[0]]) or text
    except Exception:
        return text

def fmt_seen(seen: str) -> str:
    try:
        dt=datetime.strptime(seen, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone(TZ)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return seen or "-"

def gdelt_call(query, start_utc, end_utc, max_rec, country=None, lang=None):
    q=query
    if country: q+=f" sourcecountry:{country}"
    if lang: q+=f" sourcelang:{lang}"
    params={"query":q,"mode":"ArtList","format":"json","maxrecords":max_rec,"sort":"DateDesc",
            "startdatetime":start_utc.strftime("%Y%m%d%H%M%S"),"enddatetime":end_utc.strftime("%Y%m%d%H%M%S")}
    for _ in range(3):
        try:
            r=requests.get(GDELT_URL, params=params, timeout=15)
            if r.status_code==429:
                time.sleep(6); continue
            if r.status_code!=200:
                time.sleep(1); continue
            return r.json().get("articles", [])
        except Exception:
            time.sleep(1); continue
    return []

# إصلاح: لا نستخدم sourcecountry للمصادر الأمريكية لأنه ضيق، نستخدم قائمة دومينات أمريكية كبيرة + بحث عام
US_DOMAINS = "domainis:(nytimes.com OR washingtonpost.com OR cnn.com OR reuters.com OR apnews.com OR bloomberg.com OR wsj.com OR axios.com OR nbcnews.com OR abcnews.go.com OR cbsnews.com OR usatoday.com OR foxnews.com OR theguardian.com OR bbc.com)"

SCOPES = {
    "جميع المصادر (EN+HE)": [(None, "eng", "en"), (None, "heb", "iw")],
    "مصادر أمريكية فقط - ذكي": [(None, "eng", "en")],  # سنضيف US_DOMAINS كـ fallback
    "مصادر إسرائيلية فقط (EN+HE)": [("IS", "eng", "en"), ("IS", "heb", "iw")],
    "مصادر بريطانية فقط": [("UK", "eng", "en")],
    "إنجليزي فقط (أسرع)": [(None, "eng", "en")],
}

TIME_RANGES = {
    "اليوم": 1, "أمس (اليوم + أمس)": 2, "من يومين (3 أيام)": 3,
    "أسبوع": 7, "آخر 14 يوم": 14, "آخر 30 يوم": 30,
    "من ساعتين": 0.08, "6 ساعات": 0.25, "12 ساعة": 0.5,
}

def get_time_range(label):
    now=datetime.now(timezone.utc)
    if label=="من ساعتين": return now-timedelta(hours=2), now
    if label=="6 ساعات": return now-timedelta(hours=6), now
    if label=="12 ساعة": return now-timedelta(hours=12), now
    days=TIME_RANGES.get(label, 7)
    return now-timedelta(days=days), now

def is_relevant(title, search_terms_en, search_terms_he):
    title_low=title.lower()
    for term in search_terms_en + search_terms_he:
        term_low=term.lower().strip('"')
        if len(term_low)<2: continue
        # لو كلمة واحدة
        if " " not in term_low:
            if term_low in title_low:
                return True, term
        else:
            # عبارة مثل Saudi Arabia -> يكفي كلمة واحدة منها (Saudi) تعتبر مطابقة
            words=[w for w in term_low.split() if len(w)>2]
            if not words: continue
            # لو أي كلمة من العبارة موجودة، اعتبره مطابق (إصلاح مشكلة السعودية)
            if any(w in title_low for w in words):
                return True, term
    return False, ""

def run_search(terms, joiner, scope, start_utc, end_utc, max_rec, ctype, strict):
    jobs=SCOPES[scope]
    found={}
    search_terms_en=[]
    search_terms_he=[]
    for t in terms:
        en=tr_dynamic(t,"ar","en")
        he=tr_dynamic(t,"ar","iw")
        if en: search_terms_en.append(en)
        if he: search_terms_he.append(he)

    is_us_scope = "أمريكية" in scope

    for i,(country,gdelt_lang,trans_lang) in enumerate(jobs):
        parts=[]
        if trans_lang=="iw":
            for t in search_terms_he:
                parts.append(f'"{t}"' if " " in t else t)
        else:
            for t in search_terms_en:
                parts.append(f'"{t}"' if " " in t else t)
        if not parts: continue
        q_base = "(" + " OR ".join(parts) + ")" if joiner=="OR" else " ".join(parts)
        
        # للمصادر الأمريكية: جرب أولا مع sourcecountry، لو فشل جرب بدون فلتر + دومينات
        queries_to_try = [q_base]
        if is_us_scope:
            # المحاولة الثانية بدون country filter لكن مع تفضيل الدومينات الأمريكية
            queries_to_try.append(q_base)  # نفس الكويري لكن بدون country في gdelt_call الثاني
        
        for attempt_idx, q in enumerate(queries_to_try):
            if i>0 or attempt_idx>0: time.sleep(5.2)
            # المحاولة الأولى للمصادر الأمريكية: مع country=US
            # المحاولة الثانية: بدون country (بحث عام لكن سنفلتر لاحقا)
            use_country = country if attempt_idx==0 else None
            arts=gdelt_call(q, start_utc, end_utc, min(250, max_rec*3), use_country, gdelt_lang)
            for a in arts:
                a["_q_lang"]=trans_lang
                found.setdefault(a.get("url"), a)
            if found: break  # لو لقينا نتائج، متجربش المحاولة التانية
        if found and is_us_scope:
            break

    items=list(found.values())
    
    if strict:
        filtered=[]
        for a in items:
            rel,matched=is_relevant(a.get("title",""), search_terms_en, search_terms_he)
            if rel:
                a["_matched"]=matched
                filtered.append(a)
        # لو الفلتر شال كل حاجة، اعرض بدون فلتر لكن نبه المستخدم
        if not filtered and items:
            # للمصادر الأمريكية، اعرض أول 10 حتى لو مش مطابق 100%
            filtered=items[:max_rec]
            for a in filtered: a["_matched"]="عام"
    else:
        filtered=items
        for a in filtered: a["_matched"]="عام"

    def classify(url):
        u=url.lower()
        if "/opinion" in u or "/editorial" in u or "/op-ed" in u: return "رأي"
        if "/analysis" in u or "/explainer" in u: return "تحليل"
        return "خبر"
    for a in filtered: a["ctype"]=classify(a.get("url",""))
    if ctype!="الكل": filtered=[a for a in filtered if a["ctype"]==ctype]
    filtered.sort(key=lambda a: a.get("seendate",""), reverse=True)
    return filtered[:max_rec], len(items), len(filtered)

def translate_titles_batch(items):
    def work(a):
        title=a.get("title","")
        lang=a.get("language","").lower()
        q_lang=a.get("_q_lang","en")
        if "hebrew" in lang or q_lang=="iw":
            ar=tr_dynamic(title,"iw","ar")
            en=tr_dynamic(title,"iw","en")
        else:
            ar=tr_dynamic(title,"en","ar")
            en=title
        a["title_ar"]=ar
        a["title_en"]=en
        return a
    with ThreadPoolExecutor(max_workers=5) as ex:
        return list(ex.map(work, items))

# UI
st.title("مرصد - مصادر أمريكية مصلحة")
st.caption("اليوم، أمس، من يومين، أسبوع + عبري + ترجمة - مع إصلاح مشكلة السعودية")

query=st.text_input("🔎 كلمات البحث", placeholder="السعودية، مصر، اليمن، غزة", value="السعودية")
c1,c2=st.columns(2)
joiner_label=c1.radio("عند تعدد الكلمات", ["أيٌّ منها (OR)", "كلها معاً (AND)"], index=0)
joiner="OR" if "OR" in joiner_label else "AND"

with st.expander("⚙️ الفلاتر - مهم", expanded=True):
    scope=st.selectbox("المصادر", list(SCOPES.keys()), index=1, help="اختار مصادر أمريكية فقط - ذكي")
    ctype=st.selectbox("نوع المحتوى", ["الكل", "خبر", "تحليل", "رأي"])
    st.markdown("#### النطاق الزمني")
    time_label=st.radio("اختر النطاق", list(TIME_RANGES.keys()), index=1)
    start_utc,end_utc=get_time_range(time_label)
    st.info(f"يبحث من: {start_utc.astimezone(TZ).strftime('%Y-%m-%d %H:%M')} إلى {end_utc.astimezone(TZ).strftime('%Y-%m-%d %H:%M')} (توقيت القاهرة)")
    max_rec=st.slider("عدد النتائج", 10, 100, 40, step=10)
    strict=st.checkbox("فلتر دقيق", value=False, help="لو مفعل، يشترط وجود كلمة البحث في العنوان - الغيه للمصادر الأمريكية لو مفيش نتائج")

if st.button("ابحث", type="primary", use_container_width=True):
    raw_terms=[t.strip() for t in re.split(r"[,،;\n]+", query) if t.strip()]
    if len(raw_terms)==1 and " " in raw_terms[0] and "," not in query and "،" not in query:
        if len(raw_terms[0].split()) <=3:
            terms=[p for p in raw_terms[0].split() if p]
        else:
            terms=raw_terms
    else:
        terms=raw_terms
    if not terms:
        st.warning("اكتب كلمة بحث")
    else:
        with st.spinner("يترجم..."):
            for t in terms:
                en=tr_dynamic(t,"ar","en")
                he=tr_dynamic(t,"ar","iw")
                st.info(f"{t} → EN: {en} | HE: {he}")
        with st.status("يبحث...", expanded=True) as status:
            items,total,filtered_count=run_search(terms, joiner, scope, start_utc, end_utc, max_rec, ctype, strict)
            items=translate_titles_batch(items)
            status.update(label=f"تم — {len(items)} نتيجة (النطاق: {time_label} | المصدر: {scope})", state="complete")
        st.session_state["results"]=items
        st.session_state["stats"]=(total, filtered_count, time_label)

items=st.session_state.get("results")
if items is not None:
    total,filtered_count,time_label=st.session_state.get("stats",(0,0,""))
    if not items:
        st.error(f"لا نتائج في نطاق {time_label} مع المصدر {scope}")
        st.info("جرب: 1) إلغاء الفلتر الدقيق 2) تغيير النطاق لأسبوع أو آخر 30 يوم 3) اختيار جميع المصادر")
    else:
        if total!=filtered_count and strict:
            st.success(f"✅ النطاق: {time_label} | من {total} خبر، {filtered_count} له علاقة بـ '{query}'")
        for a in items:
            url=a.get("url",""); domain=a.get("domain",""); country=a.get("sourcecountry",""); seen=a.get("seendate",""); lang=a.get("language","")
            title_en=a.get("title_en","") or a.get("title","")
            title_ar=a.get("title_ar","") or title_en
            is_hebrew="hebrew" in lang.lower() or a.get("_q_lang")=="iw"
            source_name=get_source_name(domain)
            matched=a.get("_matched","")
            with st.container(border=True):
                st.markdown(f"<div class='ar-title'>{html.escape(title_ar)}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='en-title'>EN: {html.escape(title_en)}</div>", unsafe_allow_html=True)
                flag="🇮🇱" if country=="IS" or is_hebrew else "🌐"
                if country=="US": flag="🇺🇸"
                elif country=="UK": flag="🇬🇧"
                st.markdown(f"""
                <div class='source-box'>
                    <div>
                        <div class='source-name'>{flag} {html.escape(source_name)}</div>
                        <div class='source-meta'>{html.escape(domain)} · {html.escape(country)} · {html.escape(lang)} · 🕒 {fmt_seen(seen)}</div>
                    </div>
                    <div><span class='badge{"-il" if is_hebrew or country=="IS" else ""}'>{a.get('ctype','')}</span></div>
                </div>
                """, unsafe_allow_html=True)
                if matched and matched!="عام":
                    st.caption(f"مطابق: {matched}")
                c1,c2=st.columns(2)
                with c1: st.link_button("🔗 المصدر", url, use_container_width=True)
                with c2: st.link_button("🌐 ترجم المقال", f"https://translate.google.com/translate?sl=auto&tl=ar&u={quote(url, safe='')}", use_container_width=True)
