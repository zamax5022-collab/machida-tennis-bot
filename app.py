import os
import time
from datetime import datetime, timedelta
from flask import Flask, request, abort
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

# LINE SDK v3
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest,
    PushMessageRequest, TextMessage as MessagingTextMessage
)
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent

app = Flask(__name__)

# 環境変数
access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
channel_secret = os.environ.get('LINE_CHANNEL_SECRET')
configuration = Configuration(access_token=access_token)
handler = WebhookHandler(channel_secret)

def check_machida_tennis(target_date):
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    
    # Render環境のパス設定
    chrome_bin = "/opt/render/project/.render/chrome/opt/google/chrome/google-chrome"
    driver_path = "/opt/render/project/.render/chrome/opt/google/chrome/chromedriver"
    
    if os.path.exists(chrome_bin):
        chrome_options.binary_location = chrome_bin

    try:
        if os.path.exists(driver_path):
            service = Service(executable_path=driver_path)
            driver = webdriver.Chrome(service=service, options=chrome_options)
        else:
            driver = webdriver.Chrome(options=chrome_options)
    except Exception as e:
        return f"ブラウザの起動に失敗しました: {str(e)}"

    day_num = str(target_date.day)
    wd_list = ["月", "火", "水", "木", "金", "土", "日"]
    day_wd = wd_list[target_date.weekday()]
    date_str = target_date.strftime("%Y/%m/%d")
    current_hour = datetime.now().hour
    unique_slots = set()

    try:
        driver.get("https://www.pf489.com/machida/dselect.html")
        time.sleep(2)
        driver.find_element(By.LINK_TEXT, "高機能検索").click()
        time.sleep(3)
        
        # フレーム切替
        frames = driver.find_elements(By.XPATH, "//iframe | //frame")
        for f in frames:
            try:
                driver.switch_to.frame(f)
                if "テニスコート" in driver.page_source: break
            except: driver.switch_to.default_content()

        # 施設選択（テニスコート全般）
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
        time.sleep(4)

        # 1. 「施設別空き状況」画面で対象日の有効なリンクの数を把握する
        header_xpath = f"//td[contains(., '{day_num}') and contains(., '{day_wd}')]"
        
        def get_all_valid_links():
            found_links = []
            day_headers = driver.find_elements(By.XPATH, header_xpath)
            for header in day_headers:
                if len(header.text.strip()) > 10: continue
                col_idx = len(header.find_elements(By.XPATH, "./preceding-sibling::td"))
                table = header.find_element(By.XPATH, "./ancestor::table[1]")
                for row in table.find_elements(By.TAG_NAME, "tr"):
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if len(cells) > col_idx:
                        links = cells[col_idx].find_elements(By.TAG_NAME, "a")
                        if links and links[0].text.strip() in ["○", "△"]:
                            found_links.append(links[0])
            return found_links

        # リンクの総数を取得
        total_links = len(get_all_valid_links())
        
        # 2. 各リンクを順番にクリックして詳細画面を解析
        for i in range(total_links):
            links = get_all_valid_links()
            if i >= len(links): break
            
            driver.execute_script("arguments[0].click();", links[i])
            time.sleep(3)

            # 詳細画面（時間帯別空き状況）での「次へ」対応
            next_btns = driver.find_elements(By.XPATH, "//input[contains(@value, '次へ')] | //a[contains(., '次へ')]")
            if next_btns:
                driver.execute_script("arguments[0].click();", next_btns[-1])
                time.sleep(3)

            # 詳細画面の解析
            rows = driver.find_elements(By.TAG_NAME, "tr")
            current_facility = "不明"
            for row in rows:
                text = row.text.strip()
                if any(x in text for x in ["テニスコート", "グラウンド", "クリーンセンター"]) and "202" not in text:
                    current_facility = text.split(" ")[0].split("\n")[0]
                    continue
                
                if "○" in text:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    try:
                        header_row = row.find_element(By.XPATH, "./preceding::tr[contains(., '～')][1]")
                        time_slots = [s for s in header_row.text.split() if "～" in s]
                        court_name = cells[0].text.strip().replace("\n", "")
                        for j, cell in enumerate(cells):
                            if "○" in cell.text:
                                time_idx = j - (len(cells) - len(time_slots))
                                if 0 <= time_idx < len(time_slots):
                                    slot_time = time_slots[time_idx]
                                    start_hour = int(slot_time.split(":")[0])
                                    if target_date.date() == datetime.now().date() and start_hour <= current_hour:
                                        continue
                                    unique_slots.add(f"■ {current_facility}/{court_name}：{slot_time}")
                    except: continue
            
            # 元の画面に戻る
            driver.back()
            time.sleep(3)

        if not unique_slots:
            return f"{date_str} の予約可能な空き枠はありませんでした。"
        
        return f"【{date_str} の空き状況】\n\n" + "\n".join(sorted(list(unique_slots)))

    except Exception as e:
        return f"解析エラーが発生しました: {str(e)}"
    finally:
        driver.quit()

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    text = event.message.text
    target_date = None
    if "今日" in text: target_date = datetime.now()
    elif "明日" in text: target_date = datetime.now() + timedelta(days=1)
    
    if target_date:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            # 最初の応答
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[MessagingTextMessage(text=f"{target_date.strftime('%m/%d')}を調べています。全施設確認するため20〜30秒ほどお待ちください。")]
            ))
            # 重い処理
            result = check_machida_tennis(target_date)
            # プッシュメッセージで結果を送信
            line_bot_api.push_message(PushMessageRequest(
                to=event.source.user_id,
                messages=[MessagingTextMessage(text=result)]
            ))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
