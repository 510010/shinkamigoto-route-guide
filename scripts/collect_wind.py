#!/usr/bin/env python3
"""欠航リスク予想のための風予報の蓄積（Open-Meteo）。

航路中間点ごとに Open-Meteo の風予報（10m風速・風向・ガスト、1時間毎）を取得し、
取得日から +1/+2/+3 日先の「日最大風速」などを抽出して
history/wind_forecasts.csv に追記する。生JSONも history/wind_raw/ に残す。
波の正本は気象庁 waveinf（collect_waves.py）。これは風専用の補助データ。

使い方: python3 scripts/collect_wind.py
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
OUT_CSV = os.path.join(HIST, "wind_forecasts.csv")
RAW_DIR = os.path.join(HIST, "wind_raw")

# 航路中間点（data/ports.csv の港座標から算出した概略位置。航行用ではない）
POINTS = {
    "奈良尾航路": (32.80, 129.46),   # 長崎〜奈良尾・福江（九州商船）
    "有川航路": (33.07, 129.42),     # 佐世保〜有川（九州商船）
    "鯛ノ浦航路": (32.85, 129.48),   # 鯛ノ浦〜長崎（五島産業汽船）
    "若松航路": (32.79, 128.94),     # 若松〜福江（五島旅客船）
    "崎戸航路": (33.08, 129.45),     # 佐世保〜友住（崎戸商船）
    "博多航路": (33.15, 129.63),     # 博多〜福江（野母商船）
}
URL = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
       "&hourly=wind_speed_10m,wind_direction_10m,wind_gusts_10m"
       "&forecast_days=4&wind_speed_unit=ms&timezone=Asia%2FTokyo")
HEADER = ["capture_date", "captured_at", "point", "lat", "lon", "target_date",
          "lead_days", "max_wind_ms", "dir_at_max_deg", "max_gust_ms",
          "hours_covered"]


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
            speeds = h["wind_speed_10m"]
            dirs = h["wind_direction_10m"]
            gusts = h["wind_gusts_10m"]
            for lead in (1, 2, 3):
                target = cap_date + timedelta(days=lead)
                idxs = [i for i, t in enumerate(times)
                        if t.startswith(target.isoformat())]
                if not idxs:
                    print(f"{point} target {target}: no rows", file=sys.stderr)
                    continue
                imax = max(idxs, key=lambda i: speeds[i])
                key = (cap_date.isoformat(), point, target.isoformat())
                if key in existing:
                    continue
                w.writerow([cap_date.isoformat(),
                            now.strftime("%Y-%m-%d %H:%M"),
                            point, lat, lon, target.isoformat(), lead,
                            f"{speeds[imax]:.1f}", f"{dirs[imax]:.0f}",
                            f"{max(gusts[i] for i in idxs):.1f}",
                            len(idxs)])
                added.append(key)
    print(f"added {len(added)} rows")


if __name__ == "__main__":
    main()
