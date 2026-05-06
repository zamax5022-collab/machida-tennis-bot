import os
import time
import traceback
from datetime import datetime, timedelta
from flask import Flask, request, abort

# Selenium関連のインポート
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

app = Flask(__name__)

# --- LINE設定 ---
access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
channel_secret = os.environ.get('LINE_CHANNEL_SECRET')

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent

configuration = Configuration(access_token=access_token)
handler = WebhookHandler(channel_secret)

def get_driver():
    """Chromeの起動設定"""
    print("[Log] Chromeを起動中...")
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1280,1024')
    # Renderの環境に合わせてパスが通っていることを前提としています
    return webdriver.Chrome(options=chrome_options)

def check_machida_tennis(target_dates):
    wd_names = ["月", "火", "水", "木", "金", "土", "日"]
    all_results = []

    for target_date in target_dates:
        driver = None
        current_step = "開始前"
        date_str = target_date.strftime("%m/%d")
        day_wd = wd_names[target_date.weekday()]
        
        try:
            driver = get_driver()
            # 通常の待機は20秒
            wait = WebDriverWait(driver, 20)
            
            # Step 1: トップページ
            current_step = "1.トップページ読み込み"
            print(f"[Log] {date_str} {current_step}")
            driver.get("https://www.pf489.com/machida/dselect.html")
            
            # Step 2: 高機能検索ボタン
            current_step = "2.高機能検索ボタン押下"
            print(f"[Log] {current_step}")
            high_func_link = wait.until(EC.element_to_be_clickable((By.LINK_TEXT, "高機能検索")))
            driver.execute_script("arguments[0].click();", high_func_link)
            
            # Step 3: メインフレーム切り替え（ここを大幅強化）
            current_step = "3.メインフレーム切り替え（待機強化）"
            print(f"[Log] {current_step}")
            # フレームが出現するまで最大30秒粘る
            wait_frame = WebDriverWait(driver, 30)
            wait_frame.until(EC.frame_to_be_available_and_switch_to_it((By.NAME, "MainFrame")))
            print("[Log] フレームの切り替えに成功しました")

            # Step 4: 施設選択
            current_step = "4.施設(テニス)選択"
            print(f"[Log] {current_step}")
            labels = wait.until(EC.presence_of_all_elements_located((By.TAG_NAME, "label")))
            target_found = False
            for label in labels:
                if "テニスコート" in label.text and "コミュニティ" not in label.text:
                    checkbox = driver.find_element(By.ID, label.get_attribute("for"))
                    if not checkbox.is_selected():
                        driver.execute_script("arguments[0].click();", checkbox)
                    target_found = True
            
            if not target_found:
                raise Exception("テニスコートのチェックボックスが見つかりません")

            # Step 5: 検索ボタン
            current_step = "5.空き照会ボタン押下"
            print(f"[Log] {current_step}")
            search_btn = driver.find_element(By.XPATH, "//input[contains(@value, '空き照会')]")
            driver.execute_script("arguments[0].click();", search_btn)
            
            # Step 6: カレンダー日付選択
            current_step = "6.カレンダー日付選択"
            print(f"[Log] {current_step}")
            time.sleep(3) # 画面遷移の安定待ち
            day_num = str(target_date.day)
            # 町田市特有の「日付+曜日」が含まれるリンクを探す
            target_xpath = f"//td[contains(., '{day_num}') and contains(., '{day_wd}')]//a"
            day_links = driver.find_elements(By.XPATH, target_xpath)
            
            if not day_links:
                all_results.append(f"【{date_str}】空きなし(または選択不可)")
                continue
            driver.execute_script("arguments[0].click();", day_links[0])
            
            # Step 7: 次へ
            current_step = "7.次へボタン押下"
            print(f"[Log] {current_step}")
            next_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//input[contains(@value, '次へ')]")))
            driver.execute_script("arguments[0].click();", next_btn)
            
            # Step 8: 結果抽出
            current_step = "8.詳細データ抽出"
            print(f"[Log] {current_step}")
            time.sleep(2)
            unique_slots = []
            rows = driver.find_elements(By.TAG_NAME, "tr")
            for row in rows:
                if "○" in row.text:
                    # 読みやすいように整形
                    clean_text = row.text.replace("\n", " ").strip()
                    unique_slots.append(f"■ {clean_text}")

            res = f"【{date_str}({day_wd})】\n" + ("\n".join(unique_slots) if unique_slots else "空きなし")
            all_results.append(res)
            print(f"[Log] {date_str} 完了")

        except Exception as e:
            # LINEに返すエラーメッセージを詳細化
            error_msg = f"エラー発生(Step:{current_step}): {str(e)}"
            print(f"[Error] {error_msg}")
            # Stacktraceをログに出力（RenderのLogsで確認可能）
            print(traceback.format_exc())
            all_results.append(f"【{date_str}】{error_msg}")
        finally:
            if driver:
                print(f"[Log] {date_str} ブラウザを閉じます")
                driver.quit()

    return "\n\n".join(all_results)

# --- LINE Callback & Handler ---
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except Exception as e:
        print(f"Callback Error: {e}")
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_msg = event.message.text
    # 「今日」または「明日」という言葉に反応
    if "今日" not in user_msg and "明日" not in user_msg:
        return

    today = datetime.now()
    # 日本時間への調整が必要な場合は here + timedelta(hours=9)
    target_dates = [today] if "今日" in user_msg else [today + timedelta(days=1)]
    
    result = check_machida_tennis(target_dates)
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=result)])
        )

if __name__ == "__main__":
    # Renderのポート指定に対応
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
