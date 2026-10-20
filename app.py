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
.stExpander {text-align: right;}
</style>
""", unsafe_allow_html=True)

st.title("🛰️ مرصد الأخبار - MARSAD NEWS")
st.markdown("### مباشر من المصادر العالمية | Reuters - Axios - Bloomberg")

def parse_rss(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, timeout=15, headers=headers)
        r.encoding = 'utf-8'
        root = ET.fromstring(r.content)
        items = []
        for item in root.findall('.//item')[:20]:
            title = item.find('title')
            link = item.find('link')
            desc = item.find('description')
            pub = item.find('pubDate')
            items.append({
                'title': title.text if title is not None else 'بدون عنوان',
                'link': link.text if link is not None else '#',
                'summary': re.sub('<[^<]+?>', '', desc.text)[:400] if desc is not None and desc.text else 'لا يوجد ملخص',
                'published': pub.text if pub is not None else 'الآن'
            })
        return items
    except Exception as e:
        return [{'title': f'خطأ في جلب الأخبار: {e}', 'link': '#', 'summary': '', 'published': ''}]

FEEDS = {
    "🌍 رويترز - عاجل": "http://feeds.reuters.com/reuters/topNews",
    "🇺🇸 Axios": "https://www.axios.com/feeds/feed.rss",
    "💰 Google News - اليمن": "https://news.google.com/rss/search?q=Yemen+news&hl=ar&gl=EG&ceid=EG:ar",
    "🇪🇬 Google News - مصر": "https://news.google.com/rss/search?q=Egypt&hl=ar&gl=EG&ceid=EG:ar",
    "🌐 Google News - عربي عام": "https://news.google.com/rss?hl=ar&gl=EG&ceid=EG:ar",
}

col1, col2 = st.columns([3,1])
with col2:
    source = st.selectbox("اختر المصدر:", list(FEEDS.keys()))
    if st.button("🔄 تحديث"):
        st.rerun()

with col1:
    st.info(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')} بتوقيت القاهرة - مرصد إيهاب")
    with st.spinner(f"جاري جلب الأخبار من {source}..."):
        news = parse_rss(FEEDS[source])
        st.success(f"✅ تم جلب {len(news)} خبر")
        for i, entry in enumerate(news):
            with st.expander(f"{i+1}. {entry['title']}"):
                st.write(entry['summary'])
                st.markdown(f"[🔗 فتح الخبر الأصلي]({entry['link']})")
                st.caption(entry['published'])

st.markdown("---")
st.caption("🚀 رابطك الدائم يعمل 24 ساعة - تم تطويره لإيهاب")
st.markdown("**المميزات:** بحث عربي / جلب تلقائي / بدون مكتبات خارجية / يعمل على Streamlit Cloud")
