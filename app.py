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

app = Flask(__name__)

# --- LINE設定 ---
access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
channel_secret = os.environ.get('LINE_CHANNEL_SECRET')
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent
configuration = Configuration(access_token=access_token)
handler = WebhookHandler(channel_secret)

@app.route("/", methods=['GET'])
def health_check():
    return "OK", 200

def get_driver():
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1280,1024')
    return webdriver.Chrome(options=chrome_options)

def check_machida_tennis(target_dates):
    wd_names = ["月", "火", "水", "木", "金", "土", "日"]
    all_results = []

    for target_date in target_dates:
        driver = None
        current_step = "開始前"
        try:
            driver = get_driver()
            wait = WebDriverWait(driver, 20)
            
            # Step 1: トップページ
            current_step = "1.トップページ読み込み"
            print(f"[Log] {current_step}", flush=True)
            driver.get("https://www.pf489.com/machida/dselect.html")
            
            # Step 2: 高機能検索への強制遷移（JavaScriptを使用）
            current_step = "2.高機能検索ページへ直接遷移"
            print(f"[Log] {current_step}", flush=True)
            driver.execute_script("location.href='P_A_Select_A.aspx';")
            time.sleep(5) 

            # Step 3: 施設選択
            current_step = "3.施設(テニス)選択"
            print(f"[Log] {current_step}", flush=True)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "label")))
            
            labels = driver.find_elements(By.TAG_NAME, "label")
            target_found = False
            for label in labels:
                if "テニスコート" in label.text and "コミュニティ" not in label.text:
                    checkbox = driver.find_element(By.ID, label.get_attribute("for"))
                    if not checkbox.is_selected():
                        driver.execute_script("arguments[0].click();", checkbox)
                    target_found = True
            
            if not target_found:
                raise Exception("テニスコートの選択肢が見つかりませんでした")

            # Step 4: 検索実行
            current_step = "4.空き照会ボタン押下"
            print(f"[Log] {current_step}", flush=True)
            search_btn = driver.find_element(By.XPATH, "//input[contains(@value, '空き照会')]")
            driver.execute_script("arguments[0].click();", search_btn)
            
            # Step 5: カレンダー日付選択
            current_step = "5.カレンダー日付選択"
            print(f"[Log] {current_step}", flush=True)
            time.sleep(3)
            day_num = str(target_date.day)
            day_wd = wd_names[target_date.weekday()]
            date_str = target_date.strftime("%m/%d")
            
            target_xpath = f"//td[contains(., '{day_num}') and contains(., '{day_wd}')]//a"
            day_links = driver.find_elements(By.XPATH, target_xpath)
            
            if not day_links:
                all_results.append(f"【{date_str}】空きなし(または選択不可)")
                continue
            driver.execute_script("arguments[0].click();", day_links[0])
            
            # Step 6: 次へ
            current_step = "6.次へボタン押下"
            print(f"[Log] {current_step}", flush=True)
            next_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//input[contains(@value, '次へ')]")))
            driver.execute_script("arguments[0].click();", next_btn)
            
            # Step 7: 結果抽出
            current_step = "7.詳細データ抽出"
            print(f"[Log] {current_step}", flush=True)
            time.sleep(3)
            unique_slots = []
            rows = driver.find_elements(By.TAG_NAME, "tr")
            for row in rows:
                if "○" in row.text:
                    # バックスラッシュ問題を回避するため、一度変数に代入
                    clean_text = row.text.replace('\n', ' ').strip()
                    unique_slots.append(f"■ {clean_text}")

            res = f"【{date_str}({day_wd})】\n" + ("\n".join(unique_slots) if unique_slots else "空きなし")
            all_results.append(res)
            print(f"[Log] {date_str} 完了", flush=True)

        except Exception as e:
            error_msg = f"エラー発生(Step:{current_step}): {str(e)[:100]}"
            print(f"[Error] {error_msg}", flush=True)
            all_results.append(f"【{target_date.strftime('%m/%d')}】{error_msg}")
        finally:
            if driver:
                driver.quit()

    return "\n\n".join(all_results)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Signature', request.headers.get('X-Line-Signature'))
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_msg = event.message.text
    if "今日" not in user_msg and "明日" not in user_msg:
        return
    today = datetime.now()
    target_dates = [today] if "今日" in user_msg else [today + timedelta(days=1)]
    result = check_machida_tennis(target_dates)
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=result)])
        )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
