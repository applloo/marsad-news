# -*- coding: utf-8 -*-
"""شفرات التجربة: يولّدها المالك ويرسلها مع الرابط (?k=الشفرة)، وتنتهي تلقائياً بعد مدة تُحسب من أول فتح.
تُخزَّن داخل نفس الـGist (قائمة keys). تعمل فقط إن وُجدت الأسرار ADMIN_KEY و GITHUB_TOKEN و GIST_ID."""
import secrets
import time
from datetime import datetime, timedelta, timezone

import store

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # بلا حروف ملتبسة (O/0 وI/1)
UNUSED_TTL_DAYS = 30  # شفرة لم تُفتح أبداً تسقط بعد هذه المدة من إنشائها
RECHECK_SECONDS = 600  # إعادة فحص الإلغاء من الـGist كل 10 دقائق


def now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat(timespec="seconds")


def parse(s):
    try:
        return datetime.fromisoformat(s) if s else None
    except ValueError:
        return None


def new_code():
    body = "".join(secrets.choice(ALPHABET) for _ in range(8))
    return f"MR-{body[:4]}-{body[4:]}"


def norm(code):
    return (code or "").strip().upper().replace(" ", "")


def expires_at(k):
    """موعد انتهاء الشفرة، أو None إن لم تُفتح بعد"""
    first = parse(k.get("first_seen"))
    if not first:
        return None
    return first + timedelta(hours=float(k.get("hours", 168)))


def status(k, at=None):
    """('revoked'|'expired'|'unused'|'active'|'unused_expired', تفاصيل)"""
    at = at or now()
    if k.get("revoked"):
        return "revoked"
    exp = expires_at(k)
    if exp is None:
        created = parse(k.get("created"))
        if created and at > created + timedelta(days=UNUSED_TTL_DAYS):
            return "unused_expired"
        return "unused"
    return "expired" if at > exp else "active"


def is_valid(k, at=None):
    return status(k, at) in ("active", "unused")


def create(keys, label, hours, scope="full"):
    k = {"code": new_code(), "label": (label or "").strip() or "بدون اسم", "hours": float(hours),
         "scope": scope, "created": iso(now()), "first_seen": "", "last_seen": "", "visits": 0, "revoked": False}
    keys.append(k)
    return k


def find(keys, code):
    code = norm(code)
    return next((k for k in keys if k.get("code") == code), None)


def touch(token, gist_id, code):
    """يسجّل دخولاً بالشفرة (أول فتح يبدأ العدّ). يعيد (الشفرة المحدّثة أو None، سبب الرفض)"""
    data = store.load(token, gist_id)
    k = find(data["keys"], code)
    if not k:
        return None, "الشفرة غير صحيحة."
    st_ = status(k)
    if st_ == "revoked":
        return None, "أُلغيت هذه الشفرة."
    if st_ in ("expired", "unused_expired"):
        return None, "انتهت مدة التجربة."
    t = iso(now())
    if not k.get("first_seen"):
        k["first_seen"] = t
    k["last_seen"], k["visits"] = t, int(k.get("visits", 0)) + 1
    store.save(token, gist_id, data)
    return k, ""


def recheck(token, gist_id, code):
    """فحص خفيف (بلا كتابة) لإلغاء/انتهاء الشفرة أثناء الجلسة"""
    data = store.load(token, gist_id)
    k = find(data["keys"], code)
    return bool(k and is_valid(k))


def mutate(token, gist_id, fn):
    """قراءة طازجة ← تعديل قائمة الشفرات ← حفظ (حتى لا تُكتب فوق دخول ضيف سجّل للتو)"""
    data = store.load(token, gist_id)
    out = fn(data["keys"])
    store.save(token, gist_id, data)
    return data["keys"], out


def human_left(k):
    exp = expires_at(k)
    if exp is None:
        return "لم تُفتح بعد"
    left = exp - now()
    if left.total_seconds() <= 0:
        return "انتهت"
    d, h = left.days, left.seconds // 3600
    return f"باقٍ {d} يوم و{h} ساعة" if d else f"باقٍ {h} ساعة"


def touch_ok(last):
    return time.time() - last < RECHECK_SECONDS
