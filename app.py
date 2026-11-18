# -*- coding: utf-8 -*-
"""
رادار الأخبار العالمية — بحث بالعربية في مصادر إسرائيلية وأمريكية وبريطانية + بحث عام عبر GDELT
"""
import hashlib
from collections import Counter
import html
import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote, urlparse

import streamlit as st

import core
import dossiers as dossiers_mod
import intel
from core import fmt_seen, tr
import gh_actions
import watch as watch_mod
import hmac
import links as links_mod
from about import TAB_HELP, TAB_NAMES, plain as about_plain, sections as about_sections
import keys as keys_mod
import store
import time
import writers as writers_mod
from sources import ARAB_EG_GROUP, ARABIC, EGYPT, EGYPT_ARABIC, FLAGS, ISRAEL, REGION, SECTIONS, UK, USA, egypt_only, source_country
from writers import WRITERS

DOMAIN_LABELS = {}
for _g in (ISRAEL, USA, UK, REGION, ARABIC, EGYPT):
    for _entries in _g.values():
        for _label, _doms, _ in _entries:
            for _d in _doms.split("|"):
                DOMAIN_LABELS.setdefault(_d, _label)
for _n, _d, *_rest in intel.SOURCES:
    DOMAIN_LABELS.setdefault(_d, _n)


def source_name(domain):
    domain = (domain or "").lower().replace("www.", "")
    for d, label in DOMAIN_LABELS.items():
        if domain == d or domain.endswith("." + d):
            return label
    return domain


@st.cache_data(ttl=7 * 86400, show_spinner=False)
def _ar_name(label):
    if re.search(r"[\u0600-\u06FF]", label):
        return label
    try:
        return tr(label, "en", "ar") or label
    except Exception:
        return label


def src_label(domain, with_domain=True):
    """«اسم المصدر بالعربية · 🏳️ دولته» — يُستخدم في كل مكان يظهر فيه مصدر. لا يُسقط الصفحة أبداً"""
    try:
        dom = str(domain or "").lower().replace("www.", "")
        name = str(source_name(dom))
        name_ar = str(_ar_name(name)) if name != dom else dom
        country = str(source_country(dom) or "")
        out = html.escape(name_ar)
        if with_domain and name_ar != dom:
            out += f" ({html.escape(dom)})"
        out += (f" · {FLAGS.get(country, '🏳️')} {country}" if country else " · 🏳️ دولة غير محددة")
        return out
    except Exception as e:  # أي خطأ هنا لا يجب أن يكسر عرض الخبر
        return html.escape(str(domain or "")) + f" (تعذّر تحديد الدولة: {type(e).__name__})"


st.set_page_config(page_title="رادار الأخبار العالمية", page_icon="📰", layout="centered")

st.markdown(
    """
<style>
.stApp, .stMarkdown, label, [data-testid="stWidgetLabel"] {direction: rtl; text-align: right;}
.ar-title {font-size:1.15rem; font-weight:700; line-height:1.7; margin-bottom:4px;}
.ltr {direction:ltr; text-align:left; color:#6b7280; font-size:.9rem; margin-bottom:2px;}
.meta {color:#6b7280; font-size:.85rem; margin:6px 0;}
.badge {background:#eef2ff; color:#3730a3; padding:1px 8px; border-radius:10px; font-size:.78rem;}
a.btn {display:inline-block; background:#1d4ed8; color:#fff !important; padding:8px 18px;
       border-radius:8px; text-decoration:none; font-weight:600; margin-top:4px;}
a.btn:hover {background:#1e40af;}
.card {border:1px solid rgba(128,128,128,.3); border-radius:10px; padding:12px 14px; margin-bottom:10px;}
.article-body p {line-height:2; font-size:1.05rem; margin-bottom:1rem;}
/* التابات: تنزل على أكثر من سطر فتظهر كلها بلا تمرير جانبي، وأزرارها أكبر لسهولة اللمس */
[data-baseweb="tabs"], [data-baseweb="tabs"] > div {overflow: visible !important; height: auto !important; max-height: none !important;}
[role="tablist"] {flex-wrap: wrap !important; overflow: visible !important; height: auto !important; max-height: none !important;
    gap: 6px 4px; row-gap: 6px; width: 100% !important;}
[role="tablist"] button[role="tab"] {padding: 10px 14px !important; height: auto !important; min-height: 44px !important;
    border: 1px solid rgba(128,128,128,.35) !important; border-radius: 10px !important; background: rgba(128,128,128,.08) !important;}
[role="tablist"] button[aria-selected="true"] {background: rgba(255,75,75,.18) !important; border-color: #ff4b4b !important; font-weight: 700;}
[data-baseweb="tab-highlight"], [data-baseweb="tab-border"] {display: none !important;}
[data-baseweb="tabs"] button:not([role="tab"]) {display: none !important;}  /* أسهم التمرير */
::-webkit-scrollbar {height: 14px; width: 14px;}
::-webkit-scrollbar-thumb {background: rgba(128,128,128,.6); border-radius: 8px;}
/* ألوان تابات الأقسام الاربعة (إسرائيلي/أمريكي/بريطاني/إقليمي) وحجم أكبر */
[data-testid="stTabs"] > div:first-child [role="tablist"] button[role="tab"]:nth-child(4) {background:#c0392b !important; border-color:#e74c3c !important; color:#fff !important;}
[data-testid="stTabs"] > div:first-child [role="tablist"] button[role="tab"]:nth-child(5) {background:#2563c9 !important; border-color:#4f8cf0 !important; color:#fff !important;}
[data-testid="stTabs"] > div:first-child [role="tablist"] button[role="tab"]:nth-child(6) {background:#d9822b !important; border-color:#f2a655 !important; color:#fff !important;}
[data-testid="stTabs"] > div:first-child [role="tablist"] button[role="tab"]:nth-child(7) {background:#2a8f55 !important; border-color:#4cc783 !important; color:#fff !important;}
[data-testid="stTabs"] > div:first-child [role="tablist"] button[role="tab"]:nth-child(n+4):nth-child(-n+7) {font-weight:700; min-height:50px !important; border-radius:16px !important;}
[data-testid="stTabs"] > div:first-child [role="tablist"] button[aria-selected="true"]:nth-child(n+4):nth-child(-n+7) {box-shadow:0 0 0 3px rgba(255,255,255,.55), 0 4px 14px rgba(0,0,0,.45);}
.hm-stat {border:1px solid rgba(128,128,128,.3); border-radius:12px; padding:10px 12px; text-align:center;}
.hm-stat b {display:block; font-size:1.5rem;}
.hm-row {border:1px solid rgba(128,128,128,.28); border-radius:12px; padding:10px 12px; margin-bottom:8px;}
.hm-tag {font-size:.75rem; padding:1px 8px; border-radius:10px; color:#fff; margin-left:6px;}
@media (max-width:640px){ .ar-title{font-size:1.05rem;} }
</style>
""",
    unsafe_allow_html=True,
)



# ───────────────────────── القراءة الصوتية ─────────────────────────

TTS_MODES = ["العنوان + المقال كاملاً", "العنوان + ملخص قصير", "العنوان فقط"]
ORDINALS = ["الأول", "الثاني", "الثالث", "الرابع", "الخامس", "السادس", "السابع", "الثامن", "التاسع", "العاشر"]


@st.cache_data(ttl=86400, max_entries=30, show_spinner=False)
def tts_cached(text, voice, rate):
    return core.tts(text, voice, rate)


_fragment = getattr(st, "fragment", lambda f: f)  # الجزء ده بيتحدّث لوحده من غير ما يعيد تحميل باقي التابات


def pick(container, label, options, default, key, fmt=None):
    """بديل لشريط السحب: الشريط كان بيتحرك لوحده مع الطلوع والنزول على الموبايل فيعمل تحديث للصفحة. هنا اختيارات بتتداس بس"""
    options = list(options)
    if default not in options:
        try:
            default = min(options, key=lambda o: abs(o - default))
        except Exception:
            default = options[0]
    kw = {"format_func": fmt} if fmt else {}
    if len(options) <= 6:
        return container.radio(label, options, index=options.index(default), horizontal=True, key=key, **kw)
    return container.selectbox(label, options, index=options.index(default), key=key, **kw)


def untranslated(items):
    return [x for x in items if isinstance(x, dict) and (x.get("title") or "").strip()
            and not core._HAS_AR.search(x.get("title_ar") or "") and not core._HAS_AR.search(x.get("title") or "")]


def fix_untranslated(items, limit=40):
    """بيترجم العناوين اللي فضلت بلغتها (لما الترجمة كانت واقعة وقت البحث). بيرجع عدد اللي اتصلح"""
    bad = untranslated(items)[:limit]
    if not bad:
        return 0
    try:
        core.translate_titles(bad)
    except Exception:
        return 0
    return sum(1 for x in bad if core._HAS_AR.search(x.get("title_ar") or ""))


def tts_settings(prefix):
    c1, c2 = st.columns(2)
    label = c1.selectbox("الصوت", list(core.VOICES), key=f"{prefix}_voice")
    rate = pick(c2, "السرعة", range(-30, 45, 5), 0, f"{prefix}_rate", fmt=lambda v: f"{v:+d}%")
    return core.VOICES[label], rate


def audio_block(entry, wk, name="marsad_news"):
    data, _engine, note = entry
    if note:
        st.caption("ℹ️ " + note)
    st.audio(data, format="audio/mpeg")
    st.download_button(
        "⬇️ تنزيل MP3 (للاستماع بدون إنترنت داخل المترو)", data=data, file_name=f"{name}.mp3", mime="audio/mpeg", key=f"dl_{wk}"
    )
    st.caption("⏸ للإيقاف المؤقت أو الإيقاف استخدم زر المشغّل. الصوت يستمر والشاشة مغلقة.")


def speech_text(url, title_ar, mode):
    """يجهّز النص العربي المراد نطقه حسب الوضع. يعيد (النص، ملاحظة)"""
    if mode == TTS_MODES[2]:
        return title_ar, ""
    art = core.fetch_article(url)
    if not art:
        return title_ar, "تعذّر جلب نص المقال (اشتراك أو حجب) فقُرئ العنوان فقط."
    if mode == TTS_MODES[1]:
        summ = core.summarize(url, verdict=False)
        summ = re.sub(r"^ملخص مبسّط[^\n]*\n+", "", summ)
        return f"{title_ar}. {summ}", ""
    return f"{title_ar}. {core.translate_long(art['text'])}", ""


def make_audio(text, voice, rate):
    try:
        return tts_cached(text, voice, rate)
    except Exception as e:
        st.error(f"تعذّر توليد الصوت ({type(e).__name__}): {e}")
        return None


def listen_widget(a, wk):
    aud = st.session_state.setdefault("audio", {})
    url = a.get("url", "")
    if st.button("🎧 استمع", key=f"ls_{wk}"):
        ss = st.session_state
        voice = core.VOICES[ss.get("tts_voice", list(core.VOICES)[0])]
        with st.spinner("جارٍ تجهيز الصوت (جلب النص وترجمته ثم النطق)… قد يستغرق دقيقة للمقالات الطويلة."):
            text, note0 = speech_text(url, a.get("title_ar", ""), ss.get("tts_mode", TTS_MODES[0]))
            res = make_audio(text, voice, ss.get("tts_rate", 0))
            if res:
                if len(aud) >= 6:
                    aud.pop(next(iter(aud)))
                aud[url] = (res[0], res[1], (note0 + " " + res[2]).strip())
    if url in aud:
        audio_block(aud[url], wk)


# ───────────────────────── صفحة قراءة المقال ─────────────────────────


@st.cache_data(ttl=3600, show_spinner=False)
def alt_cached(title, domain):
    items, note = core.find_alternatives(title, domain)
    return core.translate_titles(items), note


def _alt_cards(items):
    for a in items:
        lnk = f"?view={quote(a['url'], safe='')}&seen={a.get('seendate', '')}&t={quote(a['title'][:200], safe='')}{auth_qs()}"
        st.markdown(
            f"<div class='card'><div class='ar-title'>{html.escape(a.get('title_ar', ''))}</div>"
            f"<div class='ltr' dir='ltr'>{html.escape(a['title'])}</div>"
            f"<div class='meta'>🌐 {src_label(a['domain'])} · 🕒 {fmt_seen(a.get('seendate', ''))} · نص كامل ({a['chars']} حرف)</div>"
            f"<a class='btn' href='{html.escape(lnk)}' target='_blank' rel='noopener'>ترجم المقال</a></div>",
            unsafe_allow_html=True,
        )


def alt_block(title, url):
    st.markdown("### 🔁 تغطية بديلة مجانية للموضوع نفسه")
    host = core._host(url)
    with st.spinner("جارٍ البحث عن مصادر مفتوحة تغطي الخبر نفسه…"):
        items, note = alt_cached(title, host)
    if items:
        st.caption(f"{note} هذه مقالات من مواقع أخرى عن الموضوع نفسه (قد تختلف في الزاوية والتفاصيل عن المقال المغلق).")
        _alt_cards(items)
    else:
        st.info(f"لم أجد بديلاً مفتوحاً بنص كامل. {note}")
    # بحث يدوي: العنوان المستخرج من الرابط قد لا يكفي، فاكتب أنت كلمات الخبر
    st.markdown("**🔎 ابحث بكلماتك أنت عن بدائل:**")
    q = st.text_input("كلمات الخبر (بالإنجليزية أو أي لغة)", value="" if len(title) < 12 else title, key="alt_q",
                      placeholder="مثال: Ethiopia Egypt dam talks")
    if st.button("🔎 ابحث عن بدائل", key="alt_go", type="primary"):
        if len(q.strip()) < 6:
            st.warning("اكتب كلمات أكثر قليلاً.")
        else:
            with st.spinner("جارٍ البحث…"):
                st.session_state["alt_manual"] = alt_cached(q.strip(), host)
    man = st.session_state.get("alt_manual")
    if man:
        m_items, m_note = man
        if m_items:
            st.caption(m_note)
            _alt_cards(m_items)
        else:
            st.warning(f"لا نتائج بنص كامل. {m_note}")
    if q.strip():
        from urllib.parse import quote_plus
        qq = quote_plus(q.strip())
        st.markdown(f"أو افتح البحث في موقع خارجي: [أخبار Google](https://news.google.com/search?q={qq}) · "
                    f"[Google](https://www.google.com/search?q={qq}) · [Bing أخبار](https://www.bing.com/news/search?q={qq})")


def translate_proxy_url(url, tl="ar"):
    """رابط نسخة مترجمة من الصفحة عبر ترجمة جوجل (translate.goog)"""
    from urllib.parse import urlsplit
    s = urlsplit(url)
    host = (s.hostname or "").replace("-", "--").replace(".", "-")
    q = (s.query + "&" if s.query else "") + f"_x_tr_sl=auto&_x_tr_tl={tl}&_x_tr_hl={tl}&_x_tr_pto=wapp"
    return f"https://{host}.translate.goog{s.path or '/'}?{q}"


def embed_browser(url):
    """فتح الصفحة الأصلية مترجمة: أزرار تاب جديد (الأضمن) + إطار داخلي اختياري"""
    import streamlit.components.v1 as components
    with st.expander("🌐 افتح الصفحة الأصلية مترجمة للعربية", expanded=True):
        c1, c2 = st.columns(2)
        c1.link_button("🌐 مترجمة (ترجمة جوجل) ↗️", translate_proxy_url(url), use_container_width=True, type="primary")
        c2.link_button("📄 الأصلية ↗️", url, use_container_width=True)
        st.caption("لو الأصلية فتحت عندك، اضغط بيمين الماوس ← «ترجمة إلى العربية» (متصفح كروم بيترجم أي لغة). "
                   "الزرارين بيفتحوا في تاب جديد وده أضمن من الإطار.")
        if st.checkbox("جرّب عرضها داخل هذه الصفحة (قد لا يعمل مع بعض المواقع)", key="emb_on"):
            mode = st.radio("العرض", ["مترجمة للعربية", "الأصلية بلغتها"], horizontal=True, key="emb_mode")
            src = translate_proxy_url(url) if mode.startswith("مترجمة") else url
            components.html(
                f"<iframe src='{html.escape(src, quote=True)}' style='width:100%;height:690px;border:1px solid #334155;border-radius:8px;background:#fff' "
                "referrerpolicy='no-referrer'></iframe>", height=700, scrolling=False)
            st.caption("لو ظهرت علامة وش حزين، يبقى الموقع مانع العرض داخل صفحات تانية. استخدم الزرارين اللي فوق.")


_SCRIPT_RULES = (
    "القواعد: اكتب بالعامية المصرية البسيطة كأني بحكي لواحد صاحبي، بجمل قصيرة تتقال بصوت عالي من غير تعقيد. "
    "ماتختلقش أي معلومة أو رقم مش موجود في المقالات المرفقة، وكل ما فيه شك قول «حسب ما نشر...» واذكر اسم المصدر والدولة. "
    "فرّق بين اللي المصدر قاله وبين تحليلي أنا. لو في تضارب بين مصدرين وضّحه. ركّز على علاقة الموضوع بمصر. "
    "في الآخر ضيف سطر قصير: «ده تحليل مبني على مصادر مفتوحة ومش تأكيد رسمي».\n\n"
)

SCRIPT_KINDS = {
    "بدون تعليمات (النص بس)": "",
    "تحليل وربط عام": (
        "المطلوب: اقرأ المقال التالي (مترجم للعربية) كمادة تحليل. لخّص أهم ما فيه في 5 نقاط، واستخرج الأطراف والأرقام والتواريخ، "
        "ثم اذكر ما يخص مصر. وإذا أرسلتُ لك مقالات أخرى بعده فاربط بينها: ما الخيط المشترك؟ أين التناقض؟ وما الاستنتاج السياسي المحتمل؟ "
        "ميّز بين ما ورد في النص وما هو استنتاجك.\n\n"
    ),
    "🎬 ريلز فيسبوك (60–90 ثانية)": (
        "المطلوب: اكتب سكريبت ريلز فيسبوك من 150 إلى 220 كلمة (60–90 ثانية) مبني على المقال/المقالات التالية. الهيكل: "
        "(1) خطّاف أول 3 ثواني: سؤال أو معلومة صادمة. (2) الخبر في 3 أو 4 جمل. (3) ليه ده مهم لمصر. (4) جملة ختام + سؤال للمتابعين في التعليقات. "
        "اكتب بجانب كل جزء اقتراح لنص يظهر على الشاشة (3–6 كلمات).\n" + _SCRIPT_RULES
    ),
    "▶️ فيديو يوتيوب (5 دقايق)": (
        "المطلوب: اكتب سكريبت فيديو يوتيوب مدته 5 دقايق (حوالي 700 كلمة) مبني على المقال/المقالات التالية. الهيكل: "
        "(1) خطّاف 10 ثواني. (2) مقدمة قصيرة: إيه اللي حصل؟ (3) الخلفية في فقرة. (4) التحليل: أهم 3 نقاط، لكل واحدة عنوان فرعي. "
        "(5) إيه علاقة ده بمصر؟ (6) الخلاصة + سؤال للتعليقات. حدّد تقريباً الوقت لكل جزء، واقترح لقطات أو صور تظهر مع كل جزء.\n" + _SCRIPT_RULES
    ),
    "▶️ فيديو يوتيوب (9 دقايق)": (
        "المطلوب: اكتب سكريبت فيديو يوتيوب مدته حوالي 9 دقايق (1200 إلى 1300 كلمة) مبني على المقال/المقالات التالية. الهيكل: "
        "(1) خطّاف 10–15 ثانية. (2) مقدمة: إيه اللي حصل. (3) الخلفية التاريخية أو السياق. (4) عرض كل مصدر وروايته على حدة. "
        "(5) الربط: ما الخيط المشترك بين المصادر؟ وأين التناقض؟ (6) السيناريوهات المحتملة (2 أو 3) بدون جزم. (7) إيه معنى ده بالنسبة لمصر. "
        "(8) خلاصة + سؤال للتعليقات. حدّد تقريباً الوقت لكل جزء، واقترح لقطات وخرائط أو صور مناسبة.\n" + _SCRIPT_RULES
    ),
}


def copy_block(url, title, title_ar, art, body_ar):
    """نص جاهز للنسخ (نوت / ذكاء اصطناعي): العنوان والمصدر والتاريخ والرابط ثم النص المترجم"""
    dom = core._host(url)
    with st.expander("📋 انسخ المقال المترجم (للنوت أو لأي ذكاء اصطناعي)", expanded=False):
        kind = st.selectbox("أضف في أول النص تعليمات جاهزة للذكاء الاصطناعي", list(SCRIPT_KINDS), key="cp_kind")
        st.caption("لو هتبعت أكتر من مقال: اختار التعليمات مع **أول** مقال بس، ولمّا تخلّص المقالات كلها اكتب: «دلوقتي اكتب السكريبت».")
        with_orig = st.checkbox("أضف النص الأصلي بعد الترجمة", value=False, key="cp_orig")
        head = (f"العنوان: {title_ar}\nالعنوان الأصلي: {title}\nالمصدر: {source_name(dom)} ({dom}) · {source_country(dom)}\n"
                f"التاريخ: {art.get('date') or 'غير معروف'}\nالرابط: {url}\n\n")
        txt = SCRIPT_KINDS[kind] + head + body_ar.strip()
        if with_orig:
            txt += "\n\n----- النص الأصلي -----\n" + art["text"].strip()
        st.caption("اضغط أيقونة النسخ 📋 في الركن العلوي من الصندوق (بتظهر لما تقف عليه أو تلمسه)، وبعدين الصق في أي مكان. "
                   "كرر نفس الشيء مع كل مقال ولصقهم ورا بعض عشان يحصل الربط بينهم.")
        try:
            st.code(txt, language=None, wrap_lines=True)
        except TypeError:
            st.code(txt, language=None)
        st.download_button("⬇️ نزّله كملف نصي (.txt)", txt, file_name="article.txt", mime="text/plain", use_container_width=True, key="cp_dl")


def reader_head(title_en, url, wr, outlet, title_ar=""):
    """رأس صفحة المقال: العنوان بالعربي والأصلي + الجريدة + الكاتب + الموقع"""
    if title_en:
        title_ar = title_ar or tr(title_en, "auto", "ar")
        st.markdown(f"### {title_ar}")
        st.markdown(f"<div class='ltr' dir='ltr'>{html.escape(title_en)}</div>", unsafe_allow_html=True)
    bits = []
    if outlet:
        bits.append(f"📰 **الجريدة:** {html.escape(outlet)}")
    if wr:
        bits.append(f"✍️ **الكاتب:** {html.escape(wr)}")
    host = core._host(url)
    if host and host != "news.google.com":
        bits.append(f"🌐 **الموقع:** {src_label(host)}")
    if bits:
        st.markdown("  \n".join(bits), unsafe_allow_html=True)


def search_suggestions(title):
    """اقتراحات بحث بالعنوان في مصادر تانية (روابط تفتح في تاب جديد)"""
    q = re.sub(r"\s+[-|–]\s+[^-|–]{2,40}$", "", (title or "").strip())[:140]
    if len(q) < 6:
        return
    from urllib.parse import quote_plus
    qq = quote_plus(q)
    st.markdown("### 🔎 اقتراحات بحث بالعنوان في مصادر تانية")
    sites = [("Google", f"https://www.google.com/search?q={qq}"), ("أخبار Google", f"https://news.google.com/search?q={qq}"),
             ("Bing أخبار", f"https://www.bing.com/news/search?q={qq}"),
             ("AP", f"https://www.google.com/search?q={qq}+site:apnews.com"), ("Reuters", f"https://www.google.com/search?q={qq}+site:reuters.com"),
             ("BBC", f"https://www.google.com/search?q={qq}+site:bbc.com"), ("الجزيرة", f"https://www.google.com/search?q={qq}+site:aljazeera.net"),
             ("Times of Israel", f"https://www.google.com/search?q={qq}+site:timesofisrael.com"),
             ("Axios", f"https://www.google.com/search?q={qq}+site:axios.com"), ("Al-Monitor", f"https://www.google.com/search?q={qq}+site:al-monitor.com"),
             ("Middle East Eye", f"https://www.google.com/search?q={qq}+site:middleeasteye.net"), ("X (تويتر)", f"https://x.com/search?q={qq}&f=live")]
    st.markdown(" · ".join(f"[{n}]({u})" for n, u in sites))
    st.caption("كل رابط بيفتح تاب جديد ببحث بعنوان المقال، علشان تلاقي نفس الخبر عند ناس تانية.")


def reader_scroll_tool():
    """ازرار عائمة للتحكم الدقيق في التمرير اثناء قراءة المقال (الشريط الجانبي وعجلة الماوس بيقفزوا جمل كاملة)"""
    import streamlit.components.v1 as components
    components.html("""
<script>
(function(){
  try{
    var P=window.parent, D=P.document;
    var old=D.getElementById('rd-scroll-tool'); if(old) old.remove();
    var box=D.createElement('div'); box.id='rd-scroll-tool';
    box.style.cssText='position:fixed;left:10px;bottom:90px;z-index:99999;display:flex;flex-direction:column;gap:6px;direction:ltr;font-family:sans-serif';
    function btn(t,title){var b=D.createElement('button');b.textContent=t;b.title=title;
      b.style.cssText='width:56px;height:56px;border-radius:14px;border:2px solid rgba(255,255,255,.6);background:rgba(30,30,40,.92);color:#fff;font-size:26px;cursor:pointer;touch-action:manipulation;user-select:none;-webkit-user-select:none';
      return b;}
    function area(){return D.querySelector('[data-testid="stMain"]')||D.querySelector('section.main')||D.scrollingElement||D.documentElement;}
    var speed=14, timer=null, auto=false, autoTimer=null, autoSpeed=1;
    function step(dy){var el=area(); el.scrollBy({top:dy,behavior:'auto'});}
    function holdStart(dir){step(dir*speed); stopHold(); timer=setInterval(function(){step(dir*speed);},40);}
    function stopHold(){if(timer){clearInterval(timer);timer=null;}}
    function bindHold(b,dir){
      ['mousedown','touchstart'].forEach(function(e){b.addEventListener(e,function(ev){ev.preventDefault();holdStart(dir);},{passive:false});});
      ['mouseup','mouseleave','touchend','touchcancel'].forEach(function(e){b.addEventListener(e,stopHold);});
    }
    var up=btn('▲','لفوق (اضغط واستمر)'), down=btn('▼','لتحت (اضغط واستمر)');
    var play=btn('▶','تمرير تلقائي بطيء'), plus=btn('+','أسرع'), minus=btn('−','أبطأ');
    bindHold(up,-1); bindHold(down,1);
    function setAuto(on){
      auto=on; play.textContent=on?'⏸':'▶';
      if(autoTimer){clearInterval(autoTimer);autoTimer=null;}
      if(on){autoTimer=setInterval(function(){step(autoSpeed);},40);}
    }
    play.onclick=function(){setAuto(!auto);};
    plus.onclick=function(){autoSpeed=Math.min(8,autoSpeed+0.5);speed=Math.min(40,speed+4);};
    minus.onclick=function(){autoSpeed=Math.max(0.5,autoSpeed-0.5);speed=Math.max(4,speed-4);};
    [up,play,plus,minus,down].forEach(function(b){box.appendChild(b);});
    D.body.appendChild(box);
  }catch(e){}
})();
</script>""", height=0)


def reader_page():
    url = unquote(st.query_params.get("view", ""))
    seen = st.query_params.get("seen", "")
    orig_title = unquote(st.query_params.get("t", ""))
    wr = unquote(st.query_params.get("wr", ""))
    outlet = unquote(st.query_params.get("o", ""))

    st.markdown("## 📖 قراءة المقال مترجماً")
    reader_scroll_tool()
    if not url.startswith(("http://", "https://")):
        st.error("رابط غير صالح.")
        return
    gnews_link = core._host(url) == "news.google.com"
    if gnews_link:  # رابط أخبار جوجل: نحاول نوصل للرابط الاصلي للجريدة
        with st.spinner("جارٍ الوصول للرابط الاصلي للمقال…"):
            real = core.decode_gnews(url)
        if core._host(real) != "news.google.com":
            url, gnews_link = real, False
    st.markdown(f"🔗 **الرابط الأصلي:** [{html.escape(url)}]({url})")
    reader_head(orig_title, url, wr, outlet)

    embed_browser(url)

    with st.spinner("جارٍ جلب المقال وترجمته…"):
        art = None if gnews_link else core.fetch_article(url)
        if not art:
            if gnews_link:
                st.warning("رابط أخبار جوجل ما اتفكش (جوجل بيمنع فكّه من التطبيق). العنوان اللي فوق هو العنوان الحقيقي للمقال. "
                           "افتح «الأصلية» من فوق في متصفحك، او استخدم الاقتراحات تحت.")
            else:
                st.warning("تعذّر استخراج نص المقال: " + core.FETCH_WHY.get(url, "جدار اشتراك أو حجب") +
                           ". (الصفحة قد تفتح في متصفحك عادي لكن الموقع يعامل التطبيق كزائر آلي.)")
            search_suggestions(orig_title or core.title_from_url(url))
            alt_block(orig_title or core.title_from_url(url), url)
            return
        title = art["title"] if art["title"] and art["title"].lower() not in ("google news", "أخبار جوجل") else orig_title
        title = title or orig_title
        title_ar = tr(title, "auto", "ar")
        body_ar = art["text"] if art.get("pre_ar") else core.translate_long(art["text"])
        body_ok = core.translated_ok(art["text"], body_ar)

    if not body_ok:
        st.warning("⚠️ الترجمة التلقائية للنص لم تكتمل الآن (غالباً جوجل مشغول). اضغط «أعد الترجمة» بعد لحظات، "
                   "أو استخدم زرار «مترجمة (ترجمة جوجل)» فوق في التاب.")
        if st.button("🔁 أعد الترجمة", key="rd_retry"):
            st.rerun()
    trunc_alt = False
    tail = art["text"][-300:].lower()
    if len(art["text"]) < 1800 or re.search(r"loading\.\.\.|subscribe|log in to|טוען|למנויים|הרשמה", tail):
        st.warning(
            f"⚠️ النص الذي وصل التطبيق قصير ({len(art['text'])} حرفاً) ويبدو أنه المقدّمة المتاحة للزوار فقط؛ "
            "الموقع يخفي بقية المقال خلف اشتراك أو تحميل بالجافاسكربت، ولا يمكن للتطبيق تجاوز ذلك. "
            "لقراءته كاملاً: افتح الرابط الأصلي بحسابك المشترك، أو اقرأ التغطية البديلة المفتوحة أسفل الصفحة."
        )
        trunc_alt = True
    via = art.get("via") or "غير معروفة (نسخة محفوظة من قبل)"
    if via.startswith("الفتح المباشر"):
        st.success(f"🟢 طريقة جلب المقال: {via}")
    else:
        st.info(f"🟡 طريقة جلب المقال: {via} — لأن الموقع رفض فتحه مباشرة. (النص قد يختلف شكله قليلاً عن الأصل.)")
    if art.get("authors") and not wr:
        st.markdown("✍️ **الكاتب (من توقيع المقال):** " + html.escape("، ".join(art["authors"])))
    elif not wr and not art.get("authors"):
        st.caption("✍️ اسم الكاتب مش ظاهر في بيانات الصفحة اللي وصلت للتطبيق. شوفه في الصفحة الاصلية.")
    if art["date"]:
        st.markdown(f"🕒 **تاريخ النشر (حسب بيانات المصدر):** {art['date']}")
    if seen:
        st.markdown(f"🛰️ **وقت رصد المقال (توقيت القاهرة):** {fmt_seen(seen)}")

    if not orig_title or title.strip().lower() != orig_title.strip().lower():  # العنوان ظهر فوق؛ نكرره فقط لو الصفحة لها عنوان مختلف
        st.markdown(f"### {title_ar}")
        st.markdown(f"<div class='ltr' dir='ltr'>{html.escape(title)}</div>", unsafe_allow_html=True)

    if st.button("📝 ملخص المقال في نقاط"):
        with st.spinner("جارٍ التلخيص…"):
            st.info(core.summarize(url))

    copy_block(url, title, title_ar, art, body_ar)

    with st.expander("🎧 استمع للمقال بصوت مسموع", expanded=False):
        voice, rate = tts_settings("rd")
        part = st.radio("ما الذي يُقرأ؟", ["المقال كاملاً", "أول فقرات فقط (حوالي دقيقتين)"], horizontal=True, key="rd_part")
        rd_aud = st.session_state.setdefault("rd_audio", {})
        if st.button("🔊 ولّد الصوت", key="rd_go", use_container_width=True):
            txt = f"{title_ar}. {body_ar}"
            if part != "المقال كاملاً":
                txt = txt[:1800].rsplit(".", 1)[0] + "."
            with st.spinner("جارٍ تجهيز الصوت…"):
                res = make_audio(txt, voice, rate)
            if res:
                rd_aud.clear()
                rd_aud[url] = res
        if url in rd_aud:
            audio_block(rd_aud[url], "rd")

    st.divider()
    paras = "".join(
        f"<p>{html.escape(p)}</p>" for p in body_ar.split("\n") if p.strip() and p.strip().strip(".…") not in ("تحميل", "جار التحميل", "جارٍ التحميل")
    )
    st.markdown(f"<div class='article-body'>{paras}</div>", unsafe_allow_html=True)
    with st.expander("النص الأصلي"):
        st.text(art["text"])
    search_suggestions(title)
    if trunc_alt:
        st.divider()
        alt_block(title, url)



import base64 as _b64

_LOGO_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 520 140" width="520" height="140" role="img" aria-label="Ehab Ibrahim"> <defs> <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0f2a47"/><stop offset="1" stop-color="#0a1626"/></linearGradient> <linearGradient id="sw" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#22d3ee" stop-opacity="0"/><stop offset="1" stop-color="#22d3ee" stop-opacity=".75"/></linearGradient> </defs> <rect x="6" y="6" width="128" height="128" rx="28" fill="url(#bg)"/> <g transform="translate(70 70)" fill="none" stroke="#22d3ee" stroke-width="2.2" opacity=".9"> <circle r="46"/><circle r="31"/><circle r="16"/> <path d="M-46 0H46M0 -46V46" stroke-opacity=".35"/> </g> <path d="M70 70 L70 24 A46 46 0 0 1 110 47 Z" fill="url(#sw)"/> <line x1="70" y1="70" x2="110" y2="47" stroke="#67e8f9" stroke-width="2.5" stroke-linecap="round"/> <circle cx="94" cy="52" r="4.5" fill="#fbbf24"/><circle cx="52" cy="88" r="3.2" fill="#f87171"/> <text x="156" y="68" font-family="Georgia, \'Times New Roman\', serif" font-size="46" font-weight="700" fill="#e2e8f0">Ehab Ibrahim</text> <rect x="158" y="80" width="64" height="4" rx="2" fill="#22d3ee"/> <text x="158" y="112" font-family="Tahoma, Arial, sans-serif" font-size="21" fill="#94a3b8" letter-spacing=".5">رادار الأخبار العالمية</text> </svg> '


def show_logo(width=300):
    """شعار المالك (Ehab Ibrahim) فوق في التاب"""
    b = _b64.b64encode(_LOGO_SVG.encode("utf-8")).decode()
    st.markdown(f"<div style='direction:ltr;text-align:left;margin:0 0 6px'><img alt='Ehab Ibrahim' width='{width}' src='data:image/svg+xml;base64,{b}'></div>",
                unsafe_allow_html=True)


def show_footer():
    st.divider()
    st.markdown("<div style='text-align:center;color:#94a3b8;font-size:.85rem'>© Ehab Ibrahim — رادار الأخبار العالمية · جميع الحقوق محفوظة</div>",
                unsafe_allow_html=True)


# ───────────────────────── بوابة الشفرات (اختيارية: تعمل فقط إن وُجد ADMIN_KEY في Secrets) ─────────────────────────

def _sec(name):
    try:
        v = st.secrets.get(name)
    except Exception:
        v = None
    return v or os.getenv(name)


ADMIN_KEY, _GT, _GG = _sec("ADMIN_KEY"), _sec("GITHUB_TOKEN"), _sec("GIST_ID")
GATE_ON = bool(ADMIN_KEY and _GT and _GG)


def _adm_tok():
    """رمز جلسة المالك المشتق من ADMIN_KEY (لا يكشف المفتاح نفسه): يوضع في الرابط فيُعاد الدخول تلقائياً بعد انقطاع الجلسة"""
    import hashlib
    return hashlib.sha256(("marsad-session|" + (ADMIN_KEY or "")).encode("utf-8")).hexdigest()[:40]


def auth_qs():
    """يُلحق الشفرة بروابط صفحة القراءة (تُفتح في تبويب جديد = جلسة جديدة)"""
    a = st.session_state.get("auth") or {}
    return f"&k={quote(a['token'], safe='')}" if a.get("token") else ""


def _try_code(code):
    """يحاول الدخول بالشفرة؛ يعيد رسالة الخطأ أو '' عند النجاح"""
    code = (code or "").strip()
    if not code:
        return ""
    if hmac.compare_digest(code, ADMIN_KEY) or hmac.compare_digest(code, _adm_tok()):
        st.session_state["auth"] = {"role": "admin", "token": _adm_tok()}
        return ""
    try:
        k, why = keys_mod.touch(_GT, _GG, code)
    except Exception as e:
        return f"تعذّر التحقق الآن ({type(e).__name__}). أعد المحاولة بعد لحظات."
    if not k:
        return why
    st.session_state["auth"] = {"role": "guest", "token": keys_mod.norm(code), "label": k.get("label", ""),
                                "exp": keys_mod.iso(keys_mod.expires_at(k)), "checked": time.time(),
                                "scope": k.get("scope", "full")}
    return ""


def gate():
    ss = st.session_state
    if not GATE_ON:
        ss["auth"] = {"role": "admin", "token": ""}
        return
    a = ss.get("auth")
    msg = ""
    if a and a["role"] == "guest":
        exp = keys_mod.parse(a.get("exp"))
        if exp and keys_mod.now() > exp:
            ss.pop("auth")
            a, msg = None, "انتهت مدة التجربة."
        elif time.time() - a["checked"] > keys_mod.RECHECK_SECONDS:
            try:
                ok = keys_mod.recheck(_GT, _GG, a["token"])
            except Exception:
                ok = True  # تعذّر الفحص مؤقتاً: لا نطرد الضيف
            a["checked"] = time.time()
            if not ok:
                ss.pop("auth")
                a, msg = None, "أُلغيت هذه الشفرة أو انتهت مدتها."
    if a:
        # ثبّت الرمز في رابط الصفحة: لو انقطعت الجلسة (قفل شاشة الموبايل مثلاً) يُعاد الدخول تلقائياً بدل طلب الشفرة
        if a.get("token") and st.query_params.get("k", "") != a["token"]:
            st.query_params["k"] = a["token"]
        return
    code = st.query_params.get("k", "")
    if code and not ss.get("k_tried") == code:
        ss["k_tried"] = code
        msg = _try_code(code) or msg
        if ss.get("auth"):
            if ss["auth"].get("token"):
                st.query_params["k"] = ss["auth"]["token"]
            return
    show_logo()
    st.title("🔒 رادار الأخبار العالمية")
    st.markdown("هذه النسخة بالدعوة فقط. اكتب الشفرة التي وصلتك مع الرابط.")
    if msg:
        st.error(msg)
    entered = st.text_input("الشفرة", key="gate_code", type="password", placeholder="MR-XXXX-XXXX")
    if st.button("دخول", type="primary"):
        err = _try_code(entered)
        if err:
            st.error(err)
        else:
            st.rerun()
    st.stop()


gate()
IS_ADMIN = st.session_state["auth"]["role"] == "admin"

if "view" in st.query_params:
    reader_page()
    st.stop()

# ───────────────────────── التخزين: المحفوظات + المصادر المضافة ─────────────────────────

DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9\-\.]*\.[a-z]{2,}$")
# فواصل العبارات: , ، ; سطر جديد، وكذلك النقطة بعد حرف عربي (مثل: مصر. الجيش المصري.) دون المساس بالاختصارات الإنجليزية
TERM_SPLIT = re.compile(r"[,،;\n]+|(?<=[\u0600-\u06FF])\.+(?=\s|$)")



def _secret(name):
    try:
        v = st.secrets.get(name)
    except Exception:
        v = None
    return v or os.getenv(name)


GH_TOKEN, GH_GIST = _secret("GITHUB_TOKEN"), _secret("GIST_ID")
PERSIST = bool(GH_TOKEN and GH_GIST) and IS_ADMIN  # الضيف لا يرى بيانات المالك ولا يكتب فيها

if "store" not in st.session_state:
    _data, _err = store.empty(), None
    if PERSIST:
        try:
            _data = store.load(GH_TOKEN, GH_GIST)
        except Exception as _e:
            _err = f"تعذّر تحميل التخزين الدائم ({type(_e).__name__})"
    st.session_state["store"] = _data
    st.session_state["store_err"] = _err


def S():
    return st.session_state["store"]


def persist():
    if not PERSIST:
        return
    try:
        fresh = store.load(GH_TOKEN, GH_GIST)  # حتى لا نمحو شفرات أُنشئت أو دخولات سُجّلت من جلسة أخرى
        S()["keys"] = fresh["keys"]
        store.save(GH_TOKEN, GH_GIST, S())
        st.session_state["store_err"] = None
    except Exception as e:
        st.session_state["store_err"] = f"تعذّر الحفظ الدائم ({type(e).__name__})"


for _s in S()["sources"]:
    DOMAIN_LABELS[_s["domain"]] = _s["label"]

SAVE_KEYS = [
    "url", "title", "title_ar", "title_en", "seendate", "domain", "sourcecountry", "country_ar", "language",
    "ctype", "ctype_sure", "writer", "outlet", "wsrc", "snips", "snip_ar", "found", "fetched", "checked",
]


def flash(msg):
    st.session_state["flash"] = msg


def clean_domain(x):
    return (x or "").strip().lower().replace("https://", "").replace("http://", "").replace("www.", "").strip("/").split("/")[0]


def save_item(a, tab=""):
    s = S()
    if any(x.get("url") == a.get("url") for x in s["saved"]):
        return
    it = {k: a[k] for k in SAVE_KEYS if k in a}
    it["saved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    it["note"], it["tab"] = "", tab
    s["saved"].insert(0, it)
    persist()


def delete_item(url):
    S()["saved"] = [x for x in S()["saved"] if x.get("url") != url]
    persist()


def set_note(url, wkey):
    for x in S()["saved"]:
        if x.get("url") == url:
            x["note"] = st.session_state.get(wkey, "")
    persist()


def add_source():
    ss = st.session_state
    dom = clean_domain(ss.get("ms_domain", ""))
    if not DOMAIN_RE.match(dom):
        return flash("⚠️ الدومين غير صالح (مثال: example.com).")
    name = (ss.get("ms_name", "") or "").strip() or dom
    gname = ss.get("ms_group", "أمريكية")
    group = {"إسرائيلية": "il", "أمريكية": "us", "بريطانية": "uk", "تركيا/إيران/إثيوبيا": "rg"}[gname]
    lang = {"عبري": "he", "إنجليزي": "en", "كلاهما": "both", "تركي": "tr", "فارسي": "fa", "أمهري": "am", "عربي": "ar"}[ss.get("ms_lang", "إنجليزي")]
    if any(x["domain"] == dom and x["group"] == group for x in S()["sources"]):
        return flash("هذا المصدر مضاف مسبقاً.")
    S()["sources"].append({"label": name, "domain": dom, "lang": lang, "group": group})
    DOMAIN_LABELS[dom] = name
    persist()
    flash(f"✅ أُضيف «{name}» إلى مصادر التاب ({gname}) — يظهر هناك ضمن «مصادر أضفتَها».")


def add_writer():
    ss = st.session_state
    en = (ss.get("mw_en", "") or "").strip()
    ar = (ss.get("mw_ar", "") or "").strip()
    tw = core.twitter_handle(ss.get("mw_tw", ""))
    sites = [d for d in (clean_domain(x) for x in re.split(r"[,\s]+", ss.get("mw_sites", ""))) if DOMAIN_RE.match(d) and d not in ("x.com", "twitter.com")]
    country = {"أمريكي": "US", "بريطاني": "UK", "إسرائيلي": "IL", "سعودي": "SA", "خليجي": "GCC", "مصري": "EG", "عربي آخر": "AR"}[ss.get("mw_country", "أمريكي")]
    msg = lambda m: ss.__setitem__("mw_msg", m)
    if not (en or ar):
        return msg("⚠️ اكتب اسم الكاتب (بالعربي او بالانجليزي).")
    if country in ("US", "UK", "IL") and not sites:
        return msg("⚠️ الكاتب الاجنبي محتاج دومين موقع نشر واحد على الاقل (مثل nytimes.com).")
    if country not in ("US", "UK", "IL") and not (tw or sites):
        return msg("⚠️ للكاتب العربي لازم تكتب حساب تويتر (مثل @alfihrest) او موقع نشر.")
    if ss.get("mw_tw", "").strip() and not tw:
        return msg("⚠️ حساب تويتر مش مفهوم. اكتبه زي @name او الصق رابط الحساب.")
    ar = ar or (tr(en, "en", "ar") if en else "")
    en = en or ar
    heb = (ss.get("mw_heb", "") or "").strip()
    wid = "c_" + hashlib.md5((en + tw + ",".join(sites)).encode()).hexdigest()[:8]
    if any(w["id"] == wid for w in S()["writers"]):
        return msg("الكاتب ده مضاف قبل كده.")
    S()["writers"].append(
        {"id": wid, "name_ar": ar, "name_en": en, "outlet": (ss.get("mw_outlet", "") or "").strip() or (f"تويتر @{tw}" if tw else sites[0]),
         "country": country, "kind": ss.get("mw_kind", "رأي"), "sites": sites, "aliases": [],
         "heb": [heb, sites] if heb and sites else None, "twitter": tw}
    )
    persist()
    msg(f"✅ اتضاف الكاتب «{ar}»" + (f" (تويتر @{tw})" if tw else "") + " — هتلاقيه في تاب «كتّاب ومحللون» تحت قسم "
        + GROUP_LABELS.get(country, "") + ". وتقدر تلاقيه تحت في «ما أضفتَه».")


def remove_source(dom, group):
    S()["sources"] = [x for x in S()["sources"] if not (x["domain"] == dom and x["group"] == group)]
    persist()


def remove_writer(wid):
    S()["writers"] = [x for x in S()["writers"] if x["id"] != wid]
    persist()


def fill_author(idx):
    ss = st.session_state
    a = (ss.get("analysis") or {}).get("authors", [])[idx]
    ss["mw_en"] = a.get("en") or a["raw"]
    ss["mw_ar"] = a.get("ar", "")
    ss["mw_heb"] = a["raw"] if a.get("heb") else ""


def pick_author():
    names = [a["raw"] for a in (st.session_state.get("analysis") or {}).get("authors", [])]
    if st.session_state.get("mw_pick") in names:
        fill_author(names.index(st.session_state["mw_pick"]))


def do_analyze():
    ss = st.session_state
    url = (ss.get("ms_url", "") or "").strip()
    if not url:
        return
    try:
        res = core.analyze_url(url)
    except Exception as e:
        res = {"error": f"تعذّر التحليل ({type(e).__name__})", "authors": []}
    ss["analysis"] = res
    if res.get("domain"):
        ss["ms_domain"] = res["domain"]
        ss["ms_name"] = res.get("site_name") or res["domain"]
        g = res.get("group", "us")
        ss["ms_group"] = {"il": "إسرائيلية", "uk": "بريطانية", "us": "أمريكية"}[g]
        ss["ms_lang"] = "عبري" if res.get("lang") == "he" else "إنجليزي"
        ss["mw_sites"], ss["mw_outlet"] = res["domain"], ss["ms_name"]
        ss["mw_country"] = {"il": "إسرائيلي", "uk": "بريطاني", "us": "أمريكي"}[g]
    if (res.get("tweet") or {}).get("handle"):
        ss["mw_tw"] = res["tweet"]["handle"]
    if res.get("authors"):
        ss["mw_pick"] = res["authors"][0]["raw"]
        fill_author(0)


# ───────────────────────── الواجهة الرئيسية ─────────────────────────

show_logo()
st.title("📰 رادار الأخبار العالمية")
if not IS_ADMIN:
    _a = st.session_state["auth"]
    st.info(f"🎟️ نسخة تجريبية لـ «{_a.get('label', '')}» — "
            f"تنتهي {keys_mod.parse(_a['exp']).astimezone(core.TZ).strftime('%Y-%m-%d %H:%M')} بتوقيت القاهرة. "
            "لا يُحفظ شيء بعد إغلاق الصفحة.")


def render_about():
    """قسم «ما هذا التطبيق؟»: يُبنى من بيانات التطبيق نفسها فيتحدّث تلقائياً"""
    n_src = len({d for g in (ISRAEL, USA, UK, REGION, ARABIC, EGYPT) for ents in g.values() for _, d, _ in ents})
    stats = {"n_sources": n_src, "langs": [core.LANG_NAME_AR.get(c, c) for c, _, _, _ in core.LANGS],
             "n_writers": len(WRITERS), "n_files": len(intel.FILES), "file_names": list(intel.FILES), "threads": list(links_mod.THREADS)}
    with st.expander(about_plain("ما هذا التطبيق؟ وايه اللي بيعمله؟")):
        for title, body in about_sections(stats):
            st.markdown(f"**{about_plain(title)}**")
            if body is None:  # قائمة التابات من TAB_HELP
                st.markdown("\n".join(f"- **{about_plain(n)}:** {about_plain(TAB_HELP[n])}" for n in TAB_NAMES))
            else:
                st.markdown(about_plain(body))


def render_run_report():
    """زر المالك: تشغيل التقرير اليومي الآن من التطبيق (يستدعي GitHub Actions)"""
    tok, repo, branch = _sec("ACTIONS_TOKEN"), _sec("GH_REPO") or gh_actions.DEFAULT_REPO, _sec("GH_BRANCH") or "main"
    with st.expander("🔄 تحديث التقرير الآن (للمالك فقط)"):
        if not tok:
            st.info("لتفعيل الزر أضف في Secrets قيمة **ACTIONS_TOKEN**. أنشئ توكن من GitHub ← الصورة الشخصية ← Settings ← Developer settings ← "
                    "Personal access tokens ← Tokens (classic) ← Generate new token، وفعّل صلاحيتين: **repo** و**workflow**، ثم الصق قيمته. "
                    f"(المستودع الحالي: {repo})")
            return
        try:
            lr = gh_actions.last_run(tok, repo)
        except Exception as e:
            st.error(f"تعذّر قراءة حالة التشغيل ({type(e).__name__}). غالباً التوكن ناقص الصلاحية.")
            lr = None
        busy = bool(lr and lr["status"] in ("queued", "in_progress", "waiting", "requested"))
        if lr:
            ico = {"success": "✅ نجح", "failure": "❌ فشل", "cancelled": "⚪ أُلغي"}.get(lr["conclusion"] or "", "⏳ يعمل الآن" if busy else "—")
            when = keys_mod.parse(lr["created"])
            when_txt = when.astimezone(core.TZ).strftime("%Y-%m-%d %H:%M") if when else ""
            st.markdown(f"آخر تشغيل: **{ico}** — بدأ {when_txt} (القاهرة) · [تفاصيله على GitHub]({lr['url']})")
        c1, c2 = st.columns(2)
        if c1.button("▶️ شغّل التقرير الآن", type="primary", disabled=busy, key="run_rep", use_container_width=True):
            ok, msg = gh_actions.dispatch(tok, repo, branch)
            (st.success if ok else st.error)(msg)
        if c2.button("🔁 حدّث الحالة", key="run_status", use_container_width=True):
            st.rerun()
        if busy:
            st.caption("هناك تشغيل جارٍ، لذلك الزر معطّل حتى ينتهي. اضغط «حدّث الحالة» بين فترة وأخرى، ثم أعد تحميل الصفحة ليظهر التقرير الجديد.")


def render_daily():
    st.caption("نشرة تُولَّد تلقائياً كل صباح (نحو 6 بتوقيت القاهرة) لكل ملف، من عناوين عشرات المصادر العالمية والعربية، "
               "مع ما يخص مصر. ترتيب وتجميع للعناوين نفسها (بلا ذكاء اصطناعي)، وليس حكماً على صحة الأخبار.")
    if IS_ADMIN:
        render_run_report()
    if not (_GT and _GG):
        st.info("التقرير اليومي يحتاج التخزين الدائم (GITHUB_TOKEN وGIST_ID).")
        return
    if "reports" not in st.session_state or time.time() - st.session_state.get("reports_t", 0) > 600:
        try:
            st.session_state["reports"] = store.load_reports(_GT, _GG)
        except Exception as e:
            st.error(f"تعذّر تحميل التقارير ({type(e).__name__}).")
            return
        st.session_state["reports_t"] = time.time()
    rp = st.session_state["reports"]
    days = sorted((rp.get("archive") or {}).keys(), reverse=True)
    if not days:
        st.info("لا يوجد تقرير بعد. شغّل خطوة «التقرير اليومي» من GitHub Actions أول مرة (راجع README)، وبعدها يتجدد وحده كل صباح.")
        return
    day = st.selectbox("التاريخ", days, key="dr_day")
    rep = rp["archive"][day]
    gen = keys_mod.parse(rep.get("generated"))
    if gen:
        st.caption(f"آخر تحديث: {gen.astimezone(core.TZ).strftime('%Y-%m-%d %H:%M')} بتوقيت القاهرة")
    names = list(rep["files"].keys())
    pick_ = st.radio("الملف", (["📌 نشرة اليوم"] if rep.get("overview") else []) + names, horizontal=True, key="dr_file")
    if pick_.startswith("📌"):
        st.markdown(rep["overview"])
        return
    f = rep["files"][pick_]
    st.caption(f"عدد العناوين التي فُحصت: {f.get('total', '—')} · منها يخص مصر: {f.get('egypt', '—')}")
    if f.get("brief"):
        st.markdown(f["brief"])
    elif f.get("error"):
        st.warning("تعذّر توليد هذا الملف اليوم.")
    else:
        st.info("لا ملخص لهذا الملف (العناوين أدناه).")
    shown = f.get("items", [])
    if not shown:
        return
    only_eg = st.checkbox("🇪🇬 المتعلق بمصر فقط", value=False, key="dr_eg")
    with st.expander(f"📋 العناوين ({len(shown)})", expanded=not f.get("brief")):
        for a in shown:
            if only_eg and not a.get("egypt"):
                continue
            try:
                lnk = f"?view={quote(a['url'], safe='')}&seen={a.get('seendate', '')}&t={quote(a['title'][:200], safe='')}{auth_qs()}"
                eg_mark = "🇪🇬 " if a.get("egypt") else ""
                side_txt = intel.SIDES.get(a.get("side", ""), "")
                line = (f"- {eg_mark}**{a.get('title_ar', '')}** — {src_label(a.get('domain', ''))} · {a.get('ctype', '')} · "
                        f"{side_txt}  \n  [ترجم المقال]({lnk}) · [الأصل]({a.get('url', '')})")
                if a.get("ents"):
                    line += "  \n  🏷️ " + "، ".join(str(x) for x in a["ents"])
                if a.get("snip_ar"):
                    line += "  \n  > " + str(a["snip_ar"])
                st.markdown(line)
            except Exception as e:
                st.caption(f"⚠️ تعذّر عرض عنوان ({type(e).__name__}: {e})")


render_about()
if not IS_ADMIN and st.session_state["auth"].get("scope") == "reports":
    render_daily()  # اشتراك «تقرير فقط»: لا يرى بقية التطبيق
    show_footer()
    st.stop()

# ───────── حفظ نتائج البحث: تبقى (للمالك) حتى تبحث من جديد، حتى لو انقطع الاتصال او فتحت التطبيق لاحقا ─────────
RES_FILE = "marsad_results.json"


def _res_sig(d):
    its = d.get("items") or []
    return [len(its), its[0].get("url", "") if its else "", len(d.get("summaries") or {}), len(d.get("used") or [])]


if PERSIST and "_res_loaded" not in st.session_state:
    st.session_state["_res_loaded"] = True
    st.session_state["_res_loaded_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    st.session_state["_res_sigs"] = {}
    try:
        for _k, _v in (store.load_file(GH_TOKEN, GH_GIST, RES_FILE, {}) or {}).items():
            if isinstance(_v, dict) and f"res_{_k}" not in st.session_state:
                st.session_state[f"res_{_k}"] = _v
                st.session_state["_res_sigs"][_k] = _res_sig(_v)
    except Exception:
        pass


def _pack_res(v):
    out = {**v, "items": (v.get("items") or [])[:200], "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    return json.loads(json.dumps(out, ensure_ascii=False, default=str))


def reload_results():
    """يجيب آخر نتائج محفوظة (بما فيها نتيجة البحث الشامل اللي اشتغل على GitHub) ويستبدل بيها اللي في الصفحة"""
    got = store.load_file(GH_TOKEN, GH_GIST, RES_FILE, {}) or {}
    st.session_state["_res_sigs"] = {}
    n = 0
    for _k, _v in got.items():
        if isinstance(_v, dict) and "items" in _v:
            st.session_state[f"res_{_k}"] = _v
            st.session_state["_res_sigs"][_k] = _res_sig(_v)
            n += 1
    st.session_state["_res_loaded_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return n


def auto_pull_jobs():
    """لو بحث GitHub (الشامل أو تتبّع موضوع) خلص بعد ما فتحت الصفحة، بنحمّل نتيجته لوحدنا (بنبص كل دقيقتين بس)"""
    ss = st.session_state
    if not PERSIST or time.time() - ss.get("_jobs_chk", 0) < 120:
        return False
    ss["_jobs_chk"] = time.time()
    loaded = keys_mod.parse(ss.get("_res_loaded_at") or "")
    newest = None
    for fname in (SEARCH_STATUS, TOPIC_STATUS):
        try:
            stt = store.load_file(GH_TOKEN, GH_GIST, fname, {}) or {}
        except Exception:
            continue
        fin = keys_mod.parse(stt.get("finished") or "") if stt.get("state") == "done" else None
        if fin and (newest is None or fin > newest):
            newest = fin
    if newest and (loaded is None or newest > loaded):
        try:
            reload_results()
            ss["_res_loaded_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            ss["sa_status"] = store.load_file(GH_TOKEN, GH_GIST, SEARCH_STATUS, {}) or {}
            return True
        except Exception:
            return False
    return False


def save_results():
    """بيحفظ بس التابات اللي اتغيرت في الصفحة دي، وبيدمجها فوق المحفوظ (عشان ما يمسحش نتايج البحث الشامل بتاع GitHub)"""
    if not PERSIST:
        return
    sigs = st.session_state.setdefault("_res_sigs", {})
    cur = {k[4:]: v for k, v in st.session_state.items() if k.startswith("res_") and isinstance(v, dict) and "items" in v}
    changed = {k: v for k, v in cur.items() if sigs.get(k) != _res_sig(v)}
    if not changed:
        return
    try:
        remote = store.load_file(GH_TOKEN, GH_GIST, RES_FILE, {}) or {}
        remote.update({k: _pack_res(v) for k, v in changed.items()})
        store.save_file(GH_TOKEN, GH_GIST, RES_FILE, remote)
        for k, v in changed.items():
            st.session_state["_res_sigs"][k] = _res_sig(v)
    except Exception:
        pass


# ───────── التابات فوق، وكل تاب بحث يعرض فلاترَه داخله (القيم تُقرأ كمتغيرات عامة وقت تنفيذ التاب) ─────────
_now0 = datetime.now(timezone.utc)
query, match, joiner, ctype = "", core.MATCH_MODES[0], "AND", "الكل"
start_utc, end_utc, max_rec, verify, hide_nomatch = _now0 - timedelta(days=7), _now0, 30, True, False

home_box = st.container()
tab_dr, tab_wr, tab_ml, tab_il, tab_us, tab_uk, tab_rg, tab_eg, tab_br, tab_in, tab_gd, tab_dos, tab_sv, tab_ms = st.tabs(TAB_NAMES)


def use_filters(p, level="full"):
    """يرسم فلاتر هذا التاب (مفاتيحها تبدأ بـ p) ويضبط المتغيرات العامة التي تقرأها دوال البحث.
    level: full = كلمات + وقت + نوع، kw = كلمات + نوع فقط"""
    g = globals()
    g["query"] = st.text_input(
        "🔎 كلمات البحث", key=f"{p}_q",
        placeholder="مثال: وزير الخارجية المصري   —   او عدة مواضيع بفاصلة: اليمن، الحوثيين، مصر",
        help="كل ما بين فاصلتين (، او , او . بعد كلمة عربية) يُعامل كموضوع مستقل. بدون فاصلة تُعتبر الجملة كلها عبارة واحدة. للعرض بدون كلمات استخدم «اعرض كل ما نُشر».",
    )
    with st.expander("⚙️ فلاتر متقدمة (المطابقة، الوقت، نوع المحتوى)" if level == "full" else "⚙️ فلاتر (نوع المحتوى وربط العبارات)"):
        c1, c2 = st.columns(2)
        if level == "full":
            g["match"] = c1.radio("طريقة مطابقة كل عبارة", core.MATCH_MODES, key=f"{p}_match",
                                  help="Near: الكلمات متقاربة بأي ترتيب (الأنسب للجمل). Exact: العبارة بنصها المترجم حرفياً. AND: الكلمات موجودة في المقال في أي موضع.")
        jl = c2.radio("عند وجود أكثر من عبارة", ["كلها معاً (AND)", "أيٌّ منها (OR)"], key=f"{p}_join")
        g["joiner"] = "OR" if "OR" in jl else "AND"
        g["ctype"] = st.selectbox("نوع المحتوى", ["الكل", "خبر", "تحليل", "رأي"], key=f"{p}_ct0")
        if level == "full":
            mode = st.radio("النطاق الزمني", ["آخر ساعات", "آخر أيام", "تواريخ محددة"], horizontal=True, key=f"{p}_mode")
            now_utc = datetime.now(timezone.utc)
            if mode == "آخر ساعات":
                h = pick(st, "عدد الساعات", [1, 2, 3, 6, 12, 24, 36, 48, 72], 24, f"{p}_h")
                g["start_utc"], g["end_utc"] = now_utc - timedelta(hours=h), now_utc
            elif mode == "آخر أيام":
                d = pick(st, "عدد الأيام", [1, 2, 3, 5, 7, 10, 14, 21, 30, 45, 60, 90], 7, f"{p}_d")
                g["start_utc"], g["end_utc"] = now_utc - timedelta(days=d), now_utc
            else:
                today = datetime.now(core.TZ).date()
                rng = st.date_input("من – إلى", value=(today - timedelta(days=3), today), max_value=today, key=f"{p}_rng")
                if isinstance(rng, (list, tuple)) and len(rng) == 2:
                    s, e = rng
                else:
                    s = e = rng[0] if isinstance(rng, (list, tuple)) else rng
                g["start_utc"] = datetime(s.year, s.month, s.day, tzinfo=core.TZ).astimezone(timezone.utc)
                g["end_utc"] = datetime(e.year, e.month, e.day, 23, 59, 59, tzinfo=core.TZ).astimezone(timezone.utc)
            g["max_rec"] = pick(st, "عدد النتائج الأقصى", range(10, 110, 10), 30, f"{p}_max")
            g["verify"] = st.checkbox("🔍 افحص نص كل مقال واعرض جملة ذُكرت فيها كلمتك (أبطأ)", value=True, key=f"{p}_ver")
            g["hide_nomatch"] = st.checkbox("🚫 أخفِ المقالات التي لا تظهر كلمتك في نصها (موصى به)", value=True, key=f"{p}_hide",
                                            help="أخبار جوجل وGDELT أحياناً يرجّعوا مقالات الكلمة فيها بعيدة عن العنوان او مش موجودة. الفحص بيقرا نص المقال ويشيل اللي مفيهوش كلمتك.")
    if level == "full":
        st.caption("النتايج اللي تطلع بتفضل محفوظة، ومبتتمسحش غير لما تبحث من جديد.")


def pick_sources(key, groups, allow_custom=True):
    custom_lang = "en" if key == "rg" else ("ar" if key == "eg" else "both")
    """يعرض اختيار المصادر ويعيد قائمة (label, domains, lang)"""
    chosen = []
    extra_src = [(x["label"], x["domain"], x["lang"]) for x in S()["sources"] if x["group"] == key]
    if extra_src:
        groups = {**groups, "➕ مصادر أضفتَها": extra_src}
    for gname, entries in groups.items():
        labels = [e[0] for e in entries]
        sel = st.multiselect(gname, labels, default=labels, key=f"{key}_{gname}")
        chosen += [e for e in entries if e[0] in sel]
    if allow_custom:
        extra = st.text_input(
            "➕ مواقع إضافية (دومين واحد أو أكثر، بفاصلة)", placeholder="example.com, another.org", key=f"{key}_extra"
        )
        for dmn in re.split(r"[,\s]+", extra.strip().lower()):
            dmn = dmn.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
            if dmn and DOMAIN_RE.match(dmn):
                chosen.append((dmn, dmn, custom_lang))
    return chosen


def update_meta(data, sel):
    counts, ctry = {}, {}
    for a in data["items"]:
        n = source_name(a.get("domain", ""))
        counts[n] = counts.get(n, 0) + 1
        ctry[n] = source_country(a.get("domain", ""))
    data["counts"], data["ctry"] = counts, ctry
    data["silent"] = [lbl for lbl, _, _ in (sel or []) if lbl not in counts]


def do_search(key, jobs, sel=None, terms=None, pre=False, seed=None):
    terms = terms or [t.strip() for t in TERM_SPLIT.split(query) if t.strip()]
    if not terms:
        st.warning("اكتب كلمة بحث أولاً (في الخانة فوق في التاب).")
        return
    if not jobs:
        st.warning("اختر مصدراً واحداً على الأقل.")
        return
    # زر الإيقاف: الضغط عليه يقطع التنفيذ الجاري، وما ظهر حتى الآن محفوظ في session_state ويُعرض كاملاً
    st.button("⏹ إيقاف البحث والاكتفاء بالنتائج الظاهرة", key=f"stop_{key}")
    status_ph, live_ph = st.empty(), st.empty()
    status_ph.info("⏳ جارٍ التحضير والترجمة…")
    matchers = core.make_matchers_pre(jobs) if pre else core.make_matchers(terms, [j["code"] for j in jobs])
    hl = sorted({st_ for alts in matchers for stems in alts for st_ in stems}, key=len, reverse=True)
    data = {
        "items": [], "errors": [], "used": [], "summaries": {}, "counts": {}, "silent": [],
        "hidden": 0, "hl": hl, "partial": True,
    }
    st.session_state[f"res_{key}"] = data
    seed = seed or []

    def merged(items):
        have = {a["url"] for a in items}
        return sorted(items + [a for a in seed if a["url"] not in have], key=lambda a: a.get("seendate", ""), reverse=True)

    if seed:
        data["items"] = merged([])
        update_meta(data, sel)
        live_ph.markdown(live_html(data["items"], hl), unsafe_allow_html=True)
    for ev in core.search_iter(terms, joiner, match, jobs, start_utc, end_utc, max_rec, ctype):
        status_ph.info(f"⏳ {ev['msg']}")
        data["errors"], data["used"] = ev["errors"], ev["used"]
        if ev["items"] is not None:
            core.translate_titles([a for a in ev["items"] if "title_ar" not in a])
            data["items"] = merged(ev["items"])
            update_meta(data, sel)
            live_ph.markdown(live_html(data["items"], hl), unsafe_allow_html=True)
    if verify and data["items"]:
        items = data["items"]
        total = min(len(items), 80)
        for i in range(0, total, 8):
            status_ph.info(f"🔍 جارٍ فحص نصوص المقالات… ({i}/{total})")
            core.enrich_items(items[i:i + 8], matchers, joiner, limit=8)
            live_ph.markdown(live_html(items, hl), unsafe_allow_html=True)
    update_meta(data, sel)
    if hide_nomatch:
        raw = data["items"]
        data["items"] = [a for a in raw if not (a.get("fetched") and not a.get("found"))]
        data["hidden"] = len(raw) - len(data["items"])
    data["partial"] = False
    status_ph.success(f"✅ تم — {len(data['items'])} نتيجة")
    live_ph.empty()


def highlight(text, stems):
    out = html.escape(text)
    for st_ in stems:
        out = re.sub(f"({re.escape(html.escape(st_))})", r"<b>\1</b>", out, flags=re.I)
    return out


def card_html(a):
    url = a.get("url", "")
    link = (f"?view={quote(url, safe='')}&seen={a.get('seendate', '')}&t={quote(a.get('title', '')[:200], safe='')}"
            f"&wr={quote(a.get('writer', '') or '', safe='')}&o={quote(a.get('outlet', '') or '', safe='')}{auth_qs()}")
    orig = html.escape(a.get("title", ""))
    en = a.get("title_en", "")
    en_line = f"<div class='ltr' dir='ltr'>EN: {html.escape(en)}</div>" if en and en != a.get("title") else ""
    dom = a.get("domain", "")
    src = src_label(dom)
    ctag = a.get("ctype", "") + ("" if a.get("ctype_sure") else " (تقدير)")
    wline = (
        f"✍️ الكاتب: <b>{html.escape(a['writer'])}</b> — {html.escape(a.get('outlet', ''))} "
        + ("· 📌 من صفحة الكاتب" if a.get("wsrc") == "feed" else "· 🔎 بحث باسم الكاتب")
        + {True: " · ✅ الاسم مؤكَّد في توقيع المقال", False: " · ⚠️ الاسم لم يظهر في توقيع الصفحة"}.get(a.get("byline"), "")
        + "<br>"
        if a.get("writer")
        else ""
    )
    return (
        f"<div class='ar-title'>{html.escape(a.get('title_ar', ''))}</div>"
        f"<div class='ltr' dir='ltr'>{orig}</div>{en_line}"
        f"<div class='meta'>🕒 {fmt_seen(a.get('seendate', ''))} (القاهرة)<br>{wline}"
        f"🌐 المصدر: {src}"
        + (f" · 🧭 {html.escape(a['country_ar'])}" if a.get("side") and a.get("country_ar") else "")
        + f" · <span class='badge'>{html.escape(ctag)}</span></div>"
        f"<a class='btn' href='{html.escape(link)}' target='_blank' rel='noopener'>ترجم المقال</a>"
    )


_MLVL = {"محوري": "🟢 المقال عن كلمتك فعلاً", "ملحوظ": "🟡 ذُكرت بشكل ملحوظ", "عابر": "⚪ ذكر عابر غالباً (مش موضوع المقال)"}


def mention_line(a):
    if a.get("mcount") is None or not a.get("fetched"):
        return ""
    n, w = a["mcount"], max(1, a.get("words", 1))
    return f"🔢 كلمتك ذُكرت **{n}** مرة في مقال حوالي {w} كلمة — {_MLVL.get(a.get('mlevel'), '')}"


def snippet_html(a, hl):
    if not a.get("checked"):
        return ""
    if not a.get("fetched"):
        return "<div class='meta'>ℹ️ تعذّر فحص نص المقال (قد يكون خلف اشتراك أو يحجب الزحف).</div>"
    if a.get("found"):
        ml = mention_line(a).replace("**", "")
        out = f"<div class='meta'>✅ ذُكرت كلمتك في نص المقال:</div>" + (f"<div class='meta'>{html.escape(ml)}</div>" if ml else "") + f"<div>{html.escape(a.get('snip_ar', ''))}</div>"
        for sn in a.get("snips", []):
            out += f"<div class='ltr' dir='ltr'>{highlight(sn, hl)}</div>"
        return out
    return "<div class='meta'>⚠️ كلمتك لم تظهر في نص هذا المقال.</div>"


def live_html(items, hl):
    """عرض خفيف (بدون أزرار) أثناء البحث؛ تُرسم الأزرار الكاملة بعد الانتهاء أو الإيقاف"""
    return "".join(f"<div class='card'>{card_html(a)}{snippet_html(a, hl)}</div>" for a in items)


def render_results(key):
    data = st.session_state.get(f"res_{key}")
    if data is None:
        return
    if data.get("partial"):
        st.warning("⏹ توقّف البحث قبل اكتماله — هذه هي النتائج التي وُجدت حتى الآن (وقد لا تشمل فحص النصوص كاملاً).")
    for err in data["errors"]:
        st.warning(f"تنبيه من مصدر البيانات: {err}")
    with st.expander("الاستعلام المُرسل فعلياً (بعد الترجمة)"):
        for u in data["used"]:
            st.code(u, language=None)
    with st.expander("📊 توزيع النتائج على المصادر"):
        if data["counts"]:
            st.markdown("  \n".join(f"- **{n}** ({FLAGS.get(data.get('ctry', {}).get(n, ''), '🏳️')} {data.get('ctry', {}).get(n, '') or 'غير محددة'}): {c}" for n, c in sorted(data["counts"].items(), key=lambda x: -x[1])))
        if data["silent"]:
            st.markdown("**مصادر مختارة لم تُرجع نتائج:** " + "، ".join(data["silent"]))
            st.caption("غياب مصدر يعني أن GDELT لم يرصد له مقالات مطابقة في هذه الفترة، وليس أنه غير مدعوم في التطبيق.")
    if data.get("hidden"):
        st.caption(f"تم إخفاء {data['hidden']} مقالاً لم تظهر كلمتك في نصّه.")
    if not data["items"]:
        st.info("لا نتائج ضمن هذه الفلاتر. جرّب «كل الكلمات (AND)» أو وسّع النطاق الزمني أو زِد المصادر.")
    view_items = data["items"]
    if (view_items and not data.get("tr_retry") and time.time() > st.session_state.get("tr_down_until", 0)
            and untranslated(view_items[:20])):  # مرة واحدة لكل نتيجة: ترجم اللي فضل بلغته في أول صفحة
        data["tr_retry"] = True
        with st.spinner("جارٍ ترجمة العناوين اللي لسه مش مترجمة…"):
            if not fix_untranslated(view_items[:20], limit=20):
                st.session_state["tr_down_until"] = time.time() + 180  # خدمة الترجمة واقعة: ماتعطلش باقي التابات
    left_tr = len(untranslated(view_items))
    if left_tr:
        if st.button(f"🔁 ترجم العناوين اللي لسه مش مترجمة ({left_tr})", key=f"trfix_{key}"):
            with st.spinner("جارٍ الترجمة…"):
                n_fx = fix_untranslated(view_items, limit=80)
            st.caption(f"اتترجم {n_fx} عنوان." if n_fx else "خدمة الترجمة مش بترد دلوقتي. جرّب تاني بعد دقيقة.")
    if any(x.get("mcount") for x in view_items):
        if st.checkbox("🔢 رتّب حسب عدد مرات ذكر كلمتك (الأكثر ذكراً أولاً)", value=False, key=f"msort_{key}"):
            view_items = sorted(view_items, key=lambda x: (x.get("mcount") or 0), reverse=True)
    n_show = int(st.session_state.get(f"more_{key}", 20))
    total_items = len(view_items)
    for i, a in enumerate(view_items[:n_show]):
        url = a.get("url", "")
        with st.container(border=True):
            st.markdown(card_html(a), unsafe_allow_html=True)
            if a.get("checked"):
                if not a.get("fetched"):
                    st.caption("ℹ️ تعذّر فحص نص المقال (قد يكون خلف اشتراك أو يحجب الزحف).")
                elif a.get("found"):
                    st.success("✅ ذُكرت كلمتك في نص المقال:")
                    if mention_line(a):
                        st.markdown(mention_line(a))
                    st.markdown(a.get("snip_ar", ""))
                    for sn in a.get("snips", []):
                        st.markdown(f"<div class='ltr' dir='ltr'>{highlight(sn, data['hl'])}</div>", unsafe_allow_html=True)
                else:
                    st.warning("⚠️ كلمتك لم تظهر في نص هذا المقال — ربما تطابق GDELT مع الصفحة أو الروابط الجانبية.")
            if st.button("📝 ملخص المقال في نقاط", key=f"sum_{key}_{i}"):
                with st.spinner("جارٍ التلخيص…"):
                    data["summaries"][url] = core.summarize(url)
            if url in data["summaries"]:
                st.info(data["summaries"][url])
            listen_widget(a, f"{key}_{i}")
            if any(x.get("url") == url for x in S()["saved"]):
                st.caption("✅ محفوظ — تجده في تاب «المحفوظات»")
            else:
                st.button("💾 حفظ للقراءة لاحقاً", key=f"save_{key}_{i}", on_click=save_item, args=(a, key))
    if total_items > n_show:
        st.caption(f"معروض {n_show} من {total_items} نتيجة (بنعرضهم على دفعات عشان الصفحة تفضل خفيفة).")
        if st.button(f"⬇️ اعرض 20 كمان (باقي {total_items - n_show})", key=f"morebtn_{key}", use_container_width=True):
            st.session_state[f"more_{key}"] = n_show + 20
            st.rerun()


def all_entries(key, groups):
    out = []
    for entries in groups.values():
        out += list(entries)
    out += [(x["label"], x["domain"], x["lang"]) for x in S()["sources"] if x["group"] == key]
    return out


def author_variants(raw):
    """يعيد (الاسم بالإنجليزية، الاسم بالعبرية أو '') من أي لغة يكتبها المستخدم"""
    raw = raw.strip()
    if core._HAS_AR.search(raw):
        return tr(raw, "ar", "en"), tr(raw, "ar", "iw")
    if core._HEB.search(raw):
        return tr(raw, "iw", "en"), raw
    return raw, ""


def days_in_range():
    return max(1, int(-(-(end_utc - start_utc).total_seconds() // 86400)))


def add_gnews(key, sel, country, terms):
    """يضمّ نتائج أخبار Google (site:) إلى نتائج GDELT المعروضة"""
    data = st.session_state.get(f"res_{key}")
    if data is None or not terms:
        return
    with st.spinner("جارٍ ضمّ نتائج أخبار Google…"):
        items, notes = core.gnews_site_search(sel, days_in_range(), terms=terms, joiner=joiner, country=country)
    have = {a["url"] for a in data["items"]}
    new = [a for a in items if a["url"] not in have]
    if ctype != "الكل":
        new = [a for a in new if a.get("ctype") == ctype]
    if new:
        core.translate_titles(new)
        if verify:
            matchers = core.make_matchers(terms, core.codes_for(sel))
            core.enrich_items(new[:16], matchers, joiner, limit=16)
            if hide_nomatch:
                new = [a for a in new if not (a.get("fetched") and not a.get("found"))]
        data["items"] = sorted(data["items"] + new, key=lambda a: a.get("seendate", ""), reverse=True)
    data["used"] = data["used"] + notes
    update_meta(data, sel)


def gn_seed(sel, country, terms):
    """نتائج أخبار Google (سريعة) تُعرض فوراً بينما يعمل GDELT"""
    items, notes = core.gnews_site_search(sel, days_in_range(), terms=terms, joiner=joiner, country=country)
    if ctype != "الكل":
        items = [a for a in items if a.get("ctype") == ctype]
    core.translate_titles(items)
    return items, notes


def author_search(key, sel, country, author_raw, he_raw, only_confirmed, with_terms, terms):
    en, he = author_variants(author_raw)
    he = he_raw.strip() or he
    with st.spinner(f"جارٍ البحث عن مقالات «{author_raw}» في {len(sel)} مصدراً والتحقق من التوقيع…"):
        items, notes = core.gnews_site_search(
            sel, days_in_range(), terms=terms if with_terms else None, joiner=joiner,
            author=en, author_he=he or None, country=country,
        )
        if ctype != "الكل":
            items = [a for a in items if a.get("ctype") == ctype]
        core.translate_titles(items)
    hidden = 0
    if only_confirmed:
        kept = [a for a in items if a.get("byline") is not False]
        hidden, items = len(items) - len(kept), kept
    data = {
        "items": items, "errors": [] if items else ["لم يُعثر على مقالات بهذا الاسم — جرّب كتابته بالإنجليزية كما يظهر في توقيع المقال، أو وسّع النطاق الزمني."],
        "used": notes, "summaries": {}, "counts": {}, "silent": [], "hidden": hidden,
        "hl": sorted({t for t in core._name_tokens(en + " " + he)}, key=len, reverse=True),
    }
    st.session_state[f"res_{key}"] = data
    update_meta(data, sel)


def direct_title_hits(key, sel, terms):
    """بحث سريع بالكلمات في عناوين خلاصات المصادر المباشرة (RSS/الصفحة الرئيسية)، لأن GDELT وأخبار Google لا يغطيان كل المواقع"""
    d_items, d_notes = core.direct_headlines(sel, days_in_range())
    if ctype != "الكل":
        d_items = [a for a in d_items if a.get("ctype") == ctype]
    matchers = core.make_matchers(terms, core.codes_for(sel))
    hits = [a for a in d_items if core.find_mentions(a.get("title", ""), matchers, joiner)[0]]
    core.translate_titles(hits)
    data = st.session_state.get(f"res_{key}") or {"items": [], "errors": [], "used": [], "summaries": {}, "counts": {}, "silent": [], "hidden": 0, "hl": []}
    have = {x["url"].split("?")[0].rstrip("/") for x in data["items"]}
    new = [a for a in hits if a["url"].split("?")[0].rstrip("/") not in have]
    hl = sorted({st_ for alts in matchers for stems in alts for st_ in stems}, key=len, reverse=True)
    data["items"] = sorted(data["items"] + new, key=lambda a: a.get("seendate", ""), reverse=True)
    data["used"] = list(data.get("used", [])) + d_notes + [f"بحث العناوين المباشر ⟵ فُحص {len(d_items)} عنواناً من خلاصات المصادر ⟵ طابق {len(hits)} (جديد: {len(new)})"]
    data["hl"] = sorted(set(data.get("hl", [])) | set(hl), key=len, reverse=True)
    data["partial"] = False
    if new:
        data["errors"] = []  # وُجدت نتائج، فلا داعي لتحذير «لا نتائج»
    st.session_state[f"res_{key}"] = data
    update_meta(data, sel)
    if new:
        st.success(f"📡 لقيت {len(new)} نتيجة إضافية من خلاصة المصدر المباشرة (غير موجودة في GDELT ولا أخبار Google).")


def body_search(key, sel, terms, gn_country, n):
    """بحث في نص المقالات: يجمع أحدث عناوين المصادر (من مواقعها ثم أخبار Google) ويقرأ نص كل مقال ويُبقي ما ذُكرت فيه كلماتك"""
    bar = st.progress(0.0, text="جارٍ جمع أحدث مقالات المصادر…")
    d_items, d_notes = core.direct_headlines(sel, days_in_range())
    g_items, g_notes = core.gnews_site_search(sel, days_in_range(), terms=None, joiner=joiner, country=gn_country, max_items=200)
    pool = core.merge_items(d_items, g_items)
    if ctype != "الكل":
        pool = [a for a in pool if a.get("ctype") == ctype]
    pool = pool[:n]
    matchers = core.make_matchers(terms, core.codes_for(sel))
    hl = sorted({st_ for alts in matchers for stems in alts for st_ in stems}, key=len, reverse=True)
    for i in range(0, len(pool), 8):
        bar.progress(min(1.0, i / max(1, len(pool))), text=f"🔬 جارٍ قراءة نصوص المقالات… ({i}/{len(pool)})")
        core.enrich_items(pool[i:i + 8], matchers, joiner, limit=8)
    bar.empty()
    hits = [a for a in pool if a.get("found")]
    unread = sum(1 for a in pool if a.get("checked") and not a.get("fetched"))
    core.translate_titles(hits)
    note = f"بحث النص ⟵ قُرئ {len(pool) - unread} مقالاً من {len(pool)} ⟵ وُجدت الكلمات في {len(hits)}" + (f" ⟵ تعذّر فتح {unread} (حجب أو اشتراك)" if unread else "")
    data = st.session_state.get(f"res_{key}") or {"items": [], "errors": [], "used": [], "summaries": {}, "counts": {}, "silent": [], "hidden": 0, "hl": []}
    have = {x["url"] for x in data["items"]}
    data["items"] = sorted(data["items"] + [a for a in hits if a["url"] not in have], key=lambda a: a.get("seendate", ""), reverse=True)
    data["used"] = list(data.get("used", [])) + d_notes + [note]
    data["hl"] = sorted(set(data.get("hl", [])) | set(hl), key=len, reverse=True)
    data["partial"] = False
    st.session_state[f"res_{key}"] = data
    update_meta(data, sel)
    if hits:
        st.success(f"🔬 لقيت {len(hits)} مقال بيذكر كلمتك داخل النص (من {len(pool) - unread} مقال اتقرا).")
    else:
        st.info(f"🔬 قرأت {len(pool) - unread} مقال ومالقيتش كلمتك في نصوصهم." + (f" وتعذّر فتح {unread}." if unread else ""))


def curated_tab(key, groups, gd_country, gn_country, btn_label):
    sel = pick_sources(key, groups)
    pool = all_entries(key, groups)
    scope = st.radio("نطاق البحث", ["كل المصادر المختارة أعلاه", "🎯 داخل مصدر واحد فقط"], horizontal=True, key=f"{key}_scope")
    if scope.startswith("🎯"):
        names = [e[0] for e in pool]
        one = st.selectbox("اختر المصدر الذي تبحث بداخله", names, key=f"{key}_one")
        sel = [e for e in pool if e[0] == one][:1]
        st.caption("سيُبحث عن كلمتك داخل هذا الموقع وحده (عبر GDELT وأخبار Google معاً). المصادر التي أضفتَها من رابط تظهر أيضاً في القائمة.")
    qm = st.radio("طريقة البحث", ["🔎 بكلمة البحث (فوق في التاب)", "📰 اعرض كل ما نُشر (بدون كلمات)"], horizontal=True, key=f"{key}_qm")
    if qm.startswith("📰"):
        st.caption("هيقرا عناوين المصادر اللي اخترتها (أو المصدر الواحد) من مواقعها مباشرة (خلاصة RSS أو الصفحة الرئيسية)، ويكمّلها من أخبار Google، خلال الفترة المحددة فوق في التاب، من غير ما تكتب كلمة. "
                   f"عدد المصادر دلوقتي: {len(sel)}.")
        if st.button("📰 اعرض كل ما نُشر", type="primary", use_container_width=True, key=f"goall_{key}"):
            if not sel:
                st.warning("اختر مصدراً واحداً على الأقل.")
            else:
                with st.spinner(f"جارٍ قراءة عناوين {len(sel)} مصدراً من مواقعها مباشرة ثم تكميلها من أخبار Google…"):
                    d_items, d_notes = core.direct_headlines(sel, days_in_range())
                    g_items, g_notes = core.gnews_site_search(sel, days_in_range(), terms=None, joiner=joiner, country=gn_country, max_items=200)
                    items, notes = core.merge_items(d_items, g_items), d_notes + g_notes
                    if key in ("eg", "egt"):
                        items = egypt_only(items)
                    if ctype != "الكل":
                        items = [a for a in items if a.get("ctype") == ctype]
                    core.translate_titles(items)
                dd = {"items": items, "errors": [] if items else ["لم تُرجع أخبار Google عناوين لهذه المصادر في الفترة. وسّع الفترة أو غيّر المصادر."],
                      "used": notes, "summaries": {}, "counts": {}, "silent": [], "hidden": 0, "hl": []}
                st.session_state[f"res_{key}"] = dd
                update_meta(dd, sel)
        render_results(key)
        return
    c1_, c2_ = st.columns(2)
    author_raw = c1_.text_input(
        "✍️ اسم كاتب أو مراسل (اختياري)", key=f"{key}_author",
        placeholder="مثال: Barak Ravid أو باراك رافيد", help="عند كتابته يُبحث عن مقالات هذا الشخص داخل المصادر أعلاه. يمكن الكتابة بالعربية أو الإنجليزية أو العبرية.",
    )
    he_raw = c2_.text_input("اسمه بالعبرية (اختياري، لدقة أعلى)", key=f"{key}_author_he") if key == "il" else ""
    if author_raw.strip():
        o1, o2 = st.columns(2)
        with_terms = o1.checkbox("قيّد بكلمة البحث فوق في التاب أيضاً", value=False, key=f"{key}_awt")
        only_conf = o2.checkbox("أخفِ ما ثبت أن اسمه ليس في توقيع المقال", value=False, key=f"{key}_aoc")
    else:
        with_terms = only_conf = False
        use_gn = st.checkbox("➕ ضمّ نتائج أخبار Google إلى GDELT (يغطي ما يفوته GDELT)", value=True, key=f"{key}_gn")
        use_body = st.checkbox("🔬 ابحث كمان داخل نص المقالات (يقرا أحدث مقالات المصدر ويدوّر فيها؛ أبطأ بس بيلقط اللي كلمتك في وسطه)", value=False, key=f"{key}_body")
        body_n = pick(st, "عدد المقالات اللي هتتقرا", range(20, 130, 10), 60, f"{key}_bn") if use_body else 0
    if st.button(btn_label, type="primary", use_container_width=True, key=f"go_{key}"):
        terms = [t.strip() for t in TERM_SPLIT.split(query) if t.strip()]
        if author_raw.strip():
            if with_terms and not terms:
                st.warning("اكتب كلمة البحث فوق في التاب أو ألغِ التقييد بها.")
            elif not sel:
                st.warning("اختر مصدراً واحداً على الأقل.")
            else:
                author_search(key, sel, gn_country, author_raw, he_raw, only_conf, with_terms, terms)
        else:
            seed, gnotes = [], []
            if use_gn and sel and terms:
                with st.spinner("جارٍ جلب نتائج أخبار Google أولاً (سريعة)…"):
                    try:
                        seed, gnotes = gn_seed(sel, gn_country, terms)
                    except Exception as ex:
                        gnotes = [f"Google News تعذّر: {type(ex).__name__}"]
            do_search(key, core.jobs_for_sources(sel, gd_country), sel, seed=seed)
            if gnotes and st.session_state.get(f"res_{key}"):
                st.session_state[f"res_{key}"]["used"] += gnotes
            if use_body and sel and terms:
                body_search(key, sel, terms, gn_country, body_n)
            elif sel and terms:
                with st.spinner("جارٍ البحث كمان في عناوين خلاصات المصادر مباشرة…"):
                    try:
                        direct_title_hits(key, sel, terms)
                    except Exception as ex:
                        st.caption(f"تعذّر البحث المباشر في الخلاصات: {type(ex).__name__}")
            if use_body and not terms:
                st.warning("اكتب كلمة بحث فوق في التاب عشان البحث داخل النص.")
    render_results(key)


def style_tabs():
    """يلوّن التابات الرئيسية ويكبّرها بجافاسكربت (لأن الـCSS وحده مش بيمسك في كل نسخ Streamlit)"""
    import streamlit.components.v1 as components
    components.html("""
<script>
(function(){
  var COL=["#c0392b","#2563c9","#d9822b","#2a8f55","#8a5a00"];
  function paint(){
    try{
      var doc=window.parent.document;
      var lists=doc.querySelectorAll('[role="tablist"]');
      if(!lists.length) return;
      var tabs=lists[0].querySelectorAll('[role="tab"]');
      tabs.forEach(function(t,i){
        t.style.setProperty('border-radius','14px','important');
        t.style.setProperty('padding','10px 14px','important');
        t.style.setProperty('min-height','48px','important');
        t.style.setProperty('border','1px solid rgba(128,128,128,.4)','important');
        t.style.setProperty('margin','3px','important');
        if(i>=3&&i<=7){
          t.style.setProperty('background',COL[i-3],'important');
          t.style.setProperty('color','#fff','important');
          t.style.setProperty('font-weight','700','important');
          t.style.setProperty('min-height','54px','important');
          var sel=t.getAttribute('aria-selected')==='true';
          t.style.setProperty('box-shadow',sel?'0 0 0 3px rgba(255,255,255,.7),0 4px 14px rgba(0,0,0,.5)':'none','important');
          t.style.setProperty('opacity',sel?'1':'.85','important');
        } else {
          var s2=t.getAttribute('aria-selected')==='true';
          t.style.setProperty('background',s2?'rgba(255,75,75,.25)':'rgba(128,128,128,.12)','important');
        }
      });
      lists[0].style.setProperty('flex-wrap','wrap','important');
    }catch(e){}
  }
  paint(); setInterval(paint,700);
})();
</script>""", height=0)


HOME_SECTIONS = {"il": ("اسرائيلي", ISRAEL, "IL", "#c0392b"), "us": ("امريكي", USA, "US", "#2563c9"),
                 "uk": ("بريطاني", UK, "UK", "#d9822b"), "rg": ("تركيا وايران واثيوبيا", REGION, "US", "#2a8f55")}
HOME_GD = {"il": "IS", "us": "US", "uk": "UK", "rg": None}


def _ago(seen):
    try:
        dt = datetime.strptime(seen, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        m = int((datetime.now(timezone.utc) - dt).total_seconds() // 60)
        return f"منذ {m} دقيقة" if m < 60 else (f"منذ {m // 60} ساعة" if m < 2880 else f"منذ {m // 1440} يوم")
    except Exception:
        return ""


def home_search(q, keys, days, join, bar, use_gd=False):
    terms = [t.strip() for t in TERM_SPLIT.split(q) if t.strip()]
    got = {}
    for n, key in enumerate(keys):
        label, groups, gn_c, _col = HOME_SECTIONS[key]
        bar.progress(n / max(1, len(keys)), text=f"جارٍ البحث في القسم {label}…")
        sel = all_entries(key, groups)
        try:
            g_items, g_notes = core.gnews_site_search(sel, days, terms=terms, joiner=join, country=gn_c, max_items=80)
            d_items, d_notes = core.direct_headlines(sel, days)
            m = core.make_matchers(terms, core.codes_for(sel))
            d_hits = [a for a in d_items if core.find_mentions(a.get("title", ""), m, join)[0]]
            gd_items = []
            if use_gd:
                now_ = datetime.now(timezone.utc)
                last = None
                for ev in core.search_iter(terms, join, core.MATCH_MODES[0], core.jobs_for_sources(sel, HOME_GD[key]),
                                           now_ - timedelta(days=days), now_, 60, "الكل"):
                    if ev["items"] is not None:
                        last = ev["items"]
                gd_items = last or []
                g_notes = g_notes + [f"GDELT ⟵ {len(gd_items)} نتيجة"]
            items = core.merge_items(g_items, d_hits, gd_items)
            core.translate_titles(items)
        except Exception as ex:
            items, g_notes, d_notes = [], [f"تعذّر ({type(ex).__name__})"], []
        dd = {"items": items, "errors": [] if items else ["لا نتائج في الفترة دي. جرب فترة اطول او كلمات تانية."],
              "used": g_notes + d_notes, "summaries": {}, "counts": {}, "silent": [], "hidden": 0, "hl": []}
        update_meta(dd, sel)
        st.session_state[f"res_{key}"] = dd
        got[key] = items
    bar.progress(1.0, text="تم")
    merged = []
    for key, its in got.items():
        for a in its:
            merged.append({**a, "_sec": key})
    merged.sort(key=lambda a: a.get("seendate", ""), reverse=True)
    st.session_state["res_home"] = {"items": merged[:150], "q": q, "counts": {k: len(v) for k, v in got.items()},
                                    "days": days, "errors": [], "used": [], "summaries": {}}


def render_home():
    st.markdown("#### 🏠 الرئيسية")
    q = st.text_input("🔎 ابحث في كل الاقسام مرة واحدة", key="home_q", placeholder="مثال: سد النهضة، مصر السعودية، سيناء")
    c1, c2, c3 = st.columns([3, 2, 2])
    keys = c1.multiselect("الاقسام", list(HOME_SECTIONS), default=list(HOME_SECTIONS), format_func=lambda k: HOME_SECTIONS[k][0], key="home_secs")
    days = pick(c2, "الفترة (ايام)", [1, 2, 3, 5, 7, 14, 30], 3, "home_days")
    jl = c3.radio("لو اكتر من كلمة", ["اي منها", "كلها"], key="home_join")
    use_gd = st.checkbox("🌐 ضم GDELT (ادق وابطأ)", value=False, key="home_gd",
                         help="بيضيف نتايج GDELT لكل قسم. اتأخر من 3 لـ 8 دقايق. استخدمه للمواضيع المهمة.")
    if st.button("🔎 ابحث في كل الاقسام", type="primary", use_container_width=True, key="home_go"):
        if not q.strip() or not keys:
            st.warning("اكتب كلمة بحث واختار قسم واحد على الاقل.")
        else:
            bar = st.progress(0.0, text="بدأنا…")
            home_search(q, keys, days, "AND" if jl == "كلها" else "OR", bar, use_gd)
            bar.empty()
    h = st.session_state.get("res_home")
    now_utc0 = datetime.now(timezone.utc).strftime("%Y%m%d")
    all_items = [a for k in HOME_SECTIONS for a in (st.session_state.get(f"res_{k}") or {}).get("items", [])]
    today_n = sum(1 for a in all_items if str(a.get("seendate", "")).startswith(now_utc0))
    s1, s2, s3 = st.columns(3)
    n_src = len({d for g in (ISRAEL, USA, UK, REGION) for ents in g.values() for _, d, _ in ents})
    for col, num, lab in ((s1, today_n, "خبر النهارده (في نتايجك)"), (s2, len(all_items), "خبر محفوظ في الاقسام"), (s3, n_src, "مصدر مراقب")):
        col.markdown(f"<div class='hm-stat'><b>{num}</b>{lab}</div>", unsafe_allow_html=True)
    if not h:
        st.caption("اكتب كلمة وادوس «ابحث في كل الاقسام»، وهتلاقي هنا اخر الاخبار من كل الاقسام مرتبة بالاحدث، وتفاصيل كل قسم في التاب بتاعه تحت.")
        return
    cnt = " · ".join(f"{HOME_SECTIONS[k][0]}: {n}" for k, n in h.get("counts", {}).items())
    st.markdown(f"**نتيجة «{html.escape(h.get('q', ''))}»** — اخر {h.get('days')} يوم — {cnt}")
    st.caption("دي اخر الاخبار مجمعة. للتفاصيل (ملخص، ترجمة المقال، حفظ) افتح تاب القسم تحت.")
    for a in h["items"][:25]:
        sec = HOME_SECTIONS.get(a.get("_sec"), ("", None, "", "#555"))
        ttl = html.escape(a.get("title_ar") or a.get("title") or "")
        st.markdown(
            f"<div class='hm-row'><span class='hm-tag' style='background:{sec[3]}'>{sec[0]}</span>"
            f"<a href='{html.escape(a.get('url', ''))}' target='_blank'><b>{ttl}</b></a><br>"
            f"<span class='meta'>{src_label(a.get('domain', ''), False)} · {_ago(a.get('seendate', ''))}</span></div>",
            unsafe_allow_html=True)


with home_box:
    render_home()
style_tabs()
reader_scroll_tool()

with tab_il:
    use_filters("il", "full")
    st.caption("يُترجم بحثك إلى العبرية للمصادر العبرية، وإلى الإنجليزية للنسخ الإنجليزية.")
    curated_tab("il", ISRAEL, "IS", "IL", "ابحث في المصادر الإسرائيلية")

with tab_us:
    use_filters("us", "full")
    st.caption("مصادر أمريكية مهتمة بالشرق الأوسط (Axios وغيرها) ومراكز أبحاث.")
    curated_tab("us", USA, "US", "US", "ابحث في المصادر الأمريكية")

with tab_uk:
    use_filters("uk", "full")
    st.caption("صحف وقنوات بريطانية ومصادر متخصصة بالشرق الأوسط.")
    curated_tab("uk", UK, "UK", "UK", "ابحث في المصادر البريطانية")

with tab_rg:
    use_filters("rg", "full")
    st.caption("إثيوبيا (سد النهضة والقرن الأفريقي) وتركيا (شرق المتوسط) وإيران (اليمن والخليج). يُترجم بحثك تلقائياً إلى الأمهرية "
               "أو التركية أو الفارسية أو الإنجليزية بحسب لغة كل مصدر. اختر مصدراً واحداً أو عدة مصادر أو كلها، أو ابحث داخل مصدر واحد.")
    curated_tab("rg", REGION, None, "US", "ابحث في مصادر تركيا وإيران وإثيوبيا")

DAY_OPTS = {"آخر 24 ساعة": 1, "آخر 3 أيام": 3, "آخر 7 أيام": 7, "آخر 14 يوماً": 14, "آخر 30 يوماً": 30}


def browse_run(label, doms, lang, sec_name, url, kind):
    with st.spinner("جارٍ فتح القسم وترجمة العناوين…"):
        items, err = core.browse_section(url, doms)
        how = "فتح الصفحة مباشرة"
        if not items:
            pu = urlparse_path(url)
            items, notes = core.gnews_site_search([(label, pu, lang)], 14, country="IL" if lang == "he" else "US", max_items=40)
            how = "أخبار Google (الموقع يحجب الفتح المباشر)"
            err = err + " " + " | ".join(notes[:1])
        for a in items:
            ct, sure = core.classify(a["url"], a["title"])
            a["ctype"], a["ctype_sure"] = (kind, True) if kind else (ct, sure)
        core.translate_titles(items)
    data = {"items": items, "errors": [] if items else [f"تعذّر جلب القسم. {err}"], "used": [f"{url} ⟵ {how}: {len(items)}"],
            "summaries": {}, "counts": {}, "silent": [], "hidden": 0, "hl": []}
    st.session_state["res_br"] = data
    update_meta(data, None)


def urlparse_path(url):
    p = urlparse(url)
    host = p.netloc.replace("www.", "")
    path = p.path.rstrip("/")
    return host + path


with tab_br:
    use_filters("br", "kw")
    st.caption("افتح مصدراً وتصفّح أقسامه (الرأي، الأخبار…) بعناوين مترجمة للعربية؛ اضغط «ترجم المقال» على أي عنوان لقراءته مترجماً، أو احفظه. "
               "بعض المواقع المدفوعة تحجب الفتح المباشر فيُستعان بأخبار Google بدلاً منه.")
    pool_all = {}
    for grp_key, groups in (("il", ISRAEL), ("us", USA), ("uk", UK), ("rg", REGION)):
        for e in all_entries(grp_key, groups):
            pool_all[e[0]] = e
    bmode = st.radio("طريقة العرض", ["📂 أقسام موقع واحد", "📅 عناوين عدة مصادر خلال فترة"], horizontal=True, key="br_mode")
    if bmode.startswith("📅"):
        scope_all = st.radio("المصادر", ["كل المصادر", "أختار مصادر بعينها"], horizontal=True, key="br_scope")
        chosen_src = list(pool_all.keys())
        if scope_all.startswith("أختار"):
            chosen_src = st.multiselect("اختر المصادر", list(pool_all.keys()), default=["تايمز أوف إسرائيل", "جيروزاليم بوست", "Axios", "Al-Monitor", "The Guardian"], key="br_multi")
        bdays = st.selectbox("الفترة", list(DAY_OPTS.keys()), index=1, key="br_days")
        use_kw = st.checkbox("اقتصر على كلمة البحث فوق في التاب (اتركه فارغاً لعرض كل العناوين)", value=False, key="br_kw")
        if st.button("اعرض العناوين", type="primary", use_container_width=True, key="go_br2"):
            kw = [t.strip() for t in TERM_SPLIT.split(query) if t.strip()] if use_kw else None
            sel_b = [pool_all[n] for n in chosen_src]
            if not sel_b:
                st.warning("اختر مصدراً واحداً على الأقل.")
            else:
                with st.spinner(f"جارٍ جلب عناوين {len(sel_b)} مصدراً…"):
                    items, notes = core.gnews_site_search(sel_b, DAY_OPTS[bdays], terms=kw, joiner=joiner, country="US", max_items=150)
                    if ctype != "الكل":
                        items = [a for a in items if a.get("ctype") == ctype]
                    core.translate_titles(items)
                dd = {"items": items, "errors": [] if items else ["لم تُرجع أخبار Google عناوين لهذه المصادر في الفترة."],
                      "used": notes, "summaries": {}, "counts": {}, "silent": [], "hidden": 0, "hl": []}
                st.session_state["res_br"] = dd
                update_meta(dd, sel_b)
        render_results("br")
    else:
        br_pick = st.selectbox("المصدر", list(pool_all.keys()), key="br_src")
        lbl, dom_s, lang_s = pool_all[br_pick]
        dlist = [d for d in dom_s.split("|") if d]
        secs = []
        for d in dlist:
            secs += [(n, u, k) for n, u, k in SECTIONS.get(d, [])]
        secs.append(("الصفحة الرئيسية", f"https://{dlist[0]}/", None))
        secs.append(("🔗 رابط قسم آخر (أدخله بنفسك)", "", None))
        sec_names = [x[0] for x in secs]
        sec_pick = st.radio("القسم", sec_names, horizontal=True, key="br_sec")
        sname_, surl_, skind_ = secs[sec_names.index(sec_pick)]
        if not surl_:
            surl_ = st.text_input("رابط صفحة القسم (من موقع هذا المصدر)", key="br_url", placeholder=f"https://{dlist[0]}/opinion").strip()
        if st.button("افتح القسم وترجمه", type="primary", use_container_width=True, key="go_br"):
            if not surl_.startswith("http"):
                st.warning("أدخل رابطاً صحيحاً.")
            else:
                browse_run(lbl, dlist, "he" if lang_s == "he" else "en", sname_, surl_, skind_)
        render_results("br")

for _n, _d, _sd, _k, _f in intel.SOURCES:
    DOMAIN_LABELS.setdefault(_d, _n)


def intel_run(file_name, terms, days, picked, with_media, media_sel, ar_sel=()):
    meta = {}
    for n, d, sd, k, f in intel.SOURCES:
        if n in picked:
            meta[d] = (sd, k)
    sel = [(n, d, "en") for n, d, sd, k, f in intel.SOURCES if n in picked]
    media = []
    if with_media:
        for grp, groups, sd in (("il", ISRAEL, "il"), ("us", USA, "us"), ("uk", UK, "uk")):
            for e in all_entries(grp, groups):
                if e[0] in media_sel and e[2] in ("en", "both"):
                    media.append((e[0], e[1], "en"))
                    for dd in e[1].split("|"):
                        meta.setdefault(dd, (sd, "media"))
    for grp in ARABIC.values():
        for lbl_, dom_, _l in grp:
            if lbl_ in ar_sel:
                media.append((lbl_, dom_, "ar"))
                meta.setdefault(dom_, ("eg" if dom_ in EGYPT_ARABIC else "ar", "media"))
    allsel = sel + [m for m in media if m[1] not in {x[1] for x in sel}]
    with st.spinner("جارٍ البحث في المؤسسات والمصادر وتصنيف النتائج…"):
        items, notes = core.gnews_site_search(allsel, days, terms=terms or None, joiner="OR", country="US", max_items=200)
        for a in items:
            sd, k = next(((v[0], v[1]) for dd, v in meta.items() if core.domain_match(a["domain"], [dd])), ("osint", "think"))
            a["ctype"], a["ctype_sure"] = intel.classify_intel(a["title"], a["url"], k), False
            a["side"] = sd
            a["egypt"] = bool(intel.EGYPT_RE.search(a["title"]))
        core.translate_titles(items)
        for a in items:
            a["country_ar"] = intel.SIDES.get(a["side"], "") + (" · 🇪🇬 يخص مصر" if a["egypt"] else "")
    data = {"items": items, "errors": [] if items else ["لم تُرجع أخبار Google نتائج — وسّع الفترة أو غيّر الكلمات."],
            "used": notes, "summaries": {}, "counts": {}, "silent": [], "hidden": 0, "hl": [],
            "meta": {"file": file_name, "terms": terms or ["(كل ما نُشر)"], "days": days}}
    update_meta(data, None)
    st.session_state["res_in_all"] = data


def intel_matrix(view):
    """جدول ربط: المنظورات × أنواع المعلومة، وما يقوله كل منظور عن مصر"""
    rows = ["| المنظور | " + " | ".join(intel.INTEL_TYPES) + " | يخص مصر |", "|" + "---|" * (len(intel.INTEL_TYPES) + 2)]
    for code, name in intel.SIDES.items():
        sub = [a for a in view if a.get("side") == code]
        if not sub:
            continue
        cells = [str(sum(1 for a in sub if a.get("ctype") == t)) for t in intel.INTEL_TYPES]
        rows.append(f"| {name} | " + " | ".join(cells) + f" | {sum(1 for a in sub if a.get('egypt'))} |")
    st.markdown("\n".join(rows))
    eg_items = [a for a in view if a.get("egypt")]
    if eg_items:
        st.markdown("**🇪🇬 ما تقوله كل جهة عن مصر في هذا الملف:**")
        for code, name in intel.SIDES.items():
            sub = [a for a in eg_items if a.get("side") == code][:6]
            if sub:
                st.markdown(f"*{name}*")
                st.markdown("\n".join(f"- [{a.get('title_ar', '')}]({a['url']}) — {src_label(a['domain'])}" for a in sub))
    else:
        st.caption("لا توجد عناوين تخص مصر ضمن النتائج الحالية.")


with tab_in:
    st.caption("مكتب استخبارات مفتوح المصدر للشرق الأوسط والقرن الأفريقي: تصفّح مؤسسة واحدة أو عدة مؤسسات أو كلها، وأضف التحركات المصرية لأي ملف، "
               "وقارن المنظورات في جدول ربط، ثم اصنع تقريراً. التصنيف تقديري من العنوان والرابط ولا يُغني عن مراجعة المصدر.")
    all_files = list(intel.FILES.keys())
    if st.checkbox("اختر كل الملفات دفعة واحدة", value=False, key="in_allfiles"):
        fnames = all_files
    else:
        fnames = st.multiselect("الملفات (اختر ملفاً أو أكثر، وسيُبحث فيها كلها معاً)", all_files, default=all_files[:1], key="in_files")
    if not fnames:
        st.warning("اختر ملفاً واحداً على الأقل.")
        fnames = all_files[:1]
    fname = " + ".join(fnames)
    fmeta = {"terms": list(dict.fromkeys(t for f in fnames for t in intel.FILES[f]["terms"])),
             "egypt": list(dict.fromkeys(t for f in fnames for t in intel.FILES[f]["egypt"])),
             "axes": "؛ ".join(intel.FILES[f]["axes"] for f in fnames)}
    st.markdown(f"**المحاور:** {fmeta['axes']}")
    egm = st.radio("التحركات المصرية", ["الملف + التحركات المصرية", "الملف فقط", "التحركات المصرية فقط"], horizontal=True, key="in_eg")
    base_terms = fmeta["terms"] if egm != "التحركات المصرية فقط" else []
    eg_terms = fmeta["egypt"] if egm != "الملف فقط" else []
    qmode = st.radio("طريقة العرض", ["🔎 بحث بكلمات الملف", "📰 اعرض كل ما نُشر (بدون كلمات)"], horizontal=True, key="in_qmode")
    terms_txt = ""
    if qmode.startswith("🔎"):
        terms_txt = st.text_input("كلمات البحث (يمكن تعديلها؛ بالإنجليزية أو العربية، بفاصلة)", value="، ".join(base_terms + eg_terms),
                                  key=f"in_terms_{fname}_{egm}")
        if len(fnames) > 1:
            st.caption(f"سيُبحث في {len(fnames)} ملفات معاً بكلماتها مجتمعة؛ قصّ الكلمات إن كانت كثيرة.")
    names = [x[0] for x in intel.SOURCES]
    side_list = [v for k, v in intel.SIDES.items() if k != "uk"]
    side_codes = {v: k for k, v in intel.SIDES.items()}
    scope_i = st.radio("المؤسسات", ["مؤسسة واحدة", "عدة مؤسسات", "كل المؤسسات"], horizontal=True, key="in_scope", index=1)
    if scope_i == "مؤسسة واحدة":
        picked = [st.selectbox("المؤسسة", names, key="in_one")]
    elif scope_i == "كل المؤسسات":
        picked = names
    else:
        sides_pick = st.multiselect("المنظورات", side_list, default=side_list, key="in_sides")
        default_src = [x[0] for x in intel.SOURCES if intel.SIDES[x[2]] in sides_pick]
        picked = st.multiselect("المؤسسات", names, default=default_src, key=f"in_src_{'_'.join(sorted(side_codes[x] for x in sides_pick))}")
    days_i = st.selectbox("الفترة", ["آخر 7 أيام", "آخر 14 يوماً", "آخر 30 يوماً", "آخر 90 يوماً"], index=1, key="in_days")
    days_n = int(re.findall(r"\d+", days_i)[0])
    with_media = st.checkbox("➕ ضمّ تغطية الإعلام الإسرائيلي والأمريكي والبريطاني (للمقارنة)", value=True, key="in_media")
    media_sel = []
    if with_media:
        media_pool = [e[0] for g, gr in (("il", ISRAEL), ("us", USA), ("uk", UK)) for e in all_entries(g, gr) if e[2] in ("en", "both")]
        media_sel = st.multiselect("الصحف المضمومة", media_pool, default=[m for m in media_pool if m in (
            "تايمز أوف إسرائيل", "جيروزاليم بوست", "Axios", "Al-Monitor", "BBC", "The Guardian", "Reuters",
            "Foreign Policy", "Middle East Eye", "Ynetnews (إنجليزي)", "هآرتس (إنجليزي)")], key="in_media_sel")
    use_ar = st.checkbox("➕ ضمّ الصحافة العربية (مصرية وخليجية) للمقارنة", value=False, key="in_ar")
    ar_sel = []
    if use_ar:
        ar_pool = [e[0] for grp in ARABIC.values() for e in grp]
        ar_sel = st.multiselect("الصحف العربية", ar_pool, default=ar_pool[:5] + ["الشرق الأوسط", "العربية", "الجزيرة"], key="in_ar_sel")
        st.caption("تُترجم كلمات البحث تلقائياً إلى العربية. بحث اسم الكاتب لا يشمل الصحف العربية.")
    if st.button("🛰️ ابحث / اعرض", type="primary", use_container_width=True, key="go_in"):
        tl = [t.strip() for t in TERM_SPLIT.split(terms_txt) if t.strip()]
        if qmode.startswith("🔎") and not tl:
            st.warning("اكتب كلمات البحث أو اختر «اعرض كل ما نُشر».")
        elif not picked:
            st.warning("اختر مؤسسة واحدة على الأقل.")
        else:
            intel_run(fname, tl, days_n, picked, with_media, media_sel, ar_sel)

    allr = st.session_state.get("res_in_all")
    if allr:
        items = allr["items"]
        c1_, c2_ = st.columns(2)
        f_type = c1_.multiselect("نوع المعلومة", intel.INTEL_TYPES, default=intel.INTEL_TYPES, key="in_ftype")
        f_side = c2_.multiselect("المنظور", list(intel.SIDES.values()), default=list(intel.SIDES.values()), key="in_fside")
        only_eg = st.checkbox("🇪🇬 اعرض ما يخص مصر فقط", value=False, key="in_onlyeg")
        view = [a for a in items if a.get("ctype") in f_type and intel.SIDES.get(a.get("side"), "") in f_side and (a.get("egypt") or not only_eg)]
        st.caption(f"{len(view)} نتيجة من {len(items)}")
        with st.expander("🔗 خريطة الربط: المنظورات × أنواع المعلومة، وما يخص مصر"):
            intel_matrix(view)
        st.session_state["res_in"] = {**allr, "items": sorted(view, key=lambda a: a.get("seendate", ""), reverse=True)}
        m = allr["meta"]
        rep = intel.build_report(f"تقرير: {m['file']}", m["file"], m["terms"], m["days"], view)
        d1_, d2_ = st.columns(2)
        d1_.download_button("📄 نزّل التقرير التجميعي (Markdown)", rep, file_name="intel_report.md", mime="text/markdown", use_container_width=True)
        with d2_.popover("👁️ معاينة التقرير", use_container_width=True):
            st.markdown(rep)
        with st.expander("🧩 أسئلة الربط: كيف يتقاطع هذا الملف مع غيره؟"):
            st.markdown("لكل خبر أو تقرير مهم اسأل:\n" + "\n".join(f"- {q}" for q in intel.LINK_QUESTIONS))
            st.caption("تلميح: غيّر «الملف» أعلاه وأعد البحث بنفس الأطراف لترى كيف يتقاطع البحر الأحمر مع القرن الأفريقي والخليج.")
        render_results("in")

    with st.expander("🔎 العثور على التقارير المجانية (PDF ومستودعات الأبحاث)"):
        q_free = st.text_input("عنوان التقرير أو موضوعه", key="in_free", placeholder="Egypt military assessment")
        if q_free.strip():
            for lbl_, u_ in intel.search_links(q_free):
                st.markdown(f"- [{lbl_}]({u_})")
            st.caption("ابحث عن النسخ المنشورة بإذن أصحابها أو الملخصات العلنية، أو اطلب نسخة من المؤلف.")
        else:
            st.caption("اكتب موضوعاً لتظهر روابط البحث الجاهزة.")
    with st.expander("📚 دليل المؤسسات"):
        