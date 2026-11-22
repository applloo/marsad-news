# -*- coding: utf-8 -*-
"""مركز الإنذار المبكر: رصد تغيّر المواد والكيانات واللغة مع سجل قابل للمراجعة."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import re

try:
    import case_links
except Exception:  # يسمح بالاختبار أو التشغيل كحزمة مستقلة
    case_links = None

ESCALATION = {
    "تصعيد": ["تصعيد", "هجوم", "ضربة", "قصف", "اجتياح", "تهديد", "إنذار", "تعبئة", "حشد عسكري", "عملية عسكرية", "escalation", "strike", "attack", "invasion", "threat", "mobilization"],
    "تهدئة": ["تهدئة", "خفض التصعيد", "وقف إطلاق النار", "هدنة", "استئناف المفاوضات", "اتفاق", "انسحاب", "de-escalation", "ceasefire", "truce", "talks", "withdrawal"],
    "تشدد خطابي": ["لن نسمح", "خط أحمر", "رد حاسم", "ثمن باهظ", "سحق", "تدمير", "لن نتراجع", "red line", "decisive response", "crush", "destroy"],
    "انفتاح دبلوماسي": ["محادثات", "حوار", "مبادرة", "وساطة", "لقاء", "اتصال", "تفاهم", "dialogue", "initiative", "mediation", "meeting"]
}


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _material_id(m):
    return str(m.get("id") or m.get("url") or hashlib.sha1((m.get("title", "") + m.get("date", "")).encode()).hexdigest())


def _text(m):
    return " ".join(str(m.get(k) or "") for k in ("title", "text", "stance", "note"))


def _signals(text):
    low = str(text or "").lower()
    return {group: [term for term in terms if term.lower() in low] for group, terms in ESCALATION.items() if any(term.lower() in low for term in terms)}


def _entities(text):
    if case_links:
        return case_links.extract_entities(text)
    return []


def _case_snapshot(case):
    mats = case.get("materials", [])
    return {
        "material_ids": sorted(_material_id(m) for m in mats),
        "entities": sorted(set(_entities(" ".join(_text(m) for m in mats)) + _entities(case.get("title", "") + " " + case.get("description", "")))),
        "material_count": len(mats),
        "updated_at": case.get("updated_at", ""),
    }


def scan_cases(cases, state=None):
    """يقارن بالحالة السابقة. أول تشغيل يبني خط أساس ولا يصدر إنذارات بأثر رجعي."""
    state = dict(state or {})
    baselines = dict(state.get("baselines") or {})
    reports = list(state.get("reports") or [])
    alerts = []
    initialized = []
    for case in cases or []:
        cid = case.get("id")
        if not cid:
            continue
        snap = _case_snapshot(case)
        old = baselines.get(cid)
        if old is None:
            initialized.append(case.get("title", "ملف بلا عنوان"))
            baselines[cid] = snap
            continue
        old_ids = set(old.get("material_ids", []))
        new_materials = [m for m in case.get("materials", []) if _material_id(m) not in old_ids]
        old_entities = set(old.get("entities", []))
        new_entities = sorted(set(snap["entities"]) - old_entities)
        if new_materials or new_entities:
            material_alerts = []
            for m in new_materials:
                text = _text(m)
                material_alerts.append({
                    "material_id": _material_id(m), "title": m.get("title", "مادة بلا عنوان"),
                    "type": m.get("type", "غير محدد"), "date": m.get("date", ""),
                    "url": m.get("url", ""), "author": m.get("author", ""), "outlet": m.get("outlet", ""),
                    "signals": _signals(text), "entities": _entities(text),
                    "text_available": bool(m.get("text")),
                })
            alerts.append({
                "id": hashlib.sha1(f"{cid}|{now_iso()}".encode()).hexdigest()[:14],
                "case_id": cid, "case_title": case.get("title", ""),
                "created_at": now_iso(), "new_materials": material_alerts,
                "new_entities": new_entities,
                "signal_groups": sorted({g for m in material_alerts for g in m["signals"]}),
                "note": "رصد تغيّر في المواد أو الكيانات. الإشارات اللغوية مؤشرات أولية وليست حكماً على نوايا الأطراف أو حدوث تصعيد فعلي."
            })
        baselines[cid] = snap
    # احتفظ بسجل محدود لتفادي تضخم ملف التخزين الدائم.
    reports.extend(alerts)
    reports = reports[-500:]
    return {"baselines": baselines, "reports": reports, "last_scan": now_iso()}, alerts, initialized


def build_daily_brief(alerts, date_label=None):
    date_label = date_label or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"# موجز الإنذار المبكر | {date_label}", "", f"عدد الملفات التي ظهر بها تغيير: {len(alerts or [])}", ""]
    if not alerts:
        lines.append("لم تُرصد تغييرات جديدة مقارنة بآخر خط أساس محفوظ.")
    for a in alerts or []:
        lines += [f"## {a.get('case_title')}", f"وقت الرصد: {a.get('created_at')}"]
        if a.get("new_entities"):
            lines.append("أطراف/كيانات ظهرت لأول مرة في الملف: " + "، ".join(a["new_entities"]))
        for m in a.get("new_materials", []):
            lines.append(f"- [{m.get('type')}] {m.get('title')} | {m.get('outlet')} | {m.get('date')} | {m.get('url')}")
            for group, terms in m.get("signals", {}).items():
                lines.append(f"  - إشارة لغوية ({group}): " + "، ".join(terms))
        lines.append(a.get("note", ""))
        lines.append("")
    lines += ["## حدود الرصد", "هذا الموجز يرصد المواد الجديدة والتغيرات النصية فقط. لا يثبت صحة المحتوى أو تغير الموقف السياسي. مقارنة التصريحات تتطلب حفظ نصوص مؤرخة ومنسوبة إلى المتحدث نفسه؛ وتقييم التحول يحتاج مراجعة بشرية وسياقاً كاملاً."]
    return "\n".join(lines)


def build_analysis_prompt(alerts, cases_by_id=None):
    cases_by_id = cases_by_id or {}
    brief = build_daily_brief(alerts)
    return f"""أنت محلل استراتيجي. حلل موجز التغيرات التالي اعتماداً حصراً على المواد والروابط المذكورة فيه.\n\n{brief}\n\nأنتج: (1) ما الجديد مقارنة بخط الأساس؟ (2) ما الذي يمثل واقعة منشورة وما الذي هو إشارة لغوية فقط؟ (3) هل يوجد دليل كافٍ على تحول موقف؟ لا تستنتج ذلك من كلمة منفردة. (4) الأطراف الجديدة وعلاقتها المثبتة بالملف. (5) ما الملفات الأخرى التي ينبغي فحصها ولماذا؟ (6) فرضيات بديلة وتفسيرات غير تصعيدية. (7) فجوات المعلومات ومصادر التحقق الأولية المطلوبة. (8) تقدير ثقة لكل استنتاج مع مبرره. لا تخترع تصريحات أو تواريخ، ولا تخلط الارتباط بالسببية."""
