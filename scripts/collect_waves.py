#!/usr/bin/env python3
"""欠航リスク予想のための波予報の蓄積。

気象庁「海域毎の最大波高と周期」のCSV（Shift_JIS、3時間毎）を取得し、
取得日から +1/+2/+3 日先の「日最大波高」を抽出して
history/wave_forecasts.csv に追記する。生CSVも history/wave_raw/ に残す。

使い方: python3 scripts/collect_waves.py
重複（同じ取得日・海域・対象日）は追記しない。
"""
import csv
import io
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(BASE, "history")
OUT_CSV = os.path.join(HIST, "wave_forecasts.csv")
RAW_DIR = os.path.join(HIST, "wave_raw")

AREAS = {
    43: "長崎県西方・熊本県・有明海",
    42: "対馬海峡",
}
URL = "https://www.data.jma.go.jp/waveinf/data/Guid/csv/wave_guid_{:02d}.csv"
HEADER = ["capture_date", "captured_at", "area_no", "area_name", "target_date",
          "lead_days", "max_wave_m", "period_at_max_s", "hours_covered"]


def fetch(area_no):
    req = urllib.request.Request(URL.format(area_no),
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("shift_jis")


def parse(text):
    rows = []
    rdr = csv.reader(io.StringIO(text))
    for row in rdr:
        if len(row) < 7:
            continue
        try:
            y, m, d, h = (int(row[1]), int(row[2]), int(row[3]), int(row[4]))
            period, wave = float(row[5]), float(row[6])
        except ValueError:
            continue  # 見出し行など
        rows.append((datetime(y, m, d, h), period, wave))
    return rows


def main():
    now = datetime.now(JST)
    cap_date = now.date()
    os.makedirs(RAW_DIR, exist_ok=True)

    existing = set()
    if os.path.exists(OUT_CSV):
        with open(OUT_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing.add((row["capture_date"], row["area_no"],
                              row["target_date"]))
    new_file = not os.path.exists(OUT_CSV)

    added = []
    with open(OUT_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(HEADER)
        for area_no, area_name in AREAS.items():
            text = fetch(area_no)
            raw_path = os.path.join(
                RAW_DIR, f"{cap_date.isoformat()}_wave_guid_{area_no:02d}.csv")
            with open(raw_path, "w", encoding="utf-8") as rf:
                rf.write(text)
            rows = parse(text)
            for lead in (1, 2, 3):
                target = cap_date + timedelta(days=lead)
                day = [(p, wv) for (t, p, wv) in rows if t.date() == target]
                if not day:
                    print(f"area {area_no} target {target}: no rows", file=sys.stderr)
                    continue
                period_at_max, max_wave = max(day, key=lambda x: x[1])
                key = (cap_date.isoformat(), str(area_no), target.isoformat())
                if key in existing:
                    continue
                w.writerow([cap_date.isoformat(),
                            now.strftime("%Y-%m-%d %H:%M"),
                            area_no, area_name, target.isoformat(), lead,
                            f"{max_wave:.1f}", f"{period_at_max:.1f}",
                            len(day)])
                added.append(key)
    print(f"added {len(added)} rows: {added}")


if __name__ == "__main__":
    main()
