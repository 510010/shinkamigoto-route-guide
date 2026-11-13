#!/usr/bin/env python3
"""data-draft/ の名前ベースCSVを、仕様書§8の正式スキーマ（IDベース）へ変換する。
手作業マスター（operators / notices / exceptions / 運休航路）はこのスクリプト内の定義を使う。
使い方: python3 scripts/convert.py
"""
import csv, os, re, sys, calendar
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRAFT = os.path.join(ROOT, "data-draft")
DATA = os.path.join(ROOT, "data")
os.makedirs(DATA, exist_ok=True)

def read_csv(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))

def write_csv(name, fieldnames, rows):
    path = os.path.join(DATA, name)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})
    print(f"{name}: {len(rows)} rows")

# ---------------- operators (hand-maintained) ----------------
OPERATORS = [
    # id, name, official_url, status_url, reservation_url, phone, note
    ("kyushu", "九州商船", "https://kyusho.co.jp/", "https://kyusho.co.jp/status",
     "https://www2.kyusho.co.jp/", "0570-017-510", "予約センター"),
    ("goto-sangyo", "五島産業汽船", "https://www.goto-sangyo.co.jp/", "https://www.goto-sangyo.co.jp/",
     "", "0959-42-3939", "運航状況は公式サイトトップに掲載。乗船には予約が必要（鯛ノ浦本社）"),
    ("nomo", "野母商船", "https://www.nomo.co.jp/taiko/", "https://www.nomo.co.jp/taiko/",
     "https://order.nomo.co.jp/", "0570-01-0510", "フェリー太古。運航情報は公式サイトのお知らせで告知"),
    ("goto-ryokakusen", "五島旅客船株式会社", "https://goto-ryokyakusen.com/", "https://goto-ryokyakusen.com/",
     "", "0959-72-8151", "運航状況は公式サイトトップに掲載。予約は電話のみ（福江営業所）"),
    ("sakito", "崎戸商船", "", "",
     "", "0956-25-6118", "公式サイトなし。航路情報は佐世保旅客船協会・西海市のページと九州のりものinfoを参照（のりものinfoは現在メンテナンス中）"),
]
OP_NAME2ID = {name: oid for oid, name, *_ in OPERATORS}
# draft operator names -> id
OP_NAME2ID["五島旅客船株式会社"] = "goto-ryokakusen"

write_csv("operators.csv",
          ["operator_id", "name", "official_url", "status_url", "reservation_url", "phone", "note"],
          [dict(zip(["operator_id", "name", "official_url", "status_url", "reservation_url", "phone", "note"], o))
           for o in OPERATORS])

# ---------------- ports ----------------
ports = read_csv(os.path.join(DRAFT, "ports.csv"))
write_csv("ports.csv", list(ports[0].keys()), ports)
PORT_NAME2ID = {p["name"]: p["port_id"] for p in ports}
PORT_NAME2ID["奈留島"] = "naru"

def port_id(name, operator_id):
    pid = PORT_NAME2ID.get(name)
    if not pid:
        raise SystemExit(f"unknown port: {name}")
    return pid

# ---------------- stop_times conversion ----------------
STOP_FILES = ["kyushu_stop_times.csv", "goto-sangyo_stop_times.csv", "nomo_stop_times.csv",
              "goto-ryokakusen_stop_times.csv", "sakito_stop_times.csv"]

def route_for(operator_id, route_name, vessel):
    """(route_id, route_name, vessel_type) を返す"""
    if operator_id == "kyushu":
        if vessel == "ジェットフォイル":
            return ("kyushu-nagasaki-goto-jf", "長崎〜五島", "ジェットフォイル")
        if vessel.startswith("フェリー") and route_name == "長崎〜五島":
            return ("kyushu-nagasaki-goto-ferry", "長崎〜五島", "フェリー")
        if vessel.startswith("高速船"):
            return ("kyushu-sasebo-kamigoto-hs", "佐世保〜上五島", "高速船")
        if vessel.startswith("フェリー"):
            return ("kyushu-sasebo-kamigoto-ferry", "佐世保〜上五島", "フェリー")
    if operator_id == "goto-sangyo":
        return ("goto-sangyo-tainoura-nagasaki", "鯛ノ浦〜長崎", "高速船")
    if operator_id == "nomo":
        return ("nomo-hakata-fukue", "博多〜福江", "フェリー")
    if operator_id == "goto-ryokakusen":
        if vessel == "OCEAN":
            return ("ryokakusen-ocean", "郷ノ首〜福江", "フェリー（OCEAN）")
        return ("ryokakusen-taiyo", "郷ノ首〜福江", "高速船（TAIYO）")
    if operator_id == "sakito":
        return ("sakito-tomosumi-sasebo", "友住〜佐世保", "フェリー")
    raise SystemExit(f"route mapping missing: {operator_id} {route_name} {vessel}")

def pattern_kind(name):
    if "ドック" in name:
        return "例外（ドック）"
    if name.startswith("秋冬") or name.startswith("夏期") or name.startswith("冬期") or "春夏" in name:
        return "季節"
    return "通常"

patterns = OrderedDict()   # key -> row
trips = OrderedDict()      # trip_id -> row
stop_rows = []
routes = OrderedDict()

def slug(s):
    return re.sub(r"[^0-9A-Za-z]+", "-", s).strip("-").lower()

LABEL_MAP = {"下り便": "down", "上り便": "up", "下り": "down", "上り": "up"}

def trip_label_of(raw):
    s = LABEL_MAP.get(str(raw), str(raw))
    s = re.sub(r"便$", "", s)
    return slug(s) or "t"

for fn in STOP_FILES:
    rows = read_csv(os.path.join(DRAFT, fn))
    op_prefix = fn.split("_")[0]
    for r in rows:
        op_id = OP_NAME2ID[r["operator"]]
        rid, rname, vtype = route_for(op_id, r["route"], r["vessel"])
        if rid not in routes:
            routes[rid] = {"route_id": rid, "operator_id": op_id, "name": rname,
                           "vessel_type": vtype, "reservation_required": "", "checkin_deadline_min": "",
                           "suspended": "", "note": ""}
        pkey = (op_id, r["pattern"], r["valid_from"], r["valid_to"])
        if pkey not in patterns:
            pid = f"{op_prefix}-{slug(r['pattern']) or 'normal'}-{len([k for k in patterns if k[0]==op_id])+1}"
            patterns[pkey] = {"pattern_id": pid, "operator_id": op_id, "name": r["pattern"],
                              "kind": pattern_kind(r["pattern"]),
                              "valid_from": r["valid_from"], "valid_to": r["valid_to"]}
        pid = patterns[pkey]["pattern_id"]
        tkey = (rid, pid, r["trip"], r["direction"])
        trip_label = trip_label_of(r["trip"])
        pseq = pid.rsplit("-", 1)[-1]
        trip_id = f"{op_prefix}-{trip_label}-p{pseq}"
        if op_id == "goto-ryokakusen":
            trip_id = f"{op_prefix}-{'ocean' if r['vessel']=='OCEAN' else 'taiyo'}-{trip_label}-p{pseq}"
        if tkey not in trips:
            base = trip_id
            n = 2
            while trip_id in {t["trip_id"] for t in trips.values()}:
                trip_id = f"{base}-{n}"
                n += 1
            trips[tkey] = {"trip_id": trip_id, "route_id": rid, "pattern_id": pid,
                           "vessel_name": r["vessel"], "direction": r["direction"], "note": r["note"]}
        trip_id = trips[tkey]["trip_id"]
        seq = sum(1 for s in stop_rows if s["trip_id"] == trip_id) + 1
        stop_rows.append({"trip_id": trip_id, "seq": seq,
                          "port_id": port_id(r["port"], op_id),
                          "arrival": r["arrival"], "departure": r["departure"]})

# suspended route (no trips)
routes["kyushu-nagasaki-arikawa"] = {"route_id": "kyushu-nagasaki-arikawa", "operator_id": "kyushu",
                                     "name": "長崎〜有川", "vessel_type": "高速船", "reservation_required": "",
                                     "checkin_deadline_min": "", "suspended": "1",
                                     "note": "2025-08-25から全便運休中（再開未定）"}
if "goto-sangyo-tainoura-nagasaki" in routes:
    routes["goto-sangyo-tainoura-nagasaki"]["reservation_required"] = "1"

write_csv("routes.csv", ["route_id", "operator_id", "name", "vessel_type", "reservation_required",
                         "checkin_deadline_min", "suspended", "note"], list(routes.values()))
# 長崎フェリーのドックダイヤは適用期間が2つに分かれる（2026-04-03〜16 / 2026-10-05〜18）。
# v1 では直近の 10/5〜18 を有効期間として持ち、4月分は翌年度PDFで更新する。
for p in patterns.values():
    if p["operator_id"] == "kyushu" and p["name"] == "ドックダイヤ" and not p["valid_from"]:
        p["valid_from"], p["valid_to"] = "2026-10-05", "2026-10-18"
write_csv("service_patterns.csv", ["pattern_id", "operator_id", "name", "kind", "valid_from", "valid_to"],
          list(patterns.values()))
write_csv("trips.csv", ["trip_id", "route_id", "pattern_id", "vessel_name", "direction", "note"],
          list(trips.values()))
write_csv("stop_times.csv", ["trip_id", "seq", "port_id", "arrival", "departure"], stop_rows)
write_csv("ports.csv", list(ports[0].keys()), ports)

# ---------------- fares ----------------
FARE_FILES = ["kyushu_fares.csv", "goto-sangyo_fares.csv", "nomo_fares.csv",
              "goto-ryokakusen_fares.csv", "sakito_fares.csv"]
VESSEL_DEFAULT = {"nomo": "フェリー", "goto-ryokakusen": "", "goto-sangyo": "高速船", "sakito": "フェリー"}
KYUSHU_VESSELS = ("ジェットフォイル", "フェリー2等", "高速船")
fare_rows = []
for fn in FARE_FILES:
    for r in read_csv(os.path.join(DRAFT, fn)):
        op_id = OP_NAME2ID[r["operator"]]
        vessel = VESSEL_DEFAULT.get(op_id, "")
        if op_id == "kyushu":
            head = re.split(r"[、;；]", r["note"], maxsplit=1)[0].strip()
            if head in KYUSHU_VESSELS:
                vessel = head
        if op_id == "kyushu":
            # 九州商船は月次運賃：valid_from の属する月の月末日を valid_to とする。
            # 月ごとにドラフト行を蓄積すれば複数月分がそのまま併記される。
            y, m = int(r["valid_from"][:4]), int(r["valid_from"][5:7])
            valid_to = f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"
        else:
            valid_to = ""
        fare_rows.append({
            "operator_id": op_id,
            "from_port_id": port_id(r["from_port"], op_id),
            "to_port_id": port_id(r["to_port"], op_id),
            "vessel_type": vessel, "category": r["category"],
            "adult_oneway": r["adult_oneway"], "child_oneway": r["child_oneway"],
            "adult_roundtrip": r["adult_roundtrip"], "child_roundtrip": r["child_roundtrip"],
            "valid_from": r["valid_from"], "valid_to": valid_to,
            "note": r["note"], "source_url": r["source_url"]})
write_csv("fares.csv", ["operator_id", "from_port_id", "to_port_id", "vessel_type", "category",
                        "adult_oneway", "child_oneway", "adult_roundtrip", "child_roundtrip",
                        "valid_from", "valid_to", "note", "source_url"], fare_rows)

# ---------------- surcharges ----------------
sur_rows = []
for r in read_csv(os.path.join(DRAFT, "kyushu_surcharges.csv")):
    sur_rows.append({"operator_id": "kyushu", "route_name": r["route"], "vessel_type": r["vessel"],
                     "segment": r["segment"], "year_month": r["year_month"], "zone": r["zone"],
                     "adult": r["adult"], "child": r["child"], "note": r["note"], "source_url": r["source_url"]})
write_csv("surcharges.csv", ["operator_id", "route_name", "vessel_type", "segment", "year_month",
                              "zone", "adult", "child", "note", "source_url"], sur_rows)

# ---------------- notices / exceptions (hand-maintained) ----------------
NOTICES = [
    ("2026-11-11", "2026-11-27", "九州商船・佐世保〜上五島フェリーはドックダイヤで運航します",
     "FNこしき入渠のため「いのり」1隻体制となり、通常ダイヤとは時刻・行き先が異なります。時刻表にはドックダイヤを反映済みです。", "https://kyusho.co.jp/"),
    ("2026-11-04", "2026-11-10", "五島旅客船TAIYOはドック代船ダイヤで運航しています",
     "11月4日〜10日は代船による特別ダイヤです。本サイトの時刻表（通常ダイヤ）と時刻が異なります。公式サイトでご確認ください。", "https://goto-ryokyakusen.com/"),
    ("2026-11-05", "2026-11-23", "五島旅客船TAIYOは日曜・月曜が全便運休です",
     "船員不足のため、11月23日までTAIYOの日曜・月曜は全便運休です（認可済み）。", "https://goto-ryokyakusen.com/"),
    ("2026-11-29", "2026-12-28", "五島旅客船TAIYOは11月29日〜12月28日も日曜・月曜が全便運休予定です",
     "船員不足のため、11月29日〜12月28日の日曜・月曜も全便運休予定です（九州運輸局申請中）。運休日は11/29・30、12/6・7・13・14・20・21・27・28。", "https://goto-ryokyakusen.com/"),
    ("2026-11-15", "2026-11-16", "野母商船フェリー太古は計画運休です",
     "11月15日博多発の下り便と、11月16日福江発の上り便は計画運休です。", "https://www.nomo.co.jp/taiko/"),
    ("2027-01-24", "2027-11-29", "野母商船フェリー太古は2027年の運休日・ドック期間を発表しました",
     "2027年の運休日は1/24・25、2/14・15、3/28・29、6/27・28、9/26・27、10/24・25、11/28・29（いずれも日曜博多発・月曜福江発）。ドック期間は5月9日〜5月21日で太古は運航しません（貨物は代船で輸送）。", "https://www.nomo.co.jp/taiko/2026/11/13/2027%e5%b9%b4%e3%80%80%e9%81%8b%e4%bc%91%e6%97%a5%e3%83%bb%e3%83%89%e3%83%83%e3%82%af%e6%9c%9f%e9%96%93%e3%81%ae%e3%81%94%e6%a1%88%e5%86%85/"),
    ("2026-12-05", "2026-12-18", "九州商船・高速船シーレイディはドック休航予定です",
     "12月5日〜18日（予定）はシーレイディがドックのため休航し、佐世保〜上五島の高速船はシークイーンのみの運航となります。", "https://kyusho.co.jp/"),
]
write_csv("notices.csv", ["date_from", "date_to", "title", "body", "url"],
          [dict(zip(["date_from", "date_to", "title", "body", "url"], n)) for n in NOTICES])

# scope: trip_prefix | route_id ; kind: suspended | weekday_suspended
EXCEPTIONS = [
    ("2026-11-15", "2026-11-15", "trip_prefix", "nomo-down", "suspended", "", "計画運休（下り便）"),
    ("2026-11-16", "2026-11-16", "trip_prefix", "nomo-up", "suspended", "", "計画運休（上り便）"),
    ("2027-01-24", "2027-01-24", "trip_prefix", "nomo-down", "suspended", "", "計画運休（下り便）"),
    ("2027-01-25", "2027-01-25", "trip_prefix", "nomo-up", "suspended", "", "計画運休（上り便）"),
    ("2027-02-14", "2027-02-14", "trip_prefix", "nomo-down", "suspended", "", "計画運休（下り便）"),
    ("2027-02-15", "2027-02-15", "trip_prefix", "nomo-up", "suspended", "", "計画運休（上り便）"),
    ("2027-03-28", "2027-03-28", "trip_prefix", "nomo-down", "suspended", "", "計画運休（下り便）"),
    ("2027-03-29", "2027-03-29", "trip_prefix", "nomo-up", "suspended", "", "計画運休（上り便）"),
    ("2027-05-09", "2027-05-20", "trip_prefix", "nomo-down", "suspended", "", "ドック期間のため運休"),
    ("2027-05-09", "2027-05-21", "trip_prefix", "nomo-up", "suspended", "", "ドック期間のため運休"),
    ("2027-06-27", "2027-06-27", "trip_prefix", "nomo-down", "suspended", "", "計画運休（下り便）"),
    ("2027-06-28", "2027-06-28", "trip_prefix", "nomo-up", "suspended", "", "計画運休（上り便）"),
    ("2027-09-26", "2027-09-26", "trip_prefix", "nomo-down", "suspended", "", "計画運休（下り便）"),
    ("2027-09-27", "2027-09-27", "trip_prefix", "nomo-up", "suspended", "", "計画運休（上り便）"),
    ("2027-10-24", "2027-10-24", "trip_prefix", "nomo-down", "suspended", "", "計画運休（下り便）"),
    ("2027-10-25", "2027-10-25", "trip_prefix", "nomo-up", "suspended", "", "計画運休（上り便）"),
    ("2027-11-28", "2027-11-28", "trip_prefix", "nomo-down", "suspended", "", "計画運休（下り便）"),
    ("2027-11-29", "2027-11-29", "trip_prefix", "nomo-up", "suspended", "", "計画運休（上り便）"),
    ("2026-12-05", "2026-12-18", "trip_prefix", "kyushu-sl", "suspended", "", "シーレイディ ドック休航（予定）"),
    ("2027-02-01", "2027-02-26", "trip_prefix", "kyushu-sq", "suspended", "", "シークイーン ドック休航（予定）"),
    ("2027-01-01", "2027-01-01", "route", "sakito-tomosumi-sasebo", "suspended", "", "元日運休（毎年）"),
    ("2027-01-01", "2027-01-01", "route", "ryokakusen-ocean", "suspended", "", "元日運休（毎年）"),
    ("2027-01-01", "2027-01-01", "route", "ryokakusen-taiyo", "suspended", "", "元日運休（毎年）"),
    ("2026-01-01", "2026-11-23", "route", "ryokakusen-taiyo", "weekday_suspended", "0,1", "船員不足のため日曜・月曜運休（〜2026-11-23）"),
    ("2026-11-29", "2026-12-28", "route", "ryokakusen-taiyo", "weekday_suspended", "0,1", "船員不足のため日曜・月曜運休（2026-11-29〜12-28、九州運輸局申請中）"),
]
write_csv("exceptions.csv", ["date_from", "date_to", "scope_type", "scope", "kind", "weekdays", "note"],
          [dict(zip(["date_from", "date_to", "scope_type", "scope", "kind", "weekdays", "note"], e)) for e in EXCEPTIONS])

print("conversion done")
