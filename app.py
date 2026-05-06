import os
import time
from datetime import datetime, timedelta
from flask import Flask, request, abort
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.alert import Alert
from selenium.common.exceptions import NoAlertPresentException

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

app = Flask(__name__)

# --- LINE設定 (RenderのEnvironment Variablesで設定してください) ---
access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
channel_secret = os.environ.get('LINE_CHANNEL_SECRET')

configuration = Configuration(access_token=access_token)
handler = WebhookHandler(channel_secret)

def get_driver():
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    # Render環境で起動するためのパス指定
    chrome_options.binary_location = "/usr/bin/google-chrome"
    return webdriver.Chrome(options=chrome_options)

def check_machida_tennis(target_dates):
    wd_names = ["月", "火", "水", "木", "金", "土", "日"]
    all_results = []

    for target_date in target_dates:
        driver = get_driver()
        day_num = str(target_date.day)
        day_wd = wd_names[target_date.weekday()]
        date_str = target_date.strftime("%m/%d")
        unique_slots = set()
        current_hour = datetime.now().hour if target_date.date() == datetime.now().date() else -1

        try:
            driver.get("https://www.pf489.com/machida/dselect.html")
            time.sleep(2)
            driver.find_element(By.LINK_TEXT, "高機能検索").click()
            time.sleep(3)
            
            frames = driver.find_elements(By.XPATH, "//iframe | //frame")
            for f in frames:
                try:
                    driver.switch_to.frame(f)
                    if "テニスコート" in driver.page_source: break
                except: driver.switch_to.default_content()

            # 施設選択
            inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
            for ipt in inputs:
                try:
                    parent_text = driver.execute_script("return arguments[0].parentNode.parentNode.innerText;", ipt)
                    if "コミュニティセンター" in parent_text: continue
                    if ("テニスコート" in parent_text or "クリーンセンター" in parent_text) and not ipt.is_selected():
                        driver.execute_script("arguments[0].click();", ipt)
                except: continue

            driver.execute_script("arguments[0].click();", driver.find_element(By.XPATH, "//input[contains(@value, '空き照会')]"))
            time.sleep(4)

            # カレンダー画面：○△をクリックして選択 (tennis_check_01準拠)[cite: 1]
            header_xpath = f"//td[contains(., '{day_num}') and contains(., '{day_wd}')]"
            headers = driver.find_elements(By.XPATH, header_xpath)

            clicked_count = 0
            for header in headers:
                if len(header.text.strip()) > 10: continue 
                try:
                    col_idx = len(header.find_elements(By.XPATH, "./preceding-sibling::td"))
                    table = header.find_element(By.XPATH, "./ancestor::table[1]")
                    for row in table.find_elements(By.TAG_NAME, "tr"):
                        cells = row.find_elements(By.TAG_NAME, "td")
                        if len(cells) > col_idx:
                            target = cells[col_idx]
                            links = target.find_elements(By.TAG_NAME, "a")
                            if links and any(sym in links[0].text for sym in ["○", "△"]):
                                driver.execute_script("arguments[0].click();", links[0])
                                clicked_count += 1
                except: continue

            if clicked_count > 0:
                next_btns = driver.find_elements(By.XPATH, "//input[contains(@value, '次へ')] | //a[contains(., '次へ')]")
                driver.execute_script("arguments[0].click();", next_btns[-1])
                time.sleep(5)
                
                try: Alert(driver).accept()
                except NoAlertPresentException: pass

                # 詳細画面解析 (tennis_check_01準拠)[cite: 1]
                rows = driver.find_elements(By.TAG_NAME, "tr")
                current_facility = "不明な施設"
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
                            for i, cell in enumerate(cells):
                                if "○" in cell.text and cell.find_elements(By.TAG_NAME, "a"):
                                    t_idx = i - (len(cells) - len(time_slots))
                                    if 0 <= t_idx < len(time_slots):
                                        slot_time = time_slots[t_idx]
                                        if int(slot_time.split(":")[0]) > current_hour:
                                            unique_slots.add(f"■ {current_facility}/{court_name}：{slot_time}")
                        except: continue
            
            res_text = f"【{date_str}({day_wd})】\n" + ("\n".join(sorted(list(unique_slots))) if unique_slots else "空きなし")
            all_results.append(res_text)
        except Exception as e:
            all_results.append(f"【{date_str}】エラー発生")
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

@handler.add(MessageEvent, content_type=TextMessageContent)
def handle_message(event):
    user_msg = event.message.text
    today = datetime.now()
    target_dates = []

    # キーワード判定
    if "今日" in user_msg: target_dates.append(today)
    elif "明日" in user_msg: target_dates.append(today + timedelta(days=1))
    elif "週末" in user_msg:
        diff = (5 - today.weekday() + 7) % 7
        sat = today + timedelta(days=diff if diff > 0 else 7)
        target_dates.extend([sat, sat + timedelta(days=1)])
    else:
        # 曜日判定などのロジックをここに入れる（任意）
        return

    result = check_machida_tennis(target_dates)
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=result)]
            )
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
