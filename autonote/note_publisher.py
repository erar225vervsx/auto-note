"""note への公開(ブラウザ自動操作)。

note の公式APIは個人では使えないため、Playwright で編集画面を操作する。
画面の変更で壊れる可能性があるので、各操作は候補セレクタを複数持ち、
失敗時はスクリーンショットを残して処理を止める(中途半端な公開をしない)。

ログイン状態は scripts/save_note_login.py で手元のPCで保存し、
base64 にして Secrets の NOTE_STORAGE_STATE に入れる。
"""
from __future__ import annotations

import base64
import json
import random
import tempfile
import time
from pathlib import Path

import markdown as md

from .core import STATE_DIR, env, log
from .writer import split_paywall

TITLE_SEL = ['textarea[placeholder*="タイトル"]', 'textarea[placeholder*="記事タイトル"]']
BODY_SEL = ['div[contenteditable="true"][role="textbox"]', 'div.ProseMirror[contenteditable="true"]']
TAG_SEL = ['input[placeholder*="ハッシュタグ"]', 'input[role="combobox"]']


class PublishError(RuntimeError):
    pass


def _first(page, selectors: list[str], timeout: int = 15000):
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        for s in selectors:
            loc = page.locator(s).first
            try:
                if loc.count() and loc.is_visible():
                    return loc
            except Exception:  # noqa: BLE001
                pass
        page.wait_for_timeout(500)
    raise PublishError(f"要素が見つかりません: {selectors}")


def _click_text(page, texts: list[str], timeout: int = 15000) -> None:
    sels = [f'button:has-text("{t}")' for t in texts] + [f'[aria-label*="{t}"]' for t in texts]
    _first(page, sels, timeout).click()


def _human_pause(a: float = 0.6, b: float = 1.6) -> None:
    time.sleep(random.uniform(a, b))


def _paste_html(page, locator, html: str) -> None:
    """エディタに HTML を貼り付ける(1文字ずつ入力するより速く、見出しや箇条書きも保たれる)。"""
    locator.click()
    page.evaluate(
        """([html]) => {
            const el = document.activeElement;
            const dt = new DataTransfer();
            dt.setData('text/html', html);
            dt.setData('text/plain', html.replace(/<[^>]+>/g, ''));
            el.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
        }""",
        [html],
    )


def to_html(body_md: str) -> str:
    html = md.markdown(body_md, extensions=["extra", "sane_lists"])
    # note は h1 を本文に使わないので h2/h3 に寄せる
    return html.replace("<h1>", "<h2>").replace("</h1>", "</h2>")


def publish(article: dict, cfg: dict, eyecatch: Path | None = None) -> dict:
    """記事を公開し、{"url": ..., "mode": "published|draft"} を返す。"""
    from playwright.sync_api import sync_playwright

    nc = cfg["note"]
    free_md, paid_md = split_paywall(article["body_md"])
    want_paid = article["format"] == "paid" and paid_md is not None
    draft_only = want_paid and nc.get("paid_mode", "draft_only") == "draft_only"

    state = json.loads(base64.b64decode(env("NOTE_STORAGE_STATE")))
    shots = STATE_DIR / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p, tempfile.NamedTemporaryFile("w", suffix=".json") as tf:
        json.dump(state, tf)
        tf.flush()
        browser = p.chromium.launch(headless=nc.get("headless", True))
        ctx = browser.new_context(storage_state=tf.name, locale="ja-JP",
                                  viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        try:
            page.goto(nc["editor_url"], wait_until="domcontentloaded", timeout=60000)
            if "login" in page.url:
                raise PublishError("note のログイン状態が切れています。NOTE_STORAGE_STATE を更新してください")

            _first(page, TITLE_SEL, 30000).fill(article["title"])
            _human_pause()

            body_html = to_html(free_md if not want_paid else free_md + "\n\n" + paid_md)
            _paste_html(page, _first(page, BODY_SEL), body_html)
            _human_pause(1.5, 3)

            if eyecatch:
                _try_eyecatch(page, eyecatch)

            if draft_only:
                _click_text(page, ["下書き保存"])
                page.wait_for_timeout(3000)
                log.info("有料記事のため下書き保存のみ行いました: %s", article["title"])
                return {"url": page.url, "mode": "draft"}

            _click_text(page, ["公開に進む"])
            page.wait_for_timeout(2500)

            for tag in article.get("tags", [])[:8]:
                try:
                    tag_input = _first(page, TAG_SEL, 5000)
                    tag_input.fill(tag)
                    page.keyboard.press("Enter")
                    _human_pause(0.3, 0.8)
                except PublishError:
                    log.warning("ハッシュタグ入力欄が見つからないため、タグ付けをスキップ")
                    break

            if want_paid:
                _set_paid(page, article["price"])

            _click_text(page, ["投稿する", "公開する"])
            page.wait_for_timeout(5000)
            url = page.url if "/n/" in page.url else None
            return {"url": url, "mode": "published"}
        except Exception as e:
            shot = shots / f"fail-{int(time.time())}.png"
            try:
                page.screenshot(path=str(shot), full_page=True)
            except Exception:  # noqa: BLE001
                pass
            raise PublishError(f"note 公開に失敗: {e}(画面: {shot.name})") from e
        finally:
            ctx.close()
            browser.close()


def _try_eyecatch(page, path: Path) -> None:
    try:
        _click_text(page, ["画像を追加"], 5000)
        with page.expect_file_chooser(timeout=5000) as fc:
            _click_text(page, ["画像をアップロード"], 5000)
        fc.value.set_files(str(path))
        page.wait_for_timeout(2000)
        # トリミング画面の確定ボタン
        _click_text(page, ["保存", "完了", "適用"], 8000)
        page.wait_for_timeout(1500)
    except Exception as e:  # noqa: BLE001
        log.warning("見出し画像の設定をスキップ: %s", e)
        page.keyboard.press("Escape")


def _set_paid(page, price: int) -> None:
    """有料設定(実験的)。画面構成が確認できていないため、失敗したら公開を止める。"""
    try:
        _first(page, ['label:has-text("有料")', 'text=有料'], 5000).click()
        _first(page, ['input[name*="price"]', 'input[placeholder*="価格"]', 'input[type="number"]'],
               5000).fill(str(price))
    except PublishError as e:
        raise PublishError("有料設定の画面が見つからないため公開を中止しました") from e
