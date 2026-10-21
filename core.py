# -*- coding: utf-8 -*-
"""منطق البحث والترجمة (بدون Streamlit) - يعتمد على GDELT DOC 2.0 API"""
import ipaddress
import json
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from html.parser import HTMLParser

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
}
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


def build_term(term, code, match):
    x = tr(term, "ar", code)
    if _HAS_AR.search(x):
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
    words = clean_words(x, code, 3)  # AND
    return " ".join(words)


def build_query(terms, code, joiner, match):
    parts = [p for p in (build_term(t, code, match) for t in terms) if p]
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


def gdelt_call(query, start_utc, end_utc, max_rec):
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": max_rec,
        "sort": "DateDesc",
        "startdatetime": start_utc.strftime("%Y%m%d%H%M%S"),
        "enddatetime": end_utc.strftime("%Y%m%d%H%M%S"),
    }
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


def run_search(terms, joiner, match, jobs, start_utc, end_utc, max_rec, ctype, progress=None):
    n = min(250, max_rec * 3) if ctype != "الكل" else min(250, max_rec)
    found, errors, used = {}, [], []
    state = {"first": True}

    def call(full, label="", count=n):
        if not state["first"]:
            time.sleep(5.2)  # حد GDELT: طلب واحد كل 5 ثوانٍ
        state["first"] = False
        used.append(label + full)
        if progress:
            progress(f"جارٍ البحث: {full[:140]}")
        arts, err = gdelt_call(full, start_utc, end_utc, count)
        used[-1] += f"   ⟵ {len(arts)} نتيجة"
        if err:
            errors.append(f"{full[:160]}: {err}")
        return arts

    for job in jobs:
        try:
            q = build_query(terms, job["code"], joiner, match)
        except TranslationError as e:
            errors.append(f"{e} — أعد المحاولة بعد لحظات.")
            continue
        if not q:
            continue
        doms = job.get("domains")
        if not doms:
            got = call(f"{q} {job['extra']}".strip())
        else:
            got = list(call(f"{q} {job['extra']}"))
            if not got:  # خطة بديلة 1: دفعات أصغر من المواقع
                for i in range(0, min(len(doms), 32), 4):
                    got += call(f"{q} {domain_expr(doms[i:i + 4])}", "↳ دفعة: ")
            if not got and job.get("country"):  # خطة بديلة 2: فلتر البلد/اللغة ثم تصفية المواقع محلياً
                arts = call(f"{q} sourcecountry:{job['country']} sourcelang:{job['lang']}", "↳ بلد: ", 250)
                got = [a for a in arts if domain_match(a.get("domain", ""), doms)]
        for a in got:
            found.setdefault(a.get("url"), a)
    items = []
    for a in found.values():
        a["ctype"], a["ctype_sure"] = classify(a.get("url", ""), a.get("title", ""))
        if ctype == "الكل" or a["ctype"] == ctype:
            items.append(a)
    items.sort(key=lambda a: a.get("seendate", ""), reverse=True)
    return items[:max_rec], errors, used


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
    if code == "iw" and len(w) > 3 and w[0] == "ה":
        w = w[1:]
    return w[:5] if len(w) > 5 else w


def make_matchers(terms, codes):
    """لكل عبارة: قائمة بدائل (واحد لكل لغة) من جذور الكلمات"""
    out = []
    for t in terms:
        alts = []
        for code in dict.fromkeys(codes):
            words = clean_words(tr(t, "ar", code), code, 3)
            stems = [_stem(w, code) for w in words]
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
