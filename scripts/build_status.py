#!/usr/bin/env python3
"""サイト表示用の運航状況JSON（site/status.json）を history の蓄積から生成する。

第1弾（九州商船・五島産業汽船の便別表示、2026-11-07承認の掲載方針）の供給側。
collect_operations.py の直後に実行する想定で、「今日（JST）」の分だけを出す。

掲載方針との対応:
- 表示は今日だけ： status.json には今日の便しか入れない。
- 取得時刻の併記： 事業者ごとに captured_at を持たせる。九州商船は当日行の
  captured_at の最大値（夕方の翌日切替後は当日分が更新されなくなるため、
  「当日分を最後に確認した時刻」になる）。五島産業は蓄積CSVに captured_at が
  ないため、CSVの更新時刻（＝直前の収集時刻）を使う。
- 便数の異常時はその事業者を出さない： ok=False とし services は空にする
  （九州 30〜60便、五島産業 2〜8便の範囲外はレイアウト変更等の疑い）。
  フロント側は ok=False の事業者を「確認できません」＋公式リンクで表示する。
- 事業者ごとの陳腐化： captured_at が約90分以上前なら、その事業者も
  ok=False にする（片方の取得だけ止まった場合に、古い状況を出し続けないため。
  2026-11-24 五島産業の状況欄消失で、CSV更新時刻ベースの captured_at が
  実態より新しく見えた件を受けた追加）。
- 取得が全体に止まった場合は generated_at が古くなることでフロントが検知し、
  公式リンク表示に落とす（約90分ルール）。

使い方: python3 scripts/build_status.py
"""
import csv
import json
import os
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(BASE, "history")
OUT = os.path.join(BASE, "site", "status.json")

ROUTE_ORDER = {"長崎〜五島": 0, "佐世保〜上五島": 1}
VESSEL_ORDER = {"JF": 0, "高速": 0, "Fe": 1}
KYUSHU_BAND = (30, 60)
GOTO_BAND = (2, 8)
STALE_MIN = 90


def _stale(captured, now):
    """captured_at（'YYYY-MM-DD HH:MM'）が now より STALE_MIN 分以上前なら True。"""
    if not captured:
        return True
    try:
        cap = datetime.strptime(captured, "%Y-%m-%d %H:%M").replace(tzinfo=JST)
    except ValueError:
        return True
    return (now - cap) > timedelta(minutes=STALE_MIN)


def _min_of(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def sort_services(services):
    """航路→船種→港（その港の最初の便の時刻順）→時刻 の順に並べる。"""
    first_time = {}
    for s in services:
        k = (s["route"], s["vessel"], s["port"])
        if k not in first_time or _min_of(s["time"]) < first_time[k]:
            first_time[k] = _min_of(s["time"])
    return sorted(services, key=lambda s: (
        ROUTE_ORDER.get(s["route"], 9),
        VESSEL_ORDER.get(s["vessel"], 9),
        first_time[(s["route"], s["vessel"], s["port"])],
        _min_of(s["time"])))


def kyushu_block(today, now):
    path = os.path.join(HIST, "kyushu_results.csv")
    services, captured = [], None
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["date"] != today:
                    continue
                services.append({"route": r["route"], "vessel": r["vessel"],
                                 "port": r["port"], "time": r["time"],
                                 "status": r["status"]})
                if captured is None or r["captured_at"] > captured:
                    captured = r["captured_at"]
    ok = KYUSHU_BAND[0] <= len(services) <= KYUSHU_BAND[1] \
        and not _stale(captured, now)
    return {"operator_id": "kyushu", "captured_at": captured,
            "ok": ok, "services": sort_services(services) if ok else []}


def goto_block(today, now):
    path = os.path.join(HIST, "goto_sangyo_results.csv")
    services = []
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["date"] != today:
                    continue
                services.append({"route": "鯛ノ浦〜長崎", "vessel": "",
                                 "port": r["port"], "time": r["time"],
                                 "status": r["status"]})
        captured = datetime.fromtimestamp(
            os.path.getmtime(path), JST).strftime("%Y-%m-%d %H:%M")
    else:
        captured = None
    ok = GOTO_BAND[0] <= len(services) <= GOTO_BAND[1] \
        and not _stale(captured, now)
    return {"operator_id": "goto-sangyo", "captured_at": captured,
            "ok": ok, "services": sort_services(services) if ok else []}


def main():
    now = datetime.now(JST)
    today = now.strftime("%Y-%m-%d")
    data = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M"),
        "date": today,
        "operators": [kyushu_block(today, now), goto_block(today, now)],
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    for op in data["operators"]:
        print(f"{op['operator_id']}: ok={op['ok']} "
              f"services={len(op['services'])} captured_at={op['captured_at']}")
    print(f"wrote {OUT} (date {today})")


if __name__ == "__main__":
    main()
