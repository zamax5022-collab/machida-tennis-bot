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

def get_machida_debug_info(target_date):
    """ボットが取得したHTMLの生データをLINEに送って検証する"""
    date_str = target_date.strftime('%Y%m%d')
    session = requests.Session()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ja,en-US;q=0.7,en;q=0.3',
    }

    try:
        # 1. セッション確立のためにトップページを叩く
        session.get("https://www.pf489.com/machida/web/Wp_TopMenu.aspx", headers=headers, timeout=15)
        
        # 2. 直接、施設別空き状況ページを取得（検証用に施設を絞り込み）
        search_url = f"https://www.pf489.com/machida/web/Wg_ShisetsubetsuAkiJoukyou.aspx?S_DATE={date_str}&S_KBN=1&S_SISID=10,11"
        response = session.get(search_url, headers=headers, timeout=20)
        
        # 3. HTMLの中身を確認
        html_content = response.text
        # LINE送信用に特殊文字を置換し、冒頭400文字を抽出
        debug_text = html_content[:400].replace('<', '[').replace('>', ']')
        
        if "dlJikantai" in html_content or "dlShisetsu" in html_content:
            return f"✅ 【成功】データを確認できました！\n\n[解析用キーワード検出あり]\n\n中身の冒頭:\n{debug_text}..."
        elif "セッション" in html_content or "タイムアウト" in html_content:
            return f"❌ 【セッション拒否】システムに弾かれています。\n\n中身の冒頭:\n{debug_text}..."
        else:
            return f"❓ 【不明】空き情報が見つかりません。ページ構造が違うようです。\n\n中身の冒頭:\n{debug_text}..."

    except Exception as e:
        return f"⚠️ 【接続失敗】サーバーに届いていません。\nエラー: {str(e)}"

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
    
    if any(k in msg for k in ["今日", "明日", "土曜", "日曜"]):
        target_date = datetime.now() + timedelta(days=1) if "明日" in msg else datetime.now()
        
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=f"🛠 検証モード実行中 ({target_date.strftime('%m/%d')})...")]
            ))
        
        def task():
            result = get_machida_debug_info(target_date)
            push_line(user_id, result)
        
        threading.Thread(target=task).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
