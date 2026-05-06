import os
import time
from datetime import datetime, timedelta
from flask import Flask, request, abort

# LINE SDK v3 の最新インポート
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage as MessagingTextMessage
)
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

app = Flask(__name__)

# 環境変数の取得
access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
channel_secret = os.environ.get('LINE_CHANNEL_SECRET')

configuration = Configuration(access_token=access_token)
handler = WebhookHandler(channel_secret)

def check_machida_tennis(target_date):
    print(f"--- 探索開始: {target_date.strftime('%Y/%m/%d')} ---")
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--blink-settings=imagesEnabled=false') # メモリ節約
    
    chrome_bin = "/opt/render/project/.render/chrome/opt/google/chrome/google-chrome"
    if os.path.exists(chrome_bin):
        options.binary_location = chrome_bin

    driver = None
    try:
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(30)
        
        # 町田市予約システムトップ
        driver.get("https://www.pf489.com/machida/dselect.html")
        time.sleep(2)
        driver.find_element(By.LINK_TEXT, "高機能検索").click()
        time.sleep(2)
        
        # フレーム切り替え
        frames = driver.find_elements(By.XPATH, "//iframe | //frame")
        for f in frames:
            try:
                driver.switch_to.frame(f)
                if "テニスコート" in driver.page_source: break
            except: driver.switch_to.default_content()

        # 全施設を選択（コミュニティセンター以外）
        inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        for ipt in inputs:
            try:
                parent_text = driver.execute_script("return arguments[0].parentNode.parentNode.innerText;", ipt)
                if "コミュニティセンター" in parent_text: continue
                if ("テニスコート" in parent_text or "クリーンセンター" in parent_text) and not ipt.is_selected():
                    driver.execute_script("arguments[0].click();", ipt)
            except: continue

        search_btn = driver.find_element(By.XPATH, "//input[contains(@value, '空き照会')]")
        driver.execute_script("arguments[0].click();", search_btn)
        time.sleep(5)

        # カレンダー解析
        day_num = str(target_date.day)
        wd_list = ["月", "火", "水", "木", "金", "土", "日"]
        day_wd = wd_list[target_date.weekday()]
        
        header_xpath = f"//td[contains(., '{day_num}') and contains(., '{day_wd}')]"
        headers = driver.find_elements(By.XPATH, header_xpath)
        
        clicked = False
        for header in headers:
            if len(header.text.strip()) > 10: continue
            col_idx = len(header.find_elements(By.XPATH, "./preceding-sibling::td"))
            table = header.find_element(By.XPATH, "./ancestor::table[1]")
            for row in table.find_elements(By.TAG_NAME, "tr"):
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) > col_idx:
                    links = cells[col_idx].find_elements(By.TAG_NAME, "a")
                    if links and links[0].text.strip() in ["○", "△"]:
                        driver.execute_script("arguments[0].click();", links[0])
                        clicked = True
                        break
            if clicked: break
        
        if not clicked: return f"{target_date.strftime('%m/%d')} の空きはありません。"

        time.sleep(4)
        
        # 詳細解析
        unique_slots = []
        rows = driver.find_elements(By.TAG_NAME, "tr")
        current_facility = "不明"
        time_headers = []

        for row in rows:
            text = row.text.strip()
            if not text: continue
            
            if any(x in text for x in ["テニスコート", "グラウンド", "クリーンセンター"]) and "202" not in text:
                current_facility = text.split()[0].replace("\n", "")
                continue

            if "～" in text and ("09" in text or "08" in text):
                time_headers = [t for t in text.split() if "～" in t]
                continue

            if "○" in text:
                cells = row.find_elements(By.TAG_NAME, "td")
                if not cells: continue
                court_name = cells[0].text.replace("\n", "").strip()
                
                for idx, cell in enumerate(cells):
                    if "○" in cell.text:
                        time_idx = idx - (len(cells) - len(time_headers))
                        if 0 <= time_idx < len(time_headers):
                            slot_info = f"■ {current_facility} {court_name}\n   {time_headers[time_idx]}"
                            if slot_info not in unique_slots:
                                unique_slots.append(slot_info)

        if not unique_slots:
            return f"{target_date.strftime('%m/%d')}：空き表示がありましたが詳細を取得できませんでした。"
        
        return f"【{target_date.strftime('%m/%d')} 空き状況】\n\n" + "\n\n".join(unique_slots)

    except Exception as e:
        print(f"Error: {str(e)}")
        return f"エラーが発生しました: {str(e)}"
    finally:
        if driver: driver.quit()

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    except Exception as e:
        print(f"Callback Error: {e}")
        return 'OK'
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    text = event.message.text
    if "今日" in text:
        target_date = datetime.now()
    elif "明日" in text:
        target_date = datetime.now() + timedelta(days=1)
    else:
        return

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        
        # 1通目：レスポンス
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[MessagingTextMessage(text=f"{target_date.strftime('%m/%d')}の空き状況を精査中です。1分ほどお待ちください。")]
            )
        )
        
        # スクレイピング
        result = check_machida_tennis(target_date)
        
        # 2通目：プッシュ送信
        line_bot_api.push_message(
            PushMessageRequest(
                to=event.source.user_id,
                messages=[MessagingTextMessage(text=result)]
            )
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
