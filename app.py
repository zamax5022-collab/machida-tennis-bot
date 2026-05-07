import os
import re
import time
import threading
from datetime import datetime, timedelta
from flask import Flask, request, abort
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

app = Flask(__name__)

# LINE設定
access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
channel_secret = os.environ.get('LINE_CHANNEL_SECRET')
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, PushMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

configuration = Configuration(access_token=access_token)
handler = WebhookHandler(channel_secret)


# ─────────────────────────────────────────
# WebDriver初期化
# ─────────────────────────────────────────
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_argument('--window-size=1280,800')  # ヘッドレスでは--start-maximizedは無効
    chrome_options.add_argument('--blink-settings=imagesEnabled=false')  # 画像無効化でメモリ節約

    # Render環境のChromeバイナリを明示指定
    render_chrome = "/opt/render/project/.render/chrome/opt/google/chrome/google-chrome"
    if os.path.exists(render_chrome):
        chrome_options.binary_location = render_chrome

    # ChromeDriverをwebdriver-managerで自動取得
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)


# ─────────────────────────────────────────
# フレーム切替ユーティリティ
# ─────────────────────────────────────────
def enter_frame(driver, timeout=15):
    driver.switch_to.default_content()
    try:
        WebDriverWait(driver, timeout).until(
            EC.frame_to_be_available_and_switch_to_it((By.NAME, "MainFrame"))
        )
    except Exception:
        pass  # フレームがなければデフォルトコンテンツのまま続行


# ─────────────────────────────────────────
# LINEプッシュメッセージ送信
# ─────────────────────────────────────────
def push_line(user_id, text):
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).push_message(
            PushMessageRequest(to=user_id, messages=[TextMessage(text=text)])
        )


# ─────────────────────────────────────────
# スクレイピング本体
# ─────────────────────────────────────────
def scrap_and_push(user_id, target_date):
    driver = None
    step = "準備中"
    date_str = target_date.strftime('%Y%m%d')

    try:
        driver = get_driver()
        wait = WebDriverWait(driver, 20)

        # ── Step 1: 入口画面 ──────────────────────
        step = "1.入口画面"
        driver.get("https://www.pf489.com/machida/dselect.html")
        enter_frame(driver)
        btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//a[contains(., '高機能検索')]")
        ))
        driver.execute_script("arguments[0].click();", btn)

        # ── Step 2: 条件設定画面 ──────────────────
        step = "2.条件設定画面"
        enter_frame(driver)
        labels = wait.until(EC.presence_of_all_elements_located((By.TAG_NAME, "label")))
        for label in labels:
            if "テニスコート" in label.text and "コミュニティ" not in label.text:
                cb_id = label.get_attribute("for")
                if cb_id:
                    try:
                        cb = driver.find_element(By.ID, cb_id)
                        if not cb.is_selected():
                            driver.execute_script("arguments[0].click();", cb)
                    except Exception:
                        pass

        submit_btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//input[@value='空き照会']")
        ))
        driver.execute_script("arguments[0].click();", submit_btn)

        # ── Step 3: カレンダー画面 ────────────────
        step = f"3.日付選択({date_str})"
        enter_frame(driver)
        target_xpath = (
            f"//a[contains(@href, '{date_str}') "
            f"and (contains(text(), '○') or contains(text(), '△'))]"
        )
        try:
            link = wait.until(EC.element_to_be_clickable((By.XPATH, target_xpath)))
            driver.execute_script("arguments[0].click();", link)
        except Exception:
            push_line(user_id, f"📅 {target_date.strftime('%m/%d')}は現在「○/△」がありません。")
            return

        # ── Step 4: 時間帯別空き状況 ──────────────
        step = "4.詳細解析"
        enter_frame(driver)

        # テーブルが描画されるまで待機
        wait.until(EC.presence_of_element_located(
            (By.XPATH, "//table[contains(@id, 'dlJikantai')]")
        ))

        slots = []
        tables = driver.find_elements(By.XPATH, "//table[contains(@id, 'dlJikantai')]")

        for table in tables:
            # 施設名取得（日本語IDの文字化け対策で部分一致を緩く）
            try:
                park_name = table.find_element(
                    By.XPATH, "./preceding::a[contains(@id, 'LnkSisetu')][1]"
                ).text.strip()
            except Exception:
                park_name = "施設名不明"

            rows = table.find_elements(By.XPATH, ".//tr[position()>2]")
            for row in rows:
                cells = row.find_elements(By.TAG_NAME, "td")
                if not cells:
                    continue
                court = cells[0].text.strip()
                for cell in cells[1:]:
                    if "○" in cell.text or "△" in cell.text:
                        slots.append(f"📍{park_name} {court}")
                        break  # コートごとに1件あれば十分

        if slots:
            unique_slots = list(dict.fromkeys(slots))[:10]
            msg = f"🎾 {target_date.strftime('%m/%d')} 空きあり！\n" + "\n".join(unique_slots)
        else:
            msg = f"📅 {target_date.strftime('%m/%d')} 空きはありませんでした"

        push_line(user_id, msg)

    except Exception as e:
        push_line(
            user_id,
            f"⚠️ エラーが発生しました (Step: {step})\n"
            f"しばらく待ってから再度お試しください。\n詳細: {str(e)[:100]}"
        )
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


# ─────────────────────────────────────────
# Webhookエンドポイント
# ─────────────────────────────────────────
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except Exception:
        abort(400)
    return 'OK'


# ─────────────────────────────────────────
# メッセージハンドラ
# ─────────────────────────────────────────
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    text = event.message.text.strip()
    user_id = event.source.user_id
    today = datetime.now()
    target_date = None

    if "今日" in text:
        target_date = today
    elif "明日" in text:
        target_date = today + timedelta(days=1)
    else:
        # MM/DD または M/D 形式に対応
        m = re.search(r'(\d{1,2})/(\d{1,2})', text)
        if m:
            try:
                month, day = int(m.group(1)), int(m.group(2))
                target_date = today.replace(month=month, day=day)
            except ValueError:
                pass

    if target_date:
        # 即座にreplyしてLINEのタイムアウト（10秒）を回避
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(
                        text=f"🎾 {target_date.strftime('%m/%d')}の空きを確認します...\n少々お待ちください。"
                    )]
                )
            )
        # バックグラウンドでスクレイピング開始
        threading.Thread(
            target=scrap_and_push,
            args=(user_id, target_date),
            daemon=True
        ).start()
    else:
        # 認識できないメッセージへの案内
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(
                        text="📅 日付を指定して送ってください\n例：「今日」「明日」「05/10」"
                    )]
                )
            )


# ─────────────────────────────────────────
# ヘルスチェック用エンドポイント（UptimeRobot等で定期pingに使用）
# ─────────────────────────────────────────
@app.route("/health", methods=['GET'])
def health():
    return 'OK', 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
