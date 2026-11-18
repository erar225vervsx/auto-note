# 自動note

市場調査 → 需要調査 → note記事の執筆 → (人が公開) → Threads / Instagram での集客、を
毎日回すシステムです。調査と執筆は Claude の定期タスク(Pro プランの使用枠)が行い、残りは GitHub Actions が行います。
人がやるのは「投稿キットのボタンで note・Threads・Instagram に投稿する」ことだけです。執筆の手順は [WRITER.md](WRITER.md)。

**投稿キット一覧:** https://erar225vervsx.github.io/auto-note/kit/

## 全体の流れ

| 段階 | 何をするか | 使うもの |
|---|---|---|
| 1. 戦略選定(30日ごと) | ジャンル候補5つと収益モデル(有料記事 / アフィリエイト / 無料で集客)の仮説を出し、候補ごとにウェブ検索で需要・競合・有料記事の相場を調べて1つに決める | Claude 定期タスク(Pro)+ ウェブ検索 |
| 2. ネタ決め | 読者が今困っている疑問と、既存記事が答えきれていない点をウェブ検索で探す | 同上 |
| 3. 執筆 | 本文 → 厳しめの自己採点 → 75点未満なら1回書き直し → それでも未満なら見送り。SNS の文面も作り、`inbox/` に置く | 同上 |
| 4. 投稿キット | `inbox/` に記事が置かれると、見出し画像・Instagram 用カード画像を作り、記事ごとの「投稿キット」ページと Issue「【公開待ち】…」を作る | GitHub Actions、GitHub Pages、Issues |
| 5. note に公開(人) | キットのボタンでタイトル・本文(見出しつき)・見出し画像・タグをコピーして note に貼り、公開。Issue に note の URL をコメント | note |
| 6. SNS に投稿(人) | URL のコメントを合図に、キットに Threads の投稿ボタン(公式の Web Intent。文面と記事リンクが入った状態で開く)が出る。Instagram はキャプションをコピーして画像を共有 | Threads、Instagram |

調査結果には出典URLが残ります。検索が使えなかったときは「根拠なし(AIの知識のみ)」と記録し、Issue にも表示します。

## なぜ投稿ボタンだけ人が押すのか

- note は GitHub などのサーバーからの機械的なアクセスを拒否しています(403)。制限をすり抜ける方法は使いません。
- Threads・Instagram の自動投稿には Meta の開発者アカウントが必要ですが、使えない状態のため、API を使わない形にしました。
- ボタンを押す前に人が内容を確認でき、アカウント停止のリスクも下がります。

## セットアップ

1. **リポジトリ**:このリポジトリ(公開)。Instagram は「誰でも開ける画像URL」しか受け付けないため公開にし、`config.yaml` の `sns.instagram.image_base_url` に raw URL を設定済み。
2. **執筆**:Claude の定期タスク(毎日)に WRITER.md の手順で書かせる。GitHub を Claude に連携し、Claude GitHub App を auto-note に入れておく。
   予備として `command=run` で Gemini(無料枠、`GEMINI_API_KEY`)に書かせることもできる。
3. **GitHub Pages**:Settings → Pages で「Deploy from a branch」「main」「/docs」を選ぶ(投稿キットの公開に使う)。
4. (任意)Discord / Slack の Webhook URL を `NOTIFY_WEBHOOK_URL` に登録すると、記事ができたときなどに通知が届く。
5. **試運転**:定期タスクを手動で1回動かし、「【公開待ち】」Issue ができることを確かめる。

## 日々の運用で人がやること(1日数分)

- 投稿キットを開き、ボタンでコピーして note に公開する
- 公開したら、その記事の Issue に note の URL をコメントする(リポジトリの持ち主のコメントだけが反応します)
- 1〜2分後、キットの Threads ボタンを押して投稿、Instagram はキャプションをコピー → 画像を共有して投稿
- 週1のレポートを見る
- 緊急停止:`config.yaml` の `run.kill_switch: true`

## 主な設定(config.yaml)

| 項目 | 意味 |
|---|---|
| `run.articles_per_run` | 1日に作る記事数 |
| `run.min_quality_score` | 自己レビューの合格点 |
| `strategy.fixed_genre` | ジャンルを固定したいときだけ書く(空ならAIが選ぶ) |
| `strategy.review_interval_days` | 戦略を見直す間隔 |
| `writing.model` | 執筆に使うモデル(gemini-* は無料枠、claude-* は有料) |

## ファイル構成

```
autonote/
  research.py   戦略選定・需要調査(Google 検索つき)・記事ネタの管理
  writer.py     執筆・自己レビュー・改稿
  gh.py         「公開待ち」Issue の作成・クローズ
  kit.py        投稿キット(docs/kits/*.json)の作成
  sns.py        SNS 文面の予備生成(通常は執筆時に Claude が用意)
  images.py     見出し画像・Instagramカード生成
  analytics.py  レポート・通知
  llm.py        AI 呼び出し(Gemini / Claude、混雑時は軽いモデルに切り替え)
  pipeline.py   実行の入口
state/          戦略・記事ネタ・履歴・下書き(Actionsが自動でコミット)
public/images/  生成画像
docs/kit/       投稿キットのページ(GitHub Pages)
tests/          外部接続なしで全段を通すテスト
```

## 費用の目安

- GitHub Actions:公開リポジトリなので無料
- 執筆:Claude Pro の使用枠の中で動く(追加料金なし)。その日のチャットで使える量は減る
- 予備の Gemini API(`command=run`):無料枠。混雑すると失敗しやすい
- Threads / Instagram:API は使わない(手動投稿)。費用なし
