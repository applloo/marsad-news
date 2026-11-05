# -*- coding: utf-8 -*-
"""
رادار الأخبار العالمية — بحث بالعربية في مصادر إسرائيلية وأمريكية وبريطانية + بحث عام عبر GDELT
"""
import hashlib
import html
import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote, urlparse

import streamlit as st

import core
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
from sources import ARABIC, EGYPT_ARABIC, FLAGS, ISRAEL, REGION, SECTIONS, UK, USA, source_country
from writers import WRITERS

DOMAIN_LABELS = {}
for _g in (ISRAEL, USA, UK, REGION, ARABIC):
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


def tts_settings(prefix):
    c1, c2 = st.columns(2)
    label = c1.selectbox("الصوت", list(core.VOICES), key=f"{prefix}_voice")
    rate = c2.slider("السرعة", -30, 40, 0, step=5, format="%d%%", key=f"{prefix}_rate")
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


def reader_page():
    url = unquote(st.query_params.get("view", ""))
    seen = st.query_params.get("seen", "")
    orig_title = unquote(st.query_params.get("t", ""))

    st.markdown("## 📖 قراءة المقال مترجماً")
    if not url.startswith(("http://", "https://")):
        st.error("رابط غير صالح.")
        return
    st.markdown(f"🔗 **الرابط الأصلي:** [{html.escape(url)}]({url})")
    st.markdown(f"<div class='meta'>🌐 المصدر: {src_label(core._host(url))}</div>", unsafe_allow_html=True)

    embed_browser(url)

    with st.spinner("جارٍ جلب المقال وترجمته…"):
        art = core.fetch_article(url)
        if not art:
            st.warning("تعذّر استخراج نص المقال: " + core.FETCH_WHY.get(url, "جدار اشتراك أو حجب") +
                       ". (الصفحة قد تفتح في متصفحك عادي لكن الموقع يعامل التطبيق كزائر آلي.)")
            alt_block(orig_title or core.title_from_url(url), url)
            return
        title = art["title"] or orig_title
        title_ar = tr(title, "auto", "ar")
        body_ar = art["text"] if art.get("pre_ar") else core.translate_long(art["text"])
        body_ok = core.translated_ok(art["text"], body_ar)

    if not body_ok:
        st.warning("⚠️ الترجمة التلقائية للنص لم تكتمل الآن (غالباً جوجل مشغول). اضغط «أعد الترجمة» بعد لحظات، "
                   "أو استخدم زرار «مترجمة (ترجمة جوجل)» أعلى الصفحة.")
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
    if art["date"]:
        st.markdown(f"🕒 **تاريخ النشر (حسب بيانات المصدر):** {art['date']}")
    if seen:
        st.markdown(f"🛰️ **وقت رصد المقال (توقيت القاهرة):** {fmt_seen(seen)}")

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
    if trunc_alt:
        st.divider()
        alt_block(title, url)



import base64 as _b64

_LOGO_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 520 140" width="520" height="140" role="img" aria-label="Ehab Ibrahim"> <defs> <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0f2a47"/><stop offset="1" stop-color="#0a1626"/></linearGradient> <linearGradient id="sw" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#22d3ee" stop-opacity="0"/><stop offset="1" stop-color="#22d3ee" stop-opacity=".75"/></linearGradient> </defs> <rect x="6" y="6" width="128" height="128" rx="28" fill="url(#bg)"/> <g transform="translate(70 70)" fill="none" stroke="#22d3ee" stroke-width="2.2" opacity=".9"> <circle r="46"/><circle r="31"/><circle r="16"/> <path d="M-46 0H46M0 -46V46" stroke-opacity=".35"/> </g> <path d="M70 70 L70 24 A46 46 0 0 1 110 47 Z" fill="url(#sw)"/> <line x1="70" y1="70" x2="110" y2="47" stroke="#67e8f9" stroke-width="2.5" stroke-linecap="round"/> <circle cx="94" cy="52" r="4.5" fill="#fbbf24"/><circle cx="52" cy="88" r="3.2" fill="#f87171"/> <text x="156" y="68" font-family="Georgia, \'Times New Roman\', serif" font-size="46" font-weight="700" fill="#e2e8f0">Ehab Ibrahim</text> <rect x="158" y="80" width="64" height="4" rx="2" fill="#22d3ee"/> <text x="158" y="112" font-family="Tahoma, Arial, sans-serif" font-size="21" fill="#94a3b8" letter-spacing=".5">رادار الأخبار العالمية</text> </svg> '


def show_logo(width=300):
    """شعار المالك (Ehab Ibrahim) أعلى الصفحة"""
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
    n_src = len({d for g in (ISRAEL, USA, UK, REGION, ARABIC) for ents in g.values() for _, d, _ in ents})
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

st.caption("اكتب بالعربية كلمة أو عدة كلمات أو جملة مركّبة — تُترجم تلقائياً إلى العبرية والإنجليزية وتُترجم النتائج للعربية.")

query = st.text_input(
    "🔎 كلمات البحث",
    placeholder="مثال: وزير الخارجية المصري   —   أو عدة مواضيع بفاصلة: اليمن، الحوثيين، مصر السعودية",
    help="كل ما بين فاصلتين (، أو ,) يُعامل كموضوع/عبارة مستقلة. بدون فاصلة تُعتبر الجملة كلها عبارة واحدة.",
)
c1, c2 = st.columns(2)
match = c1.radio(
    "طريقة مطابقة كل عبارة",
    core.MATCH_MODES,
    help="Near: الكلمات متقاربة بأي ترتيب (الأنسب للجمل). Exact: العبارة بنصّها المترجم حرفياً. AND: الكلمات موجودة في المقال في أي موضع.",
)
joiner_label = c2.radio("عند وجود أكثر من عبارة (بفاصلة)", ["كلها معاً (AND)", "أيٌّ منها (OR)"])
joiner = "OR" if "OR" in joiner_label else "AND"

with st.expander("⚙️ الوقت ونوع المحتوى", expanded=True):
    ctype = st.selectbox("نوع المحتوى", ["الكل", "خبر", "تحليل", "رأي"])
    mode = st.radio("النطاق الزمني", ["آخر ساعات", "آخر أيام", "تواريخ محددة"], horizontal=True)
    now_utc = datetime.now(timezone.utc)
    if mode == "آخر ساعات":
        h = st.slider("عدد الساعات", 1, 72, 24)
        start_utc, end_utc = now_utc - timedelta(hours=h), now_utc
    elif mode == "آخر أيام":
        d = st.slider("عدد الأيام", 1, 90, 7)
        start_utc, end_utc = now_utc - timedelta(days=d), now_utc
    else:
        today = datetime.now(core.TZ).date()
        rng = st.date_input("من – إلى", value=(today - timedelta(days=3), today), max_value=today)
        if isinstance(rng, (list, tuple)) and len(rng) == 2:
            s, e = rng
        else:
            s = e = rng[0] if isinstance(rng, (list, tuple)) else rng
        start_utc = datetime(s.year, s.month, s.day, tzinfo=core.TZ).astimezone(timezone.utc)
        end_utc = datetime(e.year, e.month, e.day, 23, 59, 59, tzinfo=core.TZ).astimezone(timezone.utc)
    max_rec = st.slider("عدد النتائج الأقصى", 10, 100, 30, step=10)
    verify = st.checkbox("🔍 افحص نص كل مقال واعرض جملة ذُكرت فيها كلمتك (أبطأ)", value=True)
    hide_nomatch = st.checkbox("🚫 أخفِ المقالات التي لا تظهر كلمتك في نصها", value=False)

with st.expander("🎧 إعدادات القراءة الصوتية (للمترو والسماعات)"):
    tts_settings("tts")
    st.radio("ما الذي يُقرأ عند الضغط على «🎧 استمع»؟", TTS_MODES, key="tts_mode")
    st.caption("تُجهَّز القراءة بصوت عربي عصبي، ويمكن تنزيلها MP3 قبل نزول المترو للاستماع بلا إنترنت.")

def pick_sources(key, groups, allow_custom=True):
    custom_lang = "en" if key == "rg" else "both"
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
        st.warning("اكتب كلمة بحث أولاً (في الخانة أعلى الصفحة).")
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
        total = min(len(items), 40)
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
    link = f"?view={quote(url, safe='')}&seen={a.get('seendate', '')}&t={quote(a.get('title', '')[:200], safe='')}{auth_qs()}"
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
    if any(x.get("mcount") for x in view_items):
        if st.checkbox("🔢 رتّب حسب عدد مرات ذكر كلمتك (الأكثر ذكراً أولاً)", value=False, key=f"msort_{key}"):
            view_items = sorted(view_items, key=lambda x: (x.get("mcount") or 0), reverse=True)
    for i, a in enumerate(view_items):
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


tab_dr, tab_wr, tab_ml, tab_il, tab_us, tab_uk, tab_rg, tab_br, tab_in, tab_gd, tab_sv, tab_ms = st.tabs(TAB_NAMES)

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
    qm = st.radio("طريقة البحث", ["🔎 بكلمة البحث (أعلى الصفحة)", "📰 اعرض كل ما نُشر (بدون كلمات)"], horizontal=True, key=f"{key}_qm")
    if qm.startswith("📰"):
        st.caption("هيقرا عناوين المصادر اللي اخترتها (أو المصدر الواحد) من مواقعها مباشرة (خلاصة RSS أو الصفحة الرئيسية)، ويكمّلها من أخبار Google، خلال الفترة المحددة أعلى الصفحة، من غير ما تكتب كلمة. "
                   f"عدد المصادر دلوقتي: {len(sel)}.")
        if st.button("📰 اعرض كل ما نُشر", type="primary", use_container_width=True, key=f"goall_{key}"):
            if not sel:
                st.warning("اختر مصدراً واحداً على الأقل.")
            else:
                with st.spinner(f"جارٍ قراءة عناوين {len(sel)} مصدراً من مواقعها مباشرة ثم تكميلها من أخبار Google…"):
                    d_items, d_notes = core.direct_headlines(sel, days_in_range())
                    g_items, g_notes = core.gnews_site_search(sel, days_in_range(), terms=None, joiner=joiner, country=gn_country, max_items=200)
                    items, notes = core.merge_items(d_items, g_items), d_notes + g_notes
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
        with_terms = o1.checkbox("قيّد بكلمة البحث أعلى الصفحة أيضاً", value=False, key=f"{key}_awt")
        only_conf = o2.checkbox("أخفِ ما ثبت أن اسمه ليس في توقيع المقال", value=False, key=f"{key}_aoc")
    else:
        with_terms = only_conf = False
        use_gn = st.checkbox("➕ ضمّ نتائج أخبار Google إلى GDELT (يغطي ما يفوته GDELT)", value=True, key=f"{key}_gn")
        use_body = st.checkbox("🔬 ابحث كمان داخل نص المقالات (يقرا أحدث مقالات المصدر ويدوّر فيها؛ أبطأ بس بيلقط اللي كلمتك في وسطه)", value=False, key=f"{key}_body")
        body_n = st.slider("عدد المقالات اللي هتتقرا", 20, 120, 60, 10, key=f"{key}_bn") if use_body else 0
    if st.button(btn_label, type="primary", use_container_width=True, key=f"go_{key}"):
        terms = [t.strip() for t in TERM_SPLIT.split(query) if t.strip()]
        if author_raw.strip():
            if with_terms and not terms:
                st.warning("اكتب كلمة البحث أعلى الصفحة أو ألغِ التقييد بها.")
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
                st.warning("اكتب كلمة بحث أعلى الصفحة عشان البحث داخل النص.")
    render_results(key)


with tab_il:
    st.caption("يُترجم بحثك إلى العبرية للمصادر العبرية، وإلى الإنجليزية للنسخ الإنجليزية.")
    curated_tab("il", ISRAEL, "IS", "IL", "ابحث في المصادر الإسرائيلية")

with tab_us:
    st.caption("مصادر أمريكية مهتمة بالشرق الأوسط (Axios وغيرها) ومراكز أبحاث.")
    curated_tab("us", USA, "US", "US", "ابحث في المصادر الأمريكية")

with tab_uk:
    st.caption("صحف وقنوات بريطانية ومصادر متخصصة بالشرق الأوسط.")
    curated_tab("uk", UK, "UK", "UK", "ابحث في المصادر البريطانية")

with tab_rg:
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
        use_kw = st.checkbox("اقتصر على كلمة البحث أعلى الصفحة (اتركه فارغاً لعرض كل العناوين)", value=False, key="br_kw")
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
        for sd_code, sd_name in intel.SIDES.items():
            rows = [x for x in intel.SOURCES if x[2] == sd_code]
            if rows:
                st.markdown(f"**{sd_name}**")
                st.markdown("\n".join(f"- [{n}](https://{d}) — {f}" for n, d, _s, _k, f in rows))
        st.markdown("- [SIPRI — قاعدة صفقات السلاح (تصدير CSV)](https://armstransfers.sipri.org/ArmsTransfer/TransferRegister)")
        st.caption("الدومينات كتبتُها من معرفتي ولم أجرّبها كلها؛ إن لم يظهر مصدر في البحث فتحقق من دومينه.")

with tab_gd:
    st.caption("بحث واسع في كل ما يرصده GDELT حسب بلد المصدر، دون تحديد مواقع بعينها.")
    scope = st.selectbox("المصادر", list(core.GLOBAL_SCOPES.keys()), key="gd_scope")
    if st.button("ابحث (GDELT عام)", type="primary", use_container_width=True, key="go_gd"):
        do_search("gd", core.GLOBAL_SCOPES[scope])
    render_results("gd")

COUNTRIES = {"كل الدول": None, "الولايات المتحدة": "US", "بريطانيا": "UK", "إسرائيل": "IS", "البرازيل": "BR", "البرتغال": "PO", "فرنسا": "FR", "إسبانيا": "SP"}

with tab_ml:
    st.caption(
        "ترجم كلماتك إلى عدة لغات، **عدّل أي ترجمة بيدك أو اكتبها بنفسك**، ثم ابحث بها. "
        "كل لغة تُبحث في المقالات المنشورة بها. التركية والفارسية والأمهرية تعرض ما تقوله تلك الدول بلسانها؛ تغطية GDELT لها أضعف، فإن لم تظهر نتائج فوسّع الفترة."
    )
    src_txt = st.text_input(
        "العبارة بالعربية (اتركها فارغة لاستخدام خانة البحث أعلى الصفحة)", key="ml_src",
        help="افصل بين المواضيع بفاصلة.",
    )
    base_terms = [x.strip() for x in TERM_SPLIT.split(src_txt or query) if x.strip()]
    if st.button("🔤 ترجم إلى اللغات المختارة", use_container_width=True, key="ml_tr"):
        if not base_terms:
            st.warning("اكتب كلمة أو جملة بالعربية أولاً.")
        else:
            with st.spinner("جارٍ الترجمة…"):
                for code, _, _, _ in core.LANGS:
                    if st.session_state.get(f"ml_use_{code}", dict((c, d) for c, _, _, d in core.LANGS)[code]):
                        out, ok = core.translate_terms(base_terms, code)
                        st.session_state[f"ml_txt_{code}"] = "، ".join(out) if ok else ""
                        st.session_state[f"ml_fail_{code}"] = not ok
    chosen = []
    for code, name, gl, default in core.LANGS:
        c1_, c2_ = st.columns([1, 3])
        use = c1_.checkbox(name, value=default, key=f"ml_use_{code}")
        txt = c2_.text_input(f"الترجمة إلى {name}", key=f"ml_txt_{code}", label_visibility="collapsed",
                             placeholder=f"اكتب أو عدّل الترجمة ({name})")
        if st.session_state.get(f"ml_fail_{code}"):
            c2_.caption("⚠️ فشلت الترجمة الآلية — اكتبها بنفسك.")
        if use and txt.strip():
            chosen.append((code, gl, [x.strip() for x in TERM_SPLIT.split(txt) if x.strip()]))
    country_label = st.selectbox("حصر في مصادر بلد معيّن (اختياري)", list(COUNTRIES.keys()), key="ml_country")
    if st.button("ابحث بهذه الترجمات", type="primary", use_container_width=True, key="go_ml"):
        cc = COUNTRIES[country_label]
        jobs = [
            {"code": code, "extra": f"sourcelang:{gl}" + (f" sourcecountry:{cc}" if cc else ""), "terms": terms_}
            for code, gl, terms_ in chosen
        ]
        if not jobs:
            st.warning("اختر لغة واحدة على الأقل واكتب ترجمتها (اضغط «ترجم» أولاً).")
        else:
            do_search("ml", jobs, None, terms=base_terms or ["x"], pre=True)
    render_results("ml")



GROUP_LABELS = {"US": "🇺🇸 أمريكيون", "UK": "🇬🇧 بريطانيون", "IL": "🇮🇱 إسرائيليون", "SA": "🇸🇦 سعوديون (حسابات تويتر وغيرها)",
                "GCC": "🌍 خليجيون", "EG": "🇪🇬 مصريون", "AR": "🌍 عرب آخرون"}


def current_writers():
    return WRITERS + [writers_mod.W(**dict(sp, default=True)) for sp in S()["writers"]]


@st.cache_data(ttl=1800, show_spinner=False)
def cached_writers(ids, days, extra_json="[]"):
    allw = WRITERS + [writers_mod.W(**dict(sp, default=True)) for sp in json.loads(extra_json)]
    ws = [w for w in allw if w["id"] in ids]
    items, notes = core.fetch_writers(ws, days)
    return core.translate_titles(items), notes


with tab_wr:
    st.caption(
        "أحدث مقالات الرأي والتحليل لكتّاب ومراسلين مهتمين بالشرق الأوسط، بعناوين مترجمة، وزر «ترجم المقال» لقراءة النص مترجماً. "
        "النتائج تُحفظ نصف ساعة، فالفتح المتكرر سريع."
    )
    days_label = st.selectbox("الفترة", list(DAY_OPTS.keys()), index=2, key="wr_days")
    sel_ids = []
    all_w = current_writers()
    for gcode, gname in GROUP_LABELS.items():
        ws_ = [w for w in all_w if w["country"] == gcode]
        if not ws_:
            continue
        label_to_id = {f"{w['name_ar']} — {w['outlet']}": w["id"] for w in ws_}
        picked = st.multiselect(
            gname, list(label_to_id), default=[l for l, i in label_to_id.items() if next(w for w in ws_ if w["id"] == i)["default"]],
            key=f"wr_{gname}",
        )
        sel_ids += [label_to_id[p] for p in picked]
    use_ctype = st.checkbox("طبّق فلتر «نوع المحتوى» أعلاه", value=False, key="wr_ct")
    use_kw = st.checkbox("اقتصر على المقالات التي تذكر كلمات البحث أعلاه (يفحص النص — أبطأ)", value=False, key="wr_kw")
    if st.button("اعرض أحدث مقالاتهم", type="primary", use_container_width=True, key="go_wr"):
        if not sel_ids:
            st.warning("اختر كاتباً واحداً على الأقل.")
        else:
            with st.spinner("جارٍ جلب المقالات وترجمة العناوين…"):
                items, notes = cached_writers(
                    tuple(sorted(sel_ids)), DAY_OPTS[days_label], json.dumps(S()["writers"], ensure_ascii=False, sort_keys=True)
                )
                items = [dict(a) for a in items]
            kw_terms = [t_.strip() for t_ in TERM_SPLIT.split(query) if t_.strip()]
            if use_ctype and ctype != "الكل":
                items = [a for a in items if a.get("ctype") == ctype]
            matchers = []
            if use_kw and kw_terms and items:
                with st.spinner("جارٍ فحص نصوص المقالات…"):
                    matchers = core.make_matchers(kw_terms, ["en", "iw"])
                    core.enrich_items(items, matchers, joiner, limit=60)
                    items = [a for a in items if not (a.get("fetched") and not a.get("found"))]
            counts = {}
            for a in items:
                counts[a["writer"]] = counts.get(a["writer"], 0) + 1
            chosen = [w["name_ar"] for w in all_w if w["id"] in sel_ids]
            hl = sorted({s_ for alts in matchers for stems in alts for s_ in stems}, key=len, reverse=True)
            st.session_state["res_wr"] = {
                "items": items, "errors": [] if items else ["لم يُعثر على مقالات — راجع «الاستعلام المُرسل فعلياً» لمعرفة ما جُرّب."],
                "used": notes, "summaries": {}, "counts": counts,
                "silent": [n for n in chosen if n not in counts], "hidden": 0, "hl": hl,
            }
    st.caption("ℹ️ مواقع مثل نيويورك تايمز وواشنطن بوست وفاينانشال تايمز وهآرتس مدفوعة: يظهر عنوانها مترجماً، وقد يتعذّر عرض نصها الكامل.")
    render_results("wr")


def render_saved():
    s = S()
    if not PERSIST:
        st.warning(
            "💡 التخزين الدائم غير مفعّل: ما تحفظه هنا يضيع عند تحديث الصفحة أو إعادة تشغيل التطبيق. "
            "فعّله بخطوتين (الشرح في README: GITHUB_TOKEN و GIST_ID) أو نزّل نسخة احتياطية من الأسفل."
        )
    if st.session_state.get("store_err"):
        st.error(st.session_state["store_err"])
    c1, c2 = st.columns([2, 1])
    q = c1.text_input("🔎 ابحث داخل المحفوظات (عنوان، كاتب، موقع، ملاحظة)", key="sv_q")
    order = c2.selectbox("الترتيب", ["الأحدث حفظاً", "الأحدث نشراً", "الأقدم نشراً (خط زمني)"], key="sv_order")
    items = list(s["saved"])
    if q.strip():
        ql = q.strip().lower()
        items = [
            x for x in items
            if ql in " ".join(str(x.get(k, "")) for k in ("title_ar", "title", "writer", "domain", "note", "outlet")).lower()
        ]
    if order == "الأحدث نشراً":
        items.sort(key=lambda x: x.get("seendate", ""), reverse=True)
    elif order.startswith("الأقدم"):
        items.sort(key=lambda x: x.get("seendate", ""))
    with st.expander("🎙️ نشرة صوتية من المحفوظات (مثالية للمترو)"):
        labels = {f"{n + 1}. {x.get('title_ar', '')[:70]}": x for n, x in enumerate(s["saved"])}
        picked = st.multiselect("اختر المقالات (بالترتيب الذي تُقرأ به)", list(labels), default=list(labels)[:5], key="bl_pick")
        st.caption("تُقرأ حسب إعدادات «🎧 إعدادات القراءة الصوتية» أعلى الصفحة (الصوت والسرعة وما يُقرأ).")
        if st.button("🎙️ اصنع النشرة", key="bl_go", use_container_width=True):
            if not picked:
                st.warning("اختر مقالاً واحداً على الأقل.")
            else:
                ss = st.session_state
                prog = st.progress(0.0, text="جارٍ تجهيز النصوص…")
                parts = []
                for n, lab in enumerate(picked):
                    x = labels[lab]
                    txt, _ = speech_text(x["url"], x.get("title_ar", ""), ss.get("tts_mode", TTS_MODES[0]))
                    num = ORDINALS[n] if n < len(ORDINALS) else str(n + 1)
                    parts.append(f"الخبر {num}. من {_ar_name(source_name(x.get('domain', '')))}، {source_country(x.get('domain', ''))}. {txt}")
                    prog.progress((n + 1) / (len(picked) + 1), text=f"جُهّز {n + 1} من {len(picked)}")
                full = "نشرة رادار الأخبار. " + " ... ".join(parts) + " ... انتهت النشرة."
                prog.progress(0.95, text=f"جارٍ النطق (حوالي {len(full) / 13 / 60:.0f} دقيقة صوت)…")
                res = make_audio(full, core.VOICES[ss.get("tts_voice", list(core.VOICES)[0])], ss.get("tts_rate", 0))
                prog.empty()
                if res:
                    ss["bulletin"] = res
        if st.session_state.get("bulletin"):
            audio_block(st.session_state["bulletin"], "bulletin", "marsad_bulletin")
    st.caption(f"عدد المحفوظات: {len(s['saved'])}" + (f" — المعروض: {len(items)}" if q.strip() else ""))
    sums = st.session_state.setdefault("sv_sum", {})
    for it in items:
        h = hashlib.md5(it["url"].encode()).hexdigest()[:10]
        with st.container(border=True):
            st.markdown(card_html(it) + snippet_html(it, []), unsafe_allow_html=True)
            try:
                when = datetime.fromisoformat(it.get("saved_at", "")).astimezone(core.TZ).strftime("%Y-%m-%d %H:%M")
                st.caption(f"📌 حُفظ: {when}")
            except Exception:
                pass
            st.text_area(
                "📝 ملاحظتي (لربط الأحداث ببعضها)", value=it.get("note", ""), key=f"note_{h}", height=80,
                on_change=set_note, args=(it["url"], f"note_{h}"),
            )
            b1, b2 = st.columns(2)
            if b1.button("📝 ملخص سريع للمقال", key=f"svsum_{h}"):
                with st.spinner("جارٍ التلخيص…"):
                    sums[it["url"]] = core.summarize(it["url"])
            b2.button("🗑️ حذف من المحفوظات", key=f"del_{h}", on_click=delete_item, args=(it["url"],))
            listen_widget(it, f"sv_{h}")
            if it["url"] in sums:
                st.info(sums[it["url"]])
    with st.expander("💾 نسخة احتياطية (تنزيل / استيراد) — تشمل المحفوظات والمصادر والكتّاب المضافين"):
        st.download_button(
            "⬇️ تنزيل كل بياناتي (JSON)", data=json.dumps(s, ensure_ascii=False, indent=1),
            file_name="marsad_backup.json", mime="application/json",
        )
        up = st.file_uploader("⬆️ استيراد نسخة احتياطية", type=["json"], key="sv_up")
        if up is not None and st.session_state.get("sv_up_done") != (up.name, up.size):
            try:
                st.session_state["store"] = store.merge(s, json.loads(up.getvalue().decode("utf-8")))
                persist()
                st.session_state["sv_up_done"] = (up.name, up.size)
                st.rerun()
            except ValueError:
                st.error("الملف ليس نسخة احتياطية صالحة.")
        if PERSIST and st.button("🔄 تحديث من التخزين الدائم (لو حفظت من جهاز آخر)", key="sv_reload"):
            try:
                st.session_state["store"] = store.load(GH_TOKEN, GH_GIST)
                st.rerun()
            except Exception as e:
                st.error(f"تعذّر التحديث ({type(e).__name__})")


def render_manage():
    if st.session_state.get("flash"):
        st.success(st.session_state.pop("flash"))
    st.markdown("### 🔗 أضف مصدراً أو كاتباً من رابط")
    st.caption(
        "الصق رابط خبر، أو رابط تغريدة (تويتر/X)، أو منشور/صفحة فيسبوك تحوي رابط مقال، وسيستخرج التطبيق الموقع والكاتب لتضيفهما بضغطة. "
        "يمكنك أيضاً تعبئة الخانات يدوياً."
    )
    st.text_input("رابط الخبر أو التغريدة", key="ms_url", placeholder="https://...")
    st.button("🔍 حلّل الرابط", on_click=do_analyze, use_container_width=True, key="ms_an")
    an = st.session_state.get("analysis")
    if an:
        if an.get("error"):
            st.warning(an["error"])
        tw = an.get("tweet")
        if tw:
            st.info(f"🐦 تغريدة {tw.get('author', '')} (@{tw.get('handle', '')}): {tw.get('text', '')}")
        if an.get("domain"):
            st.markdown(f"**الموقع:** {an.get('site_name')} (`{an['domain']}`)  \n**العنوان:** {an.get('title', '')}")
        if an.get("authors"):
            st.selectbox("الكتّاب المكتشفون (اختر لتعبئة بياناته)", [a["raw"] for a in an["authors"]], key="mw_pick", on_change=pick_author)
    st.markdown("#### ➕ إضافة كمصدر إخباري")
    st.text_input("اسم المصدر", key="ms_name")
    st.text_input("الدومين (مثال: example.com)", key="ms_domain")
    st.radio("يُضاف إلى تاب", ["إسرائيلية", "أمريكية", "بريطانية", "تركيا/إيران/إثيوبيا"], key="ms_group", horizontal=True)
    st.radio("لغة المصدر", ["إنجليزي", "عبري", "كلاهما", "تركي", "فارسي", "أمهري", "عربي"], key="ms_lang", horizontal=True)
    st.button("➕ أضف المصدر", on_click=add_source, use_container_width=True, key="ms_add")
    st.markdown("#### ➕ إضافة ككاتب")
    st.caption("للكاتب العربي من تويتر: اكتب اسمه بالعربي + حسابه (@name) + اختار الجنسية «سعودي» او «خليجي»... ومش لازم دومين. "
               "للكاتب الاجنبي: اسمه بالانجليزي + دومين موقع النشر.")
    st.text_input("الاسم بالعربية (للعرض والبحث)", key="mw_ar")
    st.text_input("حساب تويتر/X (مثال: @alfihrest او رابط الحساب)", key="mw_tw", placeholder="@alfihrest")
    st.text_input("اسم الكاتب بالإنجليزية (للكاتب الاجنبي، او اختياري)", key="mw_en")
    st.text_input("المنفذ / الصحيفة (اختياري)", key="mw_outlet")
    st.text_input("مواقع نشره (اختياري للعربي — دومين او اكتر بفاصلة)", key="mw_sites")
    st.text_input("الاسم بالعبرية (اختياري — لمواقع عبرية)", key="mw_heb")
    st.radio("جنسية الكاتب / المنفذ", ["سعودي", "خليجي", "مصري", "عربي آخر", "أمريكي", "بريطاني", "إسرائيلي"], key="mw_country", horizontal=True)
    st.radio("نوع كتاباته", ["رأي", "تحليل", "خبر"], key="mw_kind", horizontal=True)
    st.button("➕ أضف الكاتب", on_click=add_writer, use_container_width=True, key="mw_add")
    if st.session_state.get("mw_msg"):
        (st.success if st.session_state["mw_msg"].startswith("✅") else st.warning)(st.session_state["mw_msg"])
    st.markdown("#### ما أضفتَه")
    if not S()["sources"] and not S()["writers"]:
        st.caption("لم تضف شيئاً بعد.")
    for x in S()["sources"]:
        r1, r2 = st.columns([4, 1])
        r1.markdown(f"🌐 **{x['label']}** — `{x['domain']}` — تاب: {x['group']} — لغة: {x['lang']}")
        r2.button("حذف", key=f"rs_{x['domain']}_{x['group']}", on_click=remove_source, args=(x["domain"], x["group"]))
    for w in S()["writers"]:
        r1, r2 = st.columns([4, 1])
        r1.markdown(f"✍️ **{w['name_ar']}** ({w['name_en']}) — {w['outlet']} — `{', '.join(w['sites'])}`" + (f" — 🐦 @{w['twitter']}" if w.get("twitter") else ""))
        r2.button("حذف", key=f"rw_{w['id']}", on_click=remove_writer, args=(w["id"],))
    if not PERSIST:
        st.caption("⚠️ بدون التخزين الدائم تضيع هذه الإضافات عند تحديث الصفحة؛ نزّل نسخة احتياطية من تاب «المحفوظات».")


def render_keys_admin():
    st.markdown("#### 🔑 شفرات التجربة (للمالك فقط)")
    if not GATE_ON:
        st.info("البوابة غير مفعّلة. لتفعيلها أضف في Secrets قيمة **ADMIN_KEY** (كلمة سر طويلة تخصّك) إلى جانب GITHUB_TOKEN وGIST_ID، "
                "ثم أعد تشغيل التطبيق. بعد التفعيل لن يفتح التطبيق إلا بشفرة، وتدخل أنت بكلمة ADMIN_KEY.")
        return
    def _host_url():
        try:
            h = st.context.headers.get("Host", "")
            return f"https://{h}" if h and not h.startswith(("localhost", "127.")) else ""
        except Exception:
            return ""

    base = (_sec("APP_URL") or _host_url() or st.session_state.get("app_url", "")).strip().rstrip("/")
    if not base:
        base = st.text_input("رابط التطبيق (اكتبه مرة واحدة)", placeholder="https://اسم-تطبيقك.streamlit.app", key="app_url").strip().rstrip("/")
    c1, c2 = st.columns(2)
    label = c1.text_input("اسم الشخص / الجهة (لتعرف لمن أعطيتها)", key="k_label")
    durs = {"6 ساعات": 6, "يوم": 24, "3 أيام": 72, "أسبوع": 168, "أسبوعان": 336, "شهر": 720, "مدة أخرى (بالساعات)": 0}
    dur = c2.selectbox("مدة التجربة (تبدأ من أول فتح)", list(durs), index=3, key="k_dur")
    scope_lbl = c1.selectbox("الصلاحية", ["كاملة (كل التطبيق)", "تقرير يومي فقط (اشتراك)"], key="k_scope")
    hours = durs[dur] or st.number_input("عدد الساعات", min_value=1, max_value=24 * 365, value=48, key="k_hours")
    if st.button("➕ ولّد شفرة جديدة", type="primary", key="k_new"):
        try:
            _, k = keys_mod.mutate(_GT, _GG, lambda ks: keys_mod.create(ks, label, hours, "reports" if scope_lbl.startswith("تقرير") else "full"))
            st.session_state["k_last"] = k["code"]
        except Exception as e:
            st.error(f"تعذّر الحفظ ({type(e).__name__}).")
    try:
        ks = store.load(_GT, _GG)["keys"]
    except Exception as e:
        st.error(f"تعذّر تحميل الشفرات ({type(e).__name__}).")
        return
    def link(c):
        return f"{base}/?k={c}" if base else f"?k={c}"
    if st.session_state.get("k_last"):
        st.success("تم التوليد. انسخ الرابط وأرسله:")
        st.code(link(st.session_state["k_last"]), language=None)
    icons = {"active": "🟢 فعّالة", "unused": "🟡 لم تُفتح", "expired": "⚪ انتهت", "revoked": "🔴 ملغاة", "unused_expired": "⚪ سقطت (لم تُفتح)"}
    for k in sorted(ks, key=lambda x: x.get("created", ""), reverse=True):
        stt = keys_mod.status(k)
        with st.container(border=True):
            seen = keys_mod.parse(k.get("last_seen"))
            seen_txt = seen.astimezone(core.TZ).strftime("%m-%d %H:%M") if seen else "—"
            st.markdown(f"**{k.get('label', '')}** — {icons.get(stt, stt)} — {keys_mod.human_left(k)}  \n"
                        f"{'📰 تقرير فقط' if k.get('scope') == 'reports' else 'صلاحية كاملة'} · فتحها {k.get('visits', 0)} مرة · آخر دخول: {seen_txt} (القاهرة) · المدة: {int(k.get('hours', 0))} ساعة")
            st.code(link(k["code"]), language=None)
            b1, b2 = st.columns(2)
            if stt in ("active", "unused") and b1.button("⛔ إلغاء الآن", key=f"krv_{k['code']}"):
                keys_mod.mutate(_GT, _GG, lambda ks_, c=k["code"]: keys_mod.find(ks_, c).update(revoked=True))
                st.rerun()
            if b2.button("🗑️ حذف من القائمة", key=f"kdl_{k['code']}"):
                keys_mod.mutate(_GT, _GG, lambda ks_, c=k["code"]: ks_.remove(keys_mod.find(ks_, c)))
                st.rerun()
    st.caption("ملاحظة: الضيف لا يرى محفوظاتك ولا مصادرك المضافة، وما يحفظه يزول بإغلاق الصفحة. الإلغاء يسري خلال ~10 دقائق على من هو داخل التطبيق.")


WATCH_SCOPES = {"il": "🇮🇱 اسرائيلي", "us": "🇺🇸 امريكي", "uk": "🇬🇧 بريطاني", "ar": "🇪🇬 عربي", "rg": "🌍 تركيا وايران واثيوبيا"}
WATCH_CFG, WATCH_OUT = "marsad_watch_cfg.json", "marsad_watch.json"


def _watch_load(force=False):
    if not (GH_TOKEN and GH_GIST):
        return None, {}
    if force or "watch_data" not in st.session_state or time.time() - st.session_state.get("watch_t", 0) > 300:
        try:
            st.session_state["watch_data"] = store.load_file(GH_TOKEN, GH_GIST, WATCH_OUT, None)
            st.session_state["watch_cfg"] = store.load_file(GH_TOKEN, GH_GIST, WATCH_CFG, {}) or {}
        except Exception as ex:
            st.error(f"تعذّر قراءة التقرير المحفوظ ({type(ex).__name__}).")
            return st.session_state.get("watch_data"), st.session_state.get("watch_cfg", {})
        st.session_state["watch_t"] = time.time()
    return st.session_state.get("watch_data"), st.session_state.get("watch_cfg", {})


@st.cache_data(ttl=86400, show_spinner=False)
def _tr_cached(p):
    r = tr(p, "auto", "ar")
    return r if core._HAS_AR.search(r) else p


def _watch_done_toggle(url):
    cfg = st.session_state.get("watch_cfg", {})
    done = set(cfg.get("done") or [])
    (done.discard if url in done else done.add)(url)
    cfg["done"] = sorted(done)
    st.session_state["watch_cfg"] = cfg
    try:
        store.save_file(GH_TOKEN, GH_GIST, WATCH_CFG, cfg)
    except Exception as ex:
        st.session_state["watch_err"] = f"تعذّر حفظ علامة «خلصته» ({type(ex).__name__})"


def render_watch():
    """تقرير مخصص بالكلمات والعلاقات: زر واحد يشغّله على GitHub Actions، والنتيجة محفوظة (للمالك)"""
    with st.expander("🎯 تقرير مخصص بكلمات ومواضيع معينة (زرار واحد، والنتيجة بتفضل محفوظة)", expanded=False):
        if not (GH_TOKEN and GH_GIST):
            st.info("محتاج التخزين الدائم (GITHUB_TOKEN وGIST_ID).")
            return
        data, cfg = _watch_load()
        tok, repo, branch = _sec("ACTIONS_TOKEN"), _sec("GH_REPO") or gh_actions.DEFAULT_REPO, _sec("GH_BRANCH") or "main"
        st.caption("اكتب مواضيعك، دوس زرار «شغّل»، وسيبه يشتغل على GitHub (ممكن ياخد من ربع ساعة لساعة، مش لازم تفضل فاتح التطبيق). "
                   "لما يخلص هتلاقي كل الاخبار هنا: ترجمة العنوان والمقال والملخص وعدد مرات ذكر الكلمات. وبتفضل محفوظة لحد ما تشغّل بحث جديد.")
        with st.expander("⚙️ المواضيع والاعدادات", expanded=data is None):
            txt = st.text_area("المواضيع (سطر لكل موضوع. + يعني الكلمتين مع بعض، | يعني بدائل، # تعليق)", height=280, key="watch_txt",
                               value=cfg.get("topics") or watch_mod.DEFAULT_TOPICS)
            c1, c2, c3 = st.columns(3)
            wdays = c1.select_slider("الفترة (ايام)", options=[1, 2, 3, 4], value=int(cfg.get("days") or 2), key="watch_days")
            per = c2.slider("اخبار لكل موضوع", 3, 20, int(cfg.get("per") or 10), key="watch_per")
            deep = c3.slider("اقرا وترجم اول كام خبر", 0, 10, int(cfg["deep"]) if cfg.get("deep") is not None else 5, key="watch_deep")
            keys_sel = st.multiselect("ادور في ايه؟", list(WATCH_SCOPES), default=[k for k in (cfg.get("scopes") or list(WATCH_SCOPES)) if k in WATCH_SCOPES],
                                      format_func=lambda k: WATCH_SCOPES[k], key="watch_scopes")
        if not tok:
            st.warning("زرار التشغيل محتاج ACTIONS_TOKEN في Secrets (نفس اللي عملناه للتقرير اليومي).")
        lr = None
        if tok:
            try:
                lr = gh_actions.last_run(tok, repo, "watch.yml")
            except Exception as ex:
                st.caption(f"تعذّر قراءة حالة التشغيل ({type(ex).__name__}). اتأكد انك رفعت ملف watch.yml.")
        busy = bool(lr and lr["status"] in ("queued", "in_progress", "waiting", "requested"))
        if lr:
            ico = {"success": "✅ خلص", "failure": "❌ فشل", "cancelled": "⚪ اتلغى"}.get(lr["conclusion"] or "", "⏳ شغال دلوقتي" if busy else "—")
            when = keys_mod.parse(lr["created"])
            wt = when.astimezone(core.TZ).strftime("%Y-%m-%d %H:%M") if when else ""
            upd = keys_mod.parse(lr.get("updated"))
            ut = upd.astimezone(core.TZ).strftime("%H:%M") if upd else ""
            st.markdown(f"آخر تشغيل: **{ico}** — بدأ {wt} (القاهرة)" + (f" · آخر نشاط {ut}" if busy else f" · انتهى {ut}") + f" · [افتح التفاصيل على GitHub]({lr['url']})")
        elif tok:
            st.markdown("آخر تشغيل: **لسه مفيش** (لو لسه دايس من ثواني دوس «حدّث» تحت)")
        if tok:
            st.markdown(f"[📂 صفحة التقرير المخصص على GitHub](https://github.com/{repo}/actions/workflows/watch.yml)")
        if st.session_state.get("watch_msg"):
            st.success(st.session_state["watch_msg"])
        b1, b2 = st.columns(2)
        if b1.button("▶️ شغّل البحث الكبير دلوقتي", type="primary", disabled=busy or not tok, key="watch_go", use_container_width=True):
            ts = watch_mod.parse_topics(txt)
            if not ts or not keys_sel:
                st.warning("اكتب موضوع واحد على الاقل واختار قسم واحد.")
            else:
                new_cfg = {**cfg, "topics": txt, "days": wdays, "per": per, "deep": deep, "scopes": keys_sel}
                try:
                    store.save_file(GH_TOKEN, GH_GIST, WATCH_CFG, new_cfg)
                    st.session_state["watch_cfg"] = new_cfg
                    ok, msg = gh_actions.dispatch(tok, repo, branch, "watch.yml")
                    if ok:
                        time.sleep(4)
                        st.session_state["watch_msg"] = f"✅ اتبعت الامر لـ GitHub الساعة {datetime.now(core.TZ).strftime('%H:%M')}. " + msg + " ولما يخلص دوس «حدّث»."
                        st.rerun()
                    st.error(msg)
                except Exception as ex:
                    st.error(f"مقدرتش ابدأ ({type(ex).__name__}).")
        if b2.button("🔁 حدّث (هات اخر نتيجة)", key="watch_refresh", use_container_width=True):
            st.session_state.pop("watch_msg", None)
            _watch_load(force=True)
            st.rerun()
        if st.session_state.pop("watch_err", None):
            st.warning("علامة «خلصته» ما اتحفظتش في المرة الاخيرة.")
        if not data:
            st.info("لسه مفيش نتيجة محفوظة. دوس «شغّل» وبعد ما يخلص دوس «حدّث». (اخر تحديث للنتيجة: لسه مفيش)")
            return
        done = set(cfg.get("done") or [])
        created = keys_mod.parse(data.get("created"))
        ct = created.astimezone(core.TZ).strftime("%Y-%m-%d %H:%M") if created else ""
        st.markdown(f"### النتيجة المحفوظة — اتعملت {ct} (القاهرة) · اخر {data.get('days')} يوم")
        if not data.get("done", True):
            st.warning("ده تقرير مبدئي: الروابط والعناوين جاهزة، والمقالات المترجمة والملخصات لسه بتتجهز. دوس «حدّث» بعد شوية.")
        st.caption(f"اتفحص {data.get('n_sources')} موقع، وقريت {data.get('n_pool')} عنوان مباشرة.")
        scope_names = data.get("scope_names") or []
        f1, f2, f3 = st.columns([2, 2, 1])
        scope_f = f1.selectbox("القسم", ["الكل"] + scope_names, key="watch_f_scope")
        topic_f = f2.selectbox("الموضوع", ["الكل"] + [t["title"] for t in data["topics"]], key="watch_f_topic")
        hide_done = f3.checkbox("اخفي اللي خلصته", value=False, key="watch_f_done")
        shown = 0
        for t in data["topics"]:
            if topic_f != "الكل" and t["title"] != topic_f:
                continue
            items = [a for a in t["items"] if (scope_f == "الكل" or scope_f in (a.get("scopes") or [])) and not (hide_done and a["url"] in done)]
            if not items and topic_f == "الكل":
                continue
            with st.expander(f"{t['title']} — {len(items)} خبر", expanded=topic_f != "الكل"):
                for i, a in enumerate(items):
                    shown += 1
                    ttl = (a.get("title_ar") or a.get("title") or "").replace("[", "(").replace("]", ")")
                    mark = "✅ " if a["url"] in done else ""
                    st.markdown(f"**{mark}[{ttl}]({a['url']})**  \n{source_name(a.get('domain', ''))} · {fmt_seen(a.get('seendate', ''))}")
                    if a.get("fetched") and a.get("mcount") is not None:
                        st.caption(f"الكلمات اتذكرت {a['mcount']} مرة في مقال حوالي {a.get('words', 0)} كلمة — مستوى: {a.get('mlevel', '')}" + (f" — اتجاب بـ: {a['via']}" if a.get("via") else ""))
                    for p in a.get("points_ar", []):
                        st.markdown(f"- {p if core._HAS_AR.search(p) else _tr_cached(p)}")
                    rl = f"?view={quote(a['url'], safe='')}&seen={a.get('seendate', '')}&t={quote(a.get('title', '')[:200], safe='')}{auth_qs()}"
                    st.markdown(f"[📖 افتح المقال مترجم]({rl})")
                    if a.get("full_ar"):
                        with st.expander("المقال مترجم (اول جزء)"):
                            st.write(a["full_ar"])
                    st.checkbox("خلصته", value=a["url"] in done, key=f"wd_{t['title']}_{i}_{abs(hash(a['url']))}",
                                on_change=_watch_done_toggle, args=(a["url"],))
        if not shown:
            st.caption("مفيش اخبار بالفلاتر دي.")
        if data.get("overlap"):
            with st.expander("🔗 اخبار تخص اكتر من موضوع"):
                for a, ts in data["overlap"]:
                    ttl = (a.get("title_ar") or a.get("title") or "").replace("[", "(").replace("]", ")")
                    st.markdown(f"- [{ttl}]({a['url']}) ⟵ {' | '.join(ts)}")
        with st.expander("ملاحظات فنية"):
            for n in (data.get("notes") or [])[:40]:
                st.caption(n)
        md = watch_mod.to_markdown(data, source_name, fmt_seen)
        st.download_button("⬇️ نزّل التقرير (ملف نصي)", md, file_name="custom_report.md", key="watch_dl")
        with st.expander("📋 نسخ التقرير كنص (تلصقه عند اي ذكاء اصطناعي)"):
            st.code(md, language=None)


with tab_dr:
    if IS_ADMIN:
        render_watch()
    render_daily()

with tab_sv:
    render_saved()

with tab_ms:
    if IS_ADMIN:
        render_manage()
        st.divider()
        render_keys_admin()
    else:
        st.info("إدارة المصادر والشفرات غير متاحة في النسخة التجريبية.")

show_footer()
