import os
import time
from datetime import datetime, timedelta
from flask import Flask, request
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

def check_machida_tennis(target_date):
    print(f"--- 探索開始: {target_date.strftime('%Y/%m/%d')} ---")
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--blink-settings=imagesEnabled=false')
    
    chrome_bin = "/opt/render/project/.render/chrome/opt/google/chrome/google-chrome"
    if os.path.exists(chrome_bin):
        options.binary_location = chrome_bin

    driver = None
    try:
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(30)
        
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

        # 全てのテニスコートを選択（コミュニティセンター以外）
        print("全施設を選択中...")
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

        # カレンダーから日付を探す
        day_num = str(target_date.day)
        wd_list = ["月", "火", "水", "木", "金", "土", "日"]
        day_wd = wd_list[target_date.weekday()]
        
        # 正確な日付セルを特定（10文字以内のセルに限定して誤爆を防ぐ）
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
        # 詳細画面の解析
        unique_slots = []
        rows = driver.find_elements(By.TAG_NAME, "tr")
        current_facility = "不明"

        for row in rows:
            text = row.text.strip()
            # 施設名の取得
            if any(x in text for x in ["テニスコート", "グラウンド", "クリーンセンター"]) and "202" not in text:
                current_facility = text.split()[0]
                continue
            
            # 「○」がある行を解析
            if "○" in text:
                cells = row.find_elements(By.TAG_NAME, "td")
                court_name = cells[0].text.replace("\n", "")
                
                # 時間枠のヘッダーを探す
                try:
                    header_row = row.find_element(By.XPATH, "./preceding::tr[contains(., '～')][1]")
                    time_slots = [s for s in header_row.text.split() if "～" in s]
                    
                    # ○の位置から時間を特定
                    for i, cell in enumerate(cells):
                        if "○" in cell.text:
                            # 時間枠のインデックスを計算
                            time_idx = i - (len(cells) - len(time_slots))
                            if 0 <= time_idx < len(time_slots):
                                unique_slots.append(f"■ {current_facility} {court_name}\n   {time_slots[time_idx]}")
                except: continue

        if not unique_slots: return f"{target_date.strftime('%m/%d')}：詳細を確認しましたが空きは見つかりませんでした。"
        
        return f"【{target_date.strftime('%m/%d')} 空きあり！】\n\n" + "\n\n".join(unique_slots)

    except Exception as e:
        print(f"エラー: {str(e)}")
        return f"検索中にエラーが発生しました。"
    finally:
        if driver: driver.quit()

@app.route("/callback", methods=['POST'])
def callback():
    body = request.get_data(as_text=True)
    try: handler.handle(body, request.headers.get('X-Line-Signature', ''))
    except: pass
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text
    if "今日" in text: target_date = datetime.now()
    elif "明日" in text: target_date = datetime.now() + timedelta(days=1)
    else: return

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"{target_date.strftime('%m/%d')}の全施設を調査中です。約1分お待ちください..."))
    result = check_machida_tennis(target_date)
    line_bot_api.push_message(event.source.user_id, TextSendMessage(text=result))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
