# -*- coding: utf-8 -*-
"""الربط السياسي بين الأخبار والتقارير والتحليلات بلا ذكاء اصطناعي: خيوط (ملفات ربط) لكل منها أسماء وكلمات مشتركة
بعدة لغات. أي عنوان يحمل اسماً من الخيط يُضمّ إليه مهما كانت صحيفته ولغته، ثم تُحسب الأسماء المتكررة
والمنظورات التي تتناولها والتقاطعات مع الخيوط الأخرى. لإضافة خيط أو اسم عدّل THREADS فقط."""
import re
from collections import Counter

import intel

# كل خيط: الاسم، المحاور، والكيانات: (التسمية بالعربية، نمط regex بعدة لغات)
THREADS = {
    "سد النهضة والقرن الأفريقي": {
        "ents": [
            ("سد النهضة", r"\bGERD\b|Renaissance Dam|Grand Ethiopian|سد النهضة|Rönesans Barajı|سد رنسانس|ግድብ"),
            ("نهر النيل", r"\bNile\b|Nil Nehri|النيل|رود نیل|הנילוס"),
            ("إثيوبيا", r"Ethiopia|Ethiopian|Etiyopya|إثيوبيا|اثيوبيا|اتیوپی|אתיופיה|ኢትዮጵያ"),
            ("آبي أحمد", r"Abiy|آبي أحمد|ابي احمد|آبی احمد|አብይ"),
            ("الصومال", r"Somalia|Somali\b|Somaliland|الصومال|أرض الصومال|Somali|سومالی|סומליה"),
            ("إريتريا", r"Eritrea|إريتريا|اريتريا|Eritre|اریتره"),
            ("جيبوتي", r"Djibouti|جيبوتي|Cibuti|جیبوتی"),
            ("ميناء بربرة/عصب", r"Berbera|Assab|Asseb|بربرة|عصب"),
            ("الوصول للبحر", r"sea access|access to the (red )?sea|landlocked|منفذ بحري|الوصول إلى البحر"),
            ("الشباب/قوات أفريقية", r"Al-?Shabaab|AUSSOM|ATMIS|الشباب|بعثة الاتحاد الأفريقي"),
        ],
        "axes": "إثيوبيا، مياه النيل، الصومال، إريتريا، جيبوتي",
        "generic": {"الوصول للبحر"},
    },
    "أمن البحر الأحمر وباب المندب": {
        "ents": [
            ("البحر الأحمر", r"Red Sea|Kızıldeniz|البحر الأحمر|دریای سرخ|הים האדום"),
            ("باب المندب", r"Bab[ -]?(al|el)[ -]?Mandab|Mandeb|باب المندب|باب‌المندب|באב אל"),
            ("الحوثيون", r"Houthi|Huthi|Ansar Allah|الحوثي|أنصار الله|حوثی|החות"),
            ("قناة السويس", r"Suez Canal|Süveyş|قناة السويس|کانال سوئز|תעלת סואץ"),
            ("الملاحة والشحن", r"shipping|tanker|cargo ship|container ship|Aspides|ملاحة|ناقلة|شحن"),
            ("اليمن", r"Yemen|Yemeni|Aden|Hodeidah|Sanaa|Yemen|اليمن|عدن|الحديدة|صنعاء|یمن|תימן"),
            ("إيلات", r"Eilat|Elat|إيلات|ايلات|אילת"),
            ("قواعد أجنبية", r"naval base|military base|قاعدة (بحرية|عسكرية)|Djibouti base|task force"),
        ],
        "axes": "الملاحة، الحوثيون، قناة السويس، القواعد الأجنبية",
        "generic": {"الملاحة والشحن", "قواعد أجنبية"},
    },
    "غزة والتوتر الإقليمي": {
        "ents": [
            ("غزة", r"\bGaza\b|Gazze|غزة|غزه|غزه|עזה"),
            ("حماس", r"Hamas|حماس|حماس|חמאס"),
            ("رفح ومحور فيلادلفيا", r"Rafah|Philadelphi|Rafah|رفح|فيلادلفيا|רפיח|פילדלפי"),
            ("وقف إطلاق النار", r"ceasefire|cease-fire|truce|hostage|وقف إطلاق النار|هدنة|رهائن|آتش‌بس|הפסקת אש|חטופים"),
            ("حزب الله ولبنان", r"Hezbollah|Hizbullah|Lebanon|حزب الله|لبنان|حزب‌الله|לבנון|חיזבאללה"),
            ("إيران", r"\bIran\b|Iranian|Tehran|İran|إيران|ايران|طهران|ایران|איראן"),
            ("إسرائيل", r"Israel|Israeli|Netanyahu|Tel Aviv|İsrail|إسرائيل|اسرائيل|نتنياهو|اسرائیل|ישראל|נתניהו"),
            ("الوساطة", r"mediat|Qatar|Doha|وساطة|الوسيط|قطر|الدوحة|میانجی"),
            ("سيناء", r"Sinai|سيناء|سینا|סיני"),
        ],
        "axes": "إسرائيل، إيران، حماس، حزب الله، الوساطة المصرية",
        "generic": {"إسرائيل", "الوساطة", "سيناء"},
    },
    "السودان والحدود الجنوبية": {
        "ents": [
            ("السودان", r"\bSudan\b|Sudanese|Sudan|السودان|السوداني|سودان|סודן"),
            ("الجيش السوداني والبرهان", r"Burhan|SAF\b|Sudanese army|البرهان|الجيش السوداني"),
            ("الدعم السريع", r"\bRSF\b|Rapid Support|Hemedti|Dagalo|الدعم السريع|حميدتي|دقلو"),
            ("الفاشر ودارفور", r"Fasher|Darfur|الفاشر|دارفور|Kordofan|كردفان"),
            ("الخرطوم", r"Khartoum|الخرطوم"),
            ("لاجئون ونزوح", r"refugee|displaced|famine|لاجئ|نازح|مجاعة|نزوح"),
            ("حلايب وشلاتين", r"Halaib|Halayeb|Shalateen|حلايب|شلاتين"),
            ("الحدود مع مصر", r"Wadi Halfa|border with Egypt|Egypt.{0,20}border|وادي حلفا|الحدود (مع )?مصر|أرقين"),
            ("تشاد وليبيا والمرتزقة", r"\bChad\b|mercenar|تشاد|مرتزقة"),
        ],
        "axes": "السودان، الدعم السريع، الحدود، اللاجئون",
        "generic": {"لاجئون ونزوح", "تشاد وليبيا والمرتزقة"},
    },
    "ليبيا وشرق المتوسط والتسليح": {
        "ents": [
            ("ليبيا", r"Libya|Libyan|Libya|ليبيا|الليبي|لیبی|לוב"),
            ("حفتر والدبيبة", r"Haftar|Dbeibah|Dbeibeh|Dabaiba|حفتر|الدبيبة|دبيبه"),
            ("مذكرة تركيا-ليبيا", r"Turkey.{0,25}Libya|Libya.{0,25}Turk|maritime (deal|memorandum|accord)|Blue Homeland|Mavi Vatan|مذكرة|الوطن الأزرق|الاتفاق البحري"),
            ("المنطقة الاقتصادية الخالصة", r"\bEEZ\b|exclusive economic zone|MEB|المنطقة الاقتصادية|الحدود البحرية|ترسيم"),
            ("اليونان وقبرص", r"Greece|Greek|Cyprus|Cypriot|Yunanistan|Kıbrıs|اليونان|قبرص|یونان|قبرس|יוון|קפריסין"),
            ("شرق المتوسط والغاز", r"Eastern Mediterranean|East Med|gas field|Zohr|Leviathan|Doğu Akdeniz|شرق المتوسط|حقل|غاز|زهر|لفيتان"),
            ("الجيش المصري", r"Egyptian (army|navy|air force|military|armed forces)|الجيش المصري|القوات المسلحة المصرية|البحرية المصرية"),
            ("الجيش الإسرائيلي", r"Israeli (army|military|air force|navy)|IDF\b|الجيش الإسرائيلي|צה\"ל|צבא"),
            ("صفقات تسليح", r"arms (deal|sale|purchase|transfer)|weapons? (deal|sale)|procure|صفقة (سلاح|تسليح)|تسليح|SIPRI|FMF|military aid"),
            ("رافال وفرنسا", r"Rafale|Dassault|France.{0,20}Egypt|رافال|داسو"),
            ("الصين", r"\bChina\b|Chinese|J-10|J-?35|HQ-9|HQ-?\d+|KJ-500|Çin|الصين|صيني|چین|סין"),
            ("روسيا", r"Russia|Russian|Su-35|Su-?\d\d|S-400|Rusya|روسيا|روسي|سوخوي|روسیه|רוסיה"),
            ("أمريكا (إف-16 ومساعدات)", r"F-16|F-15|Apache|Abrams|Patriot|US military aid|المساعدات العسكرية|إف-16|أباتشي"),
            ("تسريب تسليحي", r"leak|reportedly|unconfirmed|تسريب|يُزعم|غير مؤكد"),
        ],
        "axes": "ليبيا، شرق المتوسط، تركيا، اليونان وقبرص، القوة العسكرية المصرية والإسرائيلية، صفقات السلاح",
        "generic": {"الصين", "روسيا", "أمريكا (إف-16 ومساعدات)", "تسريب تسليحي", "الجيش الإسرائيلي"},
    },
}
_COMPILED = {t: [(lbl, re.compile(rx, re.I)) for lbl, rx in d["ents"]] for t, d in THREADS.items()}


def match(text):
    """{اسم الخيط: [الكيانات المطابقة]} لنص واحد"""
    out = {}
    for t, ents in _COMPILED.items():
        hit = [lbl for lbl, rx in ents if rx.search(text)]
        if hit and any(h not in THREADS[t].get("generic", ()) for h in hit):  # الكيان العام وحده لا يكفي
            out[t] = hit
    return out


def item_text(a):
    return f"{a.get('title', '')} {a.get('title_ar', '')} {a.get('url', '')}"


def tag_pool(pool):
    """يضيف لكل عنوان a['threads'] = {خيط: كيانات}"""
    for a in pool:
        a["threads"] = match(item_text(a))
    return pool


def thread_items(pool, thread):
    return [a for a in pool if thread in a.get("threads", {})]


def _score(a, thread):
    n = len(a["threads"][thread])
    return (a.get("egypt", False), n, a.get("kind") in ("think", "official", "data"), a.get("seendate", ""))


def analyse(items, thread, pool):
    """إحصاءات الربط لخيط واحد: الأسماء المتكررة، المنظورات، الجسور، التقاطعات"""
    ents = Counter(e for a in items for e in a["threads"][thread])
    by_side = {}
    for a in items:
        by_side.setdefault(a.get("side", ""), []).append(a)
    side_info = []
    for sd, lst in by_side.items():
        c = Counter(e for a in lst for e in a["threads"][thread])
        side_info.append((sd, len(lst), [e for e, _ in c.most_common(3)]))
    side_info.sort(key=lambda x: -x[1])
    bridges = []
    for e, n in ents.most_common():
        sides = {a.get("side") for a in items if e in a["threads"][thread]}
        if len(sides) >= 2:
            bridges.append((e, len(sides), n))
    cross = Counter()
    for a in items:
        for other in a["threads"]:
            if other != thread:
                cross[other] += 1
    return {"ents": ents, "sides": side_info, "bridges": bridges, "cross": cross}


def brief(thread, items, info, top, snip_row, extra=None):
    """نشرة الخيط بلا ذكاء اصطناعي. snip_row(a) تنسّق سطر العنوان"""
    n_src = len({a.get("domain") for a in items})
    n_eg = sum(1 for a in items if a.get("egypt"))
    out = [f"## الصورة العامة", f"- رُصد {len(items)} عنواناً من {n_src} مصدراً، منها {n_eg} يذكر مصر صراحة.",
           "- الأسماء الأكثر ورودا: " + "، ".join(f"{e} ({n})" for e, n in info["ents"].most_common(6)), ""]
    if info["sides"]:
        out.append("## من يتناوله؟ (المنظورات)")
        for sd, n, es in info["sides"]:
            out.append(f"- **{intel.SIDES.get(sd, sd)}** ({n}): يركّز على " + "، ".join(es))
        out.append("")
    if info["bridges"]:
        out.append("## أسماء تجمع أكثر من منظور (نقاط التقاء)")
        out += [f"- **{e}**: ذُكر عند {s} منظورات ({n} عنواناً)" for e, s, n in info["bridges"][:5]]
        out.append("")
    if info["cross"]:
        out.append("## تقاطع مع ملفات أخرى")
        out += [f"- «{t}»: {n} عنواناً مشتركاً" for t, n in info["cross"].most_common(4)]
        out.append("")
    out += ["## أبرز العناوين", *[snip_row(a) for a in top], ""]
    extra = extra if extra is not None else items
    leaks = [a for a in extra if a.get("ctype") == "تسريب غير مؤكد"][:4]
    if leaks:
        out += ["## يُنقل أن… (غير مؤكد)", *[snip_row(a) for a in leaks], ""]
    rep = [a for a in extra if a.get("ctype") in ("تقرير من مصدر متخصص", "تقدير استراتيجي")][:5]
    if rep:
        out += ["## تقارير وتقديرات متخصصة", *[snip_row(a) for a in rep], ""]
    return "\n".join(out).strip()
