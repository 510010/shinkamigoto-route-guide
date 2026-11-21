#!/usr/bin/env python3
"""九州商船の蓄積データ（kyushu_results.csv / status_changes.csv）を、
保存済みスナップショットからパーサーで再生して再構築する。

2026-11-21 に実施したパーサー修正（tr単位の対応付け・(M/D)継承・
夕方の翌日切替の検知）に合わせ、旧パーサーで汚染された最終結果
（欠航が翌日分で上書きされた等）を正しい値に戻すために使う。
通常の収集では使わない（collect_operations.py が本体）。

再生方法:
- history/snapshots/ の各キャプチャ（-hHH=毎時 / -midday=11:10 /
  無印=夕方17:15 とみなす）を時刻順に並べ、collect_operations.main() と
  同じ手順（蓄積済みを渡して parse_kyushu → upsert + 変化記録）で再生する。
- テキスト形式で保存されたスナップショット（夕方分の一部）は解析できない
  ためスキップする（毎時キャプチャが同日分をカバーする）。
- captured_at はスナップショットの名目時刻になる（実取得時刻とは数分の差）。

使い方: python3 scripts/rebuild_history.py
"""
import csv
import os
import re
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect_operations as co

JST = timezone(timedelta(hours=9))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(BASE, "history", "snapshots")


def list_captures():
    caps = []
    for name in os.listdir(SNAP):
        d = os.path.join(SNAP, name)
        if not os.path.isdir(d):
            continue
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:-h(\d{2})|-midday)?", name)
        if not m:
            continue
        day = m.group(1)
        if m.group(2):
            t = datetime.fromisoformat(f"{day}T{m.group(2)}:18:00")
        elif name.endswith("-midday"):
            t = datetime.fromisoformat(f"{day}T11:10:00")
        else:
            t = datetime.fromisoformat(f"{day}T17:15:00")
        caps.append((t.replace(tzinfo=JST), d))
    return sorted(caps)


def main():
    wins = co.dock_windows()
    store, changes, skipped = {}, [], []
    for now, d in list_captures():
        kp = os.path.join(d, "kyushu_status.txt")
        if not os.path.exists(kp):
            continue
        html = open(kp, encoding="utf-8").read()
        stored_status = {k: v[5] for k, v in store.items()}
        try:
            rows, _warnings = co.parse_kyushu(html, now, stored_status)
        except Exception:
            skipped.append(os.path.basename(d))
            continue
        for r in rows:
            r.insert(6, co.kyushu_reason(r, wins))
        for r in rows:
            k = tuple(r[i] for i in (0, 1, 2, 3, 4))
            if k in store and store[k][5] != r[5]:
                changes.append([now.strftime("%Y-%m-%d %H:%M"), r[0], r[1],
                                r[2], r[3], r[4], store[k][5], r[5]])
            store[k] = r
    with open(co.KYUSHU_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(co.KYUSHU_HEADER)
        for k in sorted(store):
            w.writerow(store[k])
    with open(co.CHANGES_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["changed_at", "date", "route", "vessel", "port", "time",
                    "from_status", "to_status"])
        w.writerows(changes)
    print(f"rebuilt: kyushu {len(store)} rows, status_changes {len(changes)} rows")
    if skipped:
        print(f"skipped (テキスト形式等): {', '.join(skipped)}")


if __name__ == "__main__":
    main()
