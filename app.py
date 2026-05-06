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

app = Flask(__name__)

# LINE設定
access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
channel_secret = os.environ.get('LINE_CHANNEL_SECRET')
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, PushMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent
configuration = Configuration(access_token=access_token)
handler = WebhookHandler(channel_secret)

def get_driver():
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--window-size=1920,1080')
    return webdriver.Chrome(options=chrome_options)

def scrap_and_push(user_id, target_date):
    driver = None
    date_str = target_date.strftime('%Y%m%d') # image_76075e.png のリンク判定用
    try:
        driver = get_driver()
        wait = WebDriverWait(driver, 20)
        
        # 1. 画面選択 (image_7607d5.jpg)
        driver.get("https://www.pf489.com/machida/dselect.html")
        time.sleep(2)
        try: driver.switch_to.frame("MainFrame")
        except: pass

        # 高機能検索をクリック
        search_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(., '高機能検索')]")))
        driver.execute_script("arguments[0].click();", search_btn)
        
        # 2. 高機能検索 (image_76079e.jpg)
        time.sleep(3)
        # 「テニスコート」を選択
        labels = driver.find_elements(By.TAG_NAME, "label")
        for label in labels:
            if "テニスコート" in label.text and "コミュニティ" not in label.text:
                cb = driver.find_element(By.ID, label.get_attribute("for"))
                if not cb.is_selected():
                    driver.execute_script("arguments[0].click();", cb)
        
        # 空き照会ボタンをクリック
        time.sleep(1)
        driver.execute_script("document.querySelector('input[value=\"空き照会\"]').click();")

        # 3. 施設別空き状況 (image_76075e.png)
        time.sleep(8)
        # 指定日の「○」または「△」のリンクを探してクリック
        # image_76075e.png の下部にある __doPostBack を含むリンクを特定
        found_date = False
        links = driver.find_elements(By.TAG_NAME, "a")
        for link in links:
            href = link.get_attribute("href") or ""
            text = link.text
            if date_str in href and ("○" in text or "△" in text):
                driver.execute_script("arguments[0].click();", link)
                found_date = True
                break
        
        if not found_date:
            final_msg = f"📅 {target_date.strftime('%m/%d')}は、施設別一覧で空き（○/△）が見つかりませんでした。"
        else:
            # 4. 時間帯別空き状況 (image_760471.png)
            time.sleep(8)
            slots = []
            
            # 画面内の全てのテーブルをループ
            tables = driver.find_elements(By.XPATH, "//table[contains(@id, 'dlJikantai')]")
            for table in tables:
                try:
                    # 施設名を取得 (テーブルの直前にある a タグ)
                    park_name = table.find_element(By.XPATH, "./preceding::a[contains(@id, 'LnkSisetu名')][1]").text.strip()
                    
                    # 時間帯のヘッダーを取得 (tr[2]のth列)
                    time_headers = [th.text.replace("\n", "") for th in table.find_elements(By.XPATH, ".//tr[2]/th")]
                    
                    # 各「面」(A面、B面など)の行をスキャン
                    rows = table.find_elements(By.XPATH, ".//tr[position()>2]")
                    for row in rows:
                        cells = row.find_elements(By.TAG_NAME, "td")
                        if not cells: continue
                        
                        court_name = cells[0].text.strip() # 例: A面
                        for i, cell in enumerate(cells[1:], 1):
                            if "○" in cell.text or "△" in cell.text:
                                time_range = time_headers[i] if i < len(time_headers) else f"枠{i}"
                                slots.append(f"📍{park_name}【{court_name}】\n   └ {time_range}")
                except:
                    continue

            if slots:
                final_msg = f"🎾 {target_date.strftime('%m/%d')}の空きを発見！\n\n" + "\n\n".join(list(dict.fromkeys(slots)))
            else:
                final_msg = f"📅 {target_date.strftime('%m/%d')}：詳細画面に遷移しましたが、空き枠の読み取りに失敗しました。"

    except Exception as e:
        final_msg = f"⚠️ エラーが発生しました\n内容: {str(e)[:100]}"
    finally:
        if driver: driver.quit()

    # LINE送信
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
                messages=[TextMessage(text=f"🔍 町田市予約システムを深層スキャン中（{target_date.strftime('%m/%d')}）...")]
            ))
        threading.Thread(target=scrap_and_push, args=(user_id, target_date)).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
