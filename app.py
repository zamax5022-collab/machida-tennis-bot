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
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1280,1024')
    return webdriver.Chrome(options=chrome_options)

def scrap_and_push(user_id, target_date):
    driver = None
    date_str = target_date.strftime('%Y%m%d')
    day_val = str(target_date.day) # 「7」など
    try:
        driver = get_driver()
        wait = WebDriverWait(driver, 20)
        
        driver.get("https://www.pf489.com/machida/dselect.html")
        search_btn = wait.until(EC.presence_of_element_located((By.XPATH, "//a[contains(., '高機能検索')]")))
        driver.execute_script("arguments[0].click();", search_btn)
        
        time.sleep(4)
        labels = wait.until(EC.presence_of_all_elements_located((By.TAG_NAME, "label")))
        for label in labels:
            if "テニスコート" in label.text and "コミュニティ" not in label.text:
                driver.execute_script("arguments[0].click();", driver.find_element(By.ID, label.get_attribute("for")))
        
        time.sleep(2)
        btns = driver.find_elements(By.TAG_NAME, "input")
        for b in btns:
            if "空き照会" in (b.get_attribute("value") or ""):
                driver.execute_script("arguments[0].click();", b)
                break

        time.sleep(10)
        # カレンダーをクリックして詳細画面へ
        js_click = f"var d='{date_str}';var a=document.getElementsByTagName('a');for(var i=0;i<a.length;i++){{if((a[i].getAttribute('href')||'').includes(d)||(a[i].getAttribute('onclick')||'').includes(d)){{a[i].click();break;}}}}"
        driver.execute_script(js_click)
        
        time.sleep(8)
        
        # --- ここからデータ抽出の改善 ---
        slots = []
        # 各施設ごとのテーブルブロックを取得
        tables = driver.find_elements(By.XPATH, "//table[@width='100%' and .//th[contains(text(), '水') or contains(text(), '木')]]")
        
        for table in tables:
            try:
                # 施設名を探す（テーブルの直前にあることが多い）
                park_name = table.find_element(By.XPATH, "./preceding::b[1]").text
                if "テニスコート" not in park_name: continue
                
                # ターゲットの日付の列（thのテキストがday_valと一致する列番号）を特定
                headers = table.find_elements(By.TAG_NAME, "th")
                col_index = -1
                for i, h in enumerate(headers):
                    if h.text.strip() == day_val:
                        col_index = i
                        break
                
                if col_index != -1:
                    # その列にある「○」や「△」を探す
                    cells = table.find_elements(By.TAG_NAME, "td")
                    # row内の該当列のテキストを確認（簡易版）
                    row_text = table.text
                    if "○" in row_text or "△" in row_text:
                        # 記号が含まれる場合のみリストに追加
                        status = "空きあり！" if "○" in row_text else "一部空き"
                        slots.append(f"📍 {park_name.split(' ')[0]}\n   状況: {status}")
            except:
                continue

        if slots:
            final_msg = f"🎾 {target_date.strftime('%m/%d')}の空き状況\n\n" + "\n".join(slots)
            final_msg += "\n\n※詳細は公式予約システムを確認してください。"
        else:
            final_msg = f"📅 {target_date.strftime('%m/%d')}は、現在空きがありません。"
        
    except Exception as e:
        final_msg = f"⚠️ 取得エラーが発生しました。\n(開発メモ: {str(e)[:50]})"
    finally:
        if driver: driver.quit()

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
                messages=[TextMessage(text=f"🔍 {target_date.strftime('%m/%d')}を検索します。")]
            ))
        threading.Thread(target=scrap_and_push, args=(user_id, target_date)).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
