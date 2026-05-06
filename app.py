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

# 環境変数（RenderのDashboardで設定してください）
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
            print(f"[Log] 検索プロセス開始: {target_date.strftime('%m/%d')}", flush=True)
            driver = get_driver()
            wait = WebDriverWait(driver, 20)
            
            # Step 1: トップページ
            current_step = "1.トップページ読み込み"
            driver.get("https://www.pf489.com/machida/dselect.html")
            
            # Step 2: 高機能検索ボタン押下（物理クリック再現）
            current_step = "2.高機能検索ボタン特定"
            search_links = wait.until(EC.presence_of_all_elements_located((By.XPATH, "//a[contains(., '高機能検索') or .//img[contains(@alt, '高機能検索')]]")))
            driver.execute_script("arguments[0].click();", search_links[0])
            
            # Step 3: 施設選択
            current_step = "3.施設(テニスコート)選択"
            success_selection = False
            for i in range(10):
                time.sleep(3)
                labels = driver.find_elements(By.TAG_NAME, "label")
                if len(labels) > 0:
                    for label in labels:
                        if "テニスコート" in label.text and "コミュニティ" not in label.text:
                            label_id = label.get_attribute("for")
                            if label_id:
                                cb = driver.find_element(By.ID, label_id)
                                if not cb.is_selected():
                                    driver.execute_script("arguments[0].click();", cb)
                                    success_selection = True
                    if success_selection: break
                print(f"[Log] Step 3 リトライ中...({i+1}/10)", flush=True)

            if not success_selection:
                raise Exception(f"施設リストが見つかりません(URL:{driver.current_url})")

            # Step 4: 空き照会ボタン
            current_step = "4.空き照会ボタン押下"
            search_btn = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@value='空き照会']")))
            driver.execute_script("arguments[0].click();", search_btn)
            
            # Step 5: カレンダー日付選択
            current_step = "5.カレンダー日付選択"
            time.sleep(5)
            day_num = str(target_date.day)
            day_wd = wd_names[target_date.weekday()]
            cal_xpath = f"//a[contains(., '{day_num}') and contains(., '{day_wd}')]"
            day_link = wait.until(EC.element_to_be_clickable((By.XPATH, cal_xpath)))
            driver.execute_script("arguments[0].click();", day_link)
            
            # Step 6: 次へ
            current_step = "6.次へボタン押下"
            next_btn = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@value='次へ']")))
            driver.execute_script("arguments[0].click();", next_btn)
            
            # Step 7: 結果抽出
            current_step = "7.結果抽出"
            time.sleep(5)
            slots = []
            rows = driver.find_elements(By.TAG_NAME, "tr")
            for r in rows:
                if "○" in r.text:
                    slots.append(f"■ {r.text.replace('\n', ' ').strip()}")
            
            res = f"【{target_date.strftime('%m/%d')}】\n" + ("\n".join(slots) if slots else "空きなし")
            all_results.append(res)

        except Exception as e:
            error_msg = f"[Error] {current_step}: {str(e)}"
            print(error_msg, flush=True)
            all_results.append(f"【{target_date.strftime('%m/%d')}】でエラーが発生しました。\nステップ: {current_step}")
        finally:
            if driver: driver.quit()

    return "\n\n".join(all_results)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    print(f"[System] Webhook受信: {body[:100]}...", flush=True)
    try:
        handler.handle(body, signature)
    except Exception as e:
        print(f"[Critical] Webhook Handle Error: {str(e)}", flush=True)
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    msg = event.message.text
    print(f"[Log] ユーザーメッセージ受信: {msg}", flush=True)
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        
        try:
            if "今日" in msg or "明日" in msg:
                # 検索の実行
                today = datetime.now()
                target_dates = [today] if "今日" in msg else [today + timedelta(days=1)]
                
                # 検索中のログ
                print(f"[Log] 検索を開始します対象: {msg}", flush=True)
                
                result = check_machida_tennis(target_dates)
                line_bot_api.reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=result)]
                ))
            else:
                line_bot_api.reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="「今日」または「明日」と送ってください。")]
                ))
        except Exception as e:
            # 内部で発生したすべてのエラーをLINEに送信
            error_detail = traceback.format_exc()
            print(f"[Critical] Handle Message Error:\n{error_detail}", flush=True)
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=f"申し訳ありません、Bot内部でエラーが発生しました。\n\n{str(e)}")]
            ))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
