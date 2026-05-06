import os
import time
from datetime import datetime, timedelta
from flask import Flask, request, abort
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 環境変数
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

def check_machida_tennis(target_date):
    print(f"--- スクレイピング開始: {target_date.strftime('%Y/%m/%d')} ---")
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')  # メモリ節約
    chrome_options.add_argument('--window-size=1280x1024')
    
    chrome_bin = "/opt/render/project/.render/chrome/opt/google/chrome/google-chrome"
    if os.path.exists(chrome_bin):
        chrome_options.binary_location = chrome_bin
        print("Chromeバイナリを確認しました。")

    driver = None
    try:
        print("Driverを起動しています...")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        
        print("町田市予約システムにアクセス中...")
        driver.get("https://www.pf489.com/machida/dselect.html")
        time.sleep(3)
        
        print("高機能検索をクリック...")
        driver.find_element(By.LINK_TEXT, "高機能検索").click()
        time.sleep(3)
        
        print("フレームの切り替えを試行中...")
        frames = driver.find_elements(By.XPATH, "//iframe | //frame")
        for f in frames:
            try:
                driver.switch_to.frame(f)
                if "テニスコート" in driver.page_source: 
                    print("対象フレームを発見しました。")
                    break
            except: 
                driver.switch_to.default_content()

        print("施設（テニスコート）を選択中...")
        inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        for ipt in inputs:
            try:
                parent_text = driver.execute_script("return arguments[0].parentNode.parentNode.innerText;", ipt)
                if "コミュニティセンター" in parent_text: continue
                if ("テニスコート" in parent_text or "クリーンセンター" in parent_text) and not ipt.is_selected():
                    driver.execute_script("arguments[0].click();", ipt)
            except: continue

        print("空き照会を実行...")
        search_btn = driver.find_element(By.XPATH, "//input[contains(@value, '空き照会')]")
        driver.execute_script("arguments[0].click();", search_btn)
        time.sleep(5)

        # 日付と曜日の特定
        day_num = str(target_date.day)
        wd_list = ["月", "火", "水", "木", "金", "土", "日"]
        day_wd = wd_list[target_date.weekday()]
        
        print(f"カレンダーから {day_num}日({day_wd}) を探しています...")
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
                        print("空き枠ボタンを発見。詳細画面へ移動します。")
                        driver.execute_script("arguments[0].click();", links[0])
                        clicked = True
                        break
            if clicked: break
        
        if not clicked: 
            print("指定日の空き枠が見つかりませんでした。")
            return f"{target_date.strftime('%m/%d')} の空きはありません。"

        time.sleep(4)
        print("詳細画面を解析中...")
        rows = driver.find_elements(By.TAG_NAME, "tr")
        current_facility = "不明"
        unique_slots = set()

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
                        if "○" in cell.text:
                            time_idx = i - (len(cells) - len(time_slots))
                            if 0 <= time_idx < len(time_slots):
                                unique_slots.add(f"■ {current_facility}/{court_name}：{time_slots[time_idx]}")
                except: continue

        print(f"解析完了。スロット数: {len(unique_slots)}")
        return f"【{target_date.strftime('%m/%d')} の空き】\n" + "\n".join(sorted(list(unique_slots))) if unique_slots else "空き枠はありません。"

    except Exception as e:
        print(f"エラー発生: {str(e)}")
        return f"エラーが発生しました: {str(e)}"
    finally:
        if driver:
            print("Driverを終了します。")
            driver.quit()

@app.route("/callback", methods=['POST'])
def callback():
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, request.headers.get('X-Line-Signature', ''))
    except:
        print("署名検証をスキップして続行します")
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text
    if "今日" in text:
        target_date = datetime.now()
    elif "明日" in text:
        target_date = datetime.now() + timedelta(days=1)
    else:
        return

    print(f"ユーザーID: {event.source.user_id} からの要求を受付")
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"{target_date.strftime('%m/%d')}を調べています。20秒ほどお待ちください..."))
    
    result = check_machida_tennis(target_date)
    
    print("LINEへ結果を送信中...")
    line_bot_api.push_message(event.source.user_id, TextSendMessage(text=result))
    print("送信完了。")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
