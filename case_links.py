# -*- coding: utf-8 -*-
"""محرك ربط الملفات البحثية: اقتراحات قابلة للتفسير، دون ادعاء السببية."""
from __future__ import annotations
import re
from collections import Counter
from datetime import datetime, timezone

STOP = {
    "في", "من", "على", "عن", "الى", "إلى", "مع", "بين", "بعد", "قبل", "حول", "هذا", "هذه", "ذلك", "تلك", "التي", "الذي", "هو", "هي", "كان", "كانت", "يكون", "يمكن", "قد", "تم", "كما", "لكن", "أو", "و", "the", "and", "for", "with", "from", "that", "this", "are", "was", "were", "has", "have", "into", "over", "after", "before", "about", "their", "its", "will", "would", "could", "should", "report", "news", "analysis", "article", "ملف", "خبر", "اخبار", "غير", "محدد", "مصدر", "صحيفة", "مقال"
}
# كيانات وأسماء شائعة بصيغ عربية وإنجليزية. هذه قائمة مساعدة قابلة للتوسيع وليست NER شاملاً.
ENTITY_ALIASES = {
    "إيران": ["إيران", "ايران", "iran", "iranian", "tehran"],
    "الولايات المتحدة": ["الولايات المتحدة", "أمريكا", "امريكا", "واشنطن", "united states", "u.s.", "us government", "washington"],
    "إسرائيل": ["إسرائيل", "اسرائيل", "israel", "israeli", "تل أبيب", "تل ابيب", "tel aviv"],
    "مصر": ["مصر", "القاهرة", "egypt", "egyptian", "cairo"],
    "السعودية": ["السعودية", "الرياض", "saudi arabia", "saudi", "riyadh"],
    "الإمارات": ["الإمارات", "الامارات", "أبوظبي", "ابوظبي", "uae", "emirates", "abu dhabi"],
    "قطر": ["قطر", "الدوحة", "qatar", "doha"],
    "تركيا": ["تركيا", "أنقرة", "انقرة", "turkey", "turkish", "ankara"],
    "روسيا": ["روسيا", "موسكو", "russia", "russian", "moscow"],
    "الصين": ["الصين", "بكين", "china", "chinese", "beijing"],
    "أوكرانيا": ["أوكرانيا", "اوكرانيا", "ukraine", "ukrainian", "kyiv", "كييف"],
    "السودان": ["السودان", "الخرطوم", "دارفور", "sudan", "sudanese", "khartoum", "darfur"],
    "اليمن": ["اليمن", "صنعاء", "عدن", "yemen", "yemeni", "sanaa", "aden"],
    "غزة": ["غزة", "قطاع غزة", "gaza"],
    "حماس": ["حماس", "hamas"],
    "حزب الله": ["حزب الله", "hezbollah", "hizbullah"],
    "الحوثيون": ["الحوثيون", "الحوثي", "أنصار الله", "انصار الله", "houthi", "ansar allah"],
    "البحر الأحمر": ["البحر الأحمر", "البحر الاحمر", "red sea"],
    "باب المندب": ["باب المندب", "bab el-mandeb", "bab al-mandab", "mandeb strait"],
    "قناة السويس": ["قناة السويس", "suez canal"],
    "الناتو": ["الناتو", "حلف شمال الأطلسي", "nato", "north atlantic treaty organization"],
    "الاتحاد الأوروبي": ["الاتحاد الأوروبي", "الاتحاد الاوروبي", "eu", "european union", "brussels"],
    "الأمم المتحدة": ["الأمم المتحدة", "الامم المتحدة", "united nations", "un", "unsc", "مجلس الأمن", "مجلس الامن"],
    "ليبيا": ["ليبيا", "طرابلس", "بنغازي", "libya", "libyan", "tripoli", "benghazi"],
    "العراق": ["العراق", "بغداد", "iraq", "iraqi", "baghdad"],
    "لبنان": ["لبنان", "بيروت", "lebanon", "lebanese", "beirut"],
    "الصومال": ["الصومال", "مقديشو", "somalia", "somali", "mogadishu"],
    "إثيوبيا": ["إثيوبيا", "اثيوبيا", "أديس أبابا", "اثيوبيا", "ethiopia", "ethiopian", "addis ababa"],
    "إريتريا": ["إريتريا", "اريتريا", "eritrea", "eritrean"],
    "جيبوتي": ["جيبوتي", "djibouti"],
    "البنك الدولي": ["البنك الدولي", "world bank"],
    "صندوق النقد الدولي": ["صندوق النقد الدولي", "imf", "international monetary fund"],
}


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def norm(text):
    text = str(text or "").lower()
    text = re.sub(r"[أإآٱ]", "ا", text)
    text = re.sub(r"ى", "ي", text)
    text = re.sub(r"ة", "ه", text)
    text = re.sub(r"ـ", "", text)
    text = re.sub(r"[^\w\u0600-\u06ff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(text):
    return {x for x in norm(text).split() if len(x) > 2 and x not in STOP and not x.isdigit()}


def _contains(text, alias):
    t, a = norm(text), norm(alias)
    if not t or not a:
        return False
    if " " in a:
        # بعض صيغ العربية تلصق الواو/الباء/اللام بأول الكلمة: والبحر الأحمر.
        words = a.split()
        source = t.split()
        if len(words) > len(source):
            return False
        for i in range(len(source) - len(words) + 1):
            first = source[i]
            if first not in {words[0], "و" + words[0], "ب" + words[0], "ل" + words[0], "ف" + words[0]}:
                continue
            if source[i + 1:i + len(words)] == words[1:]:
                return True
        return False
    return re.search(rf"(?<![\w]){re.escape(a)}(?![\w])", t) is not None


def extract_entities(text):
    found = []
    for canonical, aliases in ENTITY_ALIASES.items():
        if any(_contains(text, alias) for alias in aliases):
            found.append(canonical)
    return found


def case_text(case):
    parts = [case.get("title", ""), case.get("description", ""), " ".join(case.get("tags", [])), case.get("research_notes", "")]
    for m in case.get("materials", []):
        parts.extend([m.get("title", ""), m.get("text", "")])
    for c in case.get("claims", []):
        parts.append(c.get("statement", ""))
    for e in case.get("events", []):
        parts.extend([e.get("title", ""), e.get("detail", "")])
    return "\n".join(str(x) for x in parts if x)


def _case_terms(case):
    tag_terms = set()
    for tag in case.get("tags", []):
        tag_terms |= tokens(tag)
    title_desc = tokens(case.get("title", "") + " " + case.get("description", ""))
    full = tokens(case_text(case))
    # المصطلحات المميزة في الوسوم والعنوان أعلى وزناً من الكلمات العامة داخل النصوص.
    return tag_terms, title_desc, full


def compare_cases(a, b):
    ta, da, fa = _case_terms(a)
    tb, db, fb = _case_terms(b)
    ent_a, ent_b = set(extract_entities(case_text(a))), set(extract_entities(case_text(b)))
    shared_entities = sorted(ent_a & ent_b)
    shared_tags = sorted(ta & tb)
    shared_title_terms = sorted(da & db)
    shared_content = sorted((fa & fb) - set(shared_entities))
    # مقياس إرشادي لا يمثل احتمالاً إحصائياً ولا حكماً على وجود علاقة سببية.
    score = min(100, len(shared_entities) * 17 + len(shared_tags) * 12 + len(shared_title_terms) * 5 + min(len(shared_content), 8) * 2)
    reasons = []
    if shared_entities:
        reasons.append("كيانات مشتركة: " + "، ".join(shared_entities[:10]))
    if shared_tags:
        reasons.append("وسوم مشتركة: " + "، ".join(shared_tags[:10]))
    if shared_title_terms:
        reasons.append("مصطلحات مشتركة في العناوين/الوصف: " + "، ".join(shared_title_terms[:10]))
    if shared_content:
        reasons.append("مفردات مشتركة في المواد: " + "، ".join(shared_content[:12]))
    # أمثلة ملموسة من المواد التي تحمل الكيان المشترك.
    examples = []
    for ent in shared_entities[:5]:
        left = [m.get("title", "") for m in a.get("materials", []) if ent in extract_entities(m.get("title", "") + " " + m.get("text", ""))]
        right = [m.get("title", "") for m in b.get("materials", []) if ent in extract_entities(m.get("title", "") + " " + m.get("text", ""))]
        if left or right:
            examples.append({"entity": ent, "case_a_materials": left[:3], "case_b_materials": right[:3]})
    if len(shared_entities) >= 2 or (shared_entities and (shared_tags or shared_title_terms)) or len(shared_tags) >= 2:
        level = "قوي" if score >= 55 else "متوسط"
    elif score >= 18:
        level = "ضعيف"
    else:
        level = "غير كافٍ"
    return {"score": score, "level": level, "shared_entities": shared_entities,
            "shared_tags": shared_tags, "shared_title_terms": shared_title_terms,
            "shared_content_terms": shared_content[:20], "reasons": reasons,
            "evidence_examples": examples,
            "caveat": "هذا تشابه موضوعي قابل للمراجعة، ولا يثبت علاقة سببية أو تنسيقاً أو ارتباطاً مباشراً بين القضيتين."}


def suggest_links(cases, min_score=18):
    out = []
    cases = list(cases or [])
    for i, a in enumerate(cases):
        for b in cases[i + 1:]:
            if not a.get("id") or not b.get("id") or a.get("id") == b.get("id"):
                continue
            detail = compare_cases(a, b)
            if detail["score"] < min_score:
                continue
            out.append({"id": f"link_{a['id']}_{b['id']}", "case_a": a["id"], "case_b": b["id"],
                        "title_a": a.get("title", ""), "title_b": b.get("title", ""),
                        "status": "suggested", "created_at": now_iso(), **detail})
    out.sort(key=lambda x: (-x["score"], x["title_a"], x["title_b"]))
    return out


def merge_suggestions(existing, fresh):
    """يحافظ على قرارات المستخدم السابقة ويحدّث الاقتراحات غير المحسومة."""
    old = {(x.get("case_a"), x.get("case_b")): x for x in (existing or [])}
    result = []
    for item in fresh:
        key = (item.get("case_a"), item.get("case_b"))
        prior = old.get(key) or old.get((key[1], key[0]))
        if prior and prior.get("status") in {"accepted", "rejected"}:
            result.append({**item, "id": prior.get("id", item["id"]), "status": prior["status"],
                           "user_note": prior.get("user_note", ""), "reviewed_at": prior.get("reviewed_at")})
        else:
            result.append(item)
    # لا نحذف الروابط اليدوية المقبولة حتى لو لم تعد تظهر ضمن العتبة.
    present = {(x.get("case_a"), x.get("case_b")) for x in result}
    for item in existing or []:
        key = (item.get("case_a"), item.get("case_b"))
        if item.get("status") in {"accepted", "rejected"} and key not in present:
            result.append(item)
    return result


def set_status(links, link_id, status, note=""):
    if status not in {"accepted", "rejected", "suggested"}:
        raise ValueError("حالة الربط غير صالحة")
    changed = False
    for item in links:
        if item.get("id") == link_id:
            item["status"] = status
            item["user_note"] = note.strip()
            item["reviewed_at"] = now_iso()
            changed = True
            break
    return changed


def create_manual_link(a, b, note=""):
    if not a or not b or a.get("id") == b.get("id"):
        raise ValueError("اختار ملفين مختلفين")
    detail = compare_cases(a, b)
    return {"id": f"manual_{a['id']}_{b['id']}", "case_a": a["id"], "case_b": b["id"],
            "title_a": a.get("title", ""), "title_b": b.get("title", ""), "status": "accepted",
            "manual": True, "user_note": note.strip(), "created_at": now_iso(), **detail}



def build_link_prompt(a, b, link):
    """برومبت لاختبار طبيعة التقاطع بين ملفين اعتماداً على موادهما المحفوظة."""
    def pack(case):
        rows = [f"الملف: {case.get('title', '')}", f"الوصف: {case.get('description', '')}",
                "الوسوم: " + "، ".join(case.get("tags", []))]
        for i, m in enumerate(case.get("materials", []), 1):
            rows.append(f"مادة {i}: {m.get('title', '')}\nالنوع: {m.get('type', '')} | الكاتب: {m.get('author', '')} | المنبر: {m.get('outlet', '')} | التاريخ: {m.get('date', '')}\nالرابط: {m.get('url', '')}\nالنص المتاح: {m.get('text', '') or 'لا يوجد نص محفوظ؛ لا تستنتج من العنوان وحده.'}")
        if case.get("claims"):
            rows.append("الادعاءات المسجلة:")
            rows.extend(f"- {x.get('statement')} | النوع: {x.get('type')} | حالة الدليل: {x.get('status')} | المصدر: {x.get('source', '')}" for x in case["claims"])
        if case.get("events"):
            rows.append("الأحداث المسجلة:")
            rows.extend(f"- {x.get('date')}: {x.get('title')} | {x.get('detail')} | المصدر: {x.get('source', '')}" for x in case["events"])
        return "\n".join(rows)

    reasons = "\n".join("- " + x for x in link.get("reasons", [])) or "لا توجد أسباب آلية كافية؛ العلاقة أُنشئت يدوياً."
    return f"""أنت باحث في العلاقات الدولية ومحلل مصادر مفتوحة. اختبر التقاطع بين ملفين بحثيين دون افتراض وجود علاقة سببية أو تنسيق بينهما.

## الملف الأول
{pack(a)}

## الملف الثاني
{pack(b)}

## أسباب اقتراح الربط
{reasons}
درجة التشابه الآلية الإرشادية: {link.get('score', 0)}/100 ({link.get('level', 'غير محدد')})
ملاحظة الباحث: {link.get('user_note', 'لا توجد')}

## المطلوب
1. اشرح بدقة ما الذي يجعل الملفين متقاطعين، وما الذي قد يكون مجرد تشابه أسماء أو سياق إقليمي واسع.
2. أنشئ جدولاً للكيانات والأحداث والمصالح المشتركة، مع رابط كل نقطة بمادة محددة من الملفين.
3. فرّق بين: تقاطع موضوعي، علاقة زمنية، اعتماد أحد الحدثين على الآخر، علاقة مؤسسية موثقة، وفرضية تحتاج اختباراً.
4. اختبر ثلاث فرضيات على الأقل: وجود صلة مباشرة، وجود تأثير غير مباشر، وعدم وجود صلة تتجاوز السياق العام.
5. ابحث عن أدلة تؤيد كل فرضية وأدلة تنقضها، ولا تكتفِ بالأدلة المؤيدة.
6. افحص التسلسل الزمني: هل سبق الحدث في الملف الأول الحدث في الملف الثاني؟ وهل يوجد دليل على آلية تأثير، أم مجرد تعاقب زمني؟
7. افصل الوقائع المثبتة عن الادعاءات المنسوبة والتحليلات والتوقعات.
8. حدد المواد الناقصة والوثائق الأولية أو البيانات المستقلة التي يمكن أن تحسم طبيعة العلاقة.
9. قدم حكماً مشروطاً: ما نوع العلاقة التي تدعمها الأدلة الحالية؟ وما درجة الثقة ولماذا؟

قواعد صارمة:
- لا تخترع معلومات أو روابط أو اقتباسات.
- لا تعتبر تشابه الكيانات دليلاً على السببية أو التنسيق.
- لا تعتبر إعادة نشر الادعاء من عدة مواقع تحققاً مستقلاً إذا كانت جميعها تنقل عن أصل واحد.
- إذا كان نص المادة غير متاح، صرّح بذلك ولا تحلل ما لا تراه.
- استخدم روابط المصادر الأصلية، واذكر بوضوح ما لا يمكن حسمه من البيانات الحالية.
"""


def graph_data(cases, links, include_suggested=False):
    nodes = [{"id": c.get("id"), "label": c.get("title", "ملف"),
              "materials": len(c.get("materials", []))} for c in cases]
    edges = []
    valid_ids = {x.get("id") for x in nodes}
    for link in links:
        if link.get("case_a") not in valid_ids or link.get("case_b") not in valid_ids:
            continue
        if link.get("status") == "accepted" or (include_suggested and link.get("status") == "suggested"):
            edges.append({"source": link.get("case_a"), "target": link.get("case_b"),
                          "label": f"{link.get('score', 0)} · {link.get('level', '')}",
                          "status": link.get("status"), "reasons": link.get("reasons", [])})
    return {"nodes": nodes, "edges": edges}
