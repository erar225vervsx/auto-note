# 自動note

市場調査 → 需要調査 → note執筆 → 公開 → Threads / Instagram での集客 → 成果の取り込み、を
GitHub Actions 上で毎日自動で回すシステムです。

## 全体の流れ

| 段階 | 何をするか | 使うもの |
|---|---|---|
| 1. 戦略選定(30日ごと) | AIがジャンル候補6つと収益モデル(有料記事 / アフィリエイト / 無料で集客)の仮説を出し、note上の実データ(上位記事のスキ数、有料記事の比率と価格、記事数)で比べて1つに決める。2回目以降は自分の記事の実績も判断材料にする | Gemini API(無料枠)、note検索 |
| 2. 需要調査(ネタが3本未満のとき) | 選んだジャンルでキーワードを広げて検索し、「需要があるのに上位記事が答えきれていない切り口」を記事案として点数付きで積む | 同上 |
| 3. 執筆 | 構成案 → 本文 → 厳しめの編集長役が採点 → 基準(75点)未満なら1回改稿 → それでも未満なら公開しない | Gemini API(無料枠) |
| 4. note公開 | 編集画面をブラウザ自動操作して、タイトル・本文・見出し画像・ハッシュタグを入れて公開 | Playwright |
| 5. SNS | Threads に告知1本+要点1本。Instagram に要点カード(縦長画像)をカルーセル投稿 | Threads API、Instagram API |
| 6. 成果取り込み | 自分の記事のスキ・コメント数を取得し、次の戦略選定とネタ選びに使う。週1でレポートを通知 | note公開データ |

公開・失敗・品質不足での見送りは、Discord / Slack に通知します(任意)。

## 先に知っておいてほしいリスク

- **noteの公開はブラウザ自動操作(非公式)です。** noteの公式APIは提携サービス専用で個人では使えません。画面が変わると公開に失敗します(失敗時は画面のスクリーンショットを残して停止し、途中まで公開することはありません)。また、自動投稿を理由にアカウントが制限される可能性があります。
- **有料記事は初期設定では「下書き保存して通知」です。** 有料設定の画面操作が未確認のため。`config.yaml` の `note.paid_mode: publish` で自動化できますが、最初は下書きで動作を確認してください。
- **調査に使うnoteのデータ取得も非公式のエンドポイントです。** 問い合わせ間隔を2秒空けて負荷をかけないようにしています。
- 記事末尾にはAI活用の明記を入れています(`config.yaml` の `writing.footer`)。

## セットアップ(初回だけ・人がやる作業)

1. **GitHubにリポジトリを作る**(非公開でOK)。このフォルダの中身を push する。
2. **Gemini APIキー(無料)**を Google AI Studio(https://aistudio.google.com/apikey)で作成し、Secrets の `GEMINI_API_KEY` に登録。支払い設定はしないこと(無料枠のまま使うため)。
3. **noteのログイン状態を保存**:手元のPCで
   ```
   pip install playwright && playwright install chromium
   python scripts/save_note_login.py
   ```
   できた `note_state.b64` の中身を Secrets の `NOTE_STORAGE_STATE` に貼り、ファイルは削除。
   Variables の `NOTE_URLNAME` に note のID(`https://note.com/<ここ>`)を登録。
4. **Threads**:Meta for Developers でアプリを作り、Threads API(`threads_basic`, `threads_content_publish`)を追加 → 長期アクセストークンを発行。Secrets に `THREADS_USER_ID` / `THREADS_ACCESS_TOKEN`。
5. **Instagram**:プロアカウント(ビジネス or クリエイター)に切り替え、Instagram API(Instagramログイン)で `instagram_business_basic`, `instagram_business_content_publish` を許可した長期トークンを発行。Secrets に `IG_USER_ID` / `IG_ACCESS_TOKEN`。
6. **Instagram用の画像の置き場所**:Instagramは「誰でも開ける画像URL」しか受け付けないため、このリポジトリは公開にし、`config.yaml` の `sns.instagram.image_base_url` に raw URL を設定済み。
7. **トークンの自動更新用**:Secrets 書き込み権限のある GitHub の Personal Access Token を `GH_PAT` に登録(Threads/Instagramのトークンは60日で切れるため、月2回自動で更新します)。
8. (任意)Discord / Slack の Webhook URL を `NOTIFY_WEBHOOK_URL` に登録。
9. **試運転**:Actions → autonote → Run workflow で `command=strategy`, `dry_run=true` → 次に `command=run`, `dry_run=true`。`state/drafts/` に記事、`state/strategy.json` に選ばれたジャンルが入るので確認する。
10. 問題なければ `dry_run=false` で1回手動実行し、noteに正しく公開されるかを目で確認。以降は毎日19時台に自動で動きます。

## 日々の運用で人がやること

- 通知を眺める(公開・見送り・失敗)
- 有料記事の下書きが来たら、noteで確認して公開
- 週1のレポートを見る
- 公開に失敗し続けたら、Actions の screenshots で画面を確認(noteの画面変更 → `note_publisher.py` のセレクタ修正が必要)
- 緊急停止:`config.yaml` の `run.kill_switch: true`

## 主な設定(config.yaml)

| 項目 | 意味 |
|---|---|
| `run.articles_per_run` | 1日に公開する記事数(1〜2推奨。増やすほど停止リスクと品質低下リスクが上がる) |
| `run.min_quality_score` | 自己レビューの合格点 |
| `strategy.fixed_genre` | ジャンルを固定したいときだけ書く(空ならAIが選ぶ) |
| `strategy.review_interval_days` | 戦略を見直す間隔 |
| `writing.model` | 執筆に使うモデル(gemini-* は無料枠、claude-* は有料) |
| `note.paid_mode` | 有料記事を下書き止めにするか、自動公開するか |

## ファイル構成

```
autonote/
  research.py        戦略選定・需要調査・記事ネタの管理
  note_api.py        noteの公開データ取得(非公式)
  writer.py          執筆・自己レビュー・改稿
  note_publisher.py  noteへの公開(Playwright)
  sns.py             Threads / Instagram 投稿、トークン更新
  images.py          見出し画像・Instagramカード生成
  analytics.py       成果取得・レポート・通知
  pipeline.py        実行の入口
state/               戦略・記事ネタ・履歴・下書き(Actionsが自動でコミット)
public/images/       生成画像
scripts/save_note_login.py  noteログイン状態の保存
tests/test_dryrun.py        外部接続なしで全段を通すテスト
```

## 費用の目安

- GitHub Actions:非公開リポジトリでも無料枠内に収まる想定(1日1回・数分〜十数分)
- Gemini API:無料枠のFlash系モデルを使うので0円。1日あたり5〜10回ほどの呼び出しで、無料枠の範囲に収まる想定。無料枠では送った内容がGoogleのサービス改善に使われることがある。上限に当たった日は記事の生成が翌日に回る
- 品質を上げたくなったら `writing.model` を `claude-sonnet-5-5` などに変え、`ANTHROPIC_API_KEY` を登録すると有料のClaude APIに切り替わる
- Threads / Instagram API:無料
