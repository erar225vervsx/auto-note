# 自動note

市場調査 → 需要調査 → note記事の執筆 → (人が公開) → Threads / Instagram での集客、を
毎日回すシステムです。調査と執筆は Claude の定期タスク(Pro プランの使用枠)が行い、残りは GitHub Actions が行います。
人がやるのは「note に貼り付けて公開し、URL をコメントする」だけです。手順の詳細は [WRITER.md](WRITER.md)。

## 全体の流れ

| 段階 | 何をするか | 使うもの |
|---|---|---|
| 1. 戦略選定(30日ごと) | ジャンル候補5つと収益モデル(有料記事 / アフィリエイト / 無料で集客)の仮説を出し、候補ごとにウェブ検索で需要・競合・有料記事の相場を調べて1つに決める | Claude 定期タスク(Pro)+ ウェブ検索 |
| 2. ネタ決め | 読者が今困っている疑問と、既存記事が答えきれていない点をウェブ検索で探す | 同上 |
| 3. 執筆 | 本文 → 厳しめの自己採点 → 75点未満なら1回書き直し → それでも未満なら見送り。SNS の文面も作り、`inbox/` に置く | 同上 |
| 4. 公開待ち | `inbox/` に記事が置かれると、見出し画像を作り、記事・ハッシュタグ・公開手順・出典を Issue「【公開待ち】…」にまとめる | GitHub Actions、Issues |
| 5. 公開(人) | Issue の内容を note に貼って公開し、Issue に note の URL をコメントする | note |
| 6. SNS(自動) | URL のコメントを合図に、Threads に告知1本+要点1本、Instagram に要点カードをカルーセル投稿し、Issue を閉じる | Threads API、Instagram API |

調査結果には出典URLが残ります。検索が使えなかったときは「根拠なし(AIの知識のみ)」と記録し、Issue にも表示します。

## なぜ note の公開だけ手動なのか

note は GitHub などのサーバーからの機械的なアクセスを拒否しています(403)。制限をすり抜ける方法は使わず、
note には直接アクセスしない設計にしました。手動にすることで、公開前に人が内容を確認でき、アカウント停止のリスクも下がります。

## セットアップ

1. **リポジトリ**:このリポジトリ(公開)。Instagram は「誰でも開ける画像URL」しか受け付けないため公開にし、`config.yaml` の `sns.instagram.image_base_url` に raw URL を設定済み。
2. **執筆**:Claude の定期タスク(毎日)に WRITER.md の手順で書かせる。GitHub を Claude に連携し、Claude GitHub App を auto-note に入れておく。
   予備として `command=run` で Gemini(無料枠、`GEMINI_API_KEY`)に書かせることもできる。
3. **Threads**:Meta for Developers でアプリを作り、Threads API(`threads_basic`, `threads_content_publish`)を追加 → 長期アクセストークンを発行。Secrets に `THREADS_USER_ID` / `THREADS_ACCESS_TOKEN`。
4. **Instagram**:プロアカウント(ビジネス or クリエイター)に切り替え、Instagram API(Instagramログイン)で `instagram_business_basic`, `instagram_business_content_publish` を許可した長期トークンを発行。Secrets に `IG_USER_ID` / `IG_ACCESS_TOKEN`。
5. **トークンの自動更新用**:Secrets 書き込み権限のある GitHub の Personal Access Token を `GH_PAT` に登録(Threads/Instagramのトークンは60日で切れるため、月2回自動で更新します)。
6. (任意)Discord / Slack の Webhook URL を `NOTIFY_WEBHOOK_URL` に登録すると、記事ができたときなどに通知が届く。
7. **試運転**:定期タスクを手動で1回動かし、「【公開待ち】」Issue ができることを確かめる。

## 日々の運用で人がやること(1日数分)

- 「【公開待ち】」Issue を開き、手順どおり note に貼り付けて公開する
- 公開したら、その Issue に note の URL をコメントする(リポジトリの持ち主のコメントだけが反応します)
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
  sns.py        Threads / Instagram 投稿、トークン更新
  images.py     見出し画像・Instagramカード生成
  analytics.py  レポート・通知
  llm.py        AI 呼び出し(Gemini / Claude、混雑時は軽いモデルに切り替え)
  pipeline.py   実行の入口
state/          戦略・記事ネタ・履歴・下書き(Actionsが自動でコミット)
public/images/  生成画像
tests/          外部接続なしで全段を通すテスト
```

## 費用の目安

- GitHub Actions:公開リポジトリなので無料
- 執筆:Claude Pro の使用枠の中で動く(追加料金なし)。その日のチャットで使える量は減る
- 予備の Gemini API(`command=run`):無料枠。混雑すると失敗しやすい
- Threads / Instagram API:無料
