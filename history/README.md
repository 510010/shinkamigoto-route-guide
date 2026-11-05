# 蓄積データ（欠航リスク予想用）

欠航リスク予想の学習材料として、**その時点でしか取れないデータ**を毎日夕方に追記していく場所。
夕方の収集cron `kamigoto-history-collect`（17:40頃 JST）が追記し、commit/push する。

## ファイル

- `wave_forecasts.csv` — 気象庁「海域毎の最大波高と周期」CSVから抽出した日最大波高。
  列： capture_date, captured_at, area_no, area_name, target_date, lead_days（1〜3）,
  max_wave_m, period_at_max_s, hours_covered（その日の3時間刻み行数、最大8）
  抽出は `scripts/collect_waves.py`（重複追記なし）。
- `wave_raw/` — 取得した生CSVの控え（`YYYY-MM-DD_wave_guid_<海域番号>.csv`、Shift_JISのまま）。
- `operation_results.csv` — 野母商船・五島旅客船・崎戸商船の運航実績（日次）。
  列： date, operator_id（nomo/ryokakusen/sakito）, unit（全便/航路/便）, detail,
  status（運航/欠航（一部）/欠航（全便）/条件付き/運休（定期）/不明）, source, captured_at, note
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
  運航結果_log。ここの kyushu_status.txt はGAS停止時の保険。
- 五島産業汽船の便別実績の正本も同シートの 五島産業_raw（生文）。snapshots の goto_top.txt は
  こちら側の控え。
- 崎戸商船の日次ステータスは SmartGOTO 新上五島町版「まちニュース」
  （https://smart-goto.jp/shinkamigoto/ 、ログイン不要で公開）に崎戸商船本人が #船便 で
  投稿している（2026-11-06 確認。例：2026-11-05 は時化で全便欠航）。これを第一の取得源とする。
  九州のりものinfo.com は補助（2026-10-22から停止中）。
