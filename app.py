# -*- coding: utf-8 -*-
import streamlit as st
import requests
import time
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import html

# 1. إعدادات الصفحة الأساسية
st.set_page_config(page_title="مرصد الأخبار العالمي", page_icon="🌍", layout="centered")

# 2. تنسيق الواجهة
st.markdown("""
<style>
    .stApp, .stMarkdown, div, label, p, h1, h2, h3, span { direction: rtl; text-align: right; }
    .en-text { direction: ltr !important; text-align: left !important; color: #555; font-size: 0.9rem; margin-bottom: 8px; }
    .news-card { border: 1px solid #ddd; border-radius: 8px; padding: 15px; margin-bottom: 15px; background-color: #fcfcfc; }
    .news-title { color: #1a0dab; font-size: 1.3rem; font-weight: bold; margin-bottom: 5px; }
    .news-meta { color: #006621; font-size: 0.85rem; margin-bottom: 12px; }
    .badge { display: inline-block; padding: 3px 8px; border-radius: 12px; font-size: 0.75rem; background-color: #e0e0e0; margin-left: 5px;}
</style>
""", unsafe_allow_html=True)

COUNTRY_MAP = {
    "US": "أمريكا 🇺🇸", "UK": "بريطانيا 🇬🇧", "IS": "إسرائيل 🇮🇱",
    "EG": "مصر 🇪🇬", "SA": "السعودية 🇸🇦", "AE": "الإمارات 🇦🇪",
    "QA": "قطر 🇶🇦", "JO": "الأردن 🇯🇴", "LB": "لبنان 🇱🇧",
    "SY": "سوريا 🇸🇾", "IQ": "العراق 🇮🇶", "KW": "الكويت 🇰🇼",
    "OM": "عُمان 🇴🇲", "BH": "البحرين 🇧🇭", "YE": "اليمن 🇾🇪",
    "TR": "تركيا 🇹🇷", "IR": "إيران 🇮🇷", "FR": "فرنسا 🇫🇷",
    "DE": "ألمانيا 🇩🇪", "RU": "روسيا 🇷🇺", "CN": "الصين 🇨🇳",
    "IN": "الهند 🇮🇳", "PS": "فلسطين 🇵🇸", "LY": "ليبيا 🇱🇾", "SD": "السودان 🇸🇩"
}

SOURCE_MAP = {
    "nytimes.com": "نيويورك تايمز", "washingtonpost.com": "واشنطن بوست",
    "cnn.com": "سي إن إن (CNN)", "foxnews.com": "فوكس نيوز",
    "wsj.com": "وول ستريت جورنال", "bloomberg.com": "بلومبيرغ",
    "reuters.com": "رويترز", "apnews.com": "أسوشيتد برس",
    "axios.com": "أكسيوس", "politico.com": "بوليتيكو",
    "nbcnews.com": "إن بي سي (NBC)", "cbsnews.com": "سي بي إس (CBS)",
    "abcnews.go.com": "إيه بي سي (ABC)", "usatoday.com": "يو إس إيه توداي",
    "theintercept.com": "ذي إنترسبت", "newsweek.com": "نيوزويك",
    "time.com": "مجلة تايم", "npr.org": "الإذاعة الوطنية (NPR)",
    "bbc.com": "بي بي سي (BBC)", "theguardian.com": "الجارديان",
    "middleeasteye.net": "ميدل إيست آي", "independent.co.uk": "الإندبندنت",
    "aljazeera.net": "الجزيرة", "alarabiya.net": "العربية",
    "skynewsarabia.com": "سكاي نيوز عربية", "thegazette.com": "ذا جازيت",
    "kitabat.com": "كتابات", 
    "haaretz.com": "هآرتس", "ynet.co.il": "واي نت (Ynet)",
    "jpost.com": "جيروزاليم بوست", "timesofisrael.com": "تايمز أوف إسرائيل",
    "mako.co.il": "القناة 12 الإسرائيلية", "n12.co.il": "القناة 12 الإسرائيلية (N12)",
    "now14.co.il": "القناة 14 الإسرائيلية", "kan.org.il": "قناة كان الإسرائيلية",
    "maariv.co.il": "معاريف", "israelhayom.co.il": "إسرائيل هيوم"
}

def get_country_ar(code):
    if not code: return "دولي 🌐"
    return COUNTRY_MAP.get(code.upper(), f"{code} 🌐")

def get_source_ar(domain):
    d = domain.lower().replace("www.", "")
    if d in SOURCE_MAP: return SOURCE_MAP[d]
    name = d.split(".")[0].capitalize()
    return f"صحيفة {name}"

def clean_text(text):
    return re.sub(r'[\u0591-\u05C7\u064B-\u065F]', '', text)

@st.cache_data(ttl=3600, show_spinner=False)
def get_clean_translation(text, target_lang):
    text = text.strip()
    if not text or len(text) < 2: return text
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {"client": "gtx", "sl": "ar", "tl": target_lang, "dt": "t", "q": text}
        res = requests.get(url, params=params, timeout=5)
        if res.status_code == 200:
            translated = "".join([sentence[0] for sentence in res.json()[0] if sentence[0]]).replace('"', '')
            return clean_text(translated)
        return text
    except Exception:
        return text

def fetch_news(query, country_filter, hours_back):
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(hours=hours_back)
    
    start_str = start_date.strftime("%Y%m%d%H%M%S")
    end_str = end_date.strftime("%Y%m%d%H%M%S")
    
    # توسيع فلاتر البحث لتشمل النطاقات بشكل صريح
    us_domains = "(domain:nytimes.com OR domain:washingtonpost.com OR domain:cnn.com OR domain:foxnews.com OR domain:wsj.com OR domain:bloomberg.com OR domain:reuters.com OR domain:apnews.com OR domain:axios.com OR domain:politico.com OR domain:nbcnews.com OR domain:cbsnews.com OR domain:abcnews.go.com OR domain:usatoday.com OR domain:theintercept.com OR domain:newsweek.com)"
    uk_domains = "(sourcecountry:UK OR domain:middleeasteye.net OR domain:bbc.com OR domain:theguardian.com OR domain:independent.co.uk)"
    is_domains = "(sourcecountry:IS OR domain:haaretz.com OR domain:ynet.co.il OR domain:jpost.com OR domain:timesofisrael.com OR domain:mako.co.il OR domain:n12.co.il OR domain:now14.co.il OR domain:maariv.co.il OR domain:israelhayom.co.il OR domain:kan.org.il)"

    if country_filter == "US":
        gdelt_query = f'({query}) {us_domains}'
    elif country_filter == "UK":
        gdelt_query = f'({query}) {uk_domains}'
    elif country_filter == "IS":
        gdelt_query = f'({query}) {is_domains}'
    else:
        gdelt_query = query

    params = {
        "query": gdelt_query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": 100,
        "sort": "DateDesc",
        "startdatetime": start_str,
        "enddatetime": end_str
    }
    
    for _ in range(3):
        try:
            url = "https://api.gdeltproject.org/api/v2/doc/doc"
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                return response.json().get("articles", [])
        except Exception:
            time.sleep(1)
            continue
    return []

def get_article_type(url):
    url_lower = url.lower()
    if any(x in url_lower for x in ["/opinion/", "/editorial/", "op-ed"]): return "رأي"
    if any(x in url_lower for x in ["/analysis/", "/explainer/"]): return "تحليل"
    return "خبر"

# ================= الواجهة والتفاعل =================

st.title("محرك البحث الإخباري المتقدم 🔍")
st.markdown("💡 **نصيحة:** إذا كنت تبحث عن عدة دول أو أشخاص، افصل بينها بفاصلة (،) مثال: `مصر، السعودية، وزير الخارجية`")

search_query = st.text_input("أدخل كلمات البحث:", placeholder="مثال: اليمن، السعودية، مصر")

join_logic = st.radio("كيف تريد البحث عن هذه الكلمات؟", 
                      ["البحث عن أي عبارة منها (OR) - نتائج أكثر", "البحث عن جميع العبارات معاً (AND) - نتائج دقيقة"], 
                      horizontal=True)

col1, col2, col3 = st.columns(3)
with col1:
    source_choice = st.selectbox("نطاق المصادر:", ["جميع المصادر", "مصادر أمريكية فقط", "مصادر إسرائيلية فقط", "مصادر بريطانية فقط"])
with col2:
    time_choice = st.selectbox("النطاق الزمني:", ["آخر 24 ساعة", "آخر 48 ساعة", "آخر أسبوع", "آخر 30 يوم"])
with col3:
    type_choice = st.selectbox("نوع المقال:", ["الكل", "خبر", "تحليل", "رأي"])

time_map = {"آخر 24 ساعة": 24, "آخر 48 ساعة": 48, "آخر أسبوع": 168, "آخر 30 يوم": 720}
hours = time_map[time_choice]

source_map = {"جميع المصادر": None, "مصادر أمريكية فقط": "US", "مصادر إسرائيلية فقط": "IS", "مصادر بريطانية فقط": "UK"}
country = source_map[source_choice]

if st.button("ابحث الآن", use_container_width=True, type="primary"):
    if not search_query.strip():
        st.warning("الرجاء إدخال كلمة بحث أولاً.")
    else:
        with st.status("جاري معالجة طلبك...", expanded=True) as status:
            raw_terms = re.split(r'[،,]', search_query)
            terms = [t.strip() for t in raw_terms if t.strip()]
            
            st.write("🔄 جاري تفكيك وترجمة وتنظيف مصطلحات البحث...")
            
            query_parts = []
            
            for t in terms:
                en = get_clean_translation(t, "en")
                he = get_clean_translation(t, "iw")
                st.write(f"▪️ **{t}** ➡️ 🇬🇧 {en} | 🇮🇱 {he}")
                query_parts.append(f'"{en}" OR "{he}"')
            
            logic_operator = " OR " if "(OR)" in join_logic else " AND "
            
            if len(query_parts) > 1:
                formatted_parts = [f"({part})" for part in query_parts]
                final_query = logic_operator.join(formatted_parts)
            else:
                final_query = query_parts[0]
                
            st.write("📡 جاري جلب الأخبار من قواعد البيانات المباشرة...")
            articles = fetch_news(final_query, country, hours)
            
            filtered_articles = []
            for art in articles:
                art_type = get_article_type(art.get("url", ""))
                if type_choice == "الكل" or art_type == type_choice:
                    art["ctype"] = art_type
                    filtered_articles.append(art)
                    
            status.update(label=f"تم العثور على {len(filtered_articles)} نتيجة", state="complete")

        if not filtered_articles:
            st.info("لا توجد نتائج مطابقة لبحثك في هذا النطاق الزمني أو المصدر. جرب تغيير 'AND' إلى 'OR' أو وسّع النطاق الزمني.")
        else:
            for art in filtered_articles:
                orig_title = art.get("title", "بدون عنوان")
                url = art.get("url", "#")
                domain = art.get("domain", "مصدر غير معروف")
                seen_date = art.get("seendate", "")
                source_country = art.get("sourcecountry", "")
                
                title_ar = get_clean_translation(orig_title, "ar")
                country_ar = get_country_ar(source_country)
                source_name_ar = get_source_ar(domain)
                
                try:
                    dt = datetime.strptime(seen_date, "%Y%m%dT%H%M%SZ")
                    dt_cairo = dt.replace(tzinfo=timezone.utc) + timedelta(hours=3)
                    date_str = dt_cairo.strftime("%Y-%m-%d %H:%M")
                except:
                    date_str = seen_date

                with st.container():
                    st.markdown(f"""
                    <div class='news-card'>
                        <div class='news-title'>{html.escape(title_ar)}</div>
                        <div class='en-text'>{html.escape(orig_title)}</div>
                        <div class='news-meta'>
                            <span>📰 {html.escape(source_name_ar)} ({html.escape(domain)})</span> | 
                            <span>🌍 {html.escape(country_ar)}</span> | 
                            <span>🕒 {date_str}</span>
                            <span class='badge'>{art['ctype']}</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    c1, c2 = st.columns(2)
                    with c1:
                        st.link_button("🔗 المصدر الأصلي", url, use_container_width=True)
                    with c2:
                        translate_url = f"https://translate.google.com/translate?sl=auto&tl=ar&u={quote(url, safe='')}"
                        st.link_button("🌐 ترجم المقال (صفحة كاملة)", translate_url, use_container_width=True)
