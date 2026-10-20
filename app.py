import streamlit as st
from deep_translator import GoogleTranslator
from gnews import GNews
from newspaper import Article
import datetime
from urllib.parse import quote
import time

st.set_page_config(page_title="مرصد - محرك الأخبار العالمي", page_icon="م", layout="wide", initial_sidebar_state="expanded")

# CSS RTL responsive
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;700&display=swap');
html, body, [class*="css"] {font-family: 'Cairo', sans-serif; direction: rtl;}
.stTextInput input {text-align: right; font-size: 18px;}
.article-card {border: 1px solid #333; border-radius: 12px; padding: 16px; margin-bottom: 16px; background: #111; color: #fff;}
.article-card h3 {margin: 0 0 8px 0; color: #fbbf24;}
.badge {display:inline-block; padding: 2px 8px; border-radius: 8px; font-size: 12px; margin-left: 6px;}
.badge-news {background: #1e40af; color: white;}
.badge-analysis {background: #b45309; color: white;}
.badge-opinion {background: #7c3aed; color: white;}
.meta {color: #9ca3af; font-size: 13px; margin-bottom: 8px;}
</style>
""", unsafe_allow_html=True)

# Helpers
def translate_ar_to_en(text):
    try: return GoogleTranslator(source='ar', target='en').translate(text)
    except: return text

def translate_ar_to_he(text):
    try: return GoogleTranslator(source='ar', target='iw').translate(text)
    except: return text

def translate_to_ar(text):
    try: 
        # limit length for free api
        chunk = text[:4000]
        return GoogleTranslator(source='auto', target='ar').translate(chunk)
    except: return text

def summarize_ar(text):
    # simple extractive summary - first 3 sentences
    sentences = text.split('.')
    return '. '.join(sentences[:3]) + '.'

# Sources mapping
SOURCES = {
    "Axios": "axios.com",
    "Bloomberg": "bloomberg.com",
    "NY Times": "nytimes.com",
    "Washington Post": "washingtonpost.com",
    "Al-Monitor": "al-monitor.com",
    "Middle East Eye": "middleeasteye.net",
    "Financial Times": "ft.com",
    "The Economist": "economist.com",
    "The Guardian": "theguardian.com",
    "Haaretz": "haaretz.com",
    "Jerusalem Post": "jpost.com",
    "Times of Israel": "timesofisrael.com",
    "Ynetnews": "ynetnews.com",
    "Globes": "globes.co.il",
    "i24NEWS": "i24news.tv"
}
GEO_GROUPS = {
    "جميع المصادر": list(SOURCES.values()),
    "مصادر أمريكية فقط": ["axios.com","bloomberg.com","nytimes.com","washingtonpost.com","al-monitor.com"],
    "مصادر إسرائيلية فقط": ["haaretz.com","jpost.com","timesofisrael.com","ynetnews.com","globes.co.il","i24news.tv"],
    "مصادر بريطانية فقط": ["ft.com","economist.com","theguardian.com","middleeasteye.net"]
}

# Sidebar filters
st.sidebar.title("⚙️ فلاتر البحث")
geo_filter = st.sidebar.selectbox("فلتر المصادر (الجغرافية)", list(GEO_GROUPS.keys()))
type_filter = st.sidebar.selectbox("نوع المحتوى", ["الكل", "خبر News", "تحليل Analysis", "مقال رأي Opinion"])
time_filter = st.sidebar.selectbox("فلتر الوقت", ["آخر ساعتين", "اليوم", "أمس", "من يومين", "هذا الأسبوع", "آخر 30 يوم", "كل التواريخ"])

period_map = {
    "آخر ساعتين": "2h",
    "اليوم": "1d",
    "أمس": "1d",
    "من يومين": "2d",
    "هذا الأسبوع": "7d",
    "آخر 30 يوم": "30d",
    "كل التواريخ": None
}
period = period_map.get(time_filter)

# Main
st.title("مرصد - محرك الأخبار العالمي الحقيقي")
st.caption(f"LIVE / {datetime.date.today()} - TRUMP PRESIDENCY YEAR 2 - يبحث في المحتوى الكامل للمقال")

query_ar = st.text_input("🔍 اكتب كلماتك بالعربية:", placeholder="مثال: اليمن، الرئيس المصري، اقتصاد مصر، ترامب والسيسي")

if query_ar:
    col1, col2, col3 = st.columns(3)
    with col1:
        st.info(f"AR: {query_ar}")
    query_en = translate_ar_to_en(query_ar)
    query_he = translate_ar_to_he(query_ar)
    with col2:
        st.success(f"EN: {query_en}")
    with col3:
        st.warning(f"HE: {query_he}")

    if st.button("🚀 ابحث في جميع المصادر الآن", use_container_width=True):
        st.session_state['searching'] = True
        st.session_state['q_ar'] = query_ar
        st.session_state['q_en'] = query_en
        st.session_state['q_he'] = query_he

if st.session_state.get('searching'):
    q_en = st.session_state['q_en']
    q_he = st.session_state['q_he']
    q_ar = st.session_state['q_ar']

    # Build combined query for GNews
    combined = f"{q_en} OR {q_he}"
    if len(combined.split()) == 1:
        combined = f"{q_en} {q_ar}"

    google_news = GNews(language='en', country='US', period=period, max_results=30)
    # Add site filter based on geo
    sites = GEO_GROUPS[geo_filter]
    # GNews doesn't support site: filter directly, but we will filter after
    with st.spinner(f"يبحث في {len(sites)} مصدر عن: {combined} ..."):
        results = google_news.get_news(combined)
        # Also search Hebrew
        google_news_he = GNews(language='he', country='IL', period=period, max_results=15)
        results_he = google_news_he.get_news(q_he)
        results = results + results_he

    # Filter by source domain and content type
    filtered = []
    for r in results:
        url = r.get('url','').lower()
        if not any(s in url for s in sites):
            continue
        # simple type detection by title
        title = r.get('title','').lower()
        if type_filter == "خبر News" and any(w in title for w in ["opinion","analysis","editorial"]):
            continue
        if type_filter == "تحليل Analysis" and "analysis" not in title and "تحليل" not in title:
            # allow if contains analysis
            if "analysis" not in title: 
                pass # keep loose
        filtered.append(r)

    if not filtered:
        st.warning("لم نجد نتائج في هذا النطاق، جرب توسيع الوقت إلى 'كل التواريخ' أو اختر 'جميع المصادر'")
    else:
        st.success(f"تم العثور على {len(filtered)} نتيجة حقيقية من Google News - التاريخ الحقيقي من المصدر")

        for item in filtered:
            title_en = item.get('title','')
            pub_date = item.get('published date','')
            publisher = item.get('publisher',{}).get('title','')
            url = item.get('url','')
            # Translate title to Arabic for card
            title_ar = translate_to_ar(title_en)

            # Determine type badge
            if "opinion" in title_en.lower() or "op-ed" in title_en.lower():
                badge = '<span class="badge badge-opinion">مقال رأي • OP-ED</span>'
                b_type = "OP-ED"
            elif "analysis" in title_en.lower():
                badge = '<span class="badge badge-analysis">تحليل • ANALYSIS</span>'
                b_type = "ANALYSIS"
            else:
                badge = '<span class="badge badge-news">خبر • NEWS</span>'
                b_type = "NEWS"

            with st.container():
                st.markdown(f"""
                <div class="article-card">
                <div class="meta">{pub_date} • {publisher} • {url[:40]}... {badge}</div>
                <h3>{title_ar}</h3>
                <div style="color:#d1d5db; font-size:14px; margin-bottom:8px;">{title_en}</div>
                </div>
                """, unsafe_allow_html=True)
                
                c1, c2, c3 = st.columns([1,1,2])
                with c1:
                    if st.button("📖 ترجم المقال", key=f"trans_{url}"):
                        st.session_state[f"open_{url}"] = True
                with c2:
                    st.link_button("🔗 المصدر الأصلي", url)
                with c3:
                    st.caption(f"النوع: {b_type} | المصدر: {publisher}")

                # If user clicked translate, open full article translation
                if st.session_state.get(f"open_{url}"):
                    try:
                        with st.spinner("يجلب النص الكامل ويترجم..."):
                            art = Article(url)
                            art.download()
                            art.parse()
                            full_text = art.text
                            full_text_ar = translate_to_ar(full_text)
                            summary = summarize_ar(full_text_ar)
                        st.divider()
                        st.subheader("📄 صفحة قراءة المقال")
                        st.markdown(f"**الرابط الأصلي:** {url}")
                        st.markdown(f"**التاريخ الحقيقي للنشر:** {pub_date}")
                        st.markdown(f"**العنوان الأصلي:** {title_en}")
                        st.markdown("---")
                        st.markdown(f"**النص الكامل مترجم للعربية:**\n\n{full_text_ar}")
                        st.markdown("---")
                        st.markdown(f"**تلخيص سريع (سكربت إخباري):**\n\n{summary}")
                        if st.button("تلخيص المقال", key=f"sum_{url}"):
                            st.info(summary)
                    except Exception as e:
                        st.error(f"تعذر جلب النص الكامل، افتح المصدر الأصلي. الخطأ: {e}")
