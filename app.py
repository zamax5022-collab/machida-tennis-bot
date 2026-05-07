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
    # メモリ節約設定
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_argument('--proxy-server="direct://"')
    chrome_options.add_argument('--proxy-bypass-list=*')
    chrome_options.add_argument('--start-maximized')
    return webdriver.Chrome(options=chrome_options)

def enter_frame(driver):
    driver.switch_to.default_content()
    try:
        WebDriverWait(driver, 15).until(EC.frame_to_be_available_and_switch_to_it((By.NAME, "MainFrame")))
    except:
        pass

def scrap_and_push(user_id, target_date):
    driver = None
    step = "準備中"
    date_str = target_date.strftime('%Y%m%d')
    try:
        driver = get_driver()
        wait = WebDriverWait(driver, 20)
        
        # 1. 画面選択
        step = "1.入口画面"
        driver.get("https://www.pf489.com/machida/dselect.html")
        enter_frame(driver)
        btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(., '高機能検索')]")))
        driver.execute_script("arguments[0].click();", btn)
        
        # 2. 条件設定
        step = "2.条件設定画面"
        time.sleep(5)
        enter_frame(driver)
        labels = wait.until(EC.presence_of_all_elements_located((By.TAG_NAME, "label")))
        for label in labels:
            if "テニスコート" in label.text and "コミュニティ" not in label.text:
                cb = driver.find_element(By.ID, label.get_attribute("for"))
                if not cb.is_selected():
                    driver.execute_script("arguments[0].click();", cb)
        
        submit_btn = driver.find_element(By.XPATH, "//input[@value='空き照会']")
        driver.execute_script("arguments[0].click();", submit_btn)

        # 3. カレンダー画面
        step = f"3.日付選択({date_str})"
        time.sleep(5)
        enter_frame(driver)
        target_xpath = f"//a[contains(@href, '{date_str}') and (contains(text(), '○') or contains(text(), '△'))]"
        
        try:
            link = wait.until(EC.element_to_be_clickable((By.XPATH, target_xpath)))
            driver.execute_script("arguments[0].click();", link)
        except:
            push_line(user_id, f"📅 {target_date.strftime('%m/%d')}は現在「○/△」がありません。")
            return

        # 4. 時間帯別空き状況
        step = "4.詳細解析"
        time.sleep(5)
        enter_frame(driver)
        slots = []
        tables = driver.find_elements(By.XPATH, "//table[contains(@id, 'dlJikantai')]")
        for table in tables:
            park_name = table.find_element(By.XPATH, "./preceding::a[contains(@id, 'LnkSisetu名')][1]").text.strip()
            rows = table.find_elements(By.XPATH, ".//tr[position()>2]")
            for row in rows:
                cells = row.find_elements(By.TAG_NAME, "td")
                if not cells: continue
                court = cells[0].text.strip()
                for i, cell in enumerate(cells[1:], 1):
                    if "○" in cell.text or "△" in cell.text:
                        slots.append(f"📍{park_name} {court}")

        if slots:
            msg = f"🎾 {target_date.strftime('%m/%d')} 空きあり！\n" + "\n".join(list(dict.fromkeys(slots))[:10])
        else:
            msg = f"📅 {target_date.strftime('%m/%d')} 詳細に空きなし"
        push_line(user_id, msg)

    except Exception as e:
        push_line(user_id, f"⚠️ 中断(Step:{step})\nブラウザの負荷が高すぎました。もう一度試してください。")
    finally:
        if driver:
            driver.quit()

def push_line(user_id, text):
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).push_message(PushMessageRequest(to=user_id, messages=[TextMessage(text=text)]))

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
    text = event.message.text
    user_id = event.source.user_id
    if "今日" in text or "明日" in text or "05/07" in text:
        target_date = datetime.now() + timedelta(days=1) # 明日固定（テスト用）
        # まず即座に応答を返す（これでLINEのタイムアウトを防ぐ）
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="🎾 町田市システムを軽量モードでスキャンします...")]
            ))
        # 裏側でスキャン開始
        threading.Thread(target=scrap_and_push, args=(user_id, target_date)).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
