# -*- coding: utf-8 -*-
"""قائمة الكتّاب والمحللين. عدّلها بحرية: أضف كاتباً بسطر W(...) أو احذف سطراً."""

COUNTRY_EN = {"US": "United States", "UK": "United Kingdom", "IL": "Israel"}


def _or(items, fmt):
    items = list(items)
    if len(items) == 1:
        return fmt.format(items[0])
    return "(" + " OR ".join(fmt.format(i) for i in items) + ")"


def W(id, name_ar, name_en, outlet, country, kind, sites, feeds=(), aliases=(), heb=None, default=False):
    """kind: النوع الافتراضي (رأي/تحليل/خبر) — sites: مواقع النشر — feeds: خلاصات RSS لصفحة الكاتب إن وُجدت
    heb: (الاسم بالعبرية، [مواقع عبرية]) لبحث إضافي بالعبرية"""
    names = _or([name_en, *aliases], '"{}"')
    gn = [{"q": f"{names} {_or(sites, 'site:{}')}", "hl": "en-US", "gl": "US", "ceid": "US:en", "lang": "English"}]
    if heb:
        gn.append(
            {"q": f'"{heb[0]}" {_or(heb[1], "site:{}")}', "hl": "iw", "gl": "IL", "ceid": "IL:iw", "lang": "Hebrew"}
        )
    return {
        "id": id, "name_ar": name_ar, "name_en": name_en, "outlet": outlet, "country": country,
        "kind": kind, "feeds": list(feeds), "gn": gn, "default": default,
        "aliases": [name_en, *aliases],
    }


NYT = "https://www.nytimes.com/svc/collections/v1/publish/https://www.nytimes.com/by/{}/rss.xml"
GUARDIAN = "https://www.theguardian.com/profile/{}/rss"

WRITERS = [
    # ── أمريكيون ──
    W("friedman", "توماس فريدمان", "Thomas Friedman", "نيويورك تايمز", "US", "رأي", ["nytimes.com"],
      feeds=[NYT.format("thomas-l-friedman")], aliases=["Thomas L. Friedman"], default=True),
    W("ignatius", "ديفيد إغناطيوس", "David Ignatius", "واشنطن بوست", "US", "رأي", ["washingtonpost.com"], default=True),
    W("hubbard", "بن هابرد", "Ben Hubbard", "نيويورك تايمز", "US", "تحليل", ["nytimes.com"],
      feeds=[NYT.format("ben-hubbard")], default=True),
    W("cook", "ستيفن كوك", "Steven A. Cook", "مجلس العلاقات الخارجية / فورين بوليسي", "US", "رأي",
      ["cfr.org", "foreignpolicy.com", "bloomberg.com"], aliases=["Steven Cook"], default=True),
    W("wright", "روبن رايت", "Robin Wright", "ذا نيويوركر", "US", "رأي", ["newyorker.com"]),
    W("amiller", "آرون ديفيد ميلر", "Aaron David Miller", "كارنيجي", "US", "تحليل",
      ["carnegieendowment.org", "foreignpolicy.com", "cnn.com"]),
    W("ibish", "حسين إبيش", "Hussein Ibish", "معهد دول الخليج العربية", "US", "رأي", ["agsiw.org", "bloomberg.com"]),
    # ── بريطانيون ──
    W("bowen", "جيريمي بوين", "Jeremy Bowen", "بي بي سي", "UK", "تحليل", ["bbc.com", "bbc.co.uk"], default=True),
    W("england", "أندرو إنجلاند", "Andrew England", "فاينانشال تايمز", "UK", "تحليل", ["ft.com"], default=True),
    W("wintour", "باتريك وينتور", "Patrick Wintour", "الغارديان", "UK", "تحليل", ["theguardian.com"],
      feeds=[GUARDIAN.format("patrick-wintour")], default=True),
    W("carlstrom", "جريج كارلستروم", "Gregg Carlstrom", "الإيكونوميست", "UK", "تحليل", ["economist.com"], default=True),
    W("chulov", "مارتن شولوف", "Martin Chulov", "الغارديان", "UK", "تحليل", ["theguardian.com"],
      feeds=[GUARDIAN.format("martin-chulov")]),
    W("beaumont", "بيتر بومونت", "Peter Beaumont", "الغارديان", "UK", "تحليل", ["theguardian.com"],
      feeds=[GUARDIAN.format("peter-beaumont")]),
    W("doucet", "ليز دوسيه", "Lyse Doucet", "بي بي سي", "UK", "تحليل", ["bbc.com", "bbc.co.uk"]),
    W("hearst", "ديفيد هيرست", "David Hearst", "ميدل إيست آي", "UK", "رأي", ["middleeasteye.net"]),
    # ── إسرائيليون ──
    W("barel", "تسفي بارئيل", "Zvi Bar'el", "هآرتس", "IL", "تحليل", ["haaretz.com"], aliases=["Zvi Bar’el"],
      heb=("צבי בר\"אל", ["haaretz.co.il"]), default=True),
    W("perry", "سمدار بيري", "Smadar Perry", "يديعوت أحرونوت / Ynet", "IL", "تحليل", ["ynetnews.com"],
      heb=("סמדר פרי", ["ynet.co.il"]), default=True),
    W("yaari", "إيهود يعاري", "Ehud Yaari", "القناة 12 / معهد واشنطن", "IL", "تحليل",
      ["timesofisrael.com", "washingtonpost.com", "jpost.com", "washingtoninstitute.org"],
      heb=("אהוד יערי", ["mako.co.il", "13tv.co.il"]), default=True),
    W("issacharoff", "آفي يساخاروف", "Avi Issacharoff", "تايمز أوف إسرائيل / يديعوت", "IL", "تحليل",
      ["timesofisrael.com", "ynetnews.com"], feeds=["https://www.timesofisrael.com/writers/avi-issacharoff/feed/"],
      heb=("אבי יששכרוף", ["ynet.co.il"]), default=True),
    W("ravid", "باراك رافيد", "Barak Ravid", "أكسيوس", "IL", "خبر", ["axios.com"],
      heb=("ברק רביד", ["mako.co.il", "13tv.co.il"]), default=True),
    W("harel", "عاموس هرئيل", "Amos Harel", "هآرتس", "IL", "تحليل", ["haaretz.com"], heb=("עמוס הראל", ["haaretz.co.il"])),
    W("hass", "عميرة هاس", "Amira Hass", "هآرتس", "IL", "رأي", ["haaretz.com"], heb=("עמירה הס", ["haaretz.co.il"])),
    W("levy", "جدعون ليفي", "Gideon Levy", "هآرتس", "IL", "رأي", ["haaretz.com"], heb=("גדעון לוי", ["haaretz.co.il"])),
    W("pfeffer", "أنشل بفيفر", "Anshel Pfeffer", "هآرتس", "IL", "رأي", ["haaretz.com"], heb=("אנשל פפר", ["haaretz.co.il"])),
    W("barnea", "ناحوم برنياع", "Nahum Barnea", "يديعوت أحرونوت", "IL", "رأي", ["ynetnews.com"],
      heb=("נחום ברנע", ["ynet.co.il"])),
    W("caspit", "بن كاسبيت", "Ben Caspit", "معاريف", "IL", "رأي", ["maariv.co.il"], heb=("בן כספית", ["maariv.co.il"])),
    W("limor", "يوآف ليمور", "Yoav Limor", "إسرائيل هيوم", "IL", "تحليل", ["israelhayom.com"],
      heb=("יואב לימור", ["israelhayom.co.il"])),
    W("benyishai", "رون بن يشاي", "Ron Ben-Yishai", "Ynet", "IL", "تحليل", ["ynetnews.com"],
      heb=("רון בן ישי", ["ynet.co.il"])),
]

WRITER_GROUPS = {
    "🇺🇸 أمريكيون": [w for w in WRITERS if w["country"] == "US"],
    "🇬🇧 بريطانيون": [w for w in WRITERS if w["country"] == "UK"],
    "🇮🇱 إسرائيليون": [w for w in WRITERS if w["country"] == "IL"],
}
