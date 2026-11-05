#!/usr/bin/env python3
"""data/*.csv から site/data.json を生成する。
使い方: python3 scripts/build_data.py
"""
import csv, json, os
from collections import defaultdict
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SITE = os.path.join(ROOT, "site")
os.makedirs(SITE, exist_ok=True)

def read(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return list(csv.DictReader(f))

def t2m(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)

def num(v):
    return int(v) if v not in ("", None) else None

ports = read("ports.csv")
operators = read("operators.csv")
routes = read("routes.csv")
patterns = {p["pattern_id"]: p for p in read("service_patterns.csv")}
trips_raw = read("trips.csv")
stops_raw = read("stop_times.csv")
fares = read("fares.csv")
surcharges = read("surcharges.csv")
notices = read("notices.csv")
exceptions = read("exceptions.csv")

by_trip = defaultdict(list)
for s in stops_raw:
    by_trip[s["trip_id"]].append(s)

trips = []
for t in trips_raw:
    rs = sorted(by_trip[t["trip_id"]], key=lambda x: int(x["seq"]))
    stops, off, prev = [], 0, -1
    for r in rs:
        arr_off = dep_off = None
        if r["arrival"]:
            v = t2m(r["arrival"]) + off
            if v < prev:
                off += 1440
                v += 1440
            arr_off, prev = off // 1440, v
        if r["departure"]:
            v = t2m(r["departure"]) + off
            if v < prev:
                off += 1440
                v += 1440
            dep_off, prev = off // 1440, v
        stops.append({"port_id": r["port_id"], "arr": r["arrival"] or None,
                      "dep": r["departure"] or None, "arr_off": arr_off, "dep_off": dep_off})
    p = patterns[t["pattern_id"]]
    route = next(r for r in routes if r["route_id"] == t["route_id"])
    # 崎戸・五島産業の季節ダイヤは毎年同じ月日範囲で繰り返す
    recurs = None
    if route["operator_id"] in ("sakito", "goto-sangyo"):
        m = None
        import re
        m = re.search(r"(\d{1,2})/(\d{1,2})-(\d{1,2})/(\d{1,2})", p["name"])
        if m:
            recurs = {"from_md": f"{int(m.group(1)):02d}-{int(m.group(2)):02d}",
                      "to_md": f"{int(m.group(3)):02d}-{int(m.group(4)):02d}"}
    trips.append({
        "id": t["trip_id"], "route_id": t["route_id"], "operator_id": route["operator_id"],
        "vessel_name": t["vessel_name"], "vessel_type": route["vessel_type"],
        "direction": t["direction"], "note": t["note"],
        "pattern": {"name": p["name"], "kind": p["kind"],
                    "valid_from": p["valid_from"] or None, "valid_to": p["valid_to"] or None,
                    "recurs": recurs},
        "stops": stops})

out = {
    "meta": {"title": "上五島航路案内", "generated_at": date.today().isoformat()},
    "ports": [{**p, "lat": float(p["lat"]), "lon": float(p["lon"]),
               "aliases": [a for a in p["aliases"].split("、") if a]} for p in ports],
    "operators": operators,
    "routes": [{**r, "suspended": r["suspended"] == "1"} for r in routes],
    "trips": trips,
    "fares": [{**f, "adult_oneway": num(f["adult_oneway"]), "child_oneway": num(f["child_oneway"]),
               "adult_roundtrip": num(f["adult_roundtrip"]), "child_roundtrip": num(f["child_roundtrip"])}
              for f in fares],
    "surcharges": [{**s, "adult": num(s["adult"]), "child": num(s["child"])} for s in surcharges],
    "notices": notices,
    "exceptions": exceptions,
}
path = os.path.join(SITE, "data.json")
with open(path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print(f"wrote {path}: trips={len(trips)} fares={len(out['fares'])} ports={len(ports)}")
