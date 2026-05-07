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
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1280,1024')
    return webdriver.Chrome(options=chrome_options)

def safe_switch_to_frame(driver):
    """フレームへの切り替えを安全に行う"""
    driver.switch_to.default_content()
    try:
        # メインフレームが現れるのを最大20秒待機
        WebDriverWait(driver, 20).until(EC.frame_to_be_available_and_switch_to_it((By.NAME, "MainFrame")))
        return True
    except:
        return False

def scrap_and_push(user_id, target_date):
    driver = None
    step = "準備中"
    date_str = target_date.strftime('%Y%m%d')
    try:
        driver = get_driver()
        wait = WebDriverWait(driver, 25)
        
        # 1. サイトアクセス
        step = "1.入口画面の読み込み"
        driver.get("https://www.pf489.com/machida/dselect.html")
        time.sleep(3)
        
        if not safe_switch_to_frame(driver):
            raise Exception("メインメニューの読み込みに失敗しました")

        # 高機能検索ボタンをクリック
        btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(., '高機能検索')]")))
        driver.execute_script("arguments[0].click();", btn)
        
        # 2. 条件設定
        step = "2.条件設定画面の遷移待ち"
        time.sleep(7) # 画面遷移のバッファ
        
        # 条件設定画面のフレームに再突入
        if not safe_switch_to_frame(driver):
             raise Exception("条件設定画面への切り替えに失敗しました")

        step = "2.テニスコート選択"
        # チェックボックスが読み込まれるまで待機
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "label")))
        
        labels = driver.find_elements(By.TAG_NAME, "label")
        found = False
        for label in labels:
            if "テニスコート" in label.text and "コミュニティ" not in label.text:
                cb_id = label.get_attribute("for")
                cb = driver.find_element(By.ID, cb_id)
                if not cb.is_selected():
                    driver.execute_script("arguments[0].click();", cb)
                found = True
        
        if not found:
            raise Exception("テニスコート選択肢が見つかりませんでした")

        # 空き照会ボタンクリック
        submit_btn = driver.find_element(By.XPATH, "//input[@value='空き照会']")
        driver.execute_script("arguments[0].click();", submit_btn)

        # 3. カレンダー画面
        step = f"3.カレンダー({date_str})のスキャン"
        time.sleep(7)
        safe_switch_to_frame(driver)
        
        target_xpath = f"//a[contains(@href, '{date_str}') and (contains(text(), '○') or contains(text(), '△'))]"
        try:
            link = wait.until(EC.element_to_be_clickable((By.XPATH, target_xpath)))
            driver.execute_script("arguments[0].click();", link)
        except:
            push_line(user_id, f"📅 {target_date.strftime('%m/%d')}は現在、空きがありません。")
            return

        # 4. 詳細結果
        step = "4.施設別詳細の取得"
        time.sleep(7)
        safe_switch_to_frame(driver)
        
        results = []
        tables = driver.find_elements(By.XPATH, "//table[contains(@id, 'dlJikantai')]")
        for table in tables:
            try:
                park = table.find_element(By.XPATH, "./preceding::a[contains(@id, 'LnkSisetu名')][1]").text.strip()
                rows = table.find_elements(By.XPATH, ".//tr[position()>2]")
                for row in rows:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if cells and ("○" in row.text or "△" in row.text):
                        court = cells[0].text.strip()
                        results.append(f"📍{park}\n  └ {court}")
            except:
                continue

        if results:
            msg = f"🎾 {target_date.strftime('%m/%d')} 空き速報！\n\n" + "\n".join(list(dict.fromkeys(results))[:15])
        else:
            msg = f"📅 {target_date.strftime('%m/%d')} 詳細は埋まっていました。"
        
        push_line(user_id, msg)

    except Exception as e:
        push_line(user_id, f"⚠️ システム中断\nステップ: {step}\n内容: 町田市のサーバー応答待ちでタイムアウトしました。少し時間を置いて再試行してください。")
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
    if any(k in text for k in ["今日", "明日", "土曜", "日曜"]):
        # 日付判定（簡易版）
        days = 0
        if "明日" in text: days = 1
        elif "土曜" in text: days = (5 - datetime.now().weekday()) % 7
        target_date = datetime.now() + timedelta(days=days)
        
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=f"🔍 {target_date.strftime('%m/%d')} を精密スキャンします。1分ほどお待ちください...")]
            ))
        threading.Thread(target=scrap_and_push, args=(user_id, target_date)).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
