# -*- coding: utf-8 -*-
"""تشغيل «التقرير اليومي» (GitHub Actions) من داخل التطبيق بزر، وعرض حالة آخر تشغيل.
يحتاج سرّ ACTIONS_TOKEN (توكن بصلاحية workflow) واختيارياً GH_REPO (افتراضي applloo/marsad-news) وGH_BRANCH (main)."""
import requests

WORKFLOW = "daily.yml"
DEFAULT_REPO = "applloo/marsad-news"


def _h(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "marsad-news"}


def last_run(token, repo=DEFAULT_REPO):
    """آخر تشغيل: dict(status, conclusion, url, created) أو None"""
    r = requests.get(f"https://api.github.com/repos/{repo}/actions/workflows/{WORKFLOW}/runs",
                     params={"per_page": 1}, headers=_h(token), timeout=20)
    r.raise_for_status()
    runs = r.json().get("workflow_runs") or []
    if not runs:
        return None
    x = runs[0]
    return {"status": x.get("status"), "conclusion": x.get("conclusion"), "url": x.get("html_url"),
            "created": x.get("created_at"), "updated": x.get("updated_at")}


def dispatch(token, repo=DEFAULT_REPO, branch="main"):
    """يطلب تشغيل التقرير. يعيد (نجح؟، رسالة)"""
    r = requests.post(f"https://api.github.com/repos/{repo}/actions/workflows/{WORKFLOW}/dispatches",
                      json={"ref": branch}, headers=_h(token), timeout=20)
    if r.status_code == 204:
        return True, "بدأ التشغيل. يستغرق عادةً من 6 إلى 30 دقيقة."
    if r.status_code in (401, 403):
        return False, "التوكن مرفوض أو ينقصه صلاحية «workflow» (Actions: write)."
    if r.status_code == 404:
        return False, "لم أجد المستودع أو ملف daily.yml (تأكد من GH_REPO واسم الفرع)."
    if r.status_code == 422:
        return False, "الفرع غير صحيح (GH_BRANCH) أو الملف لا يقبل التشغيل اليدوي."
    return False, f"رفض غير متوقع من GitHub (HTTP {r.status_code})."
