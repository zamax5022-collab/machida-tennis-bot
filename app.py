import os
import time
import threading
from datetime import datetime, timedelta
from flask import Flask, request, abort
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, PushMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent

app = Flask(__name__)

access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
channel_secret = os.environ.get('LINE_CHANNEL_SECRET')
configuration = Configuration(access_token=access_token)
handler = WebhookHandler(channel_secret)

def get_driver():
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu') # GPUを無効化してメモリ節約
    chrome_options.add_argument('--memory-pressure-off') # メモリ制限対策
    chrome_options.add_argument('--window-size=1280,1024')
    return webdriver.Chrome(options=chrome_options)

def scrap_and_push(user_id, target_date):
    driver = None
    date_str = target_date.strftime('%Y%m%d')
    try:
        driver = get_driver()
        wait = WebDriverWait(driver, 20)
        
        # 1. サイトアクセス
        driver.get("https://www.pf489.com/machida/dselect.html")
        
        # 2. 高機能検索
        search_btn = wait.until(EC.presence_of_element_located((By.XPATH, "//a[contains(., '高機能検索')]")))
        driver.execute_script("arguments[0].click();", search_btn)
        
        # 3. 施設選択
        time.sleep(4)
        labels = wait.until(EC.presence_of_all_elements_located((By.TAG_NAME, "label")))
        for label in labels:
            if "テニスコート" in label.text and "コミュニティ" not in label.text:
                driver.execute_script("arguments[0].click();", driver.find_element(By.ID, label.get_attribute("for")))
        
        # 4. 空き照会ボタン
        time.sleep(2)
        btns = driver.find_elements(By.TAG_NAME, "input")
        for b in btns:
            if "空き照会" in (b.get_attribute("value") or ""):
                driver.execute_script("arguments[0].click();", b)
                break

        # 5. カレンダー画面（ここが難所）
        time.sleep(10) # 画面遷移をじっくり待つ
        # onclick属性に日付が含まれる要素を直接JavaScriptで叩く（最も確実な方法）
        js_click_script = f"""
        var links = document.getElementsByTagName('a');
        for (var i = 0; i < links.length; i++) {{
            if (links[i].getAttribute('onclick') && links[i].getAttribute('onclick').includes('{date_str}')) {{
                links[i].click();
                return true;
            }}
        }}
        return false;
        """
        success = driver.execute_script(js_click_script)
        
        if not success:
            raise Exception(f"{date_str}の予約リンク（記号）が見つかりませんでした")
        
        # 6. 結果抽出（時間帯選択画面）
        time.sleep(7)
        slots = []
        rows = driver.find_elements(By.XPATH, "//tr[contains(., '○')]")
        for r in rows:
            txt = r.text.replace("\n", " ").strip()
            if txt: slots.append(f"■ {txt}")

        final_msg = f"【{target_date.strftime('%m/%d')}の空き状況】\n" + ("\n".join(slots) if slots else "空きはありませんでした。")
        
    except Exception as e:
        final_msg = f"【エラー詳細】\nステップ: {date_str}抽出中\n内容: {str(e)[:150]}"
    finally:
        if driver:
            driver.quit()

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[TextMessage(text=final_msg)]))

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    msg = event.message.text
    user_id = event.source.user_id
    if "今日" in msg or "明日" in msg:
        target_date = datetime.now() if "今日" in msg else datetime.now() + timedelta(days=1)
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=f"{target_date.strftime('%m/%d')}を検索中です。1分ほどで結果をプッシュ通知します。")]
            ))
        threading.Thread(target=scrap_and_push, args=(user_id, target_date)).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
