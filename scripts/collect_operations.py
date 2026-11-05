#!/usr/bin/env python3
"""九州商船と五島産業汽船の運航実績を公式ページから便別に蓄積する（二重蓄積）。

- 九州商船： https://kyusho.co.jp/status のHTMLを解析し、
  history/kyushu_results.csv に upsert する（キー： date, route, vessel, port, time）。
  長崎〜有川パネルは2025-08-25から全便運休中のため対象外（ページにも明記）。
  ステータス： status-available→◯ / status-fully→✕ / status-limited→△。
  行の日付は GAS と同じ規則： 時刻の (M/D) 付きはその日付、無ければページの更新日。
- 五島産業汽船： トップページのテキストを parse_goto_sangyo.parse_captures で解析し、
  history/goto_sangyo_results.csv に 2026-11-06 以降分を upsert する
  （それ以前は GAS 由来の既存行が正本）。

使い方: python3 scripts/collect_operations.py
"""
import csv
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_goto_sangyo import parse_captures

JST = timezone(timedelta(hours=9))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(BASE, "history")
KYUSHU_CSV = os.path.join(HIST, "kyushu_results.csv")
KYUSHU_HEADER = ["date", "route", "vessel", "port", "time", "status",
                 "reason", "captured_at"]
CHANGES_CSV = os.path.join(HIST, "status_changes.csv")
GOTO_CSV = os.path.join(HIST, "goto_sangyo_results.csv")
GOTO_HEADER = ["date", "port", "time", "status", "note", "reason"]
GOTO_MOKO_FROM = "2026-11-06"


def dock_windows():
    """data/exceptions.csv から九州商船のドック期間（佐世保航路）を返す。"""
    path = os.path.join(BASE, "data", "exceptions.csv")
    wins = []
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["scope"].startswith("kyushu-") and "ドック" in row["note"]:
                    wins.append((row["date_from"], row["date_to"]))
    return wins


def kyushu_reason(row, wins):
    if row[5] != "✕":
        return ""
    if row[1] == "佐世保〜上五島" and any(a <= row[0] <= b for a, b in wins):
        return "ドック・整備"
    return "天候"

ROUTES = {"nagasaki_goto": "長崎〜五島", "sasebo_kamigoto": "佐世保〜上五島"}
VESSELS = {"ジェットフォイル": "JF", "フェリー": "Fe", "高速船": "高速"}
ICONS = {"available": "◯", "fully": "✕", "limited": "△"}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def strip_tags(html):
    txt = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    txt = re.sub(r"<[^>]+>", " ", txt)
    return re.sub(r"\s+", " ", txt)


def svc_date(page_date, th_text):
    m = re.match(r"\((\d{1,2})/(\d{1,2})\)", th_text)
    if not m:
        return page_date
    mo, dd = int(m.group(1)), int(m.group(2))
    y = page_date.year
    if mo < page_date.month - 6:
        y += 1
    elif mo > page_date.month + 6:
        y -= 1
    from datetime import date as _date
    return _date(y, mo, dd)


def parse_kyushu(html, now):
    m = re.search(r"更新：(\d{4})年(\d{1,2})月(\d{1,2})日", html)
    if not m:
        raise ValueError("更新日が見つからない")
    from datetime import date as _date
    page_date = _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    panels = [(mm.start(), mm.group(1))
              for mm in re.finditer(r'js-swich-target" data-swich="(\w+)"', html)]
    rows, warnings = [], []
    for i, (pos, key) in enumerate(panels):
        if key not in ROUTES:
            continue  # nagasaki_arikawa は全便運休中のため対象外
        end = panels[i + 1][0] if i + 1 < len(panels) else len(html)
        seg = html[pos:end]
        # h3（船種）→ h4（港）→ status-table の順に走査
        tokens = [(mm.start(), mm.group(1), mm.group(2)) for mm in re.finditer(
            r"<h3[^>]*>(.*?)</h3>|<h4[^>]*>(.*?)</h4>", seg)]
        # 上の finditer は group(1)=h3, group(2)=h4。走査し直す:
        events = []
        for mm in re.finditer(r"<h3[^>]*>(.*?)</h3>|<h4[^>]*>(.*?)</h4>|<table class=\"status-table[^\"]*\"", seg):
            if mm.group(1) is not None:
                events.append((mm.start(), "vessel", re.sub(r"<[^>]+>", "", mm.group(1)).strip()))
            elif mm.group(2) is not None:
                events.append((mm.start(), "port", re.sub(r"<[^>]+>", "", mm.group(2)).strip()))
            else:
                events.append((mm.start(), "table", mm.end()))
        vessel = port = None
        for j, (p, kind, val) in enumerate(events):
            if kind == "vessel":
                vessel = VESSELS.get(val)
            elif kind == "port":
                port = "奈留" if val == "奈留島" else val
            elif kind == "table" and vessel and port:
                tend = events[j + 1][0] if j + 1 < len(events) else len(seg)
                block = seg[val:tend]
                ths = re.findall(r"<th>(.*?)</th>", block, flags=re.S)
                icons = re.findall(r"status-(\w+)\.webp", block)
                if len(ths) != len(icons):
                    warnings.append(f"{ROUTES[key]}/{vessel}/{port}: 行{len(ths)}件≠アイコン{len(icons)}件")
                for th, icon in zip(ths, icons):
                    th = re.sub(r"<[^>]+>", "", th).strip()
                    tm = re.search(r"(\d{1,2}):(\d{2})\s*発", th)
                    if not tm:
                        continue
                    if icon not in ICONS:
                        warnings.append(f"未知のアイコン: {icon}")
                        continue
                    d = svc_date(page_date, th)
                    rows.append([d.isoformat(), ROUTES[key], vessel, port,
                                 f"{int(tm.group(1))}:{tm.group(2)}",
                                 ICONS[icon], now.strftime("%Y-%m-%d %H:%M")])
    return rows, warnings


def upsert_csv(path, header, key_idx, new_rows):
    store = {}
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                vals = [row.get(h, "") for h in header]
                if "reason" in header and not vals[header.index("reason")] \
                        and vals[header.index("status")] == "✕":
                    vals[header.index("reason")] = "天候"  # 旧形式行の移行
                store[tuple(vals[i] for i in key_idx)] = vals
    for r in new_rows:
        store[tuple(r[i] for i in key_idx)] = r
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for k in sorted(store):
            w.writerow(store[k])
    return len(store)


def read_store(path, header):
    store = {}
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                store[tuple(row.get(h, "") for h in header[:5])] = row
    return store


def main():
    now = datetime.now(JST)
    wins = dock_windows()
    html = fetch("https://kyusho.co.jp/status")
    rows, warnings = parse_kyushu(html, now)
    for r in rows:
        r.insert(6, kyushu_reason(r, wins))
    # upsert + ステータス変化ログ
    store = {}
    if os.path.exists(KYUSHU_CSV):
        with open(KYUSHU_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                store[(row["date"], row["route"], row["vessel"], row["port"],
                       row["time"])] = [row.get(h, "") for h in KYUSHU_HEADER]
    changes = []
    for r in rows:
        k = tuple(r[i] for i in (0, 1, 2, 3, 4))
        if k in store and store[k][5] != r[5]:
            changes.append([now.strftime("%Y-%m-%d %H:%M"), r[0], r[1], r[2],
                            r[3], r[4], store[k][5], r[5]])
        store[k] = r
    with open(KYUSHU_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(KYUSHU_HEADER)
        for k in sorted(store):
            w.writerow(store[k])
    if changes:
        new_chg = not os.path.exists(CHANGES_CSV)
        with open(CHANGES_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new_chg:
                w.writerow(["changed_at", "date", "route", "vessel", "port",
                            "time", "from_status", "to_status"])
            w.writerows(changes)
    print(f"kyushu: parsed {len(rows)} rows, total {len(store)}, changes {len(changes)}")
    for wmsg in warnings:
        print("WARN:", wmsg, file=sys.stderr)

    top = fetch("https://www.goto-sangyo.co.jp/")
    text = strip_tags(top)
    cap = [(now.strftime("%Y/%m/%d %H:%M:%S"), now.strftime("%Y/%m/%d"), text)]
    grows = []
    for r in parse_captures(cap):
        if r[0] >= GOTO_MOKO_FROM:
            grows.append(r + ["天候" if r[3] == "✕" else ""])
    n2 = upsert_csv(GOTO_CSV, GOTO_HEADER, [0, 1, 2], grows)
    print(f"goto: parsed {len(grows)} rows (>= {GOTO_MOKO_FROM}), total {n2}")


if __name__ == "__main__":
    main()
