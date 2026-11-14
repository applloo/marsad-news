# -*- coding: utf-8 -*-
"""الملفات والخيوط: ربط الأخبار والمنشورات في ملفات (مواضيع ثابتة) وخيوط (قصص بتتكون من الأخبار نفسها).
بدون أي ذكاء اصطناعي ولا إنترنت: عدّ وربط بالكلمات والتواريخ بس، وبعدين برومبت تحليل جاهز تنسخه لأي ذكاء اصطناعي.
تعريف الملفات في dossiers.json (يتعدل من التطبيق من غير كود)."""
import csv
import io
import json
import os
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "dossiers.json")
US_MOVES_PATH = os.path.join(HERE, "us_moves.csv")

# الأطراف: خبرين فيهم نفس طرفين في فترة قريبة بيتجمعوا في "خيط"
ENTITIES = {
    "مصر": ["مصر", "مصري", "مصرية", "القاهرة", "egypt", "egyptian", "cairo"],
    "إثيوبيا": ["إثيوبيا", "إثيوبي", "أثيوبيا", "أديس أبابا", "ethiopia", "ethiopian", "addis ababa"],
    "سد النهضة": ["سد النهضة", "gerd"],
    "السودان": ["السودان", "سوداني", "الخرطوم", "sudan", "sudanese", "khartoum"],
    "السعودية": ["السعودية", "سعودي", "الرياض", "saudi", "riyadh"],
    "إيران": ["إيران", "إيراني", "طهران", "iran", "iranian", "tehran"],
    "الحوثيين": ["الحوثي", "الحوثيين", "أنصار الله", "houthi", "houthis"],
    "سيناء": ["سيناء", "sinai"],
    "إسرائيل": ["إسرائيل", "إسرائيلي", "تل أبيب", "israel", "israeli"],
    "غزة": ["غزة", "gaza"],
    "ليبيا": ["ليبيا", "ليبي", "libya", "libyan"],
    "تشاد": ["تشاد", "تشادي", "chad"],
    "الإمارات": ["الإمارات", "إماراتي", "أبوظبي", "uae", "emirates", "emirati"],
    "الصومال": ["الصومال", "صومالي", "أرض الصومال", "somalia", "somali", "somaliland"],
    "إريتريا": ["إريتريا", "إريتري", "eritrea", "eritrean"],
    "تركيا": ["تركيا", "تركي", "أنقرة", "turkey", "turkish", "türkiye", "ankara"],
    "الصين": ["الصين", "صيني", "بكين", "china", "chinese", "beijing"],
    "روسيا": ["روسيا", "روسي", "موسكو", "russia", "russian", "moscow"],
    "أوكرانيا": ["أوكرانيا", "أوكراني", "ukraine", "ukrainian", "kyiv"],
    "الدعم السريع": ["الدعم السريع", "rsf", "rapid support forces"],
    "قطر": ["قطر", "قطري", "الدوحة", "qatar", "qatari", "doha"],
    "أمريكا": ["أمريكا", "أمريكي", "الولايات المتحدة", "واشنطن", "ترامب", "ترمب",
               "united states", "washington", "trump", "pentagon", "white house"],
}

ALERT_WORDS = [
    "قال", "قالت", "قالوا", "صرح", "صرحت", "صرحوا", "تصريح", "تصريحات", "بيان", "اعلن", "اعلنت",
    "حذر", "حذرت", "يقول", "تقول", "said", "says", "statement", "announced", "warned", "vows", "pledged",
]

STOPWORDS_RAW = """
هذا هذه ذلك تلك التي الذي الذين كان كانت يكون تكون عن على إلى الى من في مع بين عند بعد قبل
لدى لكن أيضا ايضا حيث كما وقد اليوم أمس امس يوم عام سنة بعض كل غير جديد جديدة الآن الان أن ان لن لم
ضد حول خلال منذ مثل هناك هنا قال قالت قالوا يقول تقول عنوان ملخص منشور تجريبي بشأن عبر وسط امام أمام
رئيس وزير وزارة اجل أجل حتى ولا الذى التى لماذا كيف ماذا هل اكثر أكثر اول أول ثاني تقرير تقارير مصادر مصدر
the and for with from that this have has are was were will said says after about into over more than their they its new
what who why how amid could would should been being also just year years week news report reports
"""


def normalize(text):
    """تنضيف النص للمقارنة: شيل التشكيل، وتوحيد الالف والياء والتاء المربوطة"""
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = re.sub("[ً-ْـ]", "", text)
    text = re.sub("[إأآٱ]", "ا", text)
    text = text.replace("ى", "ي").replace("ة", "ه")
    return text.lower()


def make_pattern(words):
    """بحث بكلمة كاملة، ويقبل حروف العطف والجر الملزوقة (و ف ب ل ك) و"ال" التعريف"""
    alts = sorted({normalize(w).strip() for w in words if str(w).strip()}, key=len, reverse=True)
    if not alts:
        return None
    body = "|".join(re.escape(a) for a in alts)
    return re.compile(r"(?<!\w)[وفبلك]?(?:ال)?(?:" + body + r")(?!\w)")


STOPWORDS = {normalize(w) for w in STOPWORDS_RAW.split()}
TOKEN_RE = re.compile(r"[ء-ي]{4,}|[a-z]{4,}")
ENTITY_PATTERNS = {n: make_pattern(w) for n, w in ENTITIES.items()}
ALERT_PATTERN = make_pattern(ALERT_WORDS)


def find_entities(text):
    t = normalize(text)
    return {n for n, p in ENTITY_PATTERNS.items() if p.search(t)}


def keywords_of(text):
    words = set()
    for tok in TOKEN_RE.findall(normalize(text)):
        if tok.startswith("وال") and len(tok) > 5:
            tok = tok[3:]
        elif tok.startswith("ال") and len(tok) > 4:
            tok = tok[2:]
        if tok not in STOPWORDS:
            words.add(tok)
    return words


# ───────── الملفات ─────────

def default_config_text():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return f.read()


def parse_config(text):
    """يرجع (قائمة الملفات، رسالة خطأ أو None)"""
    try:
        raw = json.loads(text)
        out = []
        for d in raw:
            groups = [g for g in d["all_of"] if isinstance(g, list) and g]
            pats = [make_pattern(g) for g in groups]
            if not pats or any(p is None for p in pats):
                raise ValueError(f"الملف «{d.get('name')}» مفيهوش كلمات")
            out.append({"name": str(d["name"]), "type": d.get("type", "ملف"), "lens": bool(d.get("lens")),
                        "all_of": groups, "patterns": pats})
        return out, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def config_to_text(dossiers):
    return json.dumps([{"name": d["name"], "type": d["type"], **({"lens": True} if d["lens"] else {}), "all_of": d["all_of"]}
                       for d in dossiers], ensure_ascii=False, indent=1)


def add_dossier(text, name, words, kind="ملف"):
    raw = json.loads(text)
    raw.append({"name": name, "type": kind, "all_of": [words]})
    return json.dumps(raw, ensure_ascii=False, indent=1)


# ───────── العناصر ─────────

def parse_day(value):
    """يقبل 2026-11-13 او 20261113T120000Z او ISO كامل"""
    s = str(value or "").strip()
    m = re.match(r"(\d{4})-?(\d{2})-?(\d{2})", s)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_dt(value):
    """يرجع datetime (UTC بدون tz) لو القيمة فيها ساعة، وإلا None"""
    s = str(value or "").strip()
    m = re.match(r"(\d{4})-?(\d{2})-?(\d{2})[T ]?(\d{2}):?(\d{2})", s)
    if not m:
        return None
    try:
        return datetime(*(int(x) for x in m.groups()))
    except ValueError:
        return None


def make_item(kind, day, source, country, title, url, summary="", extra_text="", origin="", when=None):
    """kind: خبر/منشور. extra_text: نص بيدخل في المطابقة بس (زي العنوان الانجليزي)"""
    return {"kind": kind, "date": day, "source": source or "مصدر غير معروف", "country": country or "",
            "title": (title or "").strip(), "url": (url or "").strip(), "summary": (summary or "").strip(),
            "match_text": f"{title} {summary} {extra_text}", "origin": origin, "when": when}


def from_app_item(a, label_fn, country_fn, origin):
    """يحوّل خبر من التطبيق (نتايج بحث/تقرير يومي/مخصص/محفوظات) لعنصر"""
    dom = a.get("domain", "")
    title_ar = a.get("title_ar") or ""
    title = a.get("title") or a.get("title_en") or ""
    snip = a.get("snip_ar") or ""
    if not snip and a.get("points_ar"):
        snip = " ".join(str(p) for p in a["points_ar"][:2])
    day = parse_day(a.get("seendate")) or parse_day(a.get("saved_at")) or date.today()
    return make_item("خبر", day, label_fn(dom) if dom else (a.get("outlet") or ""), a.get("country_ar") or country_fn(dom),
                     title_ar or title, a.get("url", ""), snip, extra_text=f"{title} {a.get('title_en', '')}", origin=origin,
                     when=parse_dt(a.get("seendate")))


def from_post(p):
    text = p.get("text", "")
    short = text if len(text) <= 160 else text[:157] + "..."
    return make_item("منشور", parse_day(p.get("date")) or date.today(), f"{p.get('platform', '')} - {p.get('author', '') or 'حساب'}",
                     p.get("country", ""), short, p.get("url", ""), text if short != text else "", origin="منشورات")


NEWS_COLS = ["date", "source", "country", "title", "url"]


def items_from_csv(raw_bytes, origin):
    """ملف CSV بنفس أعمدة: date, source, country, title, url, summary"""
    text = raw_bytes.decode("utf-8-sig", errors="replace") if isinstance(raw_bytes, bytes) else raw_bytes
    rd = csv.DictReader(io.StringIO(text))
    miss = [c for c in NEWS_COLS if c not in (rd.fieldnames or [])]
    if miss:
        raise ValueError("ناقص الأعمدة: " + ", ".join(miss))
    out = []
    for row in rd:
        day = parse_day(row.get("date"))
        if day:
            out.append(make_item("خبر", day, row.get("source", ""), row.get("country", ""), row.get("title", ""),
                                 row.get("url", ""), row.get("summary", ""), origin=origin))
    return out


def us_moves_items():
    try:
        with open(US_MOVES_PATH, "rb") as f:
            return items_from_csv(f.read(), "تحركات أمريكا")
    except Exception:
        return []


# ───────── الربط ─────────

def _prepare(items, dossiers):
    lens = {d["name"] for d in dossiers if d["lens"]}
    for it in items:
        t = normalize(it["match_text"])
        it["entities"] = {n for n, p in ENTITY_PATTERNS.items() if p.search(t)}
        it["statement"] = bool(ALERT_PATTERN.search(t))
        it["dos_names"] = [d["name"] for d in dossiers if all(p.search(t) for p in d["patterns"])]
        it["us"] = any(n in lens for n in it["dos_names"])
        it["words"] = keywords_of(it["match_text"])


def dedupe(items):
    seen, out = set(), []
    for it in items:
        k = it["url"] or (it["title"], it["date"])
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


def _link(items, window, min_shared):
    """الأخبار مترتبة بالتاريخ، فبنقف أول ما الفرق يعدي النافذة (سريع حتى مع آلاف الأخبار)"""
    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(items)):
        ei = items[i]["entities"]
        if len(ei) < min_shared:
            continue
        for j in range(i + 1, len(items)):
            if (items[j]["date"] - items[i]["date"]).days > window:
                break
            if len(ei & items[j]["entities"]) >= min_shared:
                ra, rb = find(i), find(j)
                if ra != rb:
                    parent[rb] = ra
    groups = defaultdict(list)
    for i, it in enumerate(items):
        groups[find(i)].append(it)
    return list(groups.values())


def _stats(items, name, kind):
    items = sorted(items, key=lambda x: x["date"])
    per_day = Counter(it["date"] for it in items)
    avg = len(items) / len(per_day)
    spikes = sorted(d for d, c in per_day.items() if len(per_day) > 1 and c >= 2 and c >= 2 * avg)
    return {
        "name": name, "type": kind, "items": items,
        "first": min(per_day), "last": max(per_day),
        "sources": sorted({it["source"] for it in items}),
        "countries": sorted({it["country"] for it in items if it["country"]}),
        "news_count": sum(1 for it in items if it["kind"] == "خبر"),
        "post_count": sum(1 for it in items if it["kind"] == "منشور"),
        "statements": sum(1 for it in items if it["statement"]),
        "spikes": spikes,
    }


def run(items, dossiers, window=3, min_shared=2, max_days=None):
    """يرجع نتيجة جاهزة للعرض والحفظ (كل التواريخ نصوص). max_days: يشيل أي خبر أقدم من كده"""
    items = dedupe([it for it in items if it["title"]])
    dropped = 0
    if max_days:
        now = datetime.utcnow()
        since = (now - timedelta(days=max_days)).date()
        before = len(items)
        if max_days < 1:  # ساعات: لو الخبر ليه ساعة نقارن بيها، وإلا بنقارن باليوم
            cut = now - timedelta(days=max_days)
            items = [it for it in items if (it["when"] >= cut if it.get("when") else it["date"] >= since)]
        else:
            items = [it for it in items if it["date"] >= since]
        dropped = before - len(items)
    items.sort(key=lambda it: it["date"])
    _prepare(items, dossiers)

    groups = []
    for d in dossiers:
        mem = [it for it in items if d["name"] in it["dos_names"]]
        if mem:
            g = _stats(mem, d["name"], d["type"])
            g["lens"] = d["lens"]
            g["us_items"] = [] if d["lens"] else [it for it in g["items"] if it["us"]]
            g["score"] = len(mem) + 2 * len(g["sources"]) + 3 * len(g["spikes"]) + g["statements"] + g["post_count"]
            groups.append(g)
    groups.sort(key=lambda g: (g["lens"], g["score"]), reverse=True)  # ملف أمريكا الأول، وبعدين الأهم

    threads = []
    singles = 0
    for grp in _link(items, window, min_shared):
        if len(grp) < 2:
            singles += 1
            continue
        ents = Counter(e for it in grp for e in it["entities"])
        name = " + ".join(e for e, _ in ents.most_common(3))
        t = _stats(grp, name, "خيط")
        dos = Counter(n for it in grp for n in it["dos_names"])
        t["dossier"] = dos.most_common(1)[0][0] if dos else "بدون ملف"
        t["us_items"] = [it for it in t["items"] if it["us"]]
        t["score"] = len(grp) + 2 * len(t["sources"]) + 3 * len(t["spikes"]) + t["statements"] + t["post_count"]
        t["long"] = (t["last"] - t["first"]).days > 14
        threads.append(t)
    threads.sort(key=lambda t: t["score"], reverse=True)

    unmatched = [it for it in items if not it["dos_names"]]
    df, pdf = Counter(), Counter()
    for it in unmatched:
        df.update(it["words"])
        if it["kind"] == "منشور":
            pdf.update(it["words"])
    sugg = [{"word": w, "news": c - pdf[w], "posts": pdf[w]} for w, c in df.most_common(60) if c >= 3][:20]
    ents = Counter(e for it in unmatched for e in it["entities"]).most_common(6)

    origins = Counter(it["origin"] for it in items)
    return _jsonable({
        "created": datetime.now().isoformat(timespec="minutes"),
        "total": len(items), "posts": sum(1 for it in items if it["kind"] == "منشور"),
        "first": items[0]["date"] if items else None, "last": items[-1]["date"] if items else None,
        "origins": dict(origins), "window": window, "min_shared": min_shared,
        "max_days": max_days, "dropped_old": dropped,
        "dossiers": groups, "threads": threads[:40], "n_threads": len(threads), "singles": singles,
        "suggested_words": sugg, "suggested_entities": [{"entity": e, "count": c} for e, c in ents],
    })


_DROP = {"match_text", "words", "entities", "dos_names", "when"}


def _jsonable(x):
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items() if k not in _DROP}
    if isinstance(x, (list, tuple, set)):
        return [_jsonable(v) for v in x]
    if isinstance(x, date):
        return x.isoformat()
    return x


# ───────── النصوص والبرومبتات ─────────

def item_lines(items, indent=""):
    lines = []
    for it in items:
        country = it.get("country") or "بلد غير محدد"
        lines.append(f"{indent}- {it['date']} | {it['kind']} | {it['source']} ({country}) | {it['title']}")
        if it.get("url"):
            lines.append(f"{indent}  {it['url']}")
        if it.get("summary"):
            lines.append(f"{indent}  {'النص' if it['kind'] == 'منشور' else 'ملخص'}: {it['summary']}")
    return lines


PROMPT = """أنت محلل أخبار. حلل {scope} ده بس بالمعلومات اللي تحت، وما تضيفش أي حدث أو تصريح أو رقم مش موجود فيها.

{scope}: {name}
الفترة: من {first} لحد {last}
{note}
العناصر بالترتيب الزمني:
{timeline}

{us_block}ملحوظة مهمة: المنشورات على فيس وتويتر ادعاءات مش وقائع. ما تعتمدش عليها كحقيقة، واكتب جنب كل ادعاء إيه اللي محتاج تحقق منه.

اكتب الرد بالعامية المصرية المبسطة، وقسّمه للنقاط دي بالترتيب:

1. الخلاصة: الموضوع في جملتين.
2. الأحداث: كل حدث بتاريخه، وجنبه هل هو "واقعة" حصلت فعلاً ولا "ادعاء أو تصريح" حد قاله.
3. التصريحات ونتيجتها: كل تصريح، إيه اللي اتبنى عليه، وإيه التبعات اللي جت بعده. ولو فيه تصريحات لترامب أو أمريكا، قارن كلامهم بالتحركات الفعلية، ولو فيه فرق بينهم اكتبه.
4. الترابط: إيه اللي سبب إيه، وإيه اللي مجرد تزامن في الوقت؟ قول الدليل على الربط.
5. الدوافع: مين مستفيد مما بيحصل، وإيه الدوافع المحتملة لكل طرف. وقول بوضوح إن ده استنتاج مش معلومة مؤكدة.
6. التبعات: قصيرة المدى (أيام أو أسابيع)، ومتوسطة (شهور)، ومين اللي هيدفع الثمن.
7. المصادر والمنشورات: لكل مصدر أو حساب، إيه الخط المعروف عنه (لو مش متأكد قول كده)، وإيه القصد المحتمل من تغطيته. ولو فيه منشورات منتشرة، اشرح ليه الناس اتفاعلت معاها، وإيه اللي ثبت منها وإيه اللي لأ.
8. وجهة نظر تانية: أقوى حجة للطرف اللي مش متفق مع الاتجاه العام للتغطية.
9. الحبكة: احكي القصة زي حدوتة بسيطة: مين الأطراف، كل واحد عايز إيه، إيه العقبة، إيه نقطة التحول، وإيه السيناريوهات المحتملة الجاية. ده تبسيط للشرح، ومش معلومات جديدة.

قواعد: كون محايد، ولو فيه خلاف في الروايات اعرضه من الطرفين. أي مصطلح سياسي أو اقتصادي اشرحه بمثال سهل. افصل دايماً بين الوقائع والتحليل، ولو المعلومات ناقصة قول كده بدل ما تكملها بالتخمين.
"""


def prompt_for(scope, g, max_items=40):
    shown = g["items"][-max_items:]
    note = f"(الأحدث بس: آخر {max_items} من {len(g['items'])} عنصر)\n" if len(g["items"]) > max_items else ""
    us_block = ""
    if g.get("us_items") and not g.get("lens"):
        us_block = ("الزاوية الأمريكية (تصريحات وتحركات ترامب وأمريكا في الملف ده):\n"
                    + "\n".join(item_lines(g["us_items"][-15:])) + "\n\n")
    return PROMPT.format(scope=scope, name=g["name"], first=g["first"], last=g["last"], note=note,
                         timeline="\n".join(item_lines(shown)), us_block=us_block)


SCRIPT_PROMPT = """انت كاتب سكريبتات مصري عبقري، قاعد على قهوة بلدي في وسط البلد في القاهرة. دمك خفيف ولسانك لازع، وبتتكلم عامية قاهرية حية زي شباب وسط البلد، مش عامية مترجمة ولا فصحى متلبسة عامية.

المطلوب: اكتبلي سكريبت فيديو عن الموضوع ده: {name}
(الفترة من {first} لحد {last}). حدد انت بنفسك هو سياسي ولا اجتماعي ولا الاتنين على حسب المعطيات، واشتغل على كده.

الأخبار والمعلومات اللي عندك (دي الوقائع الوحيدة اللي تقدر تقول عليها "حصل" أو "اتقال"):
{note}{timeline}

{us_block}الطول: حوالي {minutes} دقايق كلام، يعني قرابة {words} كلمة. ماتختصرش. اشرح وفصّل وخلّيه طويل وغني، مش خلاصة.

الخلطة اللي هتمشي عليها:

1) الهوك القاتل (أول 5 ثواني): جملة تسمّر المتابع. سؤال يوجع، أو اعتراف صادم، أو "عمرك سألت نفسك ليه...؟"، أو سؤالين يخلّوه مضطر يستنى للآخر عشان يعرف الإجابة. الهوك لازم يتبني على حاجة حقيقية من الأخبار فوق.

2) لغة الكلام: عامية قاهرية حية كأنك بتحكي لصاحبك. ممنوع الفصحى. ممنوع الكلام المثالي بتاع التنمية البشرية. ممنوع الكلام السياسي التقيل الجاف. ممنوع الأفيهات البايخة المحفوظة. ممنوع تكرر نفس الجملة الرابطة كل شوية (ماتقولش "بس استنى" ولا ما يشبهها كل مرة)، نوّع في الانتقالات زي ما أي حكّاء بيعمل.

3) الضحك: كوميديا سودا بتلسع وبتوجع وبتضحك في نفس الوقت. ارمي الحقيقة المرّة في قالب طريف. وبين كل كام جملة تقيلة أو تحليل تقيل ارمي أفيه يفك التكشيرة. الأفيه يطلع من الموقف نفسه مش من برّه.

4) فكّ المشهد: ماتقولش "ترامب قال كذا" وخلاص. فكّ المشهد: ليه التصريح ده بالذات؟ ليه دلوقتي؟ مين المستفيد؟ مين اللي بيتضغط عليه؟ وهنا اربط الخيوط ببعض: أمريكا وإيران وإسرائيل واليمن (الحوثيين) ومصر والسعودية والخليج، وكل طرف له إيه في الموضوع ده، ومصر بالذات هتتأثر إزاي (قناة السويس، الأسعار، الحدود، الدور السياسي). المتابع لازم يخرج وهو حاسس إن الواد ده فاهم وبيربط الحاجات اللي محدش بيربطها.

5) الجمل الاستنتاجية التقيلة: في نص السكريبت وفي آخره ادّيني جملتين تلاتة استنتاجية تقيلة (زي إن فلان ممكن يكون عايز يكمّل الحرب عشان يحمي منصبه، أو إن الحكاية أكبر من تصريح). الجملة دي تتقال بصوتك كرأي وتحليل ("أنا شايف"، "الظاهر"، "الحكاية ريحتها كذا")، مش كخبر مؤكد.

6) الأسئلة: كل نص دقيقة تقريباً ارمي سؤال للمتابع يخليه يفكّر ويعلّق.

الأمانة (دي مش تفاصيل، دي حدود):
- أي واقعة أو رقم أو تصريح ماينفعش تقوله غير لو موجود في الأخبار فوق. ممنوع تألف خبر أو رقم أو اقتباس عشان الأفيه أو الهوك يبقى أقوى.
- اللي طرف بيقوله عن نفسه أو عن خصمه سمّيه "بيقول" أو "بيزعم"، ماتحوّلهوش لحقيقة. والمنشورات والادعاءات تتقال إنها ادعاءات بس بأسلوبك مش بنص قانوني.
- الخلفية العامة المعروفة (زي مين الحوثيين، وأهمية مضيق هرمز أو قناة السويس، وتاريخ العلاقة بين الأطراف) تقدر تستخدمها عشان تشرح، بس لما تقولها قول إنها "خلفية معروفة" مش من الأخبار دي.
- الاستنتاج والدوافع بتاعتك قولها كرأي واضح، وماتخلطهاش بالوقائع.
- لو الأخبار فيها ناقص، قول "الملف مش قايل" بدل ما تخمّن.

حاجة صغيرة: صاحب القناة عنده لدغة بسيطة في حرف السين، فاختار كلمات سهلة على لسانه، وماتحطش كلمات فيها سين كتير ورا بعض، ولو في بديل أخف قولّه من غير ما يبوظ المعنى.

شكل الرد:
- مقسّم أجزاء، وجنب كل جزء وقته بالثواني زي [0:00 - 0:05]، وبعده النص اللي هيتقال بس (من غير شرح ولا ملاحظات جوه الكلام).
- الجزء الأول الهوك، وبعده مقدمة سريعة، وبعدين الحكاية بالترتيب مع فكّ المشهد والربط، وبعدين خلاصة وسيناريوهات، وآخره سؤال يخلّي الناس تعلّق.
- في الآخر اكتب 3 اقتراحات لعنوان الفيديو، وجملة قصيرة تتحط على الصورة المصغّرة.
"""


def script_prompt(scope, g, minutes=5, max_items=40):
    shown = g["items"][-max_items:]
    note = f"(الأحدث بس: آخر {max_items} من {len(g['items'])} عنصر)\n" if len(g["items"]) > max_items else ""
    us_block = ""
    if g.get("us_items") and not g.get("lens"):
        us_block = ("الزاوية الأمريكية (تصريحات وتحركات ترامب وأمريكا في الملف ده):\n"
                    + "\n".join(item_lines(g["us_items"][-15:])) + "\n\n")
    return SCRIPT_PROMPT.format(name=g["name"], first=g["first"], last=g["last"], note=note,
                                timeline="\n".join(item_lines(shown)), us_block=us_block,
                                minutes=minutes, words=int(minutes) * 140)


def briefing_md(res, limit=300):
    out = [
        "# تقرير الملفات والخيوط",
        f"من {res['first']} لحد {res['last']} | عناصر: {res['total']} (منشورات {res['posts']}) | "
        f"ملفات فيها عناصر: {len(res['dossiers'])} | خيوط: {res['n_threads']}",
        "", "## الملفات",
    ]
    for g in res["dossiers"]:
        out.append(f"### {g['name']}" + (" (ترند)" if g["type"] == "ترند" else ""))
        out.append(f"- العدد: {len(g['items'])} (أخبار {g['news_count']}، منشورات {g['post_count']}) من {len(g['sources'])} مصدر")
        out.append(f"- الفترة: من {g['first']} لحد {g['last']} | تصريحات: {g['statements']} | "
                   f"أيام ارتفاع: {', '.join(g['spikes']) or 'مفيش'}")
        out.extend(item_lines(g["items"][-limit:], "  "))
        if g.get("us_items"):
            out.append(f"- الزاوية الأمريكية: {len(g['us_items'])} عنصر")
            out.extend(item_lines(g["us_items"][-10:], "  "))
        out.append("")
    out.append("## خيوط القصص")
    for n, t in enumerate(res["threads"], 1):
        out.append(f"### {n}. {t['name']} (الملف الغالب: {t['dossier']})")
        out.append(f"- من {t['first']} لحد {t['last']} | {len(t['items'])} عنصر من {len(t['sources'])} مصدر")
        out.extend(item_lines(t["items"], "  "))
        out.append("")
    out.append("## اقتراحات ملفات جديدة")
    out.extend(f"- {s['word']}: {s['news']} خبر و{s['posts']} منشور" for s in res["suggested_words"])
    return "\n".join(out) + "\n"
