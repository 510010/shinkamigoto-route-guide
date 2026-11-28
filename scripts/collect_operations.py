#!/usr/bin/env python3
"""九州商船と五島産業汽船の運航実績を公式ページから便別に蓄積する（二重蓄積）。

- 九州商船： https://kyusho.co.jp/status のHTMLを解析し、
  history/kyushu_results.csv に upsert する（キー： date, route, vessel, port, time）。
  長崎〜有川パネルは2025-08-25から全便運休中のため対象外（ページにも明記）。
  ステータス： status-available→◯ / status-fully→✕ / status-limited→△。
  行の日付は GAS と同じ規則を基本としつつ、港グループ内の (M/D) 継承と
  夕方の翌日切替（リセット）検知を行う（parse_kyushu の docstring 参照）。
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
from datetime import date as _date, datetime, time as _time, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_goto_sangyo import parse_captures

JST = timezone(timedelta(hours=9))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(BASE, "history")
KYUSHU_CSV = os.path.join(HIST, "kyushu_results.csv")
KYUSHU_HEADER = ["date", "route", "vessel", "port", "time", "status",
                 "reason", "captured_at", "skips", "dest_status"]
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


def marker_date(page_date, th_text):
    """th の (M/D) 付き日付を date に変換する。付きでなければ None。

    ページの表記は全角括弧「（11/28）」のため、半角・全角の両方に対応する
    （2026-11-28: 全角に対応しておらず翌日分の早朝便が当日分を上書きした）。
    """
    m = re.search(r"[(（](\d{1,2})/(\d{1,2})[)）]", th_text)
    if not m:
        return None
    mo, dd = int(m.group(1)), int(m.group(2))
    y = page_date.year
    if mo < page_date.month - 6:
        y += 1
    elif mo > page_date.month + 6:
        y -= 1
    return _date(y, mo, dd)


def parse_kyushu(html, now, stored_status=None):
    """九州商船の運航状況ページを便別に解析する。

    日付の割り当て（2026-11-21 のシャドー検証評価を受けた修正）:
    - 行は tr 単位で th（時刻）と td（状態）を対応付ける。アイコンの代わりに
      「〇(小値賀港･宇久平港への寄港なし)」「奈良尾港への寄港なし」等の
      テキスト注記がある行は部分運航で、◯として記録する（旧方式は th と
      アイコンを別々に zip していたため注記行以降がずれていた）。
    - (M/D) 付きの行はその日付。同じ港グループ内では、(M/D) が現れた行以降の
      無印行はその日付を継承する（翌日の早朝便の先行表示に対応）。
    - グループ先頭から (M/D) が現れるまでの行は「主日付」。通常はページの
      更新日だが、夕方の更新でページ全体が翌日分に切り替わる（リセット）と
      当日分が翌日分に化けるため、リセットを検知したら主日付を翌日にする。
    リセット検知（どちらか一方で成立）:
    - いずれかのグループの先頭行に (更新日+1日) の (M/D) がある。
    - 主日付=更新日で割り当てた行の中に、蓄積済み ✕ が ◯/△ に戻る
      「欠航の巻き戻し」がある（✕は当日中には戻らない。2件以上、
      または夕方17時以降の更新で1件以上）。
    stored_status: {(date, route, vessel, port, time): status}（検知用、任意）。
    戻り値: (rows, warnings)。rows は reason を含まない9列
    [date, route, vessel, port, time, status, captured_at, skips, dest_status]。
    skips は抜港先の港名を「・」でつないだ文字列（なければ空）。
    dest_status は行き先別表記を「港名:状態・…」にした文字列（なければ空）。
    """
    m = re.search(r"更新：(\d{4})年(\d{1,2})月(\d{1,2})日(?:\([^)]*\))?\s*(\d{1,2}):(\d{2})", html)
    if not m:
        raise ValueError("更新日時が見つからない")
    page_date = _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    update_time = _time(int(m.group(4)), int(m.group(5)))
    cap = now.strftime("%Y-%m-%d %H:%M")
    panels = [(mm.start(), mm.group(1))
              for mm in re.finditer(r'js-swich-target" data-swich="(\w+)"', html)]
    groups, warnings = [], []
    for i, (pos, key) in enumerate(panels):
        if key not in ROUTES:
            continue  # nagasaki_arikawa は全便運休中のため対象外
        end = panels[i + 1][0] if i + 1 < len(panels) else len(html)
        seg = html[pos:end]
        vessel = port = None
        cur_group = None
        for mm in re.finditer(
                r"<h3[^>]*>(.*?)</h3>|<h4[^>]*>(.*?)</h4>|<tr[^>]*>(.*?)</tr>",
                seg, flags=re.S):
            if mm.group(1) is not None:
                vessel = VESSELS.get(re.sub(r"<[^>]+>", "", mm.group(1)).strip())
                cur_group = None
            elif mm.group(2) is not None:
                p = re.sub(r"<[^>]+>", "", mm.group(2)).strip()
                port = "奈留" if p == "奈留島" else p
                cur_group = None
            else:
                if not vessel or not port:
                    continue
                tr = mm.group(3)
                th = re.search(r"<th[^>]*>(.*?)</th>", tr, flags=re.S)
                if not th:
                    continue
                th_text = re.sub(r"<[^>]+>", "", th.group(1)).strip()
                tm = re.search(r"(\d{1,2}):(\d{2})\s*発", th_text)
                if not tm:
                    continue
                skips = []
                dest = ""
                icon = re.search(r"status-(\w+)\.webp", tr)
                if icon:
                    if icon.group(1) not in ICONS:
                        warnings.append(f"未知のアイコン: {icon.group(1)}")
                        continue
                    status = ICONS[icon.group(1)]
                else:
                    td = re.search(r"<td[^>]*>(.*?)</td>", tr, flags=re.S)
                    td_text = re.sub(r"<[^>]+>", "", td.group(1)).strip() if td else ""
                    dm = re.findall(r"([^\s　]+?)行き([○〇✕△])", td_text)
                    pairs = []
                    for dests, sym in dm:
                        st = "◯" if sym == "〇" else sym
                        for name in re.split(r"[･・、]", dests):
                            name = name.strip().rstrip("港")
                            if name:
                                pairs.append(
                                    ("奈留" if name == "奈留島" else name, st))
                    if len(pairs) >= 2:
                        # 行き先別表記（例「長崎行き✕　奈留・奈良尾行き〇」、
                        # 2026-11-28 追加）。便自体の状態は代表値にし、
                        # 行き先ごとの状態は dest_status に残す。
                        dest = "・".join(f"{n}:{s}" for n, s in pairs)
                        sts = {s for _, s in pairs}
                        status = "◯" if "◯" in sts else (
                            "✕" if sts == {"✕"} else "△")
                    elif "寄港なし" in td_text:
                        status = "◯"  # 部分運航（運航するが一部港に寄港しない）
                        # 抜港先の港名を構造化する（2026-11-28 追加）。既知の
                        # 形式「○(小値賀港･宇久平港への寄港なし)」に一致した
                        # ときだけ拾い、読めなければ空（従来どおり◯扱い）。
                        sm = re.search(r"[○〇]?\s*[（(]?([^()（）]*?)への寄港なし",
                                       td_text)
                        if sm:
                            for name in re.split(r"[･・、]", sm.group(1)):
                                name = name.strip().rstrip("港")
                                if name:
                                    skips.append(
                                        "奈留" if name == "奈留島" else name)
                    else:
                        warnings.append(
                            f"{ROUTES[key]}/{vessel}/{port} {th_text}: "
                            f"状態セルを解釈できない: {td_text!r}")
                        continue
                if cur_group is None:
                    cur_group = {"route": ROUTES[key], "vessel": vessel,
                                 "port": port, "rows": []}
                    groups.append(cur_group)
                cur_group["rows"].append({
                    "marker": marker_date(page_date, th_text),
                    "time": f"{int(tm.group(1))}:{tm.group(2)}",
                    "status": status,
                    "skips": skips,
                    "dest": dest,
                })

    def assign(main_date):
        rows = []
        for g in groups:
            cur = main_date
            for r in g["rows"]:
                if r["marker"] is not None:
                    cur = r["marker"]
                rows.append([cur.isoformat(), g["route"], g["vessel"],
                             g["port"], r["time"], r["status"], cap,
                             "・".join(r["skips"]), r["dest"]])
        return rows

    rows = assign(page_date)
    tomorrow = page_date + timedelta(days=1)
    rolled = any(g["rows"] and g["rows"][0]["marker"] == tomorrow
                 for g in groups)
    if not rolled and stored_status:
        flips = sum(
            1 for r in rows
            if r[0] == page_date.isoformat()
            and stored_status.get(tuple(r[i] for i in (0, 1, 2, 3, 4))) == "✕"
            and r[5] in ("◯", "△"))
        if flips >= 2 or (flips >= 1 and update_time >= _time(17, 0)):
            rolled = True
    if rolled:
        warnings.append(
            f"夕方の翌日切替（リセット）を検知: 主日付を {tomorrow.isoformat()} に切替")
        rows = assign(tomorrow)
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
    # 蓄積済みを先に読み、リセット検知（欠航の巻き戻し）に使う
    store = {}
    if os.path.exists(KYUSHU_CSV):
        with open(KYUSHU_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                store[(row["date"], row["route"], row["vessel"], row["port"],
                       row["time"])] = [row.get(h, "") for h in KYUSHU_HEADER]
    stored_status = {k: v[5] for k, v in store.items()}
    html = fetch("https://kyusho.co.jp/status")
    rows, warnings = parse_kyushu(html, now, stored_status)
    for r in rows:
        r.insert(6, kyushu_reason(r, wins))
    # upsert + ステータス変化ログ
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
    if grows:
        n2 = upsert_csv(GOTO_CSV, GOTO_HEADER, [0, 1, 2], grows)
    else:
        # 0行＝ページから状況欄が読めなかった。CSVを書き換えると更新時刻だけが
        # 進み、build_status が「取得できた」ように見せてしまうため触らない
        # （更新時刻が止まれば、build_status 側の陳腐化判定で表示が落ちる）。
        n2 = 0
        print("WARN: goto parse returned 0 rows; CSV left untouched", file=sys.stderr)
    print(f"goto: parsed {len(grows)} rows (>= {GOTO_MOKO_FROM}), total {n2}")


if __name__ == "__main__":
    main()
