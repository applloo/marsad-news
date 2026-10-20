
import streamlit as st
import feedparser
import requests
from datetime import datetime

st.set_page_config(page_title="مرصد الأخبار - MARSAD NEWS", page_icon="🛰️", layout="wide")

st.markdown("""
<style>
body {direction: rtl;}
h1 {color: #d32f2f; text-align: center;}
</style>
""", unsafe_allow_html=True)

st.title("🛰️ مرصد الأخبار - MARSAD NEWS")
st.markdown("### مباشر من المصادر العالمية | Axios - Haaretz - Bloomberg - Reuters")

# مصادر اخبار حقيقية شغالة
FEEDS = {
    "🌍 رويترز - عاجل": "http://feeds.reuters.com/reuters/topNews",
    "🇺🇸 Axios - سياسة امريكا": "https://www.axios.com/feeds/feed.rss",
    "🇮🇱 Haaretz - اسرائيل": "https://www.haaretz.com/cmlink/1.2706767",
    "💰 Bloomberg": "https://feeds.bloomberg.com/markets/news.rss",
    "🇾🇪 اليمن - Google News": "https://news.google.com/rss/search?q=Yemen&hl=ar&gl=EG&ceid=EG:ar",
    "🇪🇬 مصر - Google News": "https://news.google.com/rss/search?q=Egypt&hl=ar&gl=EG&ceid=EG:ar",
}

col1, col2 = st.columns([3,1])
with col2:
    source = st.selectbox("اختر المصدر:", list(FEEDS.keys()))
    refresh = st.button("🔄 تحديث الأخبار")

with col1:
    st.info(f"📅 التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M')} - بتوقيت القاهرة")
    if refresh or True:
        try:
            feed = feedparser.parse(FEEDS[source])
            st.success(f"✅ تم جلب {len(feed.entries)} خبر من {source}")
            for i, entry in enumerate(feed.entries[:20]):
                with st.expander(f"{i+1}. {entry.title}"):
                    st.write(entry.get('summary', 'لا يوجد ملخص')[:500])
                    st.markdown(f"[🔗 فتح الخبر الأصلي]({entry.link})")
                    st.caption(f"📅 {entry.get('published', 'الآن')}")
        except Exception as e:
            st.error(f"خطأ: {e}")
            st.write("جاري المحاولة بمصدر بديل...")
            # fallback
            try:
                r = requests.get("https://news.google.com/rss?hl=ar&gl=EG&ceid=EG:ar", timeout=10)
                feed = feedparser.parse(r.content)
                for entry in feed.entries[:10]:
                    st.write(f"- {entry.title}")
            except Exception as e2:
                st.error(str(e2))

st.markdown("---")
st.caption("🚀 رابطك الدائم: هذا الموقع يعمل 24 ساعة على Streamlit Cloud - مرصد إيهاب")
