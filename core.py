# -*- coding: utf-8 -*-
"""منطق البحث والترجمة (بدون Streamlit) - يعتمد على GDELT DOC 2.0 API"""
import base64
import email.utils
import html as _html
import ipaddress
import json
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from urllib.parse import quote, unquote, urljoin, urlparse
from zoneinfo import ZoneInfo

import xml.etree.ElementTree as ET
from html.parser import HTMLParser

import requests

try:  # اختياري: إن لم تتوفر الحزمة يعمل مستخرج بديل مدمج
    import trafilatura
except Exception:
    trafilatura = None
try:
    from deep_translator import GoogleTranslator
except Exception:
    GoogleTranslator = None

TZ = ZoneInfo("Africa/Cairo")
_HAS_AR = re.compile(r"[\u0600-\u06FF]")
_NIKUD = re.compile(r"[\u0591-\u05C7]")


class TranslationError(Exception):
    pass

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

# ───────────────────────── الترجمة ─────────────────────────


_TR_CACHE = {}


def _gtx(text, src, dest):
    r = requests.get(
        "https://translate.googleapis.com/translate_a/single",
        params={"client": "gtx", "sl": src, "tl": dest, "dt": "t", "q": text},
        headers=UA,
        timeout=20,
    )
    r.raise_for_status()
    return "".join(seg[0] for seg in r.json()[0] if seg and seg[0])


def tr(text, src="auto", dest="ar"):
    """يترجم ولا يخزّن نتائج الفشل (حتى لا يبقى الفشل المؤقت دائماً)"""
    text = (text or "").strip()
    if not text:
        return ""
    key = (text, src, dest)
    if key in _TR_CACHE:
        return _TR_CACHE[key]
    for attempt in range(3):
        for fn in (
            (lambda: GoogleTranslator(source=src, target=dest).translate(text)) if GoogleTranslator else None,
            lambda: _gtx(text, src, dest),
        ):
            if fn is None:
                continue
            try:
                out = (fn() or "").strip()
                if dest in ("iw", "he"):
                    out = _NIKUD.sub("", out)  # تشكيل العبرية يمنع المطابقة مع نصوص المقالات
                if out and not (src == "ar" and dest != "ar" and _HAS_AR.search(out)):
                    if len(_TR_CACHE) > 8000:
                        _TR_CACHE.clear()
                    _TR_CACHE[key] = out
                    return out
            except Exception:
                pass
        time.sleep(0.8)
    return text


def chunk_text(text, limit=4000):
    chunks, cur = [], ""
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        while len(para) > limit:
            cut = para.rfind(". ", 0, limit)
            cut = cut + 1 if cut > 0 else limit
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(para[:cut])
            para = para[cut:].strip()
        if not para:
            continue
        if cur and len(cur) + len(para) + 1 > limit:
            chunks.append(cur)
            cur = para
        else:
            cur = f"{cur}\n{para}" if cur else para
    if cur:
        chunks.append(cur)
    return chunks


@lru_cache(maxsize=256)
def translate_long(text):
    chunks = chunk_text(text)
    with ThreadPoolExecutor(4) as ex:
        parts = list(ex.map(lambda c: tr(c, "auto", "ar"), chunks))
    return "\n".join(parts)


# ───────────────────────── جلب المقال ─────────────────────────


def is_safe_url(url):
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return False
        for info in socket.getaddrinfo(p.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        return True
    except Exception:
        return False


class _SimpleExtractor(HTMLParser):
    """مستخرج بديل بسيط: فقرات <p> + العنوان + تاريخ النشر من الميتا"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.date, self.paras = "", "", []
        self._skip, self._in_p, self._in_title, self._buf = 0, False, False, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "nav", "footer", "header", "aside", "form", "noscript"):
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "p" and not self._skip:
            self._in_p, self._buf = True, []
        elif tag == "meta":
            k = (a.get("property") or a.get("name") or "").lower()
            if k in ("article:published_time", "og:article:published_time", "date", "pubdate") and not self.date:
                self.date = a.get("content", "")
            if k == "og:title" and a.get("content"):
                self.title = a["content"]

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "header", "aside", "form", "noscript"):
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag == "p" and self._in_p:
            t = " ".join("".join(self._buf).split())
            if len(t) > 40:
                self.paras.append(t)
            self._in_p = False

    def handle_data(self, data):
        if self._in_title and not self.title:
            self.title = data.strip()
        if self._in_p:
            self._buf.append(data)


_META_SEC = [
    re.compile(
        r'<meta[^>]+(?:property|name)=["\'](?:article:section|section|parsely-section|og:section|category)["\'][^>]*content=["\']([^"\']+)',
        re.I,
    ),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\'](?:article:section|section|parsely-section|og:section|category)["\']',
        re.I,
    ),
    re.compile(r'"articleSection"\s*:\s*\[?\s*"([^"]+)"', re.I),
]
_FIRST_PERSON = re.compile(r"\b(I|my|me|myself)\b")


def _page_meta(html_text):
    secs = []
    for rx in _META_SEC:
        m = rx.search(html_text)
        if m:
            secs.append(m.group(1))
    return " | ".join(secs)


def _extract(content, enc=None):
    text = content.decode(enc or "utf-8", errors="replace") if isinstance(content, bytes) else content
    out = None
    if trafilatura is not None:
        data = trafilatura.extract(
            text, output_format="json", with_metadata=True, favor_recall=True, include_comments=False
        )
        if data:
            d = json.loads(data)
            out = {"title": d.get("title") or "", "date": d.get("date") or "", "text": d.get("text") or ""}
    if out is None:
        ex = _SimpleExtractor()
        ex.feed(text)
        out = {"title": ex.title, "date": ex.date, "text": "\n".join(ex.paras)}
    out["section"] = _page_meta(text[:200000])
    words = max(1, len(out["text"].split()))
    out["fp"] = 1000.0 * len(_FIRST_PERSON.findall(out["text"])) / words if words > 200 else 0.0
    return out


@lru_cache(maxsize=512)
def fetch_article(url):
    if not is_safe_url(url):
        return None
    try:
        r = requests.get(url, headers=UA, timeout=15)
        r.raise_for_status()
        d = _extract(r.content, r.encoding or r.apparent_encoding)
        if len(d["text"]) < 200:
            return None
        return d
    except Exception:
        return None


# ───────────────────────── تصنيف وتنسيق ─────────────────────────

OPINION_RE = re.compile(
    r"/(opinion|opinions|op-ed|oped|editorial|editorials|commentary|column|columnists|blogs?|perspectives?|viewpoint)/",
    re.I,
)
ANALYSIS_RE = re.compile(
    r"/(analysis|analyses|explainer|explainers|insight|deep-dive|in-depth|long-read|analysis-and-features)/", re.I
)
OPINION_TITLE = re.compile(r"^(opinion|op-ed|editorial|commentary)\s*[:|\-–]", re.I)
ANALYSIS_TITLE = re.compile(r"^(analysis|explainer)\s*[:|\-–]", re.I)
SEC_OPINION = re.compile(r"opinion|op-ed|oped|editorial|commentary|column|perspective|viewpoint|דעות|رأي|آراء", re.I)
SEC_ANALYSIS = re.compile(r"analysis|explainer|insight|in-depth|deep.?dive|ניתוח|פרשנות|تحليل", re.I)


def classify(url, title):
    """يعيد (النوع، هل التصنيف مؤكد من الرابط/العنوان)"""
    if OPINION_RE.search(url) or OPINION_TITLE.search(title):
        return "رأي", True
    if ANALYSIS_RE.search(url) or ANALYSIS_TITLE.search(title):
        return "تحليل", True
    return "خبر", False


def classify_section(sec):
    if not sec:
        return None
    if SEC_OPINION.search(sec):
        return "رأي"
    if SEC_ANALYSIS.search(sec):
        return "تحليل"
    return "خبر"


def fmt_seen(seen):
    try:
        dt = datetime.strptime(seen, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone(TZ)
        return dt.strftime("%Y-%m-%d  %H:%M")
    except Exception:
        return seen or "-"


# ───────────────────────── بناء الاستعلام ─────────────────────────

STOP = {
    "en": {"the", "a", "an", "of", "in", "on", "at", "to", "for", "and", "or", "by", "with", "from", "is", "are"},
    "iw": {"של", "את", "על", "עם", "אל", "מן", "כי", "גם", "או"},
    "fr": {"de", "du", "des", "la", "le", "les", "et", "en", "un", "une", "au", "aux", "pour", "d", "l"},
    "es": {"de", "del", "la", "el", "los", "las", "y", "en", "un", "una", "para", "por", "al"},
    "pt": {"de", "do", "da", "dos", "das", "o", "a", "os", "as", "e", "em", "um", "uma", "para", "por"},
}
CJK = {"zh", "ko"}
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")
GT_CODE = {"zh": "zh-CN"}

# اللغات المتاحة في تاب الترجمة: (رمز داخلي، اسمها بالعربية، رمز GDELT sourcelang، افتراضياً مفعّلة)
LANGS = [
    ("en", "الإنجليزية", "eng", True),
    ("iw", "العبرية", "heb", True),
    ("fr", "الفرنسية", "french", False),
    ("es", "الإسبانية", "spanish", False),
    ("pt", "البرتغالية", "portuguese", False),
    ("hi", "الهندية", "hindi", False),
    ("zh", "الصينية", "chinese", False),
    ("ko", "الكورية", "korean", False),
]


def _minlen(code, default):
    return 1 if code in CJK else default


def translate_terms(terms, code):
    """يترجم كل عبارة من العربية؛ يعيد (قائمة الترجمات، هل نجحت كلها)"""
    out, ok = [], True
    for t in terms:
        x = tr(t, "ar", GT_CODE.get(code, code))
        if _HAS_AR.search(x):
            ok = False
            continue
        out.append(x)
    return out, ok and bool(out)
MATCH_MODES = ["كلمات متقاربة (Near)", "عبارة دقيقة (Exact)", "كل الكلمات (AND)"]


def clean_words(x, code, min_len):
    x = re.sub(r"[\"“”„()\[\]{}:;!?,،.]", " ", x)
    out = []
    for w in x.split():
        w = re.sub(r"['’]s$", "", w)
        if w.lower() in STOP.get(code, ()):
            continue
        if len(w) < min_len:
            continue
        out.append(w)
    return out


def build_term(term, code, match, pre=False):
    x = term if pre else tr(term, "ar", GT_CODE.get(code, code))
    if not pre and _HAS_AR.search(x):
        raise TranslationError(f"تعذّرت ترجمة «{term}» إلى {'العبرية' if code == 'iw' else 'الإنجليزية'}")
    if "Exact" in match:
        words = clean_words(x, code, 1)
        if not words:
            return ""
        return words[0] if len(words) == 1 and len(words[0]) >= 3 else '"' + " ".join(words) + '"'
    if "Near" in match:
        words = clean_words(x, code, 1)
        if not words:
            return ""
        if len(words) == 1:
            return words[0] if len(words[0]) >= 3 else '"' + words[0] + '"'
        return 'near15:"' + " ".join(words) + '"'
    words = clean_words(x, code, _minlen(code, 3))  # AND
    return " ".join(f'"{w}"' if len(w) < 3 else w for w in words)


def build_query(terms, code, joiner, match, pre=False):
    parts = [p for p in (build_term(t, code, match, pre) for t in terms) if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if joiner == "OR":
        return "(" + " OR ".join(parts) + ")"
    return " ".join(parts)


def domain_expr(domains):
    ds = []
    for d in domains:
        ds += [x for x in d.split("|") if x]
    expr = " OR ".join(f"domain:{d}" for d in ds)
    return f"({expr})" if len(ds) > 1 else expr


def _split_domains(ds):
    out = []
    for d in ds:
        out += [x for x in d.split("|") if x]
    return out


def domain_match(dom, doms):
    dom = (dom or "").lower().replace("www.", "")
    return any(dom == d or dom.endswith("." + d) for d in doms)


def jobs_for_sources(selected, country=None):
    """selected: قائمة (label, domains, lang) حيث lang في he / en / both.
    country: رمز بلد GDELT (US/UK/IS) يُستخدم كخطة بديلة إن فشل فلتر الدومين"""
    he = _split_domains([d for _, d, lang in selected if lang in ("he", "both")])
    en = _split_domains([d for _, d, lang in selected if lang in ("en", "both")])
    jobs = []
    if he:
        jobs.append({"code": "iw", "extra": domain_expr(he), "domains": he, "country": country, "lang": "heb"})
    if en:
        jobs.append({"code": "en", "extra": domain_expr(en), "domains": en, "country": country, "lang": "eng"})
    return jobs


GLOBAL_SCOPES = {
    "جميع المصادر": [
        {"code": "en", "extra": "sourcelang:eng"},
        {"code": "iw", "extra": "sourcelang:heb"},
    ],
    "مصادر أمريكية فقط": [{"code": "en", "extra": "sourcecountry:US sourcelang:eng"}],
    "مصادر إسرائيلية فقط": [
        {"code": "en", "extra": "sourcecountry:IS sourcelang:eng"},
        {"code": "iw", "extra": "sourcecountry:IS sourcelang:heb"},
    ],
    "مصادر بريطانية فقط": [{"code": "en", "extra": "sourcecountry:UK sourcelang:eng"}],
}


def gdelt_call(query, start_utc, end_utc, max_rec, timespan=None):
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": max_rec,
        "sort": "DateDesc",
        "startdatetime": start_utc.strftime("%Y%m%d%H%M%S"),
        "enddatetime": end_utc.strftime("%Y%m%d%H%M%S"),
    }
    if timespan:  # صيغة بديلة: نافذة نسبية بدل تواريخ محددة
        params.pop("startdatetime"), params.pop("enddatetime")
        params["timespan"] = timespan
    last_err = ""
    for _ in range(3):
        try:
            r = requests.get(GDELT_URL, params=params, timeout=40)
            if r.status_code == 429 or "limit requests" in r.text.lower():
                time.sleep(6)
                continue
            try:
                return r.json().get("articles", []), ""
            except ValueError:
                last_err = r.text.strip()[:200] or f"HTTP {r.status_code}"
                if "too short" in last_err.lower() or "too common" in last_err.lower():
                    break
                time.sleep(3)
        except requests.RequestException as e:
            last_err = str(e)
            time.sleep(3)
    return [], last_err


def search_iter(terms, joiner, match, jobs, start_utc, end_utc, max_rec, ctype):
    """مولّد: يُخرج حالة بعد كل طلب وأثناء الانتظار، فتُعرض النتائج أولاً بأول ويمكن إيقاف البحث في أي لحظة."""
    n = min(250, max_rec * 3) if ctype != "الكل" else min(250, max_rec)
    found, errors, used = {}, [], []
    last = {"t": 0.0}

    def snapshot():
        items = []
        for a in found.values():
            if "ctype" not in a:
                a["ctype"], a["ctype_sure"] = classify(a.get("url", ""), a.get("title", ""))
            if ctype == "الكل" or a["ctype"] == ctype:
                items.append(a)
        items.sort(key=lambda a: a.get("seendate", ""), reverse=True)
        return items[:max_rec]

    def ev(msg, items=None):
        return {"msg": msg, "items": items, "errors": errors, "used": used}

    def call(full, label="", count=n):
        wait = 5.1 - (time.time() - last["t"])  # حد GDELT: طلب كل 5 ثوانٍ (من بداية الطلب السابق)
        while wait > 0:
            yield ev(f"انتظار حدّ الطلبات في GDELT ({int(wait) + 1}ث)…")
            step = min(0.7, wait)
            time.sleep(step)
            wait -= step
        used.append(label + full)
        yield ev(f"جارٍ البحث: {full[:140]}")
        last["t"] = time.time()
        arts, err = gdelt_call(full, start_utc, end_utc, count)
        used[-1] += f"   ⟵ {len(arts)} نتيجة"
        if not arts and not err and label == "":
            # ردّ فارغ بلا خطأ: أعد المحاولة مرة بنافذة زمنية نسبية (أحياناً يتأخر GDELT في فهرسة آخر دقائق)
            hrs = int((end_utc - start_utc).total_seconds() // 3600) + 1
            span = f"{hrs}h" if hrs <= 72 else f"{-(-hrs // 24)}d"
            wait = 5.1 - (time.time() - last["t"])
            while wait > 0:
                yield ev(f"إعادة المحاولة بنافذة {span} ({int(wait) + 1}ث)…")
                step = min(0.7, wait)
                time.sleep(step)
                wait -= step
            used.append(f"↳ timespan={span}: {full}")
            yield ev("إعادة المحاولة بنافذة زمنية نسبية…")
            last["t"] = time.time()
            arts, err = gdelt_call(full, start_utc, end_utc, count, timespan=span)
            used[-1] += f"   ⟵ {len(arts)} نتيجة"
        if err:
            errors.append(f"{full[:160]}: {err}")
        return arts

    def take(arts):
        for a in arts:
            found.setdefault(a.get("url"), a)
        return ev(f"وصلت {len(arts)} نتيجة", snapshot())

    for job in jobs:
        try:
            q = build_query(job.get("terms") or terms, job["code"], joiner, match, pre=bool(job.get("terms")))
        except TranslationError as e:
            errors.append(f"{e} — أعد المحاولة بعد لحظات.")
            yield ev("تعذّرت ترجمة إحدى اللغات")
            continue
        if not q:
            continue
        doms = job.get("domains")
        if not doms:
            arts = yield from call(f"{q} {job['extra']}".strip())
            yield take(arts)
            continue
        arts = yield from call(f"{q} {job['extra']}")
        got = list(arts)
        yield take(arts)
        if not got:  # خطة بديلة 1: دفعات أصغر من المواقع
            for i in range(0, min(len(doms), 32), 4):
                arts = yield from call(f"{q} {domain_expr(doms[i:i + 4])}", "↳ دفعة: ")
                got += arts
                yield take(arts)
        if not got and job.get("country"):  # خطة بديلة 2: فلتر البلد/اللغة ثم تصفية المواقع محلياً
            arts = yield from call(f"{q} sourcecountry:{job['country']} sourcelang:{job['lang']}", "↳ بلد: ", 250)
            yield take([a for a in arts if domain_match(a.get("domain", ""), doms)])
    yield ev("تم", snapshot())


def run_search(terms, joiner, match, jobs, start_utc, end_utc, max_rec, ctype, progress=None):
    last = None
    for e in search_iter(terms, joiner, match, jobs, start_utc, end_utc, max_rec, ctype):
        if progress:
            progress(e["msg"])
        last = e
    return (last["items"] or []), last["errors"], last["used"]


def translate_titles(items):
    def work(a):
        title = a.get("title", "")
        a["title_ar"] = tr(title, "auto", "ar")
        a["title_en"] = title if a.get("language", "").lower() == "english" else tr(title, "auto", "en")
        a["country_ar"] = tr(a.get("sourcecountry", ""), "en", "ar") if a.get("sourcecountry") else ""
        return a

    with ThreadPoolExecutor(6) as ex:
        return list(ex.map(work, items))


# ───────────────────────── التحقق من نص المقال ─────────────────────────


def _stem(w, code):
    w = w.lower()
    if _CJK_RE.search(w):
        return w[:2]
    if code == "iw" and len(w) > 3 and w[0] == "ה":
        w = w[1:]
    return w[:5] if len(w) > 5 else w


def make_matchers(terms, codes):
    """لكل عبارة: قائمة بدائل (واحد لكل لغة) من جذور الكلمات"""
    out = []
    for t in terms:
        alts = []
        for code in dict.fromkeys(codes):
            words = clean_words(tr(t, "ar", GT_CODE.get(code, code)), code, _minlen(code, 3))
            stems = [_stem(w, code) for w in words]
            if stems:
                alts.append(stems)
        if alts:
            out.append(alts)
    return out


def make_matchers_pre(jobs):
    """مطابِقات من ترجمات جاهزة: لكل رقم عبارة قائمة بدائل (واحد لكل لغة)"""
    n = max((len(j.get("terms") or []) for j in jobs), default=0)
    out = []
    for i in range(n):
        alts = []
        for j in jobs:
            terms = j.get("terms") or []
            if i < len(terms):
                code = j["code"]
                stems = [_stem(w, code) for w in clean_words(terms[i], code, _minlen(code, 3))]
                if stems:
                    alts.append(stems)
        if alts:
            out.append(alts)
    return out


def find_mentions(text, matchers, joiner="AND", maxn=2):
    low = text.lower()
    ok = [any(all(st in low for st in stems) for stems in alts) for alts in matchers]
    found = bool(ok) and (all(ok) if joiner == "AND" else any(ok))
    flat = [stems for alts in matchers for stems in alts]
    scored = []
    for i, sent in enumerate(re.split(r"(?<=[.!?])\s+|\n+", text)):
        sent = sent.strip()
        if len(sent) < 25:
            continue
        sl = sent.lower()
        sc = max((sum(st in sl for st in m) / len(m) for m in flat), default=0)
        if sc > 0:
            scored.append((-sc, i, sent[:400]))
    scored.sort()
    top = sorted(scored[:maxn], key=lambda x: x[1])
    return found, [x[2] for x in top]


def enrich_items(items, matchers, joiner="AND", limit=40, workers=8):
    """يجلب نص المقالات بالتوازي ويضيف: found / snips / snip_ar، ويحسّن تصنيف النوع"""

    def work(a):
        art = fetch_article(a.get("url", ""))
        a["checked"] = True
        if not art:
            a["fetched"] = False
            return a
        a["fetched"] = True
        a["found"], snips = find_mentions(art["text"], matchers, joiner)
        a["snips"] = snips
        a["snip_ar"] = tr(" ".join(snips), "auto", "ar") if snips else ""
        sec = classify_section(art.get("section", ""))
        if sec:
            a["ctype"], a["ctype_sure"] = sec, True
        elif not a.get("ctype_sure") and art.get("fp", 0) > 6:
            a["ctype"] = "رأي"
        return a

    head = items[:limit]
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(work, head))
    return items


# ───────────────────────── كتّاب ومحللون (RSS + أخبار Google) ─────────────────────────

_DC = "{http://purl.org/dc/elements/1.1/}"
_ATOM = "{http://www.w3.org/2005/Atom}"
COUNTRY_EN = {"US": "United States", "UK": "United Kingdom", "IL": "Israel"}


def _to_utc(s):
    if not s:
        return None
    s = s.strip()
    try:
        dt = email.utils.parsedate_to_datetime(s)
    except Exception:
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_feed(content):
    root = ET.fromstring(content)
    out = []
    for it in root.iter("item"):
        src = it.find("source")
        out.append(
            {
                "title": (it.findtext("title") or "").strip(),
                "link": (it.findtext("link") or "").strip(),
                "date": _to_utc(it.findtext("pubDate") or it.findtext(_DC + "date")),
                "source_url": (src.get("url") or "") if src is not None else "",
                "source_name": ((src.text or "").strip()) if src is not None else "",
            }
        )
    for en in root.iter(_ATOM + "entry"):
        ln = en.find(_ATOM + "link")
        out.append(
            {
                "title": (en.findtext(_ATOM + "title") or "").strip(),
                "link": (ln.get("href") if ln is not None else "") or "",
                "date": _to_utc(en.findtext(_ATOM + "published") or en.findtext(_ATOM + "updated")),
                "source_url": "",
                "source_name": "",
            }
        )
    return out


def _get_feed(url):
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    if len(r.content) > 5_000_000:
        raise ValueError("الخلاصة كبيرة جداً")
    return parse_feed(r.content)


def gnews_url(q, hl, gl, ceid):
    return f"https://news.google.com/rss/search?q={quote(q)}&hl={hl}&gl={gl}&ceid={quote(ceid)}"


def decode_gnews(url):
    """يفك رابط أخبار Google إلى الرابط الأصلي (أفضل جهد؛ يعيد الرابط كما هو عند الفشل)"""
    try:
        p = urlparse(url)
        if p.netloc != "news.google.com":
            return url
        gid = p.path.rstrip("/").split("/")[-1]
        raw = base64.urlsafe_b64decode(gid + "=" * (-len(gid) % 4))
        if raw.startswith(b"\x08\x13\x22"):
            raw = raw[3:]
            if raw.endswith(b"\xd2\x01\x00"):
                raw = raw[:-3]
            n, start = raw[0], 1
            if n >= 0x80:
                n, start = (n & 0x7F) | (raw[1] << 7), 2
            direct = raw[start : start + n].decode("utf-8", "ignore")
            if direct.startswith("http"):
                return direct
        page = ""
        for base in ("https://news.google.com/rss/articles/", "https://news.google.com/articles/"):
            page = requests.get(base + gid, headers=UA, timeout=15).text
            sg = re.search(r'data-n-a-sg="([^"]+)"', page)
            ts = re.search(r'data-n-a-ts="([^"]+)"', page)
            if sg and ts:
                break
        else:
            return url
        inner = (
            '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
            f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{gid}",{ts.group(1)},"{sg.group(1)}"]'
        )
        payload = "f.req=" + quote(json.dumps([[["Fbv4je", inner]]]))
        r = requests.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            headers={"content-type": "application/x-www-form-urlencoded;charset=UTF-8", "user-agent": UA["User-Agent"]},
            data=payload,
            timeout=15,
        )
        parsed = json.loads(r.text.split("\n\n")[1])[:-2]
        out = json.loads(parsed[0][2])[1]
        return out if str(out).startswith("http") else url
    except Exception:
        return url


def _host(u):
    h = (urlparse(u).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def fetch_writer(w, days):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    items, notes = [], []

    def add(e, how, lang):
        if not e["link"] or not e["title"] or not e["date"] or e["date"] < cutoff:
            return
        title = e["title"]
        if e["source_name"] and title.endswith(" - " + e["source_name"]):
            title = title[: -len(e["source_name"]) - 3]
        items.append(
            {
                "url": e["link"], "title": title, "seendate": e["date"].strftime("%Y%m%dT%H%M%SZ"),
                "domain": _host(e["source_url"]) or _host(e["link"]),
                "sourcecountry": COUNTRY_EN.get(w["country"], ""), "language": lang,
                "writer": w["name_ar"], "writer_en": w["name_en"], "outlet": w["outlet"], "wsrc": how,
            }
        )

    for f in w["feeds"]:
        try:
            got = _get_feed(f)
            before = len(items)
            for e in got:
                add(e, "feed", "English")
            notes.append(f"{w['name_en']} ⟵ صفحة الكاتب: {len(items) - before} مقال")
        except Exception as ex:
            notes.append(f"{w['name_en']} ⟵ صفحة الكاتب تعذّر جلبها ({type(ex).__name__})")
    for g in w["gn"]:
        q = g["q"] + f" when:{max(1, days)}d"
        try:
            got = _get_feed(gnews_url(q, g["hl"], g["gl"], g["ceid"]))
            before = len(items)
            for e in got:
                add(e, "search", g["lang"])
            notes.append(f"{w['name_en']} ⟵ بحث: {q[:110]} ⟵ {len(items) - before}")
        except Exception as ex:
            notes.append(f"{w['name_en']} ⟵ البحث تعذّر ({type(ex).__name__})")
    return items, notes


def fetch_writers(writers, days, workers=6):
    all_items, notes = [], []
    with ThreadPoolExecutor(workers) as ex:
        for items, nt in ex.map(lambda w: fetch_writer(w, days), writers):
            all_items += items
            notes += nt
    seen, uniq = set(), []
    for a in sorted(all_items, key=lambda a: (a["wsrc"] != "feed", a["seendate"]), reverse=False):
        key = (a["writer"], re.sub(r"\W+", "", a["title"].lower())[:80])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(a)

    def dec(a):
        if "news.google.com" in a["url"]:
            real = decode_gnews(a["url"])
            if real != a["url"]:
                a["url"], a["domain"] = real, _host(real)
        return a

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(dec, uniq[:120]))
    for a in uniq:
        kind = next((w["kind"] for w in writers if w["name_ar"] == a["writer"]), "رأي")
        ct, sure = classify(a["url"], a["title"])
        a["ctype"], a["ctype_sure"] = (ct, True) if sure else (kind, False)
    uniq.sort(key=lambda a: a["seendate"], reverse=True)
    return uniq, notes


# ───────────────────────── بحث داخل مصادر محددة / باسم كاتب (عبر أخبار Google) ─────────────────────────

_GN_LOC = {
    "en": {"US": ("en-US", "US", "US:en"), "UK": ("en-GB", "GB", "GB:en"), "IL": ("en-IL", "IL", "IL:en")},
    "he": {"IL": ("iw", "IL", "IL:he")},
}


def _quoted(x):
    x = re.sub(r"[\"“”„]", " ", x).strip()
    return f'"{x}"' if " " in x else x


def _name_tokens(name):
    return [t.lower() for t in re.split(r"[\s\-]+", re.sub(r"[^\w\s\-]", " ", name)) if len(t) > 1]


def check_byline(url, name_variants):
    """هل اسم الكاتب مذكور كمؤلف في الصفحة؟ True/False، أو None إن تعذّر فتح الصفحة"""
    if not is_safe_url(url):
        return None
    try:
        r = requests.get(url, headers=UA, timeout=12)
        r.raise_for_status()
        page = r.text[:400000]
    except Exception:
        return None
    meta = [v for k, v in _metas(page) if k in ("author", "article:author", "parsely-author", "dc.creator", "sailthru.author", "byl")]
    for mm in re.finditer(r'"author"\s*:', page):
        meta.append(page[mm.end() : mm.end() + 400].split('"publisher"')[0])
    hay = _html.unescape(" ".join(meta)).lower()
    if not hay.strip():  # لا بيانات مؤلف في الوسوم: نبحث في مطلع النص (سطر "By ...")
        art = _extract(r.content, r.encoding or r.apparent_encoding)
        hay = art["text"][:1500].lower()
    for nm in name_variants:
        toks = _name_tokens(nm)
        if toks and all(t in hay for t in toks):
            return True
    return False


def gnews_site_search(selected, days, terms=None, joiner="OR", author=None, author_he=None, country="US",
                      verify_author=True, max_items=60):
    """يبحث في مواقع محددة عبر أخبار Google (site:). selected: (label, domains, lang).
    terms: كلمات عربية تُترجم؛ author/author_he: اسم الكاتب بالإنجليزية/العبرية. يعيد (items, notes)"""
    items, notes = [], []
    loc_c = country if country in ("US", "UK", "IL") else "US"
    buckets = {
        "en": _split_domains([d for _, d, lg in selected if lg in ("en", "both")]),
        "he": _split_domains([d for _, d, lg in selected if lg in ("he", "both")]),
    }
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    names = [n for n in (author, author_he) if n]
    for lang, doms in buckets.items():
        if not doms:
            continue
        if lang == "he":
            who = author_he or (tr(author, "en", "iw") if author else "")
            code, loc = "iw", _GN_LOC["he"]["IL"]
            if who and who not in names:
                names.append(who)
        else:
            who = author or (tr(author_he, "iw", "en") if author_he else "")
            code, loc = "en", _GN_LOC["en"][loc_c]
            if who and who not in names:
                names.append(who)
        tparts = []
        for t in terms or []:
            x = t if (code == "en" and not _HAS_AR.search(t)) else tr(t, "ar", code)
            if x and not _HAS_AR.search(x):
                tparts.append(_quoted(x))
        if terms and not tparts:
            notes.append(f"تعذّرت ترجمة الكلمات إلى {'العبرية' if code == 'iw' else 'الإنجليزية'} — تخطّيتُ هذه اللغة")
            continue
        for i in range(0, len(doms), 8):
            chunk = doms[i : i + 8]
            parts = []
            if who:
                parts.append(_quoted(who))
            if tparts:
                parts.append("(" + " OR ".join(tparts) + ")" if joiner == "OR" and len(tparts) > 1 else " ".join(tparts))
            parts.append("(" + " OR ".join(f"site:{d}" for d in chunk) + ")")
            parts.append(f"when:{max(1, days)}d")
            q = " ".join(parts)
            try:
                got = _get_feed(gnews_url(q, *loc))
            except Exception as ex:
                notes.append(f"Google News ⟵ تعذّر ({type(ex).__name__}): {q[:100]}")
                continue
            n0 = len(items)
            for e in got:
                if not e["link"] or not e["title"] or not e["date"] or e["date"] < cutoff:
                    continue
                host = _host(e["source_url"]) or _host(e["link"])
                if e["source_url"] and not domain_match(host, [x.split("/")[0] for x in chunk]):
                    continue
                title = e["title"]
                if e["source_name"] and title.endswith(" - " + e["source_name"]):
                    title = title[: -len(e["source_name"]) - 3]
                a = {
                    "url": e["link"], "title": title, "seendate": e["date"].strftime("%Y%m%dT%H%M%SZ"),
                    "domain": host, "sourcecountry": COUNTRY_EN.get(loc_c, ""),
                    "language": "Hebrew" if lang == "he" else "English",
                }
                if author or author_he:
                    a.update({"writer": author or who, "writer_en": author or who,
                              "outlet": next((l for l, d, _ in selected if domain_match(host, d.split("|"))), host),
                              "wsrc": "search"})
                items.append(a)
            notes.append(f"Google News ⟵ {q[:110]} ⟵ {len(items) - n0}")
    seen, uniq = set(), []
    for a in sorted(items, key=lambda a: a["seendate"], reverse=True):
        k = re.sub(r"\W+", "", a["title"].lower())[:80]
        if k in seen:
            continue
        seen.add(k)
        uniq.append(a)
    uniq = uniq[:max_items]

    def dec(a):
        if "news.google.com" in a["url"]:
            real = decode_gnews(a["url"])
            if real != a["url"]:
                a["url"], a["domain"] = real, _host(real)
        return a

    with ThreadPoolExecutor(6) as ex:
        list(ex.map(dec, uniq))
    # الروابط التي تعذّر فكّها تبقى على news.google.com؛ نكتفي بما انحصر في المواقع المطلوبة أو لم يُعرف موقعه
    allowed = [x.split("/")[0] for x in _split_domains([d for _, d, _ in selected])]
    uniq = [a for a in uniq if "news.google.com" in a["domain"] or domain_match(a["domain"], allowed)]
    for a in uniq:
        a["ctype"], a["ctype_sure"] = classify(a["url"], a["title"])
    if (author or author_he) and verify_author:
        def chk(a):
            a["byline"] = None if "news.google.com" in a["url"] else check_byline(a["url"], names)
            return a
        with ThreadPoolExecutor(6) as ex:
            list(ex.map(chk, uniq[:40]))
    return uniq, notes


# ───────────────────────── تغطية بديلة مفتوحة لمقال مغلق ─────────────────────────

PAYWALLED = ("nytimes.com", "wsj.com", "ft.com", "economist.com", "washingtonpost.com", "haaretz.com", "haaretz.co.il",
             "thetimes.co.uk", "thetimes.com", "telegraph.co.uk", "bloomberg.com", "reuters.com", "foreignaffairs.com",
             "newyorker.com", "theatlantic.com", "wired.com")


def title_from_url(url):
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    slug = re.sub(r"\.(html?|php)$", "", slug)
    slug = re.sub(r"-?\d{4}-\d{2}-\d{2}$", "", slug)
    return " ".join(w for w in re.split(r"[-_]+", slug) if not w.isdigit())


def find_alternatives(title, exclude_domain="", days=10, want=6):
    """يبحث عن تغطية للموضوع نفسه في مواقع مفتوحة (غير مدفوعة) ويُبقي ما يُستخرج نصه كاملاً. يعيد (items, ملاحظة)"""
    q = re.sub(r"\s+[-|–]\s+[^-|–]{2,40}$", "", (title or "").strip())[:140]
    if len(q) < 8:
        return [], "لا يوجد عنوان كافٍ للبحث عن بدائل."
    loc = _GN_LOC["he"]["IL"] if _HEB.search(q) else _GN_LOC["en"]["US"]
    try:
        got = _get_feed(gnews_url(f"{q} when:{days}d", *loc))
    except Exception as e:
        return [], f"تعذّر البحث عن بدائل ({type(e).__name__})."
    skip = list(PAYWALLED) + ([exclude_domain] if exclude_domain else [])
    cands, seen = [], set()
    for e in got[:30]:
        host = _host(e["source_url"]) or ""
        if host and domain_match(host, skip):
            continue
        t = e["title"]
        if e["source_name"] and t.endswith(" - " + e["source_name"]):
            t = t[: -len(e["source_name"]) - 3]
        k = re.sub(r"\W+", "", t.lower())[:60]
        if not t or not e["link"] or k in seen:
            continue
        seen.add(k)
        cands.append({"url": e["link"], "title": t, "domain": host,
                      "seendate": e["date"].strftime("%Y%m%dT%H%M%SZ") if e["date"] else "",
                      "language": "Hebrew" if _HEB.search(t) else "English", "sourcecountry": ""})
    cands = cands[:16]

    def work(a):
        if "news.google.com" in a["url"]:
            real = decode_gnews(a["url"])
            if real == a["url"]:
                return None
            a["url"], a["domain"] = real, _host(real)
        if domain_match(a["domain"], skip):
            return None
        art = fetch_article(a["url"])
        if not art or len(art["text"]) < 1800:
            return None
        a["chars"] = len(art["text"])
        return a

    with ThreadPoolExecutor(6) as ex:
        ok = [a for a in ex.map(work, cands) if a]
    return ok[:want], f"فُحص {len(cands)} مرشحاً، منها {len(ok)} بنص كامل."


# ───────────────────────── تصفّح قسم من موقع (روابط الصفحة + عناوينها) ─────────────────────────


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self._href, self._buf = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href, self._buf = dict(attrs).get("href"), []

    def handle_data(self, d):
        if self._href is not None:
            self._buf.append(d)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._buf).split())))
            self._href = None


def browse_section(url, domains, limit=80):
    """يفتح صفحة قسم ويستخرج روابط المقالات وعناوينها. يعيد (items, خطأ)"""
    if not is_safe_url(url):
        return [], "رابط غير صالح."
    try:
        r = requests.get(url, headers=UA, timeout=20)
        r.raise_for_status()
    except Exception as e:
        return [], f"تعذّر فتح الصفحة مباشرة ({type(e).__name__}) — غالباً يحجب الموقع الزحف الآلي."
    p = _LinkParser()
    p.feed(r.text[:1500000])
    seen, out = set(), []
    for href, text in p.links:
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        full = urljoin(r.url, href).split("#")[0]
        if not full.startswith("http") or not domain_match(_host(full), domains):
            continue
        path = urlparse(full).path
        if len(text) < 25 or len(text.split()) < 3 or full in seen or full.rstrip("/") == r.url.rstrip("/"):
            continue
        if path.count("/") < 2 and not re.search(r"\d", path):
            continue
        seen.add(full)
        out.append({"url": full, "title": text, "seendate": "", "domain": _host(full), "sourcecountry": "",
                    "language": "Hebrew" if _HEB.search(text) else "English"})
    return out[:limit], ("" if out else "لم أجد روابط مقالات واضحة في الصفحة (قد تُحمَّل بالجافاسكربت).")


# ───────────────────────── تحليل رابط (خبر أو تغريدة) لإضافة مصدر/كاتب ─────────────────────────

TW_HOSTS = {"twitter.com", "x.com", "mobile.twitter.com", "t.co"}
FB_HOSTS = {"facebook.com", "m.facebook.com", "web.facebook.com", "mbasic.facebook.com", "fb.com", "fb.watch", "l.facebook.com"}
_META_RE = re.compile(r"<meta\s+([^>]+?)/?>", re.I)
_ATTR_RE = re.compile(r"([a-zA-Z_:\-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')")
_GENERIC_AUTH = re.compile(r"^(staff|editors?|admin|reuters|ap|afp|newsroom|editorial board|the .* staff)$", re.I)
_HEB = re.compile(r"[\u0590-\u05FF]")


def _metas(page):
    out = []
    for m in _META_RE.finditer(page[:300000]):
        attrs = {k.lower(): (v1 or v2) for k, v1, v2 in _ATTR_RE.findall(m.group(1))}
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        if key and "content" in attrs:
            out.append((key, _html.unescape(attrs["content"]).strip()))
    return out


def _clean_authors(raw, site_name):
    names = []
    for r in raw:
        r = re.sub(r"^\s*(by|מאת|بقلم)\s+", "", r, flags=re.I)
        for part in re.split(r"\s+and\s+|\s*&\s*|\s*;\s*|\s*،\s*|\s*,\s*", r):
            part = part.strip(" -–|")
            if (
                2 <= len(part) <= 60
                and "http" not in part
                and "@" not in part
                and part.lower() != (site_name or "").lower()
                and not _GENERIC_AUTH.match(part)
                and part not in names
            ):
                names.append(part)
    return names[:6]


def _tweet_info(url):
    u = re.sub(r"^https?://(www\.|mobile\.)?x\.com", "https://twitter.com", url.strip())
    r = requests.get(
        "https://publish.twitter.com/oembed", params={"url": u, "omit_script": "1", "dnt": "true"}, headers=UA, timeout=15
    )
    r.raise_for_status()
    j = r.json()
    h = j.get("html", "")
    m = re.search(r"<p[^>]*>(.*?)</p>", h, re.S)
    inner = m.group(1) if m else ""
    text = " ".join(_html.unescape(re.sub(r"<[^>]+>", " ", inner)).split())
    links = []
    for l in re.findall(r'href="(https?://[^"]+)"', inner)[:4]:
        try:
            rr = requests.get(l, headers=UA, allow_redirects=True, timeout=10, stream=True)
            final = rr.url
            rr.close()
        except Exception:
            final = l
        if _host(final) not in TW_HOSTS:
            links.append(final)
    author_url = j.get("author_url", "")
    return {"author": j.get("author_name", ""), "handle": author_url.rstrip("/").split("/")[-1], "text": text, "links": links}


def _fb_info(url):
    """يقرأ وسوم og من صفحة/منشور فيسبوك العام (بهوية زاحف فيسبوك) ويستخرج اسم الصفحة وأي رابط خارجي"""
    r = requests.get(url, headers={**UA, "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"}, timeout=15)
    r.raise_for_status()
    page = r.text[:400000]
    metas = _metas(page)
    get = lambda *keys: next((v for k, v in metas if k in keys and v), "")
    links = [unquote(m) for m in re.findall(r"https?://l\.facebook\.com/l\.php\?u=([^\"&\s]+)", page)]
    links += re.findall(r"https?://[^\s\"<>]+", get("og:description"))
    links = [u for u in links if _host(u) not in FB_HOSTS and is_safe_url(u)]
    return {"name": re.sub(r"\s*[\|\-–]\s*(Facebook|فيسبوك).*$", "", get("og:title", "twitter:title")).strip(), "links": links}


def analyze_url(url):
    """يحلل رابط خبر أو تغريدة ويستخرج: الموقع، اسمه، لغته، الكتّاب. يعيد dict (قد يحوي error)"""
    url = url.strip()
    out = {"error": None, "tweet": None, "article_url": url, "domain": "", "site_name": "", "title": "",
           "authors": [], "lang": "en", "group": "us"}
    if _host(url) in TW_HOSTS:
        try:
            tw = _tweet_info(url)
        except Exception as e:
            out["error"] = f"تعذّرت قراءة التغريدة ({type(e).__name__}). الصق رابط المقال نفسه بدلاً منها."
            return out
        out["tweet"] = tw
        if not tw["links"]:
            out["article_url"] = None
            if tw["author"]:
                out["authors"] = [{"raw": tw["author"], "src": f"حساب التغريدة @{tw['handle']}"}]
            out["error"] = "لا يوجد رابط مقال داخل التغريدة؛ يمكنك إضافة صاحب الحساب ككاتب وتحديد موقعه يدوياً."
            return out
        out["article_url"] = tw["links"][0]
    if _host(out["article_url"]) in FB_HOSTS:
        try:
            fb = _fb_info(out["article_url"])
        except Exception as e:
            out["error"] = f"تعذّرت قراءة رابط فيسبوك ({type(e).__name__}) — فيسبوك يحجب كثيراً من الصفحات. الصق رابط الخبر نفسه أو أدخل الموقع يدوياً."
            return out
        if fb["links"]:
            out["article_url"] = fb["links"][0]
        else:
            if fb["name"]:
                out["authors"] = [{"raw": fb["name"], "src": "اسم صفحة فيسبوك"}]
            out["article_url"] = None
            out["error"] = "لم أجد رابط خبر داخل المنشور (فيسبوك يخفي المحتوى عن الزحف). الصق رابط الخبر نفسه، أو أدخل دومين الموقع يدوياً."
            return out
    art = out["article_url"]
    if not is_safe_url(art):
        out["error"] = "رابط غير صالح."
        return out
    try:
        r = requests.get(art, headers=UA, timeout=20)
        r.raise_for_status()
    except Exception as e:
        out["error"] = f"تعذّر فتح الصفحة ({type(e).__name__})."
        out["domain"] = _host(art)
        out["site_name"] = out["domain"]
        return out
    page = r.text[:600000]
    out["article_url"] = r.url
    out["domain"] = _host(r.url)
    metas = _metas(page)
    get = lambda *keys: next((v for k, v in metas if k in keys and v), "")
    out["site_name"] = get("og:site_name", "application-name") or out["domain"]
    out["title"] = get("og:title", "twitter:title") or ""
    m = re.search(r"<html[^>]*\blang=[\"']?([a-zA-Z\-]+)", page[:3000], re.I)
    lang = (m.group(1) if m else get("og:locale")).lower()
    out["lang"] = "he" if lang.startswith(("he", "iw")) or out["domain"].endswith(".il") and _HEB.search(out["title"]) else "en"
    raw = [v for k, v in metas if k in ("author", "parsely-author", "dc.creator", "sailthru.author") and v]
    for mm in re.finditer(r'"author"\s*:', page[:400000]):
        seg = page[mm.end() : mm.end() + 500].split('"publisher"')[0]
        raw += re.findall(r'"name"\s*:\s*"([^"]{2,80})"', seg)[:3]
    names = _clean_authors([_html.unescape(x) for x in raw], out["site_name"])
    out["authors"] = [{"raw": n, "src": "من الصفحة"} for n in names]
    if out["tweet"] and out["tweet"]["author"] and out["tweet"]["author"] not in names:
        out["authors"].append({"raw": out["tweet"]["author"], "src": f"حساب التغريدة @{out['tweet']['handle']}"})
    dom = out["domain"]
    out["group"] = "il" if dom.endswith(".il") else ("uk" if dom.endswith((".uk", "bbc.com")) else "us")
    for a in out["authors"]:
        raw_n = a["raw"]
        if _HEB.search(raw_n):
            a["en"], a["ar"], a["heb"] = tr(raw_n, "iw", "en"), tr(raw_n, "iw", "ar"), True
        elif _HAS_AR.search(raw_n):
            a["en"], a["ar"], a["heb"] = tr(raw_n, "ar", "en"), raw_n, False
        else:
            a["en"], a["ar"], a["heb"] = raw_n, tr(raw_n, "en", "ar"), False
    return out


# ───────────────────────── التلخيص ─────────────────────────


def summarize(url, api_key=None):
    art = fetch_article(url)
    if not art:
        return "تعذّر جلب نص المقال (قد يكون خلف جدار اشتراك أو يحجب الزحف)."
    if api_key:
        prompt = (
            "لخّص المقال الإخباري التالي بالعربية الفصحى المبسّطة بأسلوب يناسب كتابة سكريبت أو تعليق إخباري مباشر:\n"
            "1) خمس إلى سبع نقاط مركّزة بأهم الوقائع والأرقام والأسماء.\n"
            "2) ثم فقرة قصيرة (3-4 جمل) بصياغة جاهزة للقراءة على الهواء.\n"
            "لا تضف معلومات من خارج النص.\n\n"
            f"العنوان: {art['title']}\n\nالنص:\n{art['text'][:12000]}"
        )
        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-sonnet-5-5", "max_tokens": 900, "messages": [{"role": "user", "content": prompt}]},
                timeout=90,
            )
            r.raise_for_status()
            return "".join(b.get("text", "") for b in r.json().get("content", []))
        except Exception as e:
            return f"فشل التلخيص عبر Claude: {e}"
    sentences = re.split(r"(?<=[.!?])\s+", art["text"])[:5]
    return "ملخص مبسّط (أول جمل المقال مترجمة — أضف ANTHROPIC_API_KEY لتلخيص ذكي):\n\n" + tr(
        " ".join(sentences), "auto", "ar"
    )


# ───────────────────────── القراءة الصوتية (TTS) ─────────────────────────

try:  # أصوات مايكروسوفت العصبية (جودة عالية). إن لم تتوفر الحزمة يُستخدم صوت Google البديل
    import edge_tts as _edge_tts
except Exception:
    _edge_tts = None

VOICES = {
    "سلمى — مصرية (أنثى)": "ar-EG-SalmaNeural",
    "شاكر — مصري (ذكر)": "ar-EG-ShakirNeural",
    "حامد — سعودي (ذكر)": "ar-SA-HamedNeural",
    "زارية — سعودية (أنثى)": "ar-SA-ZariyahNeural",
    "فاطمة — إماراتية (أنثى)": "ar-AE-FatimaNeural",
    "حمدان — إماراتي (ذكر)": "ar-AE-HamdanNeural",
}
TTS_MAX_CHARS = 30000


def clean_for_tts(text):
    t = re.sub(r"https?://\S+", " ", text or "")
    t = re.sub(r"[\*\#_`>|\[\]{}<]+", " ", t)
    t = re.sub(r"\s*\n+\s*", ". ", t)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"(\s*[.،]\s*){2,}", ". ", t)
    return t.strip()


def split_for_tts(text, limit):
    """يقسّم النص إلى قطع لا تتجاوز limit عند حدود الجمل"""
    sents = re.split(r"(?<=[.!?؟…])\s+", text)
    chunks, cur = [], ""
    for s_ in sents:
        while len(s_) > limit:  # جملة طويلة جداً: قصّها عند أقرب مسافة
            cut = s_.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(s_[:cut])
            s_ = s_[cut:].strip()
        if not s_:
            continue
        if cur and len(cur) + len(s_) + 1 > limit:
            chunks.append(cur)
            cur = s_
        else:
            cur = f"{cur} {s_}" if cur else s_
    if cur:
        chunks.append(cur)
    return chunks


def _edge_chunk(text, voice, rate_str):
    import asyncio

    async def run():
        comm = _edge_tts.Communicate(text, voice, rate=rate_str)
        buf = bytearray()
        async for ch in comm.stream():
            if ch["type"] == "audio":
                buf += ch["data"]
        if not buf:
            raise RuntimeError("لم يصل صوت")
        return bytes(buf)

    last = None
    for _ in range(3):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(run())
        except Exception as e:
            last = e
            time.sleep(1.0)
        finally:
            loop.close()
    raise last


def _google_chunk(text):
    last = None
    for _ in range(2):
        try:
            r = requests.get(
                "https://translate.google.com/translate_tts",
                params={"ie": "UTF-8", "q": text, "tl": "ar", "client": "tw-ob"},
                headers=UA,
                timeout=20,
            )
            r.raise_for_status()
            if "audio" not in r.headers.get("content-type", ""):
                raise ValueError("الرد ليس صوتاً")
            return r.content
        except Exception as e:
            last = e
            time.sleep(0.8)
    raise last


def tts(text, voice="ar-EG-SalmaNeural", rate=0):
    """يحوّل نصاً عربياً إلى MP3. يعيد (bytes، المحرك، ملاحظة). يرفع RuntimeError عند فشل كل المحركات."""
    text = clean_for_tts(text)
    note = ""
    if len(text) > TTS_MAX_CHARS:
        text = text[:TTS_MAX_CHARS]
        note = f"اقتُطع النص عند {TTS_MAX_CHARS} حرفاً (نحو ساعتين) — قلّل المحتوى لقراءته كاملاً. "
    if not text:
        raise RuntimeError("لا يوجد نص للقراءة")
    err = ""
    if _edge_tts is not None:
        try:
            rate_str = f"{int(rate):+d}%"
            chunks = split_for_tts(text, 2400)
            with ThreadPoolExecutor(3) as ex:
                parts = list(ex.map(lambda c: _edge_chunk(c, voice, rate_str), chunks))
            return b"".join(parts), "edge", note
        except Exception as e:
            err = f"{type(e).__name__}"
    cut = text[:6000]
    if len(text) > 6000:
        note += "الصوت البديل يقرأ أول 6000 حرف فقط. "
    chunks = split_for_tts(cut, 180)
    with ThreadPoolExecutor(6) as ex:
        parts = list(ex.map(_google_chunk, chunks))
    why = f"تعذّر الصوت العصبي ({err})" if err else "الصوت العصبي غير مثبّت"
    return b"".join(parts), "google", f"{why}؛ استُخدم صوت Google (أبسط ولا يدعم تغيير السرعة). " + note
