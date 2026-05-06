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
        
        frames = driver.find_elements(By.XPATH, "//iframe | //frame")
        for f in frames:
            try:
                driver.switch_to.frame(f)
                if "テニスコート" in driver.page_source: break
            except: driver.switch_to.default_content()

        print("施設を選択中...")
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

        day_num = str(target_date.day)
        wd_list = ["月", "火", "水", "木", "金", "土", "日"]
        day_wd = wd_list[target_date.weekday()]
        
        # カレンダーからの遷移
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
        
        # --- 解析ロジックの強化版 ---
        unique_slots = []
        rows = driver.find_elements(By.TAG_NAME, "tr")
        current_facility = "不明"
        time_headers = []

        for row in rows:
            text = row.text.strip()
            if not text: continue
            
            # 施設名の更新
            if any(x in text for x in ["テニスコート", "グラウンド", "クリーンセンター"]) and "202" not in text:
                current_facility = text.split()[0].replace("\n", "")
                continue

            # 時間ヘッダー行の特定 (～を含む行)
            if "～" in text and ("09" in text or "08" in text):
                time_headers = [t for t in text.split() if "～" in t]
                continue

            # ○が含まれる行の解析
            if "○" in text:
                cells = row.find_elements(By.TAG_NAME, "td")
                if not cells: continue
                
                court_name = cells[0].text.replace("\n", "").strip()
                
                # セルの中身を一つずつ見て、○があれば対応する時間のヘッダーと紐付け
                # 右側から数えることで、左側の名称列を避ける
                available_indices = []
                for idx, cell in enumerate(cells):
                    if "○" in cell.text:
                        available_indices.append(idx)
                
                # 後ろから数えて時間枠を特定
                for idx in available_indices:
                    # 時間枠ヘッダーの数に合わせて、セルのインデックスを調整
                    time_idx = idx - (len(cells) - len(time_headers))
                    if 0 <= time_idx < len(time_headers):
                        slot_info = f"■ {current_facility} {court_name}\n   {time_headers[time_idx]}"
                        if slot_info not in unique_slots:
                            unique_slots.append(slot_info)

        if not unique_slots:
            return f"{target_date.strftime('%m/%d')}：システム上に○はありましたが、詳細を読み取れませんでした。直接サイトを確認してください。"
        
        return f"【{target_date.strftime('%m/%d')} 空き状況】\n\n" + "\n\n".join(unique_slots)

    except Exception as e:
        print(f"詳細エラー: {str(e)}")
        return f"エラーが発生しました。"
    finally:
        if driver: driver.quit()

# （以下、callbackやhandle_messageは前回と同じ）
