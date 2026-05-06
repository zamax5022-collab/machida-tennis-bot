import os
import time
from datetime import datetime, timedelta
from flask import Flask, request, abort
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.alert import Alert
from selenium.common.exceptions import NoAlertPresentException

# LINE SDK v3
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest,
    PushMessageRequest, TextMessage as MessagingTextMessage
)
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent

app = Flask(__name__)

# LINE設定（環境変数から取得）
access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
channel_secret = os.environ.get('LINE_CHANNEL_SECRET')
configuration = Configuration(access_token=access_token)
handler = WebhookHandler(channel_secret)

def get_driver():
    """ブラウザの初期化"""
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_bin = "/opt/render/project/.render/chrome/opt/google/chrome/google-chrome"
    driver_path = "/opt/render/project/.render/chrome/opt/google/chrome/chromedriver"
    if os.path.exists(chrome_bin): chrome_options.binary_location = chrome_bin
    service = Service(executable_path=driver_path) if os.path.exists(driver_path) else None
    return webdriver.Chrome(service=service, options=chrome_options) if service else webdriver.Chrome(options=chrome_options)

def check_machida_tennis(target_dates):
    """
    指定された日付リストを順に検索して結果を返す
    """
    wd_names = ["月", "火", "水", "木", "金", "土", "日"]
    all_results = []

    for target_date in target_dates:
        driver = get_driver()
        day_num = str(target_date.day)
        day_wd = wd_names[target_date.weekday()]
        date_str = target_date.strftime("%m/%d")
        unique_slots = set()
        # 今日を検索する場合、現時刻より前の枠は除外するための判定
        current_hour = datetime.now().hour if target_date.date() == datetime.now().date() else -1

        try:
            driver.get("https://www.pf489.com/machida/dselect.html")
            time.sleep(2)
            driver.find_element(By.LINK_TEXT, "高機能検索").click()
            time.sleep(2)
            
            # フレーム切替
            frames = driver.find_elements(By.XPATH, "//iframe | //frame")
            for f in frames:
                try:
                    driver.switch_to.frame(f)
                    if "テニスコート" in driver.page_source: break
                except: driver.switch_to.default_content()

            # 施設選択（テニスコート関連を全チェック）
            inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
            for ipt in inputs:
                try:
                    parent_text = driver.execute_script("return arguments[0].parentNode.parentNode.innerText;", ipt)
                    if "コミュニティセンター" in parent_text: continue
                    if ("テニスコート" in parent_text or "クリーンセンター" in parent_text) and not ipt.is_selected():
                        driver.execute_script("arguments[0].click();", ipt)
                except: continue

            driver.execute_script("arguments[0].click();", driver.find_element(By.XPATH, "//input[contains(@value, '空き照会')]"))
            time.sleep(3)

            # --- 日付の選択（一括選択ロジック） ---
            header_xpath = f"//td[contains(., '{day_num}') and contains(., '{day_wd}')]"
            day_headers = driver.find_elements(By.XPATH, header_xpath)
            
            click_count = 0
            for header in day_headers:
                if len(header.text.strip()) > 10: continue # 無関係な長いテキストのセルを除外
                col_idx = len(header.find_elements(By.XPATH, "./preceding-sibling::td"))
                table = header.find_element(By.XPATH, "./ancestor::table[1]")
                for row in table.find_elements(By.TAG_NAME, "tr"):
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if len(cells) > col_idx:
                        links = cells[col_idx].find_elements(By.TAG_NAME, "a")
                        if links and links[0].text.strip() in ["○", "△"]:
                            driver.execute_script("arguments[0].click();", links[0])
                            click_count += 1

            # 一つでも選択（クリック）できた場合のみ「次へ」に進む（アラート対策）
            if click_count > 0:
                driver.execute_script("arguments[0].click();", driver.find_element(By.XPATH, "//input[contains(@value, '次へ')]"))
                
                # 万が一のアラートを閉じる
                try:
                    time.sleep(1)
                    Alert(driver).accept()
                except NoAlertPresentException:
                    pass

                # 詳細画面の解析（全ページループ）
                while True:
                    time.sleep(2)
                    rows = driver.find_elements(By.TAG_NAME, "tr")
                    current_fac = "不明"
                    for row in rows:
                        text = row.text.strip()
                        # 施設名を特定
                        if any(x in text for x in ["テニスコート", "グラウンド", "クリーンセンター"]) and "202" not in text:
                            current_fac = text.split(" ")[0].split("\n")[0]
                            continue
                        
                        if "○" in text:
                            cells = row.find_elements(By.TAG_NAME, "td")
                            try:
                                header_row = row.find_element(By.XPATH, "./preceding::tr[contains(., '～')][1]")
                                time_slots = [s for s in header_row.text.split() if "～" in s]
                                court = cells[0].text.strip().replace("\n", "")
                                
                                for i, cell in enumerate(cells):
                                    if "○" in cell.text:
                                        t_idx = i - (len(cells) - len(time_slots))
                                        if 0 <= t_idx < len(time_slots):
                                            s_time = time_slots[t_idx]
                                            # 過去の時間はスキップ
                                            if int(s_time.split(":")[0]) > current_hour:
                                                unique_slots.add(f"■ {current_fac}/{court}：{s_time}")
                            except: continue
                    
                    # 次のページがあれば移動、なければ終了
                    try:
                        next_p = driver.find_element(By.XPATH, "//a[contains(text(), '次へ >>')]")
                        driver.execute_script("arguments[0].click();", next_p)
                    except: break

            # 日付ごとの結果を格納
            res_text = f"【{date_str}({day_wd})】\n" + ("\n".join(sorted(list(unique_slots))) if unique_slots else "予約可能な空きなし")
            all_results.append(res_text)

        except Exception as e:
            all_results.append(f"【{date_str}】解析中にエラー: {str(e)}")
        finally:
            driver.quit()

    return "\n\n".join(all_results)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try: handler.handle(body, signature)
    except InvalidSignatureError: abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    text = event.message.text
    today = datetime.now()
    target_dates = []
    
    # 曜日計算用マップ
    wd_map = {"月曜": 0, "火曜": 1, "水曜": 2, "木曜": 3, "金曜": 4, "土曜": 5, "日曜": 6}

    # キーワード判定
    if "今日" in text:
        target_dates.append(today)
    elif "明日" in text:
        target_dates.append(today + timedelta(days=1))
    elif "週末" in text:
        # 次の土曜日（今日が土曜なら来週ではなく今日の土曜、日曜日なら来週の土曜）
        diff_sat = (5 - today.weekday() + 7) % 7
        # 今日が土日の場合は来週の週末を探す（当日を含まない運用なら +7）
        if diff_sat == 0: diff_sat = 7
        sat = today + timedelta(days=diff_sat)
        target_dates.extend([sat, sat + timedelta(days=1)])
    else:
        # 月曜〜日曜の判定
        for key, val in wd_map.items():
            if key in text:
                diff = (val - today.weekday() + 7) % 7
                # 今日と同じ曜日なら来週のその日を指定（今日を含まない設定）
                target_dates.append(today + timedelta(days=diff if diff > 0 else 7))
                break

    if target_dates:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            date_info = "・".join([d.strftime("%m/%d") for d in target_dates])
            # 受付メッセージ
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[MessagingTextMessage(text=f"{date_info}を検索中です。1〜2分ほどお待ちください。")]
            ))
            # 検索実行
            result = check_machida_tennis(target_dates)
            # 結果をプッシュ送信
            line_bot_api.push_message(PushMessageRequest(
                to=event.source.user_id,
                messages=[MessagingTextMessage(text=result)]
            ))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
