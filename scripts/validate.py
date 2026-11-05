#!/usr/bin/env python3
"""data/*.csv を検証する。エラーがあれば終了コード1。
使い方: python3 scripts/validate.py
"""
import csv, os, sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

def read(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return list(csv.DictReader(f))

def t2m(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)

errors, warnings = [], []

ports = {p["port_id"] for p in read("ports.csv")}
routes = {r["route_id"]: r for r in read("routes.csv")}
patterns = {p["pattern_id"]: p for p in read("service_patterns.csv")}
trips = read("trips.csv")
stops = read("stop_times.csv")
fares = read("fares.csv")

trip_ids = set()
for t in trips:
    if t["trip_id"] in trip_ids:
        errors.append(f"trip_id 重複: {t['trip_id']}")
    trip_ids.add(t["trip_id"])
    if t["route_id"] not in routes:
        errors.append(f"trip {t['trip_id']}: 存在しない route {t['route_id']}")
    if t["pattern_id"] not in patterns:
        errors.append(f"trip {t['trip_id']}: 存在しない pattern {t['pattern_id']}")

by_trip = defaultdict(list)
for s in stops:
    if s["trip_id"] not in trip_ids:
        errors.append(f"stop_times: 存在しない trip {s['trip_id']}")
    if s["port_id"] not in ports:
        errors.append(f"stop_times {s['trip_id']}: 存在しない port {s['port_id']}")
    by_trip[s["trip_id"]].append(s)

for tid, rs in by_trip.items():
    rs.sort(key=lambda x: int(x["seq"]))
    if [int(r["seq"]) for r in rs] != list(range(1, len(rs) + 1)):
        errors.append(f"trip {tid}: seq が連番でない")
    prev, off = -1, 0
    for r in rs:
        for t in (r["arrival"], r["departure"]):
            if t:
                v = t2m(t) + off
                if v < prev:
                    off += 1440
                    v += 1440
                if v < prev:
                    errors.append(f"trip {tid}: 時刻が逆行 ({t})")
                prev = v
    if not rs[0]["departure"] or rs[0]["arrival"]:
        errors.append(f"trip {tid}: 始発行の着/発が不正")
    if not rs[-1]["arrival"] or rs[-1]["departure"]:
        errors.append(f"trip {tid}: 終着行の着/発が不正")

for f in fares:
    for k in ("from_port_id", "to_port_id"):
        if f[k] not in ports:
            errors.append(f"fares: 存在しない port {f[k]}")
    if not f["adult_oneway"]:
        errors.append(f"fares: 大人片道が空 ({f['operator_id']} {f['from_port_id']}->{f['to_port_id']})")

pairs = {(f["operator_id"], f["vessel_type"], f["category"], f["from_port_id"], f["to_port_id"]): f["adult_oneway"]
         for f in fares}
for k, v in list(pairs.items()):
    rev = (k[0], k[1], k[2], k[4], k[3])
    if rev in pairs and pairs[rev] != v:
        warnings.append(f"運賃が非対称: {k} ={v} / 逆={pairs[rev]}")

for p in patterns.values():
    if p["valid_to"] and p["valid_to"] < "2026-11-05":
        warnings.append(f"期限切れパターン: {p['pattern_id']} ({p['name']}, 〜{p['valid_to']})")

print(f"trips={len(trips)} stops={len(stops)} fares={len(fares)} patterns={len(patterns)}")
for w in warnings:
    print("WARN:", w)
for e in errors:
    print("ERROR:", e)
print("NG" if errors else "OK")
sys.exit(1 if errors else 0)
