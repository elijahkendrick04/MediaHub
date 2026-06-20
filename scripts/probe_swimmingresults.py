#!/usr/bin/env python3
"""
Probe swimmingresults.org reachability + the full PB-lookup chain from
*this* host (run it on the Render server to learn whether the production
egress IP can fetch swimmingresults.org directly).

Chain proven from the dev sandbox (all plain urllib + a browser UA, no API):
  1. club name -> club code   (eventrankings TargetClub select, 1266 clubs)
  2. club code -> roster       (eventrankings.php?Level=O&AgeGroup=NN -> name+tiref)
  3. tiref     -> personal best(personal_best.php?mode=A&tiref=ID)

Usage:  python3 scripts/probe_swimmingresults.py
Exit 0 if the direct path works here; non-zero if it is blocked.
"""
from __future__ import annotations
import re, sys, urllib.request, urllib.error

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
BASE = "https://www.swimmingresults.org"

def get(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
        "Referer": BASE + "/eventrankings/",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return None, "ERR %s: %s" % (type(e).__name__, e)

def main() -> int:
    ok = True

    # 1) A real PB page (Holly Greenslade, Torfaen Dolphins, tiref 1153374).
    url = BASE + "/individualbest/personal_best.php?mode=A&tiref=1153374"
    st, body = get(url)
    is_real = isinstance(body, str) and 'class="rnk_sj"' in body
    ntimes = len(re.findall(r"\b\d{1,2}:\d{2}\.\d{2}\b|\b\d{2}\.\d{2}\b", body)) if isinstance(body, str) else 0
    print("[1] personal_best.php  status=%s real_pb_page=%s time_tokens=%d"
          % (st, is_real, ntimes))
    if not (st == 200 and is_real):
        ok = False
        print("    -> blocked/unexpected. First 200 chars:\n    " +
              (body[:200].replace("\n", " ") if isinstance(body, str) else str(body)))

    # 2) Club roster (name -> tiref) for one event/age group.
    url = (BASE + "/eventrankings/eventrankings.php?Pool=L&Stroke=2&Sex=F"
           "&TargetYear=A&AgeGroup=13&AgeAt=A&StartNumber=1&RecordsToView=300"
           "&Level=O&TargetNationality=P&TargetRegion=P&TargetCounty=XXXX"
           "&TargetClub=TDOYEWAY")
    st, body = get(url)
    pairs = re.findall(r"tiref=(\d+)[^>]*>\s*([^<]+?)\s*<", body) if isinstance(body, str) else []
    found_holly = any("greensl" in n.lower() for _, n in pairs)
    print("[2] eventrankings.php  status=%s swimmers=%d holly_resolved=%s"
          % (st, len(pairs), found_holly))
    if not (st == 200 and pairs):
        ok = False

    print("\nRESULT:", "DIRECT FETCH WORKS FROM THIS HOST ✓" if ok
          else "DIRECT FETCH BLOCKED HERE — TinyFish Fetch fallback needed ✗")
    return 0 if ok else 2

if __name__ == "__main__":
    sys.exit(main())
