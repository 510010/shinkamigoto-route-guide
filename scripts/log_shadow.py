#!/usr/bin/env python3
"""シャドー検証用ログ: その日の最新キャプチャの集計を shadow_status_log.csv に1行追記する。

運航状況のサイト組み込み可否を検証するため、毎時取得のたびに
九州商船・五島産業の便数と状態内訳を記録する（表示はしない）。
"""
import csv
import os
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "history")
LOG = os.path.join(BASE, "shadow_status_log.csv")


def read_rows(name):
    path = os.path.join(BASE, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    now = datetime.now(JST)
    today = now.strftime("%Y-%m-%d")

    ky = [r for r in read_rows("kyushu_results.csv") if r["date"] == today]
    ky_cap = max((r["captured_at"] for r in ky), default="")
    ky_latest = [r for r in ky if r["captured_at"] == ky_cap]
    k_ok = sum(1 for r in ky_latest if r["status"] == "◯")
    k_ng = sum(1 for r in ky_latest if r["status"] == "✕")
    k_un = sum(1 for r in ky_latest if r["status"] == "△")

    go = [r for r in read_rows("goto_sangyo_results.csv") if r["date"] == today]
    g_ng = sum(1 for r in go if r["status"] == "✕")

    new_file = not os.path.exists(LOG)
    with open(LOG, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["logged_at", "service_date", "kyushu_captured_at", "kyushu_services",
                        "kyushu_ok", "kyushu_cancel", "kyushu_undecided",
                        "goto_services", "goto_cancel"])
        w.writerow([now.strftime("%Y-%m-%d %H:%M"), today, ky_cap, len(ky_latest),
                    k_ok, k_ng, k_un, len(go), g_ng])
    print(f"shadow log: {today} kyushu={len(ky_latest)} (ok {k_ok} / cancel {k_ng} / undecided {k_un}), goto={len(go)} (cancel {g_ng})")


if __name__ == "__main__":
    main()
