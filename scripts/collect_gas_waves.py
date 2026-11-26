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
RAW_DIR = os.path.join(HIST, "marine_raw")

POINTS = {
    "奈良尾航路": (32.7958, 129.4651),
    "有川航路": (33.0742, 129.4187),
}
URL = ("https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}"
       "&hourly=wave_height&timezone=Asia%2FTokyo")
HEADER = ["capture_date", "captured_at", "point", "lat", "lon", "target_date",
          "lead_days", "wave_height_m"]


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
                key = (cap_date.isoformat(), point, target.isoformat())
                if key in existing:
                    continue
                w.writerow([cap_date.isoformat(),
                            now.strftime("%Y-%m-%d %H:%M"),
                            point, lat, lon, target.isoformat(), lead,
                            values[idx]])
                added.append(key)
    print(f"added {len(added)} rows")


if __name__ == "__main__":
    main()
