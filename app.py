import os
import time
import traceback
from datetime import datetime, timedelta
from flask import Flask, request, abort
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
)
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
    chrome_options.add_argument('--memory-pressure-off') # メモリ対策
    chrome_options.add_argument('--window-size=1280,1024')
    return webdriver.Chrome(options=chrome_options)

def check_machida_tennis(target_dates):
    wd_names = ["月", "火", "水", "木", "金", "土", "日"]
    all_results = []

    for target_date in target_dates:
        driver = get_driver()
        wait = WebDriverWait(driver, 20)
        
        day_num = str(target_date.day)
        day_wd = wd_names[target_date.weekday()]
        date_str = target_date.strftime("%m/%d")
        unique_slots = set()
        current_hour = datetime.now().hour if target_date.date() == datetime.now().date() else -1

        try:
            print(f"--- 検索開始: {date_str} ---")
            # 直接、高機能検索のページを開いて時短
            driver.get("https://www.pf489.com/machida/P_A_Select_A.aspx")
            
            print("Step 1: ページを開きました")
            # フレーム切り替え
            wait.until(EC.frame_to_be_available_and_switch_to_it((By.NAME, "MainFrame")))
            print("Step 2: フレーム切り替え完了")

            # 施設選択
            labels = wait.until(EC.presence_of_all_elements_located((By.TAG_NAME, "label")))
            for label in labels:
                if "テニスコート" in label.text and "コミュニティ" not in label.text:
                    checkbox = driver.find_element(By.ID, label.get_attribute("for"))
                    if not checkbox.is_selected():
                        driver.execute_script("arguments[0].click();", checkbox)
            print("Step 3: 施設選択完了")

            # 検索実行
            search_btn = driver.find_element(By.XPATH, "//input[contains(@value, '空き照会')]")
            driver.execute_script("arguments[0].click();", search_btn)
            
            # カレンダー
            print("Step 4: カレンダー解析中...")
            time.sleep(3)
            target_xpath = f"//td[contains(., '{day_num}') and contains(., '{day_wd}')]//a[contains(., '○') or contains(., '△')]"
            day_links = driver.find_elements(By.XPATH, target_xpath)
            
            if not day_links:
                all_results.append(f"【{date_str}({day_wd})】\n空きなし")
                continue

            driver.execute_script("arguments[0].click();", day_links[0])
            
            # 詳細へ
            next_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//input[contains(@value, '次へ')]")))
            driver.execute_script("arguments[0].click();", next_btn)
            
            # 結果取得
            print("Step 5: 詳細取得中...")
            time.sleep(3)
            rows = driver.find_elements(By.TAG_NAME, "tr")
            for row in rows:
                if "○" in row.text:
                    text = row.text.replace("\n", " ").strip()
                    try:
                        time_part = text.split("～")[0][-2:].strip().replace(":", "")
                        if int(time_part) > current_hour:
                            unique_slots.add(f"■ {text}")
                    except:
                        unique_slots.add(f"■ {text}")

            res_text = f"【{date_str}({day_wd})】\n" + ("\n".join(sorted(list(unique_slots))) if unique_slots else "空きなし")
            all_results.append(res_text)
            print(f"--- 成功: {date_str} ---")
            
        except Exception:
            print(f"--- エラー発生 ---")
            print(traceback.format_exc())
            all_results.append(f"【{date_str}】検索エラー: 再試行してください")
        finally:
            driver.quit()

    return "\n\n".join(all_results)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_msg = event.message.text
    today = datetime.now()
    target_dates = []
    wd_map = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}

    if "今日" in user_msg:
        target_dates.append(today)
    elif "明日" in user_msg:
        target_dates.append(today + timedelta(days=1))
    elif "週末" in user_msg:
        diff_sat = (5 - today.weekday() + 7) % 7
        days_to_sat = diff_sat if diff_sat > 0 else 7
        sat = today + timedelta(days=days_to_sat)
        target_dates.extend([sat, sat + timedelta(days=1)])
    else:
        for key, val in wd_map.items():
            if key in user_msg:
                diff = (val - today.weekday() + 7) % 7
                days_to_add = diff if diff > 0 else 7
                target_dates.append(today + timedelta(days=days_to_add))
                break

    if not target_dates: return

    result = check_machida_tennis(target_dates)
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=result)])
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
