#!/usr/bin/env python3
"""サイト表示用の運航状況JSON（site/status.json）を history の蓄積から生成する。

第1弾（九州商船・五島産業汽船の便別表示、2026-11-07承認の掲載方針）の供給側。
collect_operations.py の直後に実行する想定で、「今日（JST）」の分だけを出す。

掲載方針との対応:
- 表示は今日が主体。2026-11-28 追加：事業者が翌日分を先行して出すため
  （五島産業は夕方に翌日の予定へ切替、九州商船は今日と明日を併記）、
  いつの状況か分かるよう日付を明示し、翌日分が揃っている場合は
  「明日の運航予定」として分けて入れる。五島産業の夕方の包括指定は
  実績に混ぜず goto_plan.json 経由で予定としてだけ出す。
- 取得時刻の併記： 事業者ごとに captured_at を持たせる。ただし表示する時刻は
  「その内容が確定した時刻」とする（2026-11-24 追加改定：内容が変わらないのに
  取得時刻だけ毎時進むのは違和感がある、というユーザーの指摘）。内部的には
  実際の最終取得時刻（fetched_at）も持ち、陳腐化判定にはそちらを使う。
  fetched_at は九州商船＝当日行の captured_at の最大値（夕方の翌日切替後は
  当日分が更新されなくなるため「当日分を最後に確認した時刻」になる）、
  五島産業＝蓄積CSVに captured_at がないためCSVの更新時刻（＝直前の収集時刻）。
  表示時刻は history/status_display.json に内容の署名とともに保持し、
  内容が前回生成時から変わっていなければ前回の表示時刻を引き継ぐ。
- 便数の異常時はその事業者を出さない： ok=False とし services は空にする
  （九州 30〜60便、五島産業 2〜8便の範囲外はレイアウト変更等の疑い）。
  フロント側は ok=False の事業者を「確認できません」＋公式リンクで表示する。
- 事業者ごとの陳腐化： 実際の最終取得時刻（fetched_at）が約90分以上前なら、
  その事業者も ok=False にする（片方の取得だけ止まった場合に、古い状況を
  出し続けないため。
  2026-11-24 五島産業の状況欄消失で、CSV更新時刻ベースの captured_at が
  実態より新しく見えた件を受けた追加）。ただし九州商船は、公式ページの
  主日付が翌日に切り替わると当日行が更新されなくなるため、陳腐化判定は
  当日＋翌日行の最新 captured_at（＝直近で解析に成功した時刻）で行う
  （2026-11-28、ページが昼前に翌日へ切り替わり当日分が誤って落ちた件）。
- フロント側は generated_at の古さでは表示を落とさない（2026-11-24 改定：
  デプロイ失敗で「取得できているのに出ない」が繰り返されたため。日付が
  今日でないJSONはフロントが弾く）。事業者単位の陳腐化は上記の ok 判定で担保する。

使い方: python3 scripts/build_status.py
"""
import csv
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(BASE, "history")
OUT = os.path.join(BASE, "site", "status.json")
STATE = os.path.join(HIST, "status_display.json")

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
    today_rows, fetched = [], None
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    tomorrow_rows, t_fetched = [], None
    alive = None
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["date"] in (today, tomorrow) and (
                        alive is None or r["captured_at"] > alive):
                    alive = r["captured_at"]
                if r["date"] == tomorrow:
                    tomorrow_rows.append(r)
                    if t_fetched is None or r["captured_at"] > t_fetched:
                        t_fetched = r["captured_at"]
                    continue
                if r["date"] != today:
                    continue
                today_rows.append(r)
                if fetched is None or r["captured_at"] > fetched:
                    fetched = r["captured_at"]
    # 表示は最新の取得バッチの行だけにする（2026-11-28 追加）。蓄積は
    # 追加・上書きのみのため、公式の表から消えた行（0:00掲載のドック
    # ダイヤ行が10:18の通常ダイヤ表への差し替え後も残った等）が
    # 「幽霊行」として表示され続けてしまう。最新バッチ＝現行の公式表。
    def _svc(r):
        svc = {"route": r["route"], "vessel": r["vessel"],
               "port": r["port"], "time": r["time"],
               "status": r["status"]}
        # 抜港先リスト（寄港しない港）があれば持たせる（2026-11-28 追加）
        sk = [p for p in (r.get("skips") or "").split("・") if p]
        if sk:
            svc["skips"] = sk
        # 行き先別表記（行き先ごとに状態が分かれる便）があれば持たせる
        dm = {}
        for part in (r.get("dest_status") or "").split("・"):
            if ":" in part:
                n, s = part.split(":", 1)
                dm[n] = s
        if dm:
            svc["dest"] = dm
        return svc
    services = [_svc(r) for r in today_rows if r["captured_at"] == fetched]
    ok = KYUSHU_BAND[0] <= len(services) <= KYUSHU_BAND[1] \
        and not _stale(alive, now)
    # 明日分は最新バッチが揃っている場合だけ「明日の運航予定」として出す
    # （2026-11-28 追加：公式ページが今日と明日を並べるため、いつの状況か
    # 日付で区別して出す。部分的な表は出さない）
    t_services = [_svc(r) for r in tomorrow_rows
                  if r["captured_at"] == t_fetched]
    tomorrow_block = None
    if KYUSHU_BAND[0] <= len(t_services) <= KYUSHU_BAND[1] \
            and not _stale(alive, now):
        tomorrow_block = {"date": tomorrow,
                          "services": sort_services(t_services)}
    return {"operator_id": "kyushu", "fetched_at": fetched,
            "raw_services": sort_services(services),
            "raw_tomorrow": tomorrow_block["services"] if tomorrow_block else [],
            "tomorrow": tomorrow_block,
            "ok": ok, "services": sort_services(services) if ok else []}


def goto_block(today, now):
    path = os.path.join(HIST, "goto_sangyo_results.csv")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    services, t_services = [], []
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                svc = {"route": "鯛ノ浦〜長崎", "vessel": "",
                       "port": r["port"], "time": r["time"],
                       "status": r["status"]}
                if r["date"] == today:
                    services.append(svc)
                elif r["date"] == tomorrow:
                    t_services.append(svc)
        fetched = datetime.fromtimestamp(
            os.path.getmtime(path), JST).strftime("%Y-%m-%d %H:%M")
    else:
        fetched = None
    ok = GOTO_BAND[0] <= len(services) <= GOTO_BAND[1] \
        and not _stale(fetched, now)
    # 明日の欄：明記の予告（欠航予告など）があれば便別に、なければ夕方に
    # 記録された包括指定の予定（goto_plan.json）だけを出す（2026-11-28 追加）
    tomorrow_block = None
    if GOTO_BAND[0] <= len(t_services) <= GOTO_BAND[1]:
        tomorrow_block = {"date": tomorrow,
                          "services": sort_services(t_services)}
    else:
        plan_path = os.path.join(HIST, "goto_plan.json")
        if os.path.exists(plan_path):
            try:
                with open(plan_path, encoding="utf-8") as f:
                    plan = json.load(f)
                if plan.get("for_date") == tomorrow:
                    tomorrow_block = {"date": tomorrow,
                                      "plan": plan.get("status", "通常運航予定")}
            except (ValueError, OSError):
                pass
    return {"operator_id": "goto-sangyo", "fetched_at": fetched,
            "raw_services": sort_services(services),
            "raw_tomorrow": tomorrow_block["services"]
            if tomorrow_block and "services" in tomorrow_block else [],
            "tomorrow": tomorrow_block,
            "ok": ok, "services": sort_services(services) if ok else []}


def _signature(block):
    """表示内容の署名。内容が変わったかどうかだけを見る（明日の欄を含む）。"""
    payload = json.dumps(
        {"today": block["raw_services"],
         "tomorrow": block.get("raw_tomorrow", []),
         "plan": (block.get("tomorrow") or {}).get("plan")},
        ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _display_times(blocks, today):
    """表示用 captured_at を決める。内容が前回生成時と同じ事業者は前回の
    表示時刻を引き継ぎ、変わった事業者は今回の fetched_at を表示時刻にする。
    状態は history/status_display.json に日付つきで保持する。"""
    state = {}
    if os.path.exists(STATE):
        try:
            with open(STATE, encoding="utf-8") as f:
                state = json.load(f)
        except (ValueError, OSError):
            state = {}
    if state.get("date") != today:
        state = {"date": today, "operators": {}}
    ops = state.setdefault("operators", {})
    for b in blocks:
        sig = _signature(b)
        prev = ops.get(b["operator_id"]) or {}
        if prev.get("sig") == sig and prev.get("since"):
            b["captured_at"] = prev["since"]
        else:
            b["captured_at"] = b["fetched_at"]
            ops[b["operator_id"]] = {"sig": sig, "since": b["fetched_at"]}
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def main():
    now = datetime.now(JST)
    today = now.strftime("%Y-%m-%d")
    blocks = [kyushu_block(today, now), goto_block(today, now)]
    _display_times(blocks, today)
    for b in blocks:
        del b["fetched_at"], b["raw_services"], b["raw_tomorrow"]
    data = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M"),
        "date": today,
        "operators": blocks,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    for op in data["operators"]:
        print(f"{op['operator_id']}: ok={op['ok']} "
              f"services={len(op['services'])} captured_at={op['captured_at']}")
    print(f"wrote {OUT} (date {today})")


if __name__ == "__main__":
    main()
