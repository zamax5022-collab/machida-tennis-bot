import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, abort
from datetime import datetime, timedelta
import threading

app = Flask(__name__)

# LINE設定
access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
channel_secret = os.environ.get('LINE_CHANNEL_SECRET')
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, PushMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent
configuration = Configuration(access_token=access_token)
handler = WebhookHandler(channel_secret)

def get_machida_tennis_info(target_date):
    """BS4を使って町田市の空き情報を直接解析する関数"""
    date_str = target_date.strftime('%Y%m%d')
    # 町田市の空き照会URL（テニスコート等、主要施設を指定したパラメータ付き）
    url = f"https://www.pf489.com/machida/web/Wg_ShisetsubetsuAkiJoukyou.aspx?S_DATE={date_str}&S_KBN=1&S_SISID=10,11,12,13,14,15,16,17,18,19,20"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        
        # HTMLの解析開始
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 施設別テーブルを探す
        results = []
        # 町田市のシステムは dlJikantai というIDの中に時間帯別の表がある
        tables = soup.find_all('table', id=lambda x: x and 'dlJikantai' in x)
        
        for table in tables:
            # 施設名を取得（テーブルの少し前にある <a> タグの中身）
            park_tag = table.find_previous('a', id=lambda x: x and 'LnkSisetu名' in x)
            park_name = park_tag.get_text(strip=True) if park_tag else "不明な施設"
            
            # 時間帯ヘッダー（trの2番目にある）
            headers_row = table.find_all('tr')[1]
            time_slots = [th.get_text(strip=True) for th in headers_row.find_all('th')]
            
            # 各面（A面、B面など）の行を解析
            rows = table.find_all('tr')[2:]
            for row in rows:
                cells = row.find_all('td')
                if not cells: continue
                
                court_name = cells[0].get_text(strip=True)
                for i, cell in enumerate(cells[1:]):
                    status = cell.get_text(strip=True)
                    if '○' in status or '△' in status:
                        time_range = time_slots[i+1] if (i+1) < len(time_slots) else "時間不明"
                        results.append(f"📍{park_name}【{court_name}】\n   └ {time_range} ({status})")

        if not results:
            return f"📅 {target_date.strftime('%m/%d')} は「○」が見つかりませんでした。"
        
        return f"🎾 {target_date.strftime('%m/%d')} 空き速報！\n\n" + "\n\n".join(list(dict.fromkeys(results))[:15])

    except Exception as e:
        return f"⚠️ 解析エラー: {str(e)[:50]}"

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
        
        # まず返信する
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=f"🔍 BS4高速モードで {target_date.strftime('%m/%d')} をスキャン中...")]
            ))
        
        # 非同期で重い処理を実行
        def task():
            result = get_machida_tennis_info(target_date)
            push_line(user_id, result)
        
        threading.Thread(target=task).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
