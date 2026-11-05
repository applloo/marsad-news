# -*- coding: utf-8 -*-
"""يشغّل التقرير المخصص على GitHub Actions (زر في التطبيق). يقرأ الاعدادات من الـGist (marsad_watch_cfg.json)
ويكتب النتيجة في marsad_watch.json فتبقى محفوظة وتظهر في التطبيق كلما فتحه المالك. لا يستهلك رصيد Anthropic."""
import os
import sys

import core
import store
import watch
from sources import ARABIC, ISRAEL, REGION, UK, USA

CFG, OUT = "marsad_watch_cfg.json", "marsad_watch.json"
SCOPES = {"il": ("🇮🇱 اسرائيلي", ISRAEL), "us": ("🇺🇸 امريكي", USA), "uk": ("🇬🇧 بريطاني", UK), "ar": ("🇪🇬 عربي", ARABIC), "rg": ("🌍 تركيا وايران واثيوبيا", REGION)}


def main():
    tok, gid = os.getenv("GIST_TOKEN"), os.getenv("GIST_ID")
    if not (tok and gid):
        sys.exit("GIST_TOKEN و GIST_ID مطلوبان")
    cfg = store.load_file(tok, gid, CFG, {}) or {}
    topics = watch.parse_topics(cfg.get("topics") or watch.DEFAULT_TOPICS)
    keys = [k for k in (cfg.get("scopes") or list(SCOPES)) if k in SCOPES]
    try:
        custom = store.load(tok, gid)["sources"]
    except Exception:
        custom = []
    sel, scopes = [], {}
    for k in keys:
        name, groups = SCOPES[k]
        ents = [e for g in groups.values() for e in g] + [(x["label"], x["domain"], x["lang"]) for x in custom if x.get("group") == k]
        sel += ents
        scopes[name] = [d.split("/")[0] for _l, doms, _g in ents for d in core._split_domains([doms])]
    days = int(cfg.get("days") or 2)
    save = lambda rep: store.save_file(tok, gid, OUT, {**rep, "scope_names": list(scopes), "topics_text": cfg.get("topics", "")})
    rep = watch.build_report(topics, sel, days, int(cfg.get("per") or 8), int(cfg.get("deep") if cfg.get("deep") is not None else 3),
                             progress=lambda f, m: print(f"{f:.0%} {m}", flush=True), scopes=scopes, fulltext=True, checkpoint=save)
    save(rep)
    print("تم الحفظ", flush=True)


if __name__ == "__main__":
    main()
