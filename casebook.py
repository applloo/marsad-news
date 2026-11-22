# -*- coding: utf-8 -*-
"""مركز الملفات البحثية: تجميع مواد القضية، الخط الزمني، سجل الادعاءات، وخريطة الخلاف."""
from __future__ import annotations
from datetime import datetime, timezone
from urllib.parse import urlparse

MATERIAL_TYPES = ["خبر", "تصريح", "مقال رأي", "تحليل", "وثيقة", "بيان رسمي", "بحث / تقرير"]
CLAIM_TYPES = ["واقعة قابلة للتحقق", "ادعاء منسوب", "تفسير / تحليل", "توقع", "رأي / حكم قيمي"]
EVIDENCE_STATUSES = ["موثق بمصدر أولي", "مدعوم بمصادر مستقلة", "منسوب لمصدر واحد", "متنازع عليه", "غير متحقق بعد"]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _id(prefix):
    return f"{prefix}_{int(datetime.now(timezone.utc).timestamp() * 1000000)}"


def domain(url):
    try:
        return (urlparse(url or "").hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def new_case(title, description="", tags=None):
    stamp = now_iso()
    return {
        "id": _id("case"), "title": title.strip(), "description": description.strip(),
        "tags": list(tags or []), "created_at": stamp, "updated_at": stamp,
        "materials": [], "claims": [], "events": [], "research_notes": "",
    }


def add_material(case, article, material_type="خبر", stance="", note=""):
    article = dict(article or {})
    url = (article.get("url") or article.get("link") or "").strip()
    title = (article.get("title_ar") or article.get("title") or article.get("headline") or "مادة بلا عنوان").strip()
    key = url or (title + "|" + str(article.get("date") or article.get("seendate") or ""))
    if any(x.get("key") == key for x in case.setdefault("materials", [])):
        return False
    item = {
        "id": _id("mat"), "key": key, "type": material_type,
        "title": title, "author": article.get("writer") or article.get("author") or "غير محدد",
        "outlet": article.get("outlet") or article.get("source") or article.get("domain") or domain(url) or "غير محدد",
        "domain": article.get("domain") or domain(url), "date": article.get("date") or article.get("seendate") or "",
        "url": url, "text": article.get("text") or article.get("full_text") or article.get("summary") or article.get("snip_ar") or "",
        "stance": stance, "note": note, "added_at": now_iso(),
    }
    case["materials"].append(item)
    case["updated_at"] = now_iso()
    return True


def add_claim(case, statement, claim_type="واقعة قابلة للتحقق", status="غير متحقق بعد", source="", note=""):
    statement = (statement or "").strip()
    if not statement:
        raise ValueError("نص الادعاء مطلوب")
    claim = {"id": _id("claim"), "statement": statement, "type": claim_type, "status": status,
             "source": (source or "").strip(), "note": (note or "").strip(), "created_at": now_iso()}
    case.setdefault("claims", []).append(claim)
    case["updated_at"] = now_iso()
    return claim


def add_event(case, date, title, detail="", source=""):
    title = (title or "").strip()
    if not title:
        raise ValueError("عنوان الحدث مطلوب")
    event = {"id": _id("event"), "date": (date or "غير محدد").strip(), "title": title,
             "detail": (detail or "").strip(), "source": (source or "").strip(), "created_at": now_iso()}
    case.setdefault("events", []).append(event)
    case["updated_at"] = now_iso()
    return event


def remove_item(case, collection, item_id):
    if collection not in {"materials", "claims", "events"}:
        return False
    before = len(case.get(collection, []))
    case[collection] = [x for x in case.get(collection, []) if x.get("id") != item_id]
    if len(case[collection]) != before:
        case["updated_at"] = now_iso()
        return True
    return False


def build_prompt(case):
    materials = case.get("materials", [])
    claims = case.get("claims", [])
    events = sorted(case.get("events", []), key=lambda x: (x.get("date") or "9999", x.get("created_at") or ""))
    mats = []
    for i, m in enumerate(materials, 1):
        mats.append(
            f"[{i}] النوع: {m.get('type')} | العنوان: {m.get('title')}\n"
            f"الكاتب: {m.get('author')} | المنبر: {m.get('outlet')} | الدومين: {m.get('domain')}\n"
            f"التاريخ: {m.get('date')} | الرابط الأصلي: {m.get('url')}\n"
            f"موقف/زاوية مضافة يدوياً: {m.get('stance') or 'غير محدد'} | ملاحظة: {m.get('note') or 'لا توجد'}\n"
            f"النص أو الملخص المتاح: {m.get('text') or 'لا يوجد نص محفوظ؛ لا تستنتج محتوى المادة من عنوانها وحده.'}"
        )
    clm = "\n".join(f"- {c.get('statement')} | التصنيف: {c.get('type')} | حالة الدليل: {c.get('status')} | المصدر: {c.get('source') or 'غير مرفق'} | ملاحظة: {c.get('note') or 'لا توجد'}" for c in claims) or "لا يوجد سجل ادعاءات مدخل يدوياً. استخرج الادعاءات من المواد مع إبقائها غير متحققة حتى فحصها."
    timeline = "\n".join(f"- {e.get('date')}: {e.get('title')} | {e.get('detail')} | المصدر: {e.get('source') or 'غير مرفق'}" for e in events) or "لا يوجد خط زمني مدخل يدوياً؛ استخرج الأحداث المؤرخة من المواد فقط مع ذكر مصدر كل تاريخ."
    return f"""أنت فريق بحث وتحليل إعلامي وسياسي يعمل على ملف بحثي متعدد المصادر. أنجز تحليلاً موثقاً ومتوازناً للقضية التالية، ولا تتعامل مع المواد المرفقة كأنها صحيحة تلقائياً.

عنوان الملف: {case.get('title', 'ملف بلا عنوان')}
وصف القضية ونطاقها: {case.get('description') or 'غير محدد'}
الوسوم: {', '.join(case.get('tags', [])) or 'لا توجد'}
ملاحظات الباحث: {case.get('research_notes') or 'لا توجد'}

المواد المجمعة ({len(materials)}):
{chr(10).join(mats) if mats else 'لا توجد مواد مرفقة.'}

سجل الادعاءات الذي أدخله الباحث:
{clm}

أحداث الخط الزمني المدخلة:
{timeline}

أخرج التقرير بالأقسام التالية:
1. ملخص تنفيذي: ما القضية؟ ما الذي نعرفه؟ وما الذي لا نعرفه؟
2. خريطة مصادر: صنّف المواد إلى أخبار، تصريحات، رأي، تحليل، وثائق، وبيانات. وضّح حدود العينة والفجوات الجغرافية والزمنية.
3. سجل الوقائع والادعاءات: جدول يضم الادعاء، نوعه (واقعة/ادعاء منسوب/تفسير/توقع/رأي)، من قاله، المصدر الأصلي، حالة التحقق، وما يلزم للتحقق.
4. فصل الحقيقة عن التفسير: لا تصف الرأي أو التوقع بأنه واقعة. انسب كل ادعاء إلى قائله.
5. الخط الزمني: رتب الأحداث بالتاريخ، واربط كل حدث بمصدره. ميّز تاريخ الحدث عن تاريخ نشر المادة.
6. خريطة الأطراف: الدول والمؤسسات والشخصيات، مصالحها المعلنة والمحتملة، وما هو موثق وما هو استنتاج.
7. خريطة المواقف: قارن مواقف الصحف والكتّاب والمحللين، مع فصل رأي الكاتب عن الخط التحريري للمؤسسة. لا تختزل المؤسسات في يمين/يسار إذا كان الوصف غير دقيق.
8. نقاط الاتفاق والاختلاف: حدد الاتفاق على الوقائع، والاختلاف في تفسيرها، والاختلاف في التوقعات أو المصالح.
9. مصفوفة التناقضات: الادعاءان المتعارضان، مصدر كل منهما، هل التعارض مباشر أم زمني أم اصطلاحي أم تفسيري، وما الذي يحسمه.
10. استقلال المصادر: اكشف إن كانت عدة مواد تكرر مصدراً أصلياً واحداً؛ لا تعتبر التكرار تأكيداً مستقلاً.
11. الفرضيات والتفسيرات البديلة: اعرض أقوى تفسير بديل، والأدلة التي تدعمه أو تضعفه، دون تخمين النوايا.
12. ما الذي يحتاج تحققاً إضافياً؟ اقترح وثائق أولية وبيانات رسمية ومصادر مستقلة محددة النوع.
13. تقدير الثقة: قيّم كل استنتاج على حدة (مرتفع/متوسط/منخفض) مع سبب واضح، ولا تمنح درجة ثقة كلية مضللة.
14. خلاصة الباحث: استنتاج مشروط بالأدلة الحالية، وأسئلة مفتوحة، وما الذي قد يغير الاستنتاج.

قواعد صارمة:
- لا تخترع وقائع أو اقتباسات أو روابط أو سيراً ذاتية أو معلومات ملكية وتمويل.
- لا تعتبر ملخصاً آلياً أو عنواناً بديلاً عن النص الكامل.
- لا تخلط بين الارتباط الزمني والسببية.
- لا تعتبر تعدد المقالات تعدداً للمصادر إذا كانت جميعها تنقل عن أصل واحد.
- اذكر بوضوح عندما تكون البيانات ناقصة أو متضاربة.
- استخدم لغة عربية واضحة، وجداول عملية، وروابط المواد الأصلية حيث تتوفر.
"""
