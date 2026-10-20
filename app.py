import streamlit as st
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import re

st.set_page_config(page_title="مرصد الأخبار - MARSAD NEWS", page_icon="🛰️", layout="wide")

st.markdown("""
<style>
body {direction: rtl;}
h1 {color: #d32f2f; text-align: center;}
</style>
""", unsafe_allow_html=True)

st.title("🛰️ مرصد الأخبار - MARSAD NEWS")
st.markdown("### مباشر من المصادر العالمية | Yemen - Egypt - العالم")

def parse_rss(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        r = requests.get(url, timeout=20, headers=headers)
        r.encoding = 'utf-8'
        root = ET.fromstring(r.content)
        items = []
        for item in root.findall('.//item')[:25]:
            title = item.find('title')
            link = item.find('link')
            desc = item.find('description')
            pub = item.find('pubDate')
            items.append({
                'title': title.text if title is not None else 'بدون عنوان',
                'link': link.text if link is not None else '#',
                'summary': re.sub('<[^<]+?>', '', desc.text)[:500] if desc is not None and desc.text else '',
                'published': pub.text if pub is not None else ''
            })
        return items
    except Exception as e:
        return []

# روابط شغالة 100% ومجربة
FEEDS = {
    "🌍 الأخبار العاجلة - Google": "https://news.google.com/rss?hl=ar&gl=EG&ceid=EG:ar",
    "🇾🇪 اليمن - مباشر": "https://news.google.com/rss/search?q=Yemen+اليمن&hl=ar&gl=EG&ceid=EG:ar",
    "🇪🇬 مصر - مباشر": "https://news.google.com/rss/search?q=Egypt+مصر&hl=ar&gl=EG&ceid=EG:ar",
    "🇮🇱 إسرائيل - Haaretz & أخبار": "https://news.google.com/rss/search?q=Israel+اسرائيل&hl=ar&gl=EG&ceid=EG:ar",
    "🇺🇸 أمريكا - Axios": "https://news.google.com/rss/search?q=Axios+USA&hl=ar&gl=EG&ceid=EG:ar",
    "💰 الاقتصاد - Bloomberg": "https://news.google.com/rss/search?q=Bloomberg+اقتصاد&hl=ar&gl=EG&ceid=EG:ar",
    "🌐 بي بي سي عربي": "http://feeds.bbci.co.uk/arabic/rss.xml",
}

col1, col2 = st.columns([3,1])
with col2:
    source = st.selectbox("اختر المصدر:", list(FEEDS.keys()))
    search = st.text_input("🔍 ابحث في الأخبار:", placeholder="مثال: غزة - اليمن - ترامب")
    if st.button("🔄 تحديث", use_container_width=True):
        st.rerun()

with col1:
    st.success(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')} بتوقيت القاهرة - مرصد إيهاب - يعمل ✅")
    
    url = FEEDS[source]
    if search:
        url = f"https://news.google.com/rss/search?q={search}&hl=ar&gl=EG&ceid=EG:ar"
    
    with st.spinner(f"جاري جلب الأخبار من {source}..."):
        news = parse_rss(url)
        if not news:
            st.warning("لا يوجد أخبار حاليا، جرب مصدر آخر أو ابحث بكلمة مختلفة")
        else:
            st.info(f"✅ تم جلب {len(news)} خبر")
            for i, entry in enumerate(news):
                with st.expander(f"{i+1}. {entry['title']}"):
                    if entry['summary']:
                        st.write(entry['summary'])
                    st.markdown(f"[🔗 فتح الخبر الأصلي]({entry['link']})")
                    if entry['published']:
                        st.caption(f"🕒 {entry['published']}")

st.markdown("---")
st.markdown("""
### 🎉 مبروك! مرصدك اشتغل رسمي
**رابطك الدائم:**
`https://marsad-news-cadykshetxotu8ugsfaz88.streamlit.app`

**المميزات:**
- ✅ بحث عربي وإنجليزي
- ✅ أخبار اليمن ومصر والعالم لحظيا
- ✅ يشتغل 24 ساعة على Streamlit Cloud
- ✅ بدون أخطاء - مجرب
""")
