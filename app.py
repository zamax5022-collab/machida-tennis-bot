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

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, PushMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent

app = Flask(__name__)

# 環境変数
access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
channel_secret = os.environ.get('LINE_CHANNEL_SECRET')
configuration = Configuration(access_token=access_token)
handler = WebhookHandler(channel_secret)

def get_driver():
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1280,1024')
    return webdriver.Chrome(options=chrome_options)

def scrap_and_push(user_id, target_date):
    driver = None
    date_str = target_date.strftime('%Y%m%d')
    try:
        driver = get_driver()
        wait = WebDriverWait(driver, 20)
        
        # 1-4. 検索手順
        driver.get("https://www.pf489.com/machida/dselect.html")
        search_btn = wait.until(EC.presence_of_element_located((By.XPATH, "//a[contains(., '高機能検索')]")))
        driver.execute_script("arguments[0].click();", search_btn)
        
        time.sleep(4)
        labels = wait.until(EC.presence_of_all_elements_located((By.TAG_NAME, "label")))
        for label in labels:
            if "テニスコート" in label.text and "コミュニティ" not in label.text:
                driver.execute_script("arguments[0].click();", driver.find_element(By.ID, label.get_attribute("for")))
        
        time.sleep(2)
        btns = driver.find_elements(By.TAG_NAME, "input")
        for b in btns:
            if "空き照会" in (b.get_attribute("value") or ""):
                driver.execute_script("arguments[0].click();", b)
                break

        # 5. カレンダー画面
        time.sleep(10)
        js_click_script = f"""
        var dateStr = '{date_str}';
        var links = document.getElementsByTagName('a');
        for (var i = 0; i < links.length; i++) {{
            var href = links[i].getAttribute('href') || "";
            var onclick = links[i].getAttribute('onclick') || "";
            if (href.includes(dateStr) || onclick.includes(dateStr)) {{
                links[i].click();
                return true;
            }}
        }}
        return false;
        """
        if not driver.execute_script(js_click_script):
            raise Exception(f"{date_str}の予約リンクが見つかりません。")

        # 6. 結果抽出（文字数オーバー対策）
        time.sleep(8)
        slots = []
        rows = driver.find_elements(By.XPATH, "//tr[contains(., '○') or contains(., '△')]")
        
        current_park = "施設不明"
        for r in rows:
            txt = r.text.replace("\n", " ").strip()
            # 公園名を特定
            if "公園" in txt and "テニスコート" in txt:
                current_park = txt.split(" ")[0]
            
            # 「○」があるデータだけをコンパクトに保存
            if "○" in txt or "△" in txt:
                slots.append(f"【{current_park}】{txt}")

        # LINEの5000文字制限に合わせ、安全のため4000文字でカット
        content = "\n\n".join(slots)
        if len(content) > 4000:
            content = content[:4000] + "\n...(以下略。空きが多すぎるため一部のみ表示します)"

        if slots:
            final_msg = f"🎾 {target_date.strftime('%m/%d')}の空き状況です：\n\n" + content
        else:
            final_msg = f"📅 {target_date.strftime('%m/%d')}の空きはありませんでした。"
        
    except Exception as e:
        final_msg = f"⚠️ エラー\n内容: {str(e)[:100]}"
    finally:
        if driver:
            driver.quit()

    # LINE送信
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.push_message(PushMessageRequest(
            to=user_id,
            messages=[TextMessage(text=final_msg)]
        ))

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
                messages=[TextMessage(text=f"🔍 {target_date.strftime('%m/%d')}を検索中です。1分ほどお待ちください。")]
            ))
        threading.Thread(target=scrap_and_push, args=(user_id, target_date)).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
