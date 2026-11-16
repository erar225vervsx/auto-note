"""手元のPCで1回だけ実行し、note のログイン状態を保存するスクリプト。

使い方:
  pip install playwright && playwright install chromium
  python scripts/save_note_login.py
  → ブラウザが開くので、note に普通にログインする
  → ログインできたらターミナルで Enter を押す
  → note_state.b64 ができるので、中身を GitHub Secrets の NOTE_STORAGE_STATE に貼る
  → 貼り終えたら note_state.b64 は削除する(ログイン情報そのものなので共有しない)
"""
import base64
import json

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(locale="ja-JP")
    page = ctx.new_page()
    page.goto("https://note.com/login")
    input("ログインが完了したら Enter を押してください > ")
    state = ctx.storage_state()
    browser.close()

with open("note_state.b64", "w") as f:
    f.write(base64.b64encode(json.dumps(state).encode()).decode())
print("note_state.b64 を作成しました。Secrets に登録したら削除してください。")
