#!/usr/bin/env python3
"""GAS「欠航率調べ」と同じ波予報の蓄積（Open-Meteo Marine API）。

GASの一本化のため、GASと同一の取得方法を再現する（2026-11-27 開始）：
- https://marine-api.open-meteo.com/v1/marine?hourly=wave_height&timezone=Asia/Tokyo
- 地点： 奈良尾航路 (32.7958, 129.4651) / 有川航路 (33.0742, 129.4187)
- 対象日 +1/+2/+3 日の「12:00 の波高」を取る（GAS の idx = lead*24 + 12 と同じ）
history/gas_wave_forecasts.csv に追記し、生JSONも history/marine_raw/ に残す。

使い方: python3 scripts/collect_gas_waves.py
重複（同じ取得日・地点・対象日）は追記しない。
"""
import csv
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(BASE, "history")
OUT_CSV = os.path.join(HIST, "gas_wave_forecasts.csv")
OUT_3H_CSV = os.path.join(HIST, "gas_wave_3hourly.csv")
OUT_SAIL_CSV = os.path.join(HIST, "sailing_wave_forecasts.csv")
KYUSHU_RESULTS = os.path.join(HIST, "kyushu_results.csv")
GOTO_RESULTS = os.path.join(HIST, "goto_sangyo_results.csv")
RAW_DIR = os.path.join(HIST, "marine_raw")

POINTS = {
    "奈良尾航路": (32.7958, 129.4651),
    "有川航路": (33.0742, 129.4187),
}
URL = ("https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}"
       "&hourly=wave_height&timezone=Asia%2FTokyo")
HEADER = ["capture_date", "captured_at", "point", "lat", "lon", "target_date",
          "lead_days", "wave_height_m"]
HEADER_3H = ["capture_date", "captured_at", "point", "target_date",
             "lead_days", "hour", "wave_height_m"]
HEADER_SAIL = ["capture_date", "captured_at", "target_date", "lead_days",
               "route", "vessel", "port", "time", "point", "wave_height_m"]


def sailing_template(cap_date):
    """直近14日の運航実績から (route, vessel, port, time, point) の便一覧を作る。"""
    since = (cap_date - timedelta(days=14)).isoformat()
    tpl = {}
    if os.path.exists(KYUSHU_RESULTS):
        with open(KYUSHU_RESULTS, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["date"] < since:
                    continue
                point = "有川航路" if row["route"].startswith("佐世保") else "奈良尾航路"
                key = (row["route"], row["vessel"], row["port"], row["time"])
                tpl[key] = point
    if os.path.exists(GOTO_RESULTS):
        with open(GOTO_RESULTS, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["date"] < since:
                    continue
                key = ("鯛ノ浦〜長崎", "フェリー", row["port"], row["time"])
                tpl[key] = "奈良尾航路"
    return tpl


def fetch(lat, lon):
    req = urllib.request.Request(URL.format(lat=lat, lon=lon),
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    now = datetime.now(JST)
    cap_date = now.date()
    os.makedirs(RAW_DIR, exist_ok=True)

    existing = set()
    if os.path.exists(OUT_CSV):
        with open(OUT_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing.add((row["capture_date"], row["point"],
                              row["target_date"]))
    new_file = not os.path.exists(OUT_CSV)

    template = sailing_template(cap_date)
    existing_sail = set()
    if os.path.exists(OUT_SAIL_CSV):
        with open(OUT_SAIL_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing_sail.add((row["capture_date"], row["target_date"],
                                   row["lead_days"], row["route"],
                                   row["vessel"], row["port"], row["time"]))
    new_sail_file = not os.path.exists(OUT_SAIL_CSV)
    fs = open(OUT_SAIL_CSV, "a", newline="", encoding="utf-8")
    ws = csv.writer(fs)
    if new_sail_file:
        ws.writerow(HEADER_SAIL)

    existing_3h = set()
    if os.path.exists(OUT_3H_CSV):
        with open(OUT_3H_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing_3h.add((row["capture_date"], row["point"],
                                 row["target_date"], row["hour"]))
    new_3h_file = not os.path.exists(OUT_3H_CSV)
    f3 = open(OUT_3H_CSV, "a", newline="", encoding="utf-8")
    w3 = csv.writer(f3)
    if new_3h_file:
        w3.writerow(HEADER_3H)

    added = []
    with open(OUT_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(HEADER)
        for point, (lat, lon) in POINTS.items():
            data = fetch(lat, lon)
            raw_path = os.path.join(
                RAW_DIR, f"{cap_date.isoformat()}_{point}.json")
            with open(raw_path, "w", encoding="utf-8") as rf:
                json.dump(data, rf, ensure_ascii=False)
            h = data["hourly"]
            times = h["time"]
            values = h["wave_height"]
            for lead in (1, 2, 3):
                target = cap_date + timedelta(days=lead)
                idx = lead * 24 + 12
                expect = f"{target.isoformat()}T12:00"
                if idx >= len(times) or times[idx] != expect:
                    print(f"{point} lead{lead}: index mismatch "
                          f"(times[{idx}]={times[idx] if idx < len(times) else 'OOR'}"
                          f" != {expect})", file=sys.stderr)
                    continue
                for hour in range(0, 24, 3):
                    idx_h = lead * 24 + hour
                    expect_h = f"{target.isoformat()}T{hour:02d}:00"
                    if idx_h >= len(times) or times[idx_h] != expect_h:
                        continue
                    key3 = (cap_date.isoformat(), point,
                            target.isoformat(), str(hour))
                    if key3 in existing_3h:
                        continue
                    w3.writerow([cap_date.isoformat(),
                                 now.strftime("%Y-%m-%d %H:%M"),
                                 point, target.isoformat(), lead, hour,
                                 values[idx_h]])
                    existing_3h.add(key3)
                for (route, vessel, port, dep), pt in template.items():
                    if pt != point:
                        continue
                    hh, mm = map(int, dep.split(":"))
                    hour = (hh + (1 if mm >= 30 else 0)) % 24
                    idx_s = lead * 24 + hour
                    if idx_s >= len(times):
                        continue
                    keys = (cap_date.isoformat(), target.isoformat(),
                            str(lead), route, vessel, port, dep)
                    if keys in existing_sail:
                        continue
                    ws.writerow([cap_date.isoformat(),
                                 now.strftime("%Y-%m-%d %H:%M"),
                                 target.isoformat(), lead, route, vessel,
                                 port, dep, point, values[idx_s]])
                    existing_sail.add(keys)
                key = (cap_date.isoformat(), point, target.isoformat())
                if key in existing:
                    continue
                w.writerow([cap_date.isoformat(),
                            now.strftime("%Y-%m-%d %H:%M"),
                            point, lat, lon, target.isoformat(), lead,
                            values[idx]])
                added.append(key)
    f3.close()
    fs.close()
    print(f"added {len(added)} rows")


if __name__ == "__main__":
    main()
