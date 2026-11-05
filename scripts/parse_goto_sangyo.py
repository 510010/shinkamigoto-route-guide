#!/usr/bin/env python3
"""五島産業汽船の運航実績を GAS の生文スナップショットから便別に起こす。

入力： Google Sheets「欠航率調べ_波予報と欠航情報」の 五島産業_raw タブを
      values get で取得した JSON（goto_raw.json としてカレントに置く）
出力： goto_parsed.csv（date, port, time, status, note）
方針： 文中の日付アンカー（本日/明日/明後日・M/D・N日）ごとに便を割り当て、
      明記された欠航・運航を優先し、通常運航の包括指定は明記がない便だけに適用。
      特別ダイヤの日は直近のダイヤ表記を採用する。
検証： 2025-12-26 / 2026-01-10 / 01-21 / 01-22 / 03-06 / 11-05 の6日分を
      原文と突き合わせて一致を確認済み（2026-11-06）。
"""
import json, re, csv
from datetime import date, timedelta
from collections import defaultdict, Counter

d = json.load(open("goto_raw.json"))
rows = (d.get("values") or [])[1:]

def norm(t):
    t = re.sub(r"<[^>]+>", " ", t)
    t = t.replace("&nbsp;", " ").replace("：", ":").replace("　", " ").replace("長 崎", "長崎")
    return re.sub(r"\s+", " ", t)

def cap_date(s):
    y, m, dd = s.split(" ")[0].split("/")
    return date(int(y), int(m), int(dd))

def tmm(s):  # '07:45' -> '7:45'
    h, m = s.split(":"); return f"{int(h)}:{m}"

ANCH = re.compile(r"(本日|明日|明後日)\s*\(?\s*(\d{1,2})/(\d{1,2})\s*\)?|(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)|(?<!\d)(\d{1,2})日")
ENUM = re.compile(r"(鯛ノ浦|長崎)発\s*([\d:、，及びと\s]+?)(?=鯛ノ浦発|長崎発|は|を|明日|明後日|本日|$)")

def resolve_md(cd, m, dd):
    for off in range(-4, 6):
        t = cd + timedelta(days=off)
        if t.month == m and t.day == dd: return t
    return None

# stmts[(date,port,time)] = (priority, capture_idx, status, note); priority 2=explicit,1=general
stmts = {}
def put(key, prio, idx, st, note):
    cur = stmts.get(key)
    if cur is None or (prio, idx) >= (cur[0], cur[1]):
        stmts[key] = (prio, idx, st, note)

universes = defaultdict(set)
for idx, (cap_s, tgt_s, raw) in enumerate(rows):
    cd = cap_date(cap_s)
    txt = norm(raw)
    for port_jp, port in (("鯛ノ浦発", "鯛ノ浦"), ("長崎発", "長崎")):
        ms = list(re.finditer(port_jp + r"\s*((?:[①②③④]\s*\d{1,2}:\d{2}\s*)+)", txt))
        if ms:
            m = ms[-1] if "特別ダイヤ" in txt else ms[0]
            for tm in re.findall(r"\d{1,2}:\d{2}", m.group(1)):
                universes[cd].add((port, tmm(tm))); universes[cd + timedelta(days=1)].add((port, tmm(tm)))
    cur_date = cd
    for s in [x for x in re.split(r"[。]", txt) if x.strip()]:
        if "運航ダイヤはコチラ" in s: continue
        # events in order
        events = []
        for mm in ANCH.finditer(s):
            if mm.group(1):
                rel = {"本日":0,"明日":1,"明後日":2}[mm.group(1)]
                events.append((mm.start(), "anchor", cd + timedelta(days=rel)))
            elif mm.group(4):
                t = resolve_md(cd, int(mm.group(4)), int(mm.group(5)))
                if t: events.append((mm.start(), "anchor", t))
            elif mm.group(6):
                t = resolve_md(cd, cd.month if int(mm.group(6))>=cd.day-4 else cd.month, int(mm.group(6)))
                # bare N日: find month by proximity
                tt = None
                for off in range(-4, 6):
                    cand = cd + timedelta(days=off)
                    if cand.day == int(mm.group(6)): tt = cand; break
                if tt: events.append((mm.start(), "anchor", tt))
        for mm in ENUM.finditer(s):
            times = [tmm(x) for x in re.findall(r"\d{1,2}:\d{2}", mm.group(2))]
            if times: events.append((mm.start(), "enum", (mm.group(1), times, mm.end())))
        events.sort()
        allcancel_here = "全便欠航" in s
        sent_cancel = "欠航" in s
        sent_op = ("運航" in s) and not allcancel_here
        # assign enums to governing anchor (last anchor at or before enum start, else cur_date)
        local_date = cur_date
        for pos, kind, val in events:
            if kind == "anchor": local_date = val
            else:
                port, times, eend = val
                after = s[eend:]
                nxt = ANCH.search(after)
                window = after[:nxt.start()] if nxt else after
                if "欠航" in window: st = "✕"
                elif "運航" in window: st = "◯"
                elif sent_cancel and not sent_op: st = "✕"
                elif sent_op and not sent_cancel: st = "◯"
                elif sent_cancel: st = "✕"  # sentence-level fallback (mixed anchor sentence)
                else: continue
                for tm in times:
                    universes[local_date].add((port, tm))
                    put((local_date, port, tm), 2, idx, st, "明記")
        if events:
            last_anchor = [v for _, k, v in events if k == "anchor"]
            if last_anchor: cur_date = last_anchor[-1]
        if allcancel_here:
            # applies to the anchor governing the 全便欠航 position
            pos = s.find("全便欠航")
            gov = cur_date
            for p, k, v in events:
                if k == "anchor" and p <= pos: gov = v
            for (port, tm) in list(universes.get(gov, set())):
                put((gov, port, tm), 2, idx, "✕", "全便欠航")
        elif sent_op and ("通常運航" in s or "運航予定" in s or "運航します" in s or "運航いたします" in s):
            gov = cur_date
            for (port, tm) in list(universes.get(gov, set())):
                if (gov, port, tm) not in stmts or stmts[(gov, port, tm)][0] < 2:
                    put((gov, port, tm), 1, idx, "◯", "包括指定")

out, unresolved = [], []
keys = set(stmts) | {(dt, p, t) for dt, ss in universes.items() for (p, t) in ss}
for (dt, port, tm) in sorted(keys):
    if (dt, port, tm) in stmts:
        prio, idx, st, note = stmts[(dt, port, tm)]
        out.append([dt.isoformat(), port, tm, st, note])
    else: unresolved.append((dt, port, tm))
with open("goto_parsed.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["date","port","time","status","note"]); w.writerows(out)
c = Counter(r[3] for r in out); days = sorted(set(r[0] for r in out))
print("parsed:", len(out), dict(c), "| unresolved:", len(unresolved), "| days:", len(days), days[0], "->", days[-1])
for dt in ("2025-12-26","2026-01-10","2026-01-21","2026-01-22","2026-03-06","2026-11-05"):
    sub = [r for r in out if r[0]==dt]
    print(dt, " | ".join(f"{r[1]}{r[2]}={r[3]}" for r in sub))
