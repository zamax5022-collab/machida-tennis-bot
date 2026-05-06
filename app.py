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

def wait_and_click(driver, xpath, timeout=20):
    """要素が表示され、クリック可能になるまで待機してクリックする安全関数"""
    element = WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((By.XPATH, xpath))
    )
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    time.sleep(1) # スクロール後の安定待ち
    driver.execute_script("arguments[0].click();", element)

def scrap_and_push(user_id, target_date):
    driver = None
    date_str = target_date.strftime('%Y%m%d')
    try:
        driver = get_driver()
        
        # 1. 画面選択
        driver.get("https://www.pf489.com/machida/dselect.html")
        time.sleep(2)
        try: driver.switch_to.frame("MainFrame")
        except: pass

        # 高機能検索をクリック
        wait_and_click(driver, "//a[contains(., '高機能検索')]")
        
        # 2. 高機能検索
        time.sleep(2)
        # 「テニスコート」を選択
        labels = WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.TAG_NAME, "label"))
        )
        for label in labels:
            if "テニスコート" in label.text and "コミュニティ" not in label.text:
                cb = driver.find_element(By.ID, label.get_attribute("for"))
                if not cb.is_selected():
                    driver.execute_script("arguments[0].click();", cb)
        
        # 空き照会ボタンをクリック
        wait_and_click(driver, "//input[@value='空き照会']")

        # 3. 施設別空き状況
        time.sleep(5)
        # 指定日の「○」または「△」のリンクを特定してクリック
        target_xpath = f"//a[contains(@href, '{date_str}') and (contains(text(), '○') or contains(text(), '△'))]"
        
        try:
            wait_and_click(driver, target_xpath)
            found_date = True
        except:
            found_date = False
        
        if not found_date:
            final_msg = f"📅 {target_date.strftime('%m/%d')}は、現在空き（○/△）が見つかりませんでした。"
        else:
            # 4. 時間帯別空き状況
            time.sleep(5)
            slots = []
            
            # 画面内の全てのテーブルをループ
            tables = WebDriverWait(driver, 20).until(
                EC.presence_of_all_elements_located((By.XPATH, "//table[contains(@id, 'dlJikantai')]"))
            )
            
            for table in tables:
                try:
                    park_name = table.find_element(By.XPATH, "./preceding::a[contains(@id, 'LnkSisetu名')][1]").text.strip()
                    time_headers = [th.text.replace("\n", "") for th in table.find_elements(By.XPATH, ".//tr[2]/th")]
                    rows = table.find_elements(By.XPATH, ".//tr[position()>2]")
                    
                    for row in rows:
                        cells = row.find_elements(By.TAG_NAME, "td")
                        if not cells: continue
                        
                        court_name = cells[0].text.strip()
                        for i, cell in enumerate(cells[1:], 1):
                            if "○" in cell.text or "△" in cell.text:
                                time_range = time_headers[i] if i < len(time_headers) else f"枠{i}"
                                slots.append(f"📍{park_name}【{court_name}】\n   └ {time_range}")
                except:
                    continue

            if slots:
                final_msg = f"🎾 {target_date.strftime('%m/%d')}の空き状況\n\n" + "\n\n".join(list(dict.fromkeys(slots)))
            else:
                final_msg = f"📅 {target_date.strftime('%m/%d')}：詳細画面に移動しましたが、枠情報の取得に失敗しました。"

    except Exception as e:
        # エラー内容をより分かりやすく
        error_msg = str(e)
        if "timeout" in error_msg.lower():
            final_msg = "⚠️ タイムアウト：画面の読み込みが間に合いませんでした。もう一度試してみてください。"
        else:
            final_msg = f"⚠️ システムエラーが発生しました。\n(詳細: {error_msg[:100]})"
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
                messages=[TextMessage(text=f"🔍 2026/05/07の空き情報を精密スキャン中です...")]
            ))
        threading.Thread(target=scrap_and_push, args=(user_id, target_date)).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
