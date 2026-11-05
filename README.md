# 上五島航路案内

新上五島町に関わる船舶（フェリー・高速船・ジェットフォイル）の時刻表と運賃を、
町民と観光客の両方がスマートフォンで素早く調べられるようにした非公式の案内サイトです。

- 公開URL（予定）: https://510010.github.io/shinkamigoto-route-guide/
- 個人運営（非公式）です。運航可否・最新運賃の最終確認は各事業者の公式情報でお願いします。

## 構成

- `site/` — 静的サイト本体（HTML/CSS/JS、PWA）。`site/data.json` は生成物です
- `data/` — 正本CSV（港・事業者・航路・運行パターン・便・発着時刻・運賃・調整金・お知らせ・例外）
- `data-draft/` — 情報収集時の転記ドラフト（出典メモ）
- `scripts/` — `convert.py`（ドラフト→正式CSV）、`validate.py`（検証）、`build_data.py`（data.json生成）
- `上五島航路案内_仕様書_v0.3.md` — 仕様書

## データ更新の流れ

1. `data/` のCSVを編集する
2. `python3 scripts/validate.py` で検証
3. `python3 scripts/build_data.py` で `site/data.json` を再生成
4. push すると GitHub Actions が検証・生成・公開（GitHub Pages）を自動で行います

燃料調整金は月次で変わります（九州商船）。`data/surcharges.csv` と九州商船の運賃（`data/fares.csv`）は毎月差し替えてください。

## 対象事業者

九州商船、五島産業汽船、野母商船、五島旅客船、崎戸商船
