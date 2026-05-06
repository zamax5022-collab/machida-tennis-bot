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

# 環境変数
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
    try:
        driver = get_driver()
        wait = WebDriverWait(driver, 20)
        
        # 1-4. 検索手順（省略せず確実に実行）
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

        # 5. カレンダー画面で日付をクリック
        time.sleep(10)
        js_click = f"var d='{date_str}';var a=document.getElementsByTagName('a');for(var i=0;i<a.length;i++){{if((a[i].getAttribute('href')||'').includes(d)||(a[i].getAttribute('onclick')||'').includes(d)){{a[i].click();break;}}}}"
        driver.execute_script(js_click)
        
        # 6. 時間帯別空き状況画面（ここが本番）
        time.sleep(8)
        slots = []
        
        # 画面内の全てのテーブルを解析
        tables = driver.find_elements(By.XPATH, "//table[@bordercolor='#333399']")
        
        for table in tables:
            try:
                # 施設名を取得（テーブルの直前にあるリンクテキスト）
                park_name = table.find_element(By.XPATH, "./preceding::a[contains(@id, 'LnkSisetu名')][1]").text
                
                # 時間帯の見出し（9:00〜11:00など）を取得
                time_headers = [th.text.replace("\n", "") for th in table.find_elements(By.XPATH, ".//tr[2]/th")]
                
                # コート（A面、B面など）の行をループ
                rows = table.find_elements(By.XPATH, ".//tr[position()>2]")
                for row in rows:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if not cells: continue
                    
                    court_name = cells[0].text # A面、B面など
                    
                    # 各時間帯の「○」をチェック
                    for i, cell in enumerate(cells[1:]):
                        if i < len(time_headers) and ("○" in cell.text or "△" in cell.text):
                            slots.append(f"📍{park_name}\n   └ {court_name}：{time_headers[i]}")
            except:
                continue

        if slots:
            # 重複を除去して整理
            unique_slots = list(dict.fromkeys(slots))
            final_msg = f"🎾 {target_date.strftime('%m/%d')}の空き状況（○/△）\n\n" + "\n".join(unique_slots)
        else:
            final_msg = f"📅 {target_date.strftime('%m/%d')}は空きがありませんでした。"
        
    except Exception as e:
        final_msg = f"⚠️ 取得エラーが発生しました。\n(詳細: {str(e)[:50]})"
    finally:
        if driver: driver.quit()

    # プッシュ送信
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
                messages=[TextMessage(text=f"🔍 {target_date.strftime('%m/%d')}のコート別詳細を調べています...")]
            ))
        threading.Thread(target=scrap_and_push, args=(user_id, target_date)).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
