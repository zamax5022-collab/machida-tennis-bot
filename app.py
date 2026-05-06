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

# 環境変数（Renderで設定したもの）
access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
channel_secret = os.environ.get('LINE_CHANNEL_SECRET')

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent

configuration = Configuration(access_token=access_token)
handler = WebhookHandler(channel_secret)

def get_driver():
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--window-size=1280,1024')
    return webdriver.Chrome(options=chrome_options)

def check_machida_tennis(target_dates):
    all_results = []
    wd_names = ["月", "火", "水", "木", "金", "土", "日"]

    for target_date in target_dates:
        driver = None
        current_step = "初期化"
        try:
            driver = get_driver()
            wait = WebDriverWait(driver, 20)
            
            # Step 1-4: 施設選択・空き照会ボタン（ここは成功実績あり）
            driver.get("https://www.pf489.com/machida/dselect.html")
            search_links = wait.until(EC.presence_of_all_elements_located((By.XPATH, "//a[contains(., '高機能検索')]")))
            driver.execute_script("arguments[0].click();", search_links[0])
            
            time.sleep(3)
            labels = driver.find_elements(By.TAG_NAME, "label")
            for label in labels:
                if "テニスコート" in label.text and "コミュニティ" not in label.text:
                    label_id = label.get_attribute("for")
                    if label_id:
                        cb = driver.find_element(By.ID, label_id)
                        if not cb.is_selected(): driver.execute_script("arguments[0].click();", cb)
            
            time.sleep(3)
            btns = driver.find_elements(By.TAG_NAME, "input")
            for b in btns:
                if "空き照会" in (b.get_attribute("value") or ""):
                    driver.execute_script("arguments[0].click();", b)
                    break

            # Step 5: 日付選択（画像に基づき修正）
            current_step = "5.カレンダー日付選択"
            time.sleep(8)
            
            day_num = str(target_date.day)
            # 画像の構造：日付の数字(7)の下にある「×」や「△」のリンクを探す
            # aタグの中で、onclick属性にその日付(20260507等)が含まれるものを探す
            date_str = target_date.strftime('%Y%m%d')
            target_link = None
            
            links = driver.find_elements(By.TAG_NAME, "a")
            for l in links:
                href = l.get_attribute("href") or ""
                onclick = l.get_attribute("onclick") or ""
                if date_str in href or date_str in onclick:
                    target_link = l
                    break
            
            if target_link:
                driver.execute_script("arguments[0].click();", target_link)
            else:
                raise Exception(f"{day_num}日のリンク（記号部分）が見つかりません")
            
            # Step 6: 次へ
            current_step = "6.次画面へ遷移"
            time.sleep(5)
            # ページ内に「次へ」や「表示」ボタンがあれば押す
            next_btns = driver.find_elements(By.XPATH, "//input[@value='次へ' or @value='表示' or @value='空き状況を表示']")
            if next_btns:
                driver.execute_script("arguments[0].click();", next_btns[0])
            
            # Step 7: 結果抽出
            current_step = "7.結果抽出"
            time.sleep(5)
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
            all_results.append(f"【{target_date.strftime('%m/%d')}】エラー：{current_step}\n内容：{str(e)[:50]}")
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
        if "今日" in msg or "明日" in msg:
            target_dates = [datetime.now()] if "今日" in msg else [datetime.now() + timedelta(days=1)]
            result = check_machida_tennis(target_dates)
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=result)]))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
