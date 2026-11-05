# 蓄積データ（欠航リスク予想用）

欠航リスク予想の学習材料として、**その時点でしか取れないデータ**を毎日夕方に追記していく場所。
夕方の収集cron `kamigoto-history-collect`（17:40頃 JST）が追記し、commit/push する。

## ファイル

- `wave_forecasts.csv` — 気象庁「海域毎の最大波高と周期」CSVから抽出した日最大波高。
  列： capture_date, captured_at, area_no, area_name, target_date, lead_days（1〜3）,
  max_wave_m, period_at_max_s, hours_covered（その日の3時間刻み行数、最大8）
  抽出は `scripts/collect_waves.py`（重複追記なし）。
- `wave_raw/` — 取得した生CSVの控え（`YYYY-MM-DD_wave_guid_<海域番号>.csv`、Shift_JISのまま）。
- `wind_forecasts.csv` — Open-Meteo の風予報から抽出した日最大風速など（2026-11-06 開始）。
  列： capture_date, captured_at, point（航路中間点6地点： 奈良尾/有川/鯛ノ浦/若松/崎戸/博多航路）,
  lat, lon, target_date, lead_days（1〜3）, max_wind_ms, dir_at_max_deg, max_gust_ms, hours_covered
  抽出は `scripts/collect_wind.py`（重複追記なし）。生JSONは `wind_raw/` に残す。
  波の正本は気象庁 waveinf のまま。風はこれが唯一の出典。
- `kyushu_results.csv` — 九州商船の便別実績（2026-11-06〜、モコ側の蓄積）。
  列： date, route（長崎〜五島/佐世保〜上五島）, vessel（JF/Fe/高速）, port, time, status（◯/✕/△）, captured_at
  出典は公式の運航状況ページで、`scripts/collect_operations.py` が毎夕 upsert する。
  長崎〜有川航路は2025-08-25から全便運休中のため含まない
  （同ページのパネルには運休の明記と共に便が「運航」アイコンで並んでおり、
  GASログの「長崎発・高速・欠航ゼロ」はこれを取り込んだもの）。
  GASシート 運航結果_log（2025-12-25〜）と二重蓄積で、相互の突き合わせ用。
- `wave_actuals.csv` — 波の実況ペア。気象庁CSVの解析区間（取得時刻以前）から作る日最大波高。
  列： area_no, area_name, date, max_wave_m, period_at_max_s, hours_covered, updated_at
  collect_waves.py が upsert する。予報（wave_forecasts）と実績を突き合わせる検証用。
- `status_changes.csv` — 便のステータス変化ログ（昼→夕方の遷移）。
  列： changed_at, date, route, vessel, port, time, from_status, to_status
  collect_operations.py が前回取得値と異なる便を自動追記する。「未定（△）がいつ欠航に
  変わったか」の分析用。昼キャプチャ（cron `kamigoto-midday-capture`、11時台）と
  夕方収集の2回/日で拾う。
- 実績ファイルの `reason` 列： 欠航理由のタグ（天候/ドック・整備/故障/乗務員/計画運休/
  その他/不明）。九州商船は data/exceptions.csv のドック期間に当たる佐世保航路の欠航を
  「ドック・整備」、他を「天候」と自動判定する。五島産業・崎戸は文面（海上時化等）より「天候」。
  野母・五島旅客船・崎戸の日次行は夕方収集が文面から判定する。
- `operation_results.csv` — 野母商船・五島旅客船・崎戸商船の運航実績（日次）。  列： date, operator_id（nomo/ryokakusen/sakito）, unit（全便/航路/便）, detail,
  status（運航/欠航（一部）/欠航（全便）/条件付き/運休（定期）/不明）, source, captured_at, note
- `goto_sangyo_results.csv` — 五島産業汽船の便別実績（2025-12-26〜2026-11-05、1,146便）。
  GASシート 五島産業_raw の生文を `scripts/parse_goto_sangyo.py` で機械解析した派生データ。
  列： date, port（鯛ノ浦/長崎）, time, status（◯/✕）, note（根拠の種別）。
  原文と突き合わせた6日分では全便一致。36便分は判定材料がなく未収録。
- `snapshots/YYYY-MM-DD/` — 各事業者ページの夕方時点のテキスト控え
  （kyushu_status.txt / goto_top.txt / nomo_top.txt / ryokakusen_top.txt / sakito.txt）。
  解釈に迷う日の原文を後から確認するために残す。

## 海域と航路の対応

- 海域43「長崎県西方・熊本県・有明海」： 長崎〜五島（九州商船）、佐世保〜上五島（九州商船）、
  鯛ノ浦〜長崎（五島産業汽船）、若松〜福江（五島旅客船）、佐世保〜友住（崎戸商船）
- 海域42「対馬海峡」： 博多〜福江（野母商船）。同航路の福江側は海域43にもかかるため両方記録する。

## ルール

- 追記のみ。過去行の書き換え・削除はしない（誤りに気づいたら note で訂正行を足す）。
- 九州商船の便別実績の正本はユーザーのGASシート「欠航率調べ_波予報と欠航情報」の
  運航結果_log。2026-11-06 からはモコ側でも kyushu_results.csv に二重蓄積する
  （ユーザーの決定。どちらが止まっても途切れないようにし、食い違いの検知にも使う）。
  snapshots の kyushu_status.txt は原文確認用の控え。
- 五島産業汽船の便別実績は goto_sangyo_results.csv（〜2026-11-05 は GAS の 五島産業_raw 由来、
  以降はモコ側の夕方解析）。snapshots の goto_top.txt は控え。
- 崎戸商船の日次ステータスは SmartGOTO 新上五島町版「まちニュース」
  （https://smart-goto.jp/shinkamigoto/ 、ログイン不要で公開）に崎戸商船本人が #船便 で
  投稿している（2026-11-06 確認。例：2026-11-05 は時化で全便欠航）。これを第一の取得源とする。
  九州のりものinfo.com は補助（2026-10-22から停止中）。
