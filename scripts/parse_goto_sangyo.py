#!/usr/bin/env python3
"""五島産業汽船の運航実績を、生文スナップショットから便別に起こす解析器。

parse_captures(captures) が本体。
  captures: [(取得日時 'YYYY/MM/DD HH:MM:SS', 対象日 'YYYY/MM/DD', 生テキスト), ...]
  戻り値: [[date_iso, port, time, status, note], ...]

CLI として使う場合： Google Sheets「欠航率調べ_波予報と欠航情報」の 五島産業_raw
タブを values get で取得した JSON を goto_raw.json として置き、実行すると
goto_parsed.csv を書く。

方針： 文中の日付アンカー（本日/明日/明後日・M/D・N日）ごとに便を割り当て、
明記された欠航・運航を優先し、通常運航の包括指定は明記がない便だけに適用。
特別ダイヤの日は直近のダイヤ表記を採用する。
検証： 2025-12-26 / 2026-01-10 / 01-21 / 01-22 / 03-06 / 11-05 の6日分を
原文と突き合わせて一致を確認済み（2026-11-06）。
"""
import json
import re
from datetime import date, timedelta
from collections import defaultdict


def _norm(t):
    t = re.sub(r"<[^>]+>", " ", t)
    t = t.replace("&nbsp;", " ").replace("：", ":").replace("　", " ").replace("長 崎", "長崎")
    return re.sub(r"\s+", " ", t)


def _cap_date(s):
    y, m, dd = s.split(" ")[0].split("/")
    return date(int(y), int(m), int(dd))


def _tmm(s):
    h, m = s.split(":")
    return f"{int(h)}:{m}"


_ANCH = re.compile(r"(本日|明日|明後日)\s*\(?\s*(\d{1,2})/(\d{1,2})\s*\)?|(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)|(?<!\d)(\d{1,2})日")
_ENUM = re.compile(r"(鯛ノ浦|長崎)発\s*([\d:、，及びと\s]+?)(?=鯛ノ浦発|長崎発|は|を|明日|明後日|本日|$)")


def _resolve_md(cd, m, dd):
    for off in range(-4, 6):
        t = cd + timedelta(days=off)
        if t.month == m and t.day == dd:
            return t
    return None


def parse_captures(captures):
    stmts = {}

    def put(key, prio, idx, st, note):
        cur = stmts.get(key)
        if cur is None or (prio, idx) >= (cur[0], cur[1]):
            stmts[key] = (prio, idx, st, note)

    universes = defaultdict(set)
    for idx, (cap_s, tgt_s, raw) in enumerate(captures):
        cd = _cap_date(cap_s)
        txt = _norm(raw)
        for port_jp, port in (("鯛ノ浦発", "鯛ノ浦"), ("長崎発", "長崎")):
            ms = list(re.finditer(port_jp + r"\s*((?:[①②③④]\s*\d{1,2}:\d{2}\s*)+)", txt))
            if ms:
                m = ms[-1] if "特別ダイヤ" in txt else ms[0]
                for tm in re.findall(r"\d{1,2}:\d{2}", m.group(1)):
                    universes[cd].add((port, _tmm(tm)))
                    universes[cd + timedelta(days=1)].add((port, _tmm(tm)))
        cur_date = cd
        for s in [x for x in re.split(r"[。]", txt) if x.strip()]:
            if "運航ダイヤはコチラ" in s:
                continue
            events = []
            for mm in _ANCH.finditer(s):
                if mm.group(1):
                    rel = {"本日": 0, "明日": 1, "明後日": 2}[mm.group(1)]
                    events.append((mm.start(), "anchor", cd + timedelta(days=rel)))
                elif mm.group(4):
                    t = _resolve_md(cd, int(mm.group(4)), int(mm.group(5)))
                    if t:
                        events.append((mm.start(), "anchor", t))
                elif mm.group(6):
                    tt = None
                    for off in range(-4, 6):
                        cand = cd + timedelta(days=off)
                        if cand.day == int(mm.group(6)):
                            tt = cand
                            break
                    if tt:
                        events.append((mm.start(), "anchor", tt))
            for mm in _ENUM.finditer(s):
                times = [_tmm(x) for x in re.findall(r"\d{1,2}:\d{2}", mm.group(2))]
                if times:
                    events.append((mm.start(), "enum", (mm.group(1), times, mm.end())))
            events.sort()
            allcancel_here = "全便欠航" in s
            sent_cancel = "欠航" in s
            sent_op = ("運航" in s) and not allcancel_here
            local_date = cur_date
            for pos, kind, val in events:
                if kind == "anchor":
                    local_date = val
                else:
                    port, times, eend = val
                    after = s[eend:]
                    nxt = _ANCH.search(after)
                    window = after[:nxt.start()] if nxt else after
                    if "欠航" in window:
                        st = "✕"
                    elif "運航" in window:
                        st = "◯"
                    elif sent_cancel and not sent_op:
                        st = "✕"
                    elif sent_op and not sent_cancel:
                        st = "◯"
                    elif sent_cancel:
                        st = "✕"
                    else:
                        continue
                    for tm in times:
                        universes[local_date].add((port, tm))
                        put((local_date, port, tm), 2, idx, st, "明記")
            if events:
                last_anchor = [v for _, k, v in events if k == "anchor"]
                if last_anchor:
                    cur_date = last_anchor[-1]
            if allcancel_here:
                pos = s.find("全便欠航")
                gov = cur_date
                for p, k, v in events:
                    if k == "anchor" and p <= pos:
                        gov = v
                for (port, tm) in list(universes.get(gov, set())):
                    put((gov, port, tm), 2, idx, "✕", "全便欠航")
            elif sent_op and ("通常運航" in s or "運航予定" in s or "運航します" in s or "運航いたします" in s):
                gov = cur_date
                for (port, tm) in list(universes.get(gov, set())):
                    if (gov, port, tm) not in stmts or stmts[(gov, port, tm)][0] < 2:
                        put((gov, port, tm), 1, idx, "◯", "包括指定")

    out = []
    keys = set(stmts) | {(dt, p, t) for dt, ss in universes.items() for (p, t) in ss}
    for (dt, port, tm) in sorted(keys):
        if (dt, port, tm) in stmts:
            prio, idx, st, note = stmts[(dt, port, tm)]
            out.append([dt.isoformat(), port, tm, st, note])
    return out


if __name__ == "__main__":
    import csv
    d = json.load(open("goto_raw.json"))
    rows = (d.get("values") or [])[1:]
    parsed = parse_captures(rows)
    with open("goto_parsed.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "port", "time", "status", "note"])
        w.writerows(parsed)
    print(f"parsed {len(parsed)} services")
