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
    # 町田市のシステムに合わせ、あえて古いブラウザのふりをして安定させます
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    return webdriver.Chrome(options=chrome_options)

def scrap_and_push(user_id, target_date):
    driver = None
    date_str = target_date.strftime('%Y%m%d')
    try:
        driver = get_driver()
        wait = WebDriverWait(driver, 20)
        
        # 1-4. 検索手順
        driver.get("https://www.pf489.com/machida/dselect.html")
        
        # メインフレームに切り替え（町田市攻略の鍵）
        time.sleep(3)
        try:
            driver.switch_to.frame("MainFrame")
        except:
            pass # フレームがない場合はそのまま進む

        search_btn = wait.until(EC.presence_of_element_located((By.XPATH, "//a[contains(., '高機能検索')]")))
        driver.execute_script("arguments[0].click();", search_btn)
        
        time.sleep(5)
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
        
        # 6. 時間帯別空き状況画面の解析
        time.sleep(10)
        slots = []
        
        # 画面上の全ての「○」や「△」を探し、その親要素をたどって情報を特定する
        elements = driver.find_elements(By.XPATH, "//*[contains(text(), '○') or contains(text(), '△')]")
        
        for el in elements:
            try:
                # この「○」が含まれるテーブル行(tr)を取得
                row = el.find_element(By.XPATH, "./ancestor::tr[1]")
                # その行の1番左のセルがコート名
                court_name = row.find_elements(By.TAG_NAME, "td")[0].text.strip()
                
                # その行が含まれるテーブルの直近にある施設名を取得
                table = el.find_element(By.XPATH, "./ancestor::table[1]")
                park_name = table.find_element(By.XPATH, "./preceding::a[contains(@id, 'LnkSisetu名')][1]").text.strip()
                
                # 何番目の列かによって時間を特定（少し強引ですが確実な方法）
                cell_index = el.find_element(By.XPATH, "./ancestor::td[1]").get_attribute("cellIndex")
                # 列番号から時間を推測（町田市の標準レイアウト）
                times = ["9-11", "11-13", "13-15", "15-17", "17-19", "19-21"]
                time_label = times[int(cell_index)-1] if 0 < int(cell_index) <= len(times) else "不明な時間"
                
                slots.append(f"📍{park_name}\n   └ {court_name}：{time_label}")
            except:
                continue

        if slots:
            unique_slots = list(dict.fromkeys(slots))
            final_msg = f"🎾 {target_date.strftime('%m/%d')}の空きを発見！\n\n" + "\n".join(unique_slots)
        else:
            final_msg = f"📅 {target_date.strftime('%m/%d')}は、詳細画面でも空きが見つかりませんでした。"
        
    except Exception as e:
        final_msg = f"⚠️ 取得エラー\n詳細: {str(e)[:100]}"
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
                messages=[TextMessage(text=f"🔍 {target_date.strftime('%m/%d')}の深層データをスキャン中です...")]
            ))
        threading.Thread(target=scrap_and_push, args=(user_id, target_date)).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
