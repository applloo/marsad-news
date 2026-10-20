# -*- coding: utf-8 -*-
import streamlit as st
import requests
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import html

# 1. إعدادات الصفحة الأساسية
st.set_page_config(page_title="مرصد الأخبار العالمي", page_icon="🌍", layout="centered")

# 2. تنسيق الواجهة لتدعم اللغة العربية بالكامل (RTL)
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

# 3. دوال الترجمة (مع استخدام الكاش لسرعة الأداء وتجنب الحظر)
@st.cache_data(ttl=3600, show_spinner=False)
def translate_text(text, target_lang):
    if not text or len(text.strip()) < 2: return text
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {"client": "gtx", "sl": "auto", "tl": target_lang, "dt": "t", "q": text}
        res = requests.get(url, params=params, timeout=5)
        if res.status_code == 200:
            return "".join([sentence[0] for sentence in res.json()[0] if sentence[0]])
        return text
    except Exception:
        return text

# 4. دالة جلب الأخبار من GDELT (مُحسنة لتوسيع نطاق البحث)
def fetch_news(query, country_filter, hours_back):
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(hours=hours_back)
    
    start_str = start_date.strftime("%Y%m%d%H%M%S")
    end_str = end_date.strftime("%Y%m%d%H%M%S")
    
    # تحسين صيغة البحث وتخفيف القيود
    gdelt_query = query
    if country_filter == "US":
        # استخدام domain بدلاً من domainis لتوسيع فرص المطابقة
        gdelt_query = f'{query} (domain:nytimes.com OR domain:washingtonpost.com OR domain:cnn.com OR domain:foxnews.com OR domain:wsj.com OR domain:bloomberg.com OR domain:reuters.com OR domain:apnews.com)'
    elif country_filter == "UK":
        gdelt_query = f'{query} sourcecountry:UK'
    elif country_filter == "IS":
        gdelt_query = f'{query} sourcecountry:IS'

    params = {
        "query": gdelt_query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": 100,  # زيادة عدد النتائج المستردة قبل الفلترة
        "sort": "DateDesc",
        "startdatetime": start_str,
        "enddatetime": end_str
    }
    
    # إضافة محاولات اتصال متعددة لتجنب السقوط المؤقت لسيرفرات GDELT
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

# 5. تصنيف نوع المقال
def get_article_type(url):
    url_lower = url.lower()
    if any(x in url_lower for x in ["/opinion/", "/editorial/", "op-ed"]): return "رأي"
    if any(x in url_lower for x in ["/analysis/", "/explainer/"]): return "تحليل"
    return "خبر"

# ================= الواجهة والتفاعل =================

st.title("محرك البحث الإخباري المتقدم 🔍")
st.markdown("ابحث باللغة العربية، وسيقوم النظام بالبحث في المصادر العالمية والمحلية بعد الترجمة.")

# حقل البحث
search_query = st.text_input("أدخل كلمات البحث (مثال: مصر السعودية، الشرق الأوسط، إلخ):")

# الفلاتر
col1, col2, col3 = st.columns(3)
with col1:
    source_choice = st.selectbox("نطاق المصادر:", ["جميع المصادر", "مصادر أمريكية فقط", "مصادر إسرائيلية فقط", "مصادر بريطانية فقط"])
with col2:
    time_choice = st.selectbox("النطاق الزمني:", ["آخر 24 ساعة", "آخر 48 ساعة", "آخر أسبوع", "آخر 30 يوم"])
with col3:
    type_choice = st.selectbox("نوع المقال:", ["الكل", "خبر", "تحليل", "رأي"])

# تعيين قيم الفلاتر
time_map = {"آخر 24 ساعة": 24, "آخر 48 ساعة": 48, "آخر أسبوع": 168, "آخر 30 يوم": 720}
hours = time_map[time_choice]

source_map = {
    "جميع المصادر": None,
    "مصادر أمريكية فقط": "US",
    "مصادر إسرائيلية فقط": "IS",
    "مصادر بريطانية فقط": "UK"
}
country = source_map[source_choice]

if st.button("ابحث الآن", use_container_width=True, type="primary"):
    if not search_query.strip():
        st.warning("الرجاء إدخال كلمة بحث أولاً.")
    else:
        with st.status("جاري معالجة طلبك...", expanded=True) as status:
            # 1. ترجمة الكلمات
            st.write("🔄 جاري ترجمة مصطلحات البحث...")
            query_en = translate_text(search_query, "en")
            query_he = translate_text(search_query, "iw")
            
            st.write(f"🇬🇧 الإنجليزية: {query_en}")
            st.write(f"🇮🇱 العبرية: {query_he}")
            
            # 2. بناء استعلام ذكي
            if country == "IS":
                final_query = f'("{query_en}" OR "{query_he}")'
            else:
                final_query = f'"{query_en}"'
                
            # 3. جلب الأخبار
            st.write("📡 جاري البحث في المصادر الإخبارية...")
            articles = fetch_news(final_query, country, hours)
            
            # 4. فلترة النوع (خبر، تحليل، رأي)
            filtered_articles = []
            for art in articles:
                art_type = get_article_type(art.get("url", ""))
                if type_choice == "الكل" or art_type == type_choice:
                    art["ctype"] = art_type
                    filtered_articles.append(art)
                    
            status.update(label=f"تم العثور على {len(filtered_articles)} نتيجة", state="complete")

        # ================= عرض النتائج =================
        if not filtered_articles:
            st.info("لا توجد نتائج مطابقة لبحثك في هذا النطاق الزمني أو المصدر. جرب اختيار 'الكل' في الفلاتر أو توسيع النطاق الزمني.")
        else:
            for art in filtered_articles:
                orig_title = art.get("title", "بدون عنوان")
                url = art.get("url", "#")
                domain = art.get("domain", "مصدر غير معروف")
                seen_date = art.get("seendate", "")
                
                # ترجمة العنوان للعربية للعرض
                title_ar = translate_text(orig_title, "ar")
                
                # تنسيق التاريخ لتوقيت مصر
                try:
                    dt = datetime.strptime(seen_date, "%Y%m%dT%H%M%SZ")
                    dt_cairo = dt.replace(tzinfo=timezone.utc) + timedelta(hours=3)
                    date_str = dt_cairo.strftime("%Y-%m-%d %H:%M")
                except:
                    date_str = seen_date

                # رسم بطاقة الخبر
                with st.container():
                    st.markdown(f"""
                    <div class='news-card'>
                        <div class='news-title'>{html.escape(title_ar)}</div>
                        <div class='en-text'>{html.escape(orig_title)}</div>
                        <div class='news-meta'>
                            <span>🌐 {html.escape(domain)}</span> | 
                            <span>🕒 {date_str}</span>
                            <span class='badge'>{art['ctype']}</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # أزرار الإجراءات
                    c1, c2 = st.columns(2)
                    with c1:
                        st.link_button("🔗 المصدر الأصلي", url, use_container_width=True)
                    with c2:
                        translate_url = f"https://translate.google.com/translate?sl=auto&tl=ar&u={quote(url, safe='')}"
                        st.link_button("🌐 ترجم المقال (صفحة كاملة)", translate_url, use_container_width=True)
