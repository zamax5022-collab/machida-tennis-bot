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
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# --- LINE API設定 ---
# 本来は環境変数から取得するのが安全です
LINE_CHANNEL_ACCESS_TOKEN = 'あなたのチャネルアクセストークン'
LINE_CHANNEL_SECRET = 'あなたのチャネルシークレット'

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- Selenium スクレイピング関数 ---
def check_machida_tennis(target_date):
    """
    target_date: datetimeオブジェクト
    """
    chrome_options = Options()
    chrome_options.add_argument('--headless')  # サーバーでは画面を出さない
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    
    # Render環境用のChromeパス（render-build.shでインストールした場所）
    if os.path.exists("/opt/render/project/.render/chrome/opt/google/chrome/google-chrome"):
        chrome_options.binary_location = "/opt/render/project/.render/chrome/opt/google/chrome/google-chrome"

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    
    day_num = str(target_date.day)
    # 簡易的に曜日の文字を特定
    wd_list = ["月", "火", "水", "木", "金", "土", "日"]
    day_wd = wd_list[target_date.weekday()]
    date_str = target_date.strftime("%Y/%m/%d")
    current_hour = datetime.now().hour

    results = []

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

        search_btn = driver.find_element(By.XPATH, "//input[contains(@value, '空き照会')]")
        driver.execute_script("arguments[0].click();", search_btn)
        time.sleep(4)

        # カレンダー画面でクリック
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
        
        if not clicked:
            return f"{date_str} の空きは見つかりませんでした。"

        # 詳細画面解析
        next_btns = driver.find_elements(By.XPATH, "//input[contains(@value, '次へ')] | //a[contains(., '次へ')]")
        driver.execute_script("arguments[0].click();", next_btns[-1])
        time.sleep(5)

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
                header_row = row.find_element(By.XPATH, "./preceding::tr[contains(., '～')][1]")
                time_slots = [s for s in header_row.text.split() if "～" in s]
                court_name = cells[0].text.strip().replace("\n", "")
                
                for i, cell in enumerate(cells):
                    if "○" in cell.text and cell.find_elements(By.TAG_NAME, "a"):
                        time_idx = i - (len(cells) - len(time_slots))
                        if 0 <= time_idx < len(time_slots):
                            slot_time = time_slots[time_idx]
                            start_hour = int(slot_time.split(":")[0])
                            # 今日調べる場合のみ時間切れをチェック
                            if target_date.date() == datetime.now().date() and start_hour <= current_hour:
                                continue
                            unique_slots.add(f"■ {current_facility}/{court_name}：{slot_time}")

        return f"【{date_str} の空き】\n" + "\n".join(sorted(list(unique_slots))) if unique_slots else "空き枠はありませんでした。"

    except Exception as e:
        return f"エラーが発生しました: {str(e)}"
    finally:
        driver.quit()

# --- LINE Webhook ---
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text
    target_date = None

    if "今日" in text:
        target_date = datetime.now()
    elif "明日" in text:
        target_date = datetime.now() + timedelta(days=1)
    
    if target_date:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"{target_date.strftime('%m/%d')}を調べています。15秒ほどお待ちください..."))
        result_text = check_machida_tennis(target_date)
        # 応答期限が切れる可能性があるため、プッシュメッセージで送信
        line_bot_api.push_message(event.source.user_id, TextSendMessage(text=result_text))
    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="「今日」または「明日」と話しかけてください。"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)