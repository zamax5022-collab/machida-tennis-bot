import os
import time
import threading
from datetime import datetime, timedelta
from flask import Flask, request, abort
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

app = Flask(__name__)

# LINE設定
access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
channel_secret = os.environ.get('LINE_CHANNEL_SECRET')
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, PushMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent
configuration = Configuration(access_token=access_token)
handler = WebhookHandler(channel_secret)

def get_driver():
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--window-size=1920,1080')
    # ユーザーエージェントを設定して「人間らしさ」を出す
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    return webdriver.Chrome(options=chrome_options)

def enter_frame(driver):
    driver.switch_to.default_content()
    try:
        # フレームが現れるまで最大20秒待機
        WebDriverWait(driver, 20).until(EC.frame_to_be_available_and_switch_to_it((By.NAME, "MainFrame")))
    except:
        pass

def scrap_and_push(user_id, target_date):
    driver = None
    step = "開始"
    date_str = target_date.strftime('%Y%m%d')
    try:
        driver = get_driver()
        wait = WebDriverWait(driver, 30) # 待機を30秒に強化
        
        # 1. 画面選択
        step = "1.入口画面"
        driver.get("https://www.pf489.com/machida/dselect.html")
        time.sleep(3)
        enter_frame(driver)

        # 高機能検索
        btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(., '高機能検索')]")))
        driver.execute_script("arguments[0].click();", btn)
        
        # 2. 条件設定
        step = "2.条件設定画面への遷移待ち"
        time.sleep(8) # 画面切り替わりを長めに待つ
        
        # 最大3回、フレーム再侵入と要素探しをリトライ
        for i in range(3):
            try:
                enter_frame(driver)
                # テニスコートのラベルが出るまで待つ
                wait.until(EC.presence_of_element_located((By.TAG_NAME, "label")))
                break
            except:
                time.sleep(5)
                if i == 2: raise Exception("テニス選択画面が読み込めませんでした")

        step = "2.テニス選択実行"
        labels = driver.find_elements(By.TAG_NAME, "label")
        found_tennis = False
        for label in labels:
            if "テニスコート" in label.text and "コミュニティ" not in label.text:
                cb = driver.find_element(By.ID, label.get_attribute("for"))
                if not cb.is_selected():
                    driver.execute_script("arguments[0].click();", cb)
                found_tennis = True
        
        if not found_tennis: raise Exception("テニスコートの項目が見つかりません")

        # 空き照会ボタン
        submit_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@value='空き照会']")))
        driver.execute_script("arguments[0].click();", submit_btn)

        # 3. カレンダー画面
        step = f"3.カレンダー画面({date_str})"
        time.sleep(8)
        enter_frame(driver)
        
        target_xpath = f"//a[contains(@href, '{date_str}') and (contains(text(), '○') or contains(text(), '△'))]"
        try:
            link = wait.until(EC.element_to_be_clickable((By.XPATH, target_xpath)))
            driver.execute_script("arguments[0].click();", link)
        except:
            final_msg = f"📅 {target_date.strftime('%m/%d')}は、現在空き（○/△）が見つかりませんでした。"
            # ここで終了させる
            push_line(user_id, final_msg)
            return

        # 4. 時間帯別空き状況
        step = "4.詳細解析"
        time.sleep(8)
        enter_frame(driver)
        
        slots = []
        tables = wait.until(EC.presence_of_all_elements_located((By.XPATH, "//table[contains(@id, 'dlJikantai')]")))
        
        for table in tables:
            try:
                park_name = table.find_element(By.XPATH, "./preceding::a[contains(@id, 'LnkSisetu名')][1]").text.strip()
                time_headers = [th.text.replace("\n", "") for th in table.find_elements(By.XPATH, ".//tr[2]/th")]
                rows = table.find_elements(By.XPATH, ".//tr[position()>2]")
                for row in rows:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if not cells: continue
                    court_name = cells[0].text.strip()
                    for i, cell in enumerate(cells[1:], 1):
                        if "○" in cell.text or "△" in cell.text:
                            t_range = time_headers[i] if i < len(time_headers) else f"枠{i}"
                            slots.append(f"📍{park_name}【{court_name}】\n   └ {t_range}")
            except: continue

        if slots:
            final_msg = f"🎾 {target_date.strftime('%m/%d')}の空き状況\n\n" + "\n\n".join(list(dict.fromkeys(slots)))
        else:
            final_msg = f"📅 {target_date.strftime('%m/%d')}：空きが見つかりませんでした。"

    except Exception as e:
        final_msg = f"【エラー詳細】\nステップ：{step}\n内容：{str(e)[:100]}"
    finally:
        if driver: driver.quit()

    push_line(user_id, final_msg)

def push_line(user_id, text):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[TextMessage(text=text)]))

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
    user_id = event.source.user_id
    if "今日" in msg or "明日" in msg:
        target_date = datetime.now() if "今日" in msg else datetime.now() + timedelta(days=1)
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=f"🔍 調査開始...（町田市システムが重いため、1分ほどかかります）")]
            ))
        threading.Thread(target=scrap_and_push, args=(user_id, target_date)).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
