# -*- coding: utf-8 -*-
"""مكتب الاستخبارات المفتوحة: سجل المصادر، الملفات المترابطة، التصنيف، وبناء التقرير"""
import re
from datetime import datetime

SIDES = {
    "us": "🇺🇸 منظور أمريكي",
    "il": "🇮🇱 منظور إسرائيلي",
    "eu": "🇪🇺 منظور أوروبي/دولي",
    "reg": "🌍 منظور إقليمي وأفريقي",
    "osint": "📡 بيانات ومصادر مفتوحة",
    "uk": "🇬🇧 منظور بريطاني",
}

# (الاسم، الدومين، المنظور، النوع: think/official/data، التخصص)
SOURCES = [
    ("ISW", "understandingwar.org", "us", "think", "تحركات الجيوش والميليشيات والخرائط العسكرية"),
    ("CSIS", "csis.org", "us", "think", "التسليح الأمريكي وإيران وإسرائيل والخليج"),
    ("RAND", "rand.org", "us", "think", "الدراسات الاستراتيجية والعسكرية العميقة"),
    ("CFR", "cfr.org", "us", "think", "السياسة الخارجية الأمريكية ومصالح واشنطن"),
    ("War on the Rocks", "warontherocks.com", "us", "think", "تحليلات عسكرية واستراتيجية"),
    ("Stimson Center", "stimson.org", "us", "think", "الأمن الإقليمي والانتشار العسكري"),
    ("Congressional Research Service", "crsreports.congress.gov", "us", "official", "تقارير رسمية للكونجرس: مساعدات مصر، السعودية، عقوبات إيران"),
    ("INSS", "inss.org.il", "il", "think", "الأمن القومي الإسرائيلي وإيران ومصر"),
    ("Alma Center", "israel-alma.org", "il", "think", "حزب الله وسوريا والحدود الشمالية"),
    ("JISS", "jiss.org.il", "il", "think", "الاستراتيجية العسكرية والسياسة الأمنية الإسرائيلية"),
    ("Begin-Sadat Center (BESA)", "besacenter.org", "il", "think", "الدراسات الأمنية والعسكرية"),
    ("IISS", "iiss.org", "eu", "think", "التوازن العسكري والقوات المسلحة"),
    ("SIPRI", "sipri.org", "eu", "data", "صفقات السلاح والإنفاق العسكري"),
    ("ECFR", "ecfr.eu", "eu", "think", "العلاقات الأوروبية والشرق الأوسط"),
    ("RUSI", "rusi.org", "eu", "think", "الدراسات الدفاعية والاستخباراتية"),
    ("Chatham House", "chathamhouse.org", "eu", "think", "السياسة الدولية والأمن الإقليمي"),
    ("International Crisis Group", "crisisgroup.org", "eu", "think", "النزاعات والتحركات السياسية"),
    ("Middle East Institute", "mei.edu", "reg", "think", "مصر والخليج وإيران وتركيا والقرن الأفريقي"),
    ("Arab Center Washington DC", "arabcenterdc.org", "reg", "think", "السياسات العربية والأمن الإقليمي"),
    ("Washington Institute", "washingtoninstitute.org", "us", "think", "إسرائيل وإيران والخليج"),
    ("Atlantic Council", "atlanticcouncil.org", "us", "think", "السياسة الأمريكية والتحالفات"),
    ("Africa Center for Strategic Studies", "africacenter.org", "reg", "think", "أفريقيا والقرن الأفريقي والأمن"),
    ("ISS Africa", "issafrica.org", "reg", "think", "السودان وإثيوبيا والصومال والبحر الأحمر"),
    ("Bellingcat", "bellingcat.com", "osint", "think", "تحقيقات مفتوحة وتحليل الصور"),
    ("ACLED", "acleddata.com", "osint", "data", "بيانات الاشتباكات والصراعات"),
    ("Liveuamap", "liveuamap.com", "osint", "data", "الأحداث الميدانية على الخرائط"),
    ("UN Digital Library", "digitallibrary.un.org", "osint", "official", "تقارير ووثائق الأمم المتحدة"),
    ("ReliefWeb", "reliefweb.int", "osint", "official", "تقارير الأزمات والنزاعات الإنسانية"),
]

# الملفات المترابطة الستة: (كلمات بحث افتراضية بالإنجليزية، الأطراف، أسئلة الربط)
FILES = {
    "شرق المتوسط": {
        "terms": ["Eastern Mediterranean", "Egypt Turkey Israel gas", "Cyprus Greece Turkey naval"],
        "axes": "مصر، إسرائيل، تركيا، قبرص، اليونان",
    },
    "البحر الأحمر": {
        "terms": ["Red Sea shipping", "Houthi Red Sea attacks", "Eritrea Djibouti Red Sea base"],
        "axes": "مصر، السعودية، اليمن، إسرائيل، إريتريا، جيبوتي",
    },
    "الخليج وإيران": {
        "terms": ["Iran Gulf security", "Saudi Arabia UAE Iran", "Iran nuclear military assessment"],
        "axes": "السعودية، الإمارات، إيران، قطر، أمريكا",
    },
    "المشرق العربي": {
        "terms": ["Hezbollah Lebanon Israel", "Syria Turkey Israel", "Syria military"],
        "axes": "سوريا، لبنان، حزب الله، إسرائيل، تركيا",
    },
    "القرن الأفريقي": {
        "terms": ["Horn of Africa", "Ethiopia Sea access Red Sea", "Somalia Egypt Turkey UAE", "Sudan war"],
        "axes": "إثيوبيا، الصومال، إريتريا، السودان، جيبوتي",
    },
    "القوى الكبرى": {
        "terms": ["Russia China Middle East", "US military posture Middle East"],
        "axes": "أمريكا، روسيا، الصين، أوروبا",
    },
}

LINK_QUESTIONS = [
    "علاقته بالتنافس التركي الإماراتي",
    "موقف إثيوبيا من الوصول إلى البحر",
    "تأثيره على المصالح المصرية",
    "موقف السعودية من أمن البحر الأحمر",
    "انعكاساته على المصالح الإسرائيلية",
    "الموقف الأمريكي والصيني والروسي",
]

INTEL_TYPES = ["معلومة مؤكدة", "تقرير من مصدر متخصص", "تسريب غير مؤكد", "تقدير استراتيجي", "خبر إعلامي"]

_LEAK = re.compile(r"reportedly|unconfirmed|leak|sources? (say|said|claim)|alleged|rumou?r|claims?\b|purported|unverified|according to (an )?unnamed", re.I)
_ASSESS = re.compile(r"assessment|outlook|forecast|scenario|implications|what to expect|estimate|prospects|strategy|strategic|balance|trajector|options for", re.I)


def classify_intel(title, url, kind):
    """تصنيف تقديري من العنوان/الرابط/نوع الجهة — ليس حكماً على صحة المعلومة"""
    t = f"{title} {url}"
    if _LEAK.search(title):
        return "تسريب غير مؤكد"
    if _ASSESS.search(t):
        return "تقدير استراتيجي"
    if kind == "media":
        return "خبر إعلامي"
    if kind in ("official", "data"):
        return "معلومة مؤكدة"
    return "تقرير من مصدر متخصص"


def search_links(term):
    """روابط بحث مجانية عن التقارير (تُفتح في تبويب جديد)"""
    from urllib.parse import quote_plus as q
    t = term.strip()
    return [
        ("Google — ملفات PDF", f"https://www.google.com/search?q={q(chr(34) + t + chr(34) + ' filetype:pdf')}"),
        ("Google — تقارير مراكز الأبحاث", f"https://www.google.com/search?q={q(t + ' (site:csis.org OR site:rand.org OR site:inss.org.il OR site:rusi.org OR site:mei.edu OR site:crisisgroup.org) filetype:pdf')}"),
        ("Google Scholar", f"https://scholar.google.com/scholar?q={q(t)}"),
        ("SSRN", f"https://papers.ssrn.com/sol3/results.cfm?txtKey_Words={q(t)}"),
        ("CORE", f"https://core.ac.uk/search?q={q(t)}"),
        ("OpenAlex", f"https://openalex.org/works?search={q(t)}"),
        ("Internet Archive", f"https://archive.org/search?query={q(t)}"),
        ("ReliefWeb", f"https://reliefweb.int/updates?search={q(t)}"),
        ("UN Digital Library", f"https://digitallibrary.un.org/search?ln=en&p={q(t)}"),
        ("SIPRI — قاعدة صفقات السلاح (CSV)", "https://armstransfers.sipri.org/ArmsTransfer/TransferRegister"),
    ]


def build_report(title, file_name, terms, days, items):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    out = [f"# {title}", f"*الملف: {file_name} — كلمات البحث: {', '.join(terms)} — آخر {days} يوماً — أُنشئ {now}*", "",
           "> التصنيف تقديري يعتمد على العنوان والرابط ونوع الجهة، وليس حكماً على صحة المعلومة؛ راجع المصدر الأصلي دائماً.", ""]
    for typ in INTEL_TYPES:
        sub = [a for a in items if a.get("ctype") == typ]
        if not sub:
            continue
        out += [f"## {typ} ({len(sub)})", ""]
        for a in sub:
            d = a.get("seendate", "")
            d = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) >= 8 else "-"
            out += [f"- **{a.get('title_ar', '')}**  ",
                    f"  {a.get('title', '')}  ",
                    f"  {a.get('country_ar', '')} · {a.get('domain', '')} · {d} · [الرابط الأصلي]({a.get('url', '')})"]
        out.append("")
    return "\n".join(out)
