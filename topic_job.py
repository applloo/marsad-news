# -*- coding: utf-8 -*-
"""تتبّع موضوع أو ترند على GitHub Actions (زر في التطبيق، في تاب الشأن المصري وتاب الملفات والخيوط).
بيقرا الموضوع من الـGist (marsad_topic_cfg.json)، بيدور عليه في المصادر المختارة بنفس طريقة البحث الشامل،
وبيحفظ النتيجة في marsad_results.json تحت اسم egt (الشأن المصري) أو trend (السياسة)، فتظهر في التطبيق وتدخل في الملفات والخيوط."""
import json
import os
import re
import sys
import time

import store
from search_job import RES, now_iso, search_scope
from sources import ARAB_EG_GROUP, ARABIC, EGYPT, ISRAEL, REGION, UK, USA

CFG, STATUS = "marsad_topic_cfg.json", "marsad_topic_job.json"


def _uniq(entries):
    seen, out = set(), []
    for e in entries:
        if e[1] not in seen:
            seen.add(e[1])
            out.append(e)
    return out


def pick_sources(profile, scope):
    local = [e for g, ents in EGYPT.items() if g != ARAB_EG_GROUP for e in ents]
    arab = list(EGYPT[ARAB_EG_GROUP])
    world = [e for gg in (ISRAEL, USA, UK, REGION, ARABIC) for ents in gg.values() for e in ents]
    if profile == "eg":
        if scope == "local":
            return _uniq(local), "EG", "EG"
        if scope == "arab":
            return _uniq(local + arab), "EG", "EG"
        return _uniq(local + arab + [e for gg in (ARABIC, ISRAEL, USA, UK) for ents in gg.values() for e in ents]), "EG", "EG"
    if scope == "us_uk":
        return _uniq([e for gg in (USA, UK) for ents in gg.values() for e in ents]), None, "US"
    if scope == "plus_eg":
        return _uniq(world + local), None, "US"
    return _uniq(world), None, "US"


def main():
    tok, gid = os.getenv("GIST_TOKEN"), os.getenv("GIST_ID")
    if not (tok and gid):
        sys.exit("GIST_TOKEN و GIST_ID مطلوبان")
    cfg = store.load_file(tok, gid, CFG, {}) or {}
    topic = (cfg.get("topic") or "").strip()
    if not topic:
        sys.exit("مفيش موضوع")
    alts = cfg.get("alts") or ""
    terms = [topic] + [t.strip() for t in re.split(r"[,،;\n]+", alts) if t.strip()]
    profile = cfg.get("profile") or "eg"
    key = "egt" if profile == "eg" else "trend"
    status = {"state": "running", "started": now_iso(), "updated": now_iso(), "topic": topic, "profile": profile}

    def put():
        status["updated"] = now_iso()
        try:
            store.save_file(tok, gid, STATUS, status)
        except Exception as e:
            print("status save failed", e, flush=True)

    put()
    try:
        sel, gd, gn = pick_sources(profile, cfg.get("scope") or "")
        try:
            custom = store.load(tok, gid).get("sources", [])
        except Exception:
            custom = []
        run_cfg = {"days": float(cfg.get("days") or 3), "joiner": "OR", "max_rec": 40, "verify": True, "hide_nomatch": True}
        data = search_scope(key, {"sel": sel}, gd, gn, [x for x in custom if x.get("group") == key], terms, run_cfg, print)
        data = {**data, "partial": False, "saved_at": now_iso(), "job": True, "job_terms": terms,
                "topic": topic, "alts": alts, "days": cfg.get("days"), "created": now_iso()}
        body = json.loads(json.dumps(data, ensure_ascii=False, default=str))
        body["items"] = body.get("items", [])[:200]
        for _ in range(3):
            try:
                allres = store.load_file(tok, gid, RES, {}) or {}
                allres[key] = body
                store.save_file(tok, gid, RES, allres)
                break
            except Exception as e:
                print("save retry", e, flush=True)
                time.sleep(3)
        status["count"] = len(body["items"])
        status["state"] = "done"
    except Exception as e:
        status["state"] = "failed"
        status["error"] = f"{type(e).__name__}: {e}"
        print("فشل", e, flush=True)
    status["finished"] = now_iso()
    put()
    print("تم", flush=True)


if __name__ == "__main__":
    main()
