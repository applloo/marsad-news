# -*- coding: utf-8 -*-
"""أدوات الملفات والخيوط وورشة تحليل المقالات والرأي في مرصد الأخبار."""
from __future__ import annotations
from datetime import datetime, timezone
from urllib.parse import urlparse
import re


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def domain_of(url):
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""

# توصيفات أولية قابلة للتعديل. لا تُعامل كتصنيف قطعي أو كحكم على صدقية التغطية.
# يُفضّل التفريق بين قسم الأخبار وقسم الرأي داخل المؤسسة الواحدة.
OUTLET_PROFILES = {
    "nytimes.com": {"name": "The New York Times", "country": "الولايات المتحدة", "ownership": "مؤسسة إعلامية خاصة", "orientation": "ليبرالي / وسط-يسار في صفحة الرأي غالباً؛ التغطية الإخبارية تُقيّم منفصلة", "type": "صحيفة عامة", "caveat": "لا تخلط بين خط صفحة الرأي ومعايير القسم الإخباري.", "confidence": "متوسط"},
    "washingtonpost.com": {"name": "The Washington Post", "country": "الولايات المتحدة", "ownership": "صحيفة خاصة", "orientation": "ليبرالي / وسط-يسار في صفحة الرأي غالباً", "type": "صحيفة عامة", "caveat": "الموقف التحريري قد يختلف بين الافتتاحيات والكتاب المستقلين والأخبار.", "confidence": "متوسط"},
    "wsj.com": {"name": "The Wall Street Journal", "country": "الولايات المتحدة", "ownership": "صحيفة خاصة", "orientation": "قسم الأخبار ذو تقاليد مهنية مستقلة عن صفحة الرأي؛ صفحة الرأي محافظة / يمين الوسط غالباً", "type": "صحيفة اقتصادية وسياسية", "caveat": "يجب فصل تقييم قسم الأخبار عن صفحة الرأي.", "confidence": "مرتفع"},
    "foxnews.com": {"name": "Fox News", "country": "الولايات المتحدة", "ownership": "شبكة إعلامية تجارية", "orientation": "محافظة / يمين في البرامج والرأي؛ تختلف النشرات الخبرية عن التعليق", "type": "شبكة تلفزيونية وموقع", "caveat": "افصل بين الخبر والرأي والبرامج الحوارية.", "confidence": "مرتفع"},
    "theguardian.com": {"name": "The Guardian", "country": "المملكة المتحدة", "ownership": "مملوكة لمؤسسة Scott Trust", "orientation": "يسار الوسط / تقدمية غالباً", "type": "صحيفة عامة", "caveat": "توجد آراء متعددة داخل الصحيفة ولا يمثل كاتب واحد المؤسسة كلها.", "confidence": "مرتفع"},
    "telegraph.co.uk": {"name": "The Telegraph", "country": "المملكة المتحدة", "ownership": "صحيفة تجارية", "orientation": "محافظة / يمين الوسط غالباً", "type": "صحيفة عامة", "caveat": "التوجه وصف عام للخط التحريري وليس حكماً على كل مادة.", "confidence": "مرتفع"},
    "ft.com": {"name": "Financial Times", "country": "المملكة المتحدة", "ownership": "صحيفة تجارية مملوكة لمجموعة إعلامية", "orientation": "ليبرالية اقتصادياً ومؤيدة عموماً للتجارة والأسواق؛ لا تختزل في محور يمين/يسار", "type": "صحيفة اقتصادية", "caveat": "حلّل زاوية الاقتصاد والسياسة الخارجية كلّاً على حدة.", "confidence": "متوسط"},
    "economist.com": {"name": "The Economist", "country": "المملكة المتحدة", "ownership": "مجلة أسبوعية خاصة", "orientation": "ليبرالية كلاسيكية، مؤيدة للأسواق والتجارة والانفتاح الدولي", "type": "مجلة تحليلية", "caveat": "توجهها الفكري لا يعني أن كل تحليل يتبنى النتيجة نفسها.", "confidence": "مرتفع"},
    "bbc.com": {"name": "BBC", "country": "المملكة المتحدة", "ownership": "هيئة بث خدمة عامة", "orientation": "لا يُنسب لها تصنيف حزبي يمين/يسار بشكل مبسط؛ تخضع لمتطلبات الحياد التحريري", "type": "هيئة بث عامة", "caveat": "قيّم صياغة المادة ومصادرها وسياقها بدلاً من افتراض انحياز مسبق.", "confidence": "مرتفع"},
    "reuters.com": {"name": "Reuters", "country": "دولي", "ownership": "وكالة أنباء تجارية", "orientation": "وكالة إخبارية وليست صحيفة رأي حزبية؛ لا يصح اختزالها في يمين/يسار", "type": "وكالة أنباء", "caveat": "راجع اختيار المصادر والعناوين والسياق، ولا تفترض أن غياب الرأي يعني غياب خيارات تحريرية.", "confidence": "مرتفع"},
    "apnews.com": {"name": "Associated Press", "country": "الولايات المتحدة", "ownership": "تعاونية إخبارية غير ربحية مملوكة لأعضائها", "orientation": "وكالة أنباء؛ لا تصنيف حزبي مبسط", "type": "وكالة أنباء", "caveat": "قيّم الخبر على أساس التوثيق والمصادر والسياق.", "confidence": "مرتفع"},
    "aljazeera.net": {"name": "الجزيرة", "country": "قطر", "ownership": "شبكة إعلامية ممولة من دولة قطر", "orientation": "تغطية عربية ودولية؛ تُدرس زواياها بحسب الملف والبرنامج والمادة", "type": "شبكة إخبارية", "caveat": "التمويل والسياق المؤسسي معلومتان مهمتان لكنهما لا تثبتان وحدهما صحة أو خطأ مادة بعينها.", "confidence": "متوسط"},
    "aljazeera.com": {"name": "Al Jazeera English", "country": "قطر", "ownership": "شبكة إعلامية ممولة من دولة قطر", "orientation": "تغطية دولية؛ يلزم فحص المادة ومصادرها بشكل مستقل", "type": "شبكة إخبارية", "caveat": "لا تستنتج دوافع كل صحفي من جهة التمويل وحدها.", "confidence": "متوسط"},
    "alarabiya.net": {"name": "العربية", "country": "السعودية", "ownership": "شبكة تجارية ضمن مجموعة إعلامية سعودية", "orientation": "تغطية إخبارية عربية؛ تُفحص الزاوية بحسب الموضوع والبرنامج", "type": "شبكة إخبارية", "caveat": "تجنب تحويل الارتباط المؤسسي إلى حكم مسبق على كل خبر.", "confidence": "متوسط"},
    "middleeasteye.net": {"name": "Middle East Eye", "country": "المملكة المتحدة", "ownership": "موقع إخباري مستقل معلن", "orientation": "يميل في تغطيته إلى نقد السياسات الغربية والإسرائيلية وبعض الحكومات الإقليمية؛ يلزم تقييم كل مادة", "type": "موقع إخباري", "caveat": "التوصيف العام لا يغني عن فحص الأدلة والمصادر في المقال.", "confidence": "متوسط"},
    "haaretz.com": {"name": "Haaretz", "country": "إسرائيل", "ownership": "صحيفة خاصة", "orientation": "ليبرالية / يسار الوسط إسرائيلياً في الرأي والافتتاحيات غالباً", "type": "صحيفة إسرائيلية", "caveat": "السياق السياسي الإسرائيلي مختلف عن تقسيمات اليمين واليسار في دول أخرى.", "confidence": "مرتفع"},
    "jpost.com": {"name": "The Jerusalem Post", "country": "إسرائيل", "ownership": "صحيفة تجارية", "orientation": "يميل الخط التحريري إلى الوسط/يمين الوسط الإسرائيلي في ملفات الأمن والسياسة", "type": "صحيفة إسرائيلية", "caveat": "افصل بين الخبر والرأي وبين كتاب الصحيفة والضيوف.", "confidence": "متوسط"},
}

PROMPT_TEMPLATES = {
    "تحليل مقال واحد": """أنت محلل إعلامي وباحث في السياسة الدولية. حلّل المقال المرفق وحده، ولا تضف وقائع غير موجودة فيه.

بيانات المقال:
العنوان: {title}
الكاتب: {author}
المنبر: {outlet} ({domain})
تاريخ النشر: {date}
رابط الأصل: {url}

وصف المنبر (مبدئي وقابل للمراجعة): {outlet_profile}
وصف الكاتب (المتاح فقط): {author_profile}

النص المتاح:
{text}

اكتب التحليل بالعربية، مع تقسيم واضح:
1) ملخص الأطروحة في 3 أسطر.
2) ما الوقائع التي يسوقها الكاتب؟ وما الادعاءات أو التوقعات أو الأحكام القيمية؟
3) ما الأدلة والمصادر التي يستند إليها؟ وما الذي لم يثبته؟
4) إطار الكاتب: كيف صاغ المشكلة؟ من الفاعل ومن الضحية ومن صاحب القرار؟ وما المفردات المحمّلة المستخدمة؟
5) الافتراضات الضمنية والثغرات والقفزات المنطقية.
6) مصلحة المنبر وخطه التحريري المحتمل: استخدم الوصف أعلاه كقرينة لا كدليل على نية الكاتب، ولا تنسب دوافع بلا مستند.
7) ما أقوى حجة مضادة للمقال؟ وما المعلومات التي قد تغيّر الحكم؟
8) أسئلة تحقق ومصادر مستقلة ينبغي الرجوع إليها.
9) خلاصة موزونة: ما الذي أقنعك؟ ما الذي لم يثبت؟ وما درجة الثقة ولماذا؟

افصل بين نص المقال واستنتاجك. إذا لم يتوفر النص الكامل فصرّح بذلك ولا تستنتج من العنوان وحده.""",
    "مقارنة مقالات رأي": """قارن مقالات الرأي والتحليل المرفقة حول القضية نفسها. لا تتعامل مع أي مقال باعتباره حقيقة نهائية.

المواد:
{articles}

المطلوب:
1) استخرج أطروحة كل كاتب في جملة واحدة.
2) اعمل جدولاً: الكاتب، المنبر، نوع المادة، الموقف، الأدلة، الافتراضات.
3) نقاط الاتفاق والاختلاف الحقيقي، لا مجرد اختلاف اللغة.
4) أين تتعارض الوقائع؟ وأين يتعارض تفسير الوقائع؟ وأين تختلف التوقعات أو المصالح؟
5) ما الأدلة المشتركة؟ وما الادعاءات المنفردة التي تحتاج تحققاً؟
6) حلّل أثر الخط التحريري والمنظور الجغرافي والمؤسسي لكل منبر دون اختزال الكاتب في تصنيف سياسي.
7) قدّم أقوى نسخة من حجة كل طرف (steelman) ثم اختبرها.
8) اذكر ما لا يمكن حسمه من المواد الحالية، وما المصادر الإضافية المطلوبة.
9) اختم بخريطة خلاف مختصرة واستنتاج مشروط بدرجة الثقة.

ممنوع اختراع اقتباسات أو معلومات عن التمويل أو التوجه السياسي. ميّز بوضوح بين الوقائع والتفسير والرأي والتوقع.""",
    "تحليل ملف مقالات متراكم": """أنت محرر ملف بحثي. حلّل مجموعة المقالات المجمعة داخل ملف واحد باعتبارها عينة من النقاش الإعلامي حول القضية، لا باعتبارها تمثيلاً كاملاً لكل الآراء.

اسم الملف: {case_name}
الفترة: {period}
المقالات:
{articles}

نفّذ:
1) خطاً زمنياً لتطور الحجج والمواقف.
2) خريطة مدارس التفسير والفاعلين والمصالح.
3) كيف تغيرت أطروحات الكتّاب من مقال لآخر؟
4) ما الروايات المتعارضة؟ صنّف التعارض: وقائع، أرقام، أسباب، نوايا، أو توقعات.
5) ما الذي تؤيده مصادر متعددة مستقلة، وما الذي تكرره شبكة مصادر واحدة؟
6) رصد الاقتباس الانتقائي والمعلومات الناقصة واللغة العاطفية.
7) أقوى تفسير بديل، وما الأدلة التي تدعمه أو تضعفه.
8) انعكاسات القضية على مصر والمنطقة عند وجود صلة موثقة.
9) خلاصة تنفيذية، أسئلة مفتوحة، ومصادر تحقق مقترحة.

لا تساوِ بين الآراء لمجرد وجودها؛ قيّم قوة الأدلة. لا تعتبر تكرار الادعاء في عدة مقالات تأكيداً مستقلاً إذا كانت تنقل عن مصدر واحد.""",
    "تحليل التناقضات بين المصادر": """افحص المواد التالية لاكتشاف التناقضات والتوافقات.

المواد:
{articles}

أنشئ مصفوفة تتضمن: الادعاء، المصدر الأول، المصدر الثاني، نوع التعارض، الدليل المتاح، ما ينقص للحسم.
فرّق بين تناقض مباشر، اختلاف توقيت، اختلاف تعريف أو مصطلح، اختلاف تقدير، واختلاف زاوية تحريرية.
لا تحاول التوفيق القسري بين روايتين. حدّد الادعاءات القابلة للتحقق، واقترح خطوات تحقق ومصادر أولية مستقلة. اختم بما يمكن قوله بثقة وما يجب إبقاؤه مفتوحاً.""",
    "ملف صحفي عن كاتب أو صحيفة": """أنشئ بطاقة تعريف بحثية للكاتب والمنبر اعتماداً على البيانات المرفقة والمصادر الموثوقة المتاحة.

الكاتب: {author}
المنبر: {outlet}
المقالات المتاحة: {articles}

اعرض:
- السيرة المهنية والمناصب ذات الصلة إن كانت موثقة.
- نوع الإنتاج: أخبار، تقارير، رأي، تحليل، أبحاث.
- الموضوعات المتكررة ومجالات التخصص.
- المواقف المعلنة في المقالات المرفقة مع أمثلة وروابط.
- تعريف المنبر وملكيته وتمويله المعلن وهيكله التحريري إذا توفرت مصادر.
- التوجه التحريري: صفه بأبعاد محددة (اقتصادي، اجتماعي، سياسة خارجية، قومي/دولي) وتجنب اختزاله في يمين/يسار إذا كان ذلك مضللاً.
- ما لا نعرفه، وما لا يصح استنتاجه.

لا تنسب انتماء حزبياً أو تمويلاً أو ولاءً دون دليل موثق. فرّق بين مواقف الكاتب الشخصية وخط المؤسسة.""",
}


def outlet_profile(url_or_domain, custom=None):
    domain = domain_of(url_or_domain) if "://" in str(url_or_domain) else str(url_or_domain or "").lower().replace("www.", "")
    if custom and domain in custom:
        return custom[domain]
    if domain in OUTLET_PROFILES:
        return OUTLET_PROFILES[domain]
    # match parent domains
    for d, p in OUTLET_PROFILES.items():
        if domain.endswith("." + d):
            return p
    return {"name": domain or "غير محدد", "country": "غير محدد", "ownership": "غير متاح", "orientation": "غير مصنف؛ يحتاج تحققاً", "type": "غير محدد", "caveat": "لا تستنتج التوجه من اسم الموقع أو جنسيته.", "confidence": "غير متاح"}


def format_article(a, custom_outlets=None, custom_writers=None):
    domain = a.get("domain") or domain_of(a.get("url", ""))
    outlet = a.get("outlet") or a.get("source") or domain or "غير محدد"
    op = outlet_profile(domain, custom_outlets)
    writer = a.get("writer") or a.get("author") or "غير محدد"
    wp = ""
    for _wid, _profile in (custom_writers or {}).items():
        if _profile.get("name") == writer or _wid == writer:
            wp = _profile.get("profile", "")
            break
    return (f"العنوان: {a.get('title_ar') or a.get('title') or 'غير متاح'}\n"
            f"الكاتب: {writer}\n"
            f"المنبر: {outlet}\n"
            f"بطاقة المنبر: {op.get('orientation', 'غير مصنف')} | الملكية: {op.get('ownership', 'غير متاحة')} | درجة التوثيق: {op.get('confidence', 'غير متاحة')}\n"
            f"ملاحظات الكاتب المحفوظة: {wp or 'لا توجد بطاقة موثقة محفوظة'}\n"
            f"التاريخ: {a.get('date') or a.get('seendate') or 'غير محدد'}\n"
            f"الرابط: {a.get('url') or 'غير متاح'}\n"
            f"النوع: {a.get('ctype') or a.get('kind') or 'غير محدد'}\n"
            f"النص/الملخص المتاح: {a.get('text') or a.get('summary') or a.get('snip_ar') or 'لا يوجد نص محفوظ'}")


def make_prompt(kind, articles, case_name="ملف بحثي", period="غير محددة", author="غير محدد", outlet="غير محدد", author_profile="غير متاح", custom_outlets=None, custom_writers=None):
    articles = list(articles or [])
    if kind == "تحليل مقال واحد":
        a = articles[0] if articles else {}
        domain = a.get("domain") or domain_of(a.get("url", ""))
        prof = outlet_profile(domain, custom_outlets)
        op = "؛ ".join(f"{k}: {v}" for k, v in prof.items())
        return PROMPT_TEMPLATES[kind].format(title=a.get("title_ar") or a.get("title") or "غير محدد",
            author=a.get("writer") or a.get("author") or author, outlet=a.get("outlet") or a.get("source") or outlet,
            domain=domain, date=a.get("date") or a.get("seendate") or "غير محدد", url=a.get("url") or "غير متاح",
            outlet_profile=op, author_profile=author_profile or "لا توجد سيرة موثقة مضافة؛ لا تفترض ميوله.",
            text=a.get("text") or a.get("full_text") or a.get("summary") or a.get("snip_ar") or "لا يوجد نص كامل محفوظ. اطلب من المستخدم لصق النص الكامل قبل التحليل.")
    joined = "\n\n---\n\n".join(format_article(a, custom_outlets, custom_writers) for a in articles)
    if kind == "مقارنة مقالات رأي":
        return PROMPT_TEMPLATES[kind].format(articles=joined)
    if kind == "تحليل ملف مقالات متراكم":
        dates = [str(a.get("date") or a.get("seendate") or "")[:10] for a in articles if a.get("date") or a.get("seendate")]
        period = period if period != "غير محددة" else (f"{min(dates)} إلى {max(dates)}" if dates else "غير محددة")
        return PROMPT_TEMPLATES[kind].format(case_name=case_name, period=period, articles=joined)
    if kind == "تحليل التناقضات بين المصادر":
        return PROMPT_TEMPLATES[kind].format(articles=joined)
    return PROMPT_TEMPLATES[kind].format(author=author, outlet=outlet, articles=joined)


def new_record(name, description="", tags=None, kind="ملف", articles=None):
    return {"id": f"{int(datetime.now(timezone.utc).timestamp() * 1000)}", "name": name.strip(), "description": description.strip(),
            "tags": list(tags or []), "kind": kind, "articles": list(articles or []), "created_at": now_iso(), "updated_at": now_iso()}
