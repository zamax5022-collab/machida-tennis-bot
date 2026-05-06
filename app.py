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
from linebot.v3.webhooks import Message_event, TextMessageContent
configuration = Configuration(access_token=access_token)
handler = WebhookHandler(channel_secret)

@app.route("/", methods=['GET'])
def health_check():
    return "Bot is active", 200

def get_driver():
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1280,1024')
    # ボット検知回避用のUser-Agent
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    return webdriver.Chrome(options=chrome_options)

def check_machida_tennis(target_dates):
    wd_names = ["月", "火", "水", "木", "金", "土", "日"]
    all_results = []

    for target_date in target_dates:
        driver = None
        current_step = "開始前"
        try:
            driver = get_driver()
            wait = WebDriverWait(driver, 30)
            
            # Step 1: トップページから入る（セッション確立に必須）
            current_step = "1.トップページ読み込み"
            print(f"[Log] {current_step}", flush=True)
            driver.get("https://www.pf489.com/machida/dselect.html")
            
            # Step 2: 「高機能検索へ」ボタンを物理的にクリック
            current_step = "2.高機能検索ボタンクリック"
            print(f"[Log] {current_step}", flush=True)
            # 画像リンク(P_A_Select_A.aspx)を探してクリック
            search_link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(@href, 'P_A_Select_A.aspx')]")))
            driver.execute_script("arguments[0].click();", search_link)
            
            # Step 3: 施設選択
            current_step = "3.施設(テニス)選択"
            print(f"[Log] {current_step}", flush=True)
            time.sleep(5) # 画面遷移待ち
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "label")))
            
            labels = driver.find_elements(By.TAG_NAME, "label")
            found_count = 0
            for label in labels:
                # 「テニスコート」を含み、「コミュニティ」を含まないものを選択
                if "テニスコート" in label.text and "コミュニティ" not in label.text:
                    label_id = label.get_attribute("for")
                    if label_id:
                        cb = driver.find_element(By.ID, label_id)
                        if not cb.is_selected():
                            driver.execute_script("arguments[0].click();", cb)
                        found_count += 1
            
            print(f"[Log] 選択施設数: {found_count}", flush=True)
            if found_count == 0:
                raise Exception("テニス施設が見つかりません。")

            # Step 4: 空き照会ボタン押下
            current_step = "4.空き照会ボタン押下"
            print(f"[Log] {current_step}", flush=True)
            search_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@value='空き照会']")))
            driver.execute_script("arguments[0].click();", search_btn)
            
            # Step 5: カレンダー日付選択
            current_step = "5.カレンダー日付選択"
            print(f"[Log] {current_step}", flush=True)
            time.sleep(5)
            day_num = str(target_date.day)
            day_wd = wd_names[target_date.weekday()]
            date_str = target_date.strftime("%m/%d")
            
            # 曜日と日付が含まれるリンクを特定
            cal_xpath = f"//a[contains(text(), '{day_num}') and contains(text(), '{day_wd}')]"
            day_links = driver.find_elements(By.XPATH, cal_xpath)
            
            if not day_links:
                all_results.append(f"【{date_str}({day_wd})】カレンダー選択不可")
                continue
            driver.execute_script("arguments[0].click();", day_links[0])
            
            # Step 6: 次へボタン押下
            current_step = "6.次へボタン押下"
            print(f"[Log] {current_step}", flush=True)
            next_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@value='次へ']")))
            driver.execute_script("arguments[0].click();", next_btn)
            
            # Step 7: 結果抽出
            current_step = "7.結果データ抽出"
            print(f"[Log] {current_step}", flush=True)
            time.sleep(4)
            slots = []
            rows = driver.find_elements(By.TAG_NAME, "tr")
            for r in rows:
                if "○" in r.text:
                    clean_text = r.text.replace("\n", " ").strip()
                    slots.append(f"■ {clean_text}")
            
            res = f"【{date_str}({day_wd})】\n" + ("\n".join(slots) if slots else "空きなし")
            all_results.append(res)

        except Exception as e:
            print(f"[Error] {current_step} で失敗: {str(e)[:100]}", flush=True)
            all_results.append(f"【{target_date.strftime('%m/%d')}】エラー: {current_step}")
        finally:
            if driver:
                driver.quit()

    return "\n\n".join(all_results)

# --- LINE Callback & Handler ---
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
    if "今日" in msg or "明日" in msg:
        today = datetime.now()
        target_dates = [today] if "今日" in msg else [today + timedelta(days=1)]
        result = check_machida_tennis(target_dates)
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=result)]))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
