import streamlit as st
import requests
from datetime import datetime, timedelta

st.set_page_config(page_title="مرصد - GDELT العالمي", page_icon="🌍", layout="wide")
st.title("🌍 مرصد - محرك GDELT العالمي")
st.caption("نفس فكرة Claude - يبحث في آلاف المواقع")

def translate_query(ar_text):
    mapping = {"مصر":"Egypt","اليمن":"Yemen","السعودية":"Saudi","غزة":"Gaza","السيسي":"【entity-Sisi¦canonical_name=Abdel Fattah el-Sisi】","إسرائيل":"Israel","ترامب":"【entity-Trump¦canonical_name=Donald Trump】"}
    en = ar_text
    he = ar_text
    for ar,en_word in mapping.items():
        if ar in ar_text: en = en.replace(ar,en_word)
    return en, he

def search_gdelt(query_en, time_filter, geo_filter):
    now = datetime.utcnow()
    hours = {"من ساعتين":2,"اليوم":24,"أمس":48,"من يومين":48,"أسبوع":168,"آخر 30 يوم":720}.get(time_filter,2160)
    start = (now - timedelta(hours=hours)).strftime("%Y%m%d%H%M%S")
    end = now.strftime("%Y%m%d%H%M%S")
    source_filter = ""
    if geo_filter=="مصادر أمريكية فقط": source_filter=" sourcecountry:US"
    elif geo_filter=="مصادر إسرائيلية فقط": source_filter=" sourcecountry:IS"
    elif geo_filter=="مصادر بريطانية فقط": source_filter=" sourcecountry:UK"
    full_query = f"({query_en}){source_filter}"
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {"query":full_query,"mode":"artlist","maxrecords":50,"format":"json","startdatetime":start,"enddatetime":end,"sort":"datedesc"}
    try:
        r = requests.get(url, params=params, timeout=20)
        return r.json().get('articles',[])
    except Exception as e:
        return []

# Sidebar
st.sidebar.title("⚙️ الفلاتر")
geo = st.sidebar.selectbox("المصادر:", ["جميع المصادر","مصادر أمريكية فقط","مصادر إسرائيلية فقط","مصادر بريطانية فقط"])
time_f = st.sidebar.selectbox("الوقت:", ["من ساعتين","اليوم","أمس","من يومين","أسبوع","آخر 30 يوم"])

q_ar = st.text_input("🔍 اكتب بالعربية:", placeholder="مثال: مصر السعودية، اليمن")
if q_ar:
    q_en,q_he = translate_query(q_ar)
    st.info(f"AR: {q_ar} | EN: {q_en} | HE: {q_he}")
    if st.button("🚀 ابحث في GDELT الآن", type="primary", use_container_width=True):
        with st.spinner(f"يبحث في آلاف المواقع..."):
            articles = search_gdelt(q_en, time_f, geo)
        if not articles:
            st.warning("لا يوجد نتائج")
        else:
            st.success(f"✅ وجد {len(articles)} مقال")
            for art in articles[:30]:
                with st.expander(f"{art.get('title','')} - {art.get('sourcecountry','')}"):
                    st.write(f"**Domain:** {art.get('domain','')}")
                    st.write(f"**تاريخ الرصد:** {art.get('seendate','')} (وقت التقاط GDELT)")
                    st.link_button("🔗 فتح المصدر", art.get('url',''))
                    st.link_button("📖 ترجم المقال (يفتح تبويب)", f"https://translate.google.com/translate?sl=auto&tl=ar&u={art.get('url','')}")
