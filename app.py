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
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent

app = Flask(__name__)

# 環境変数
access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
channel_secret = os.environ.get('LINE_CHANNEL_SECRET')
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
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    return webdriver.Chrome(options=chrome_options)

def check_machida_tennis(target_dates):
    wd_names = ["月", "火", "水", "木", "金", "土", "日"]
    all_results = []

    for target_date in target_dates:
        driver = None
        current_step = "初期化"
        try:
            print(f"[Log] 検索開始: {target_date.strftime('%m/%d')}", flush=True)
            driver = get_driver()
            wait = WebDriverWait(driver, 30)
            
            # Step 1-3: 施設選択まで
            driver.get("https://www.pf489.com/machida/dselect.html")
            search_links = wait.until(EC.presence_of_all_elements_located((By.XPATH, "//a[contains(., '高機能検索') or .//img[contains(@alt, '高機能検索')]]")))
            driver.execute_script("arguments[0].click();", search_links[0])
            
            time.sleep(5)
            labels = wait.until(EC.presence_of_all_elements_located((By.TAG_NAME, "label")))
            for label in labels:
                if "テニスコート" in label.text and "コミュニティ" not in label.text:
                    label_id = label.get_attribute("for")
                    if label_id:
                        cb = driver.find_element(By.ID, label_id)
                        if not cb.is_selected():
                            driver.execute_script("arguments[0].click();", cb)
            
            # Step 4: 空き照会ボタン
            current_step = "4.空き照会ボタン押下"
            time.sleep(5)
            btn_clicked = False
            btns = driver.find_elements(By.TAG_NAME, "input")
            for b in btns:
                val = b.get_attribute("value")
                if val and "空き照会" in val:
                    driver.execute_script("arguments[0].click();", b)
                    btn_clicked = True
                    break
            
            # Step 5: 日付選択
            current_step = "5.カレンダー日付選択"
            time.sleep(10) # 画面遷移をじっくり待つ
            
            day_num = str(target_date.day)
            target_link = None
            links = driver.find_elements(By.TAG_NAME, "a")
            for l in links:
                txt = l.text.strip()
                # 日付リンク（例: "7" や "7(木)"）を特定
                if txt.startswith(day_num) and (len(txt) == len(day_num) or not txt[len(day_num)].isdigit()):
                    target_link = l
                    break
            
            if target_link:
                driver.execute_script("arguments[0].click();", target_link)
            else:
                # すでに次画面（時間帯選択）に飛んでいるか確認
                if "利用目的" not in driver.page_source:
                    raise Exception(f"{day_num}日のリンクがありません")
            
            # Step 6: 次へ（または表示）
            current_step = "6.次へ/表示ボタン押下"
            time.sleep(7) # 日付クリック後の更新を待つ
            next_found = False
            all_inputs = driver.find_elements(By.TAG_NAME, "input")
            for inp in all_inputs:
                v = inp.get_attribute("value")
                if v in ["次へ", "表示", "空き状況を表示"]:
                    driver.execute_script("arguments[0].click();", inp)
                    next_found = True
                    break
            
            # Step 7: 結果抽出
            current_step = "7.結果抽出"
            time.sleep(7)
            slots = []
            rows = driver.find_elements(By.TAG_NAME, "tr")
            for r in rows:
                txt = r.text.replace("\n", " ").strip()
                if "○" in txt:
                    slots.append(f"■ {txt}")
            
            day_wd = wd_names[target_date.weekday()]
            res = f"【{target_date.strftime('%m/%d')}({day_wd})】\n" + ("\n".join(slots) if slots else "空きなし")
            all_results.append(res)

        except Exception as e:
            # エラーの詳細をLINEに返す形式に変更
            err_detail = str(e).split('\n')[0] # 1行目のみ抽出
            all_results.append(f"【{target_date.strftime('%m/%d')}】エラー：{current_step}\n内容：{err_detail}")
            print(traceback.format_exc(), flush=True)
        finally:
            if driver: driver.quit()

    return "\n\n".join(all_results)

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
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        try:
            if "今日" in msg or "明日" in msg:
                today = datetime.now()
                target_dates = [today] if "今日" in msg else [today + timedelta(days=1)]
                result = check_machida_tennis(target_dates)
                line_bot_api.reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=result)]
                ))
            else:
                line_bot_api.reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="「今日」または「明日」と入力してください。")]
                ))
        except Exception:
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="重大なシステムエラーが発生しました。")]
            ))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
