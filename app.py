import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, abort
from datetime import datetime, timedelta

app = Flask(__name__)

# LINE設定
access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
channel_secret = os.environ.get('LINE_CHANNEL_SECRET')
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent
configuration = Configuration(access_token=access_token)
handler = WebhookHandler(channel_secret)

def get_vacant_info(target_date):
    date_str = target_date.strftime('%Y%m%d')
    session = requests.Session()
    # 町田市システムはUser-Agentが古いと拒絶されることがあるため設定
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})

    try:
        # 1. 初期アクセスしてセッション開始
        res = session.get("https://www.pf489.com/machida/web/Wp_TopMenu.aspx")
        
        # 2. テニスコートの条件を指定して空き照会へ (POSTリクエスト)
        # 本来は複雑なViewStateが必要ですが、最もシンプルな「直接検索URL」を試行します
        search_url = f"https://www.pf489.com/machida/web/Wg_ShisetsubetsuAkiJoukyou.aspx?S_DATE={date_str}&S_KBN=1&S_SISID=10,11,12,13,14,15"
        res = session.get(search_url)
        
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 3. 解析
        results = []
        # 町田市のテーブル構造から「○」または「△」を含む行を抽出
        for link in soup.find_all('a', href=True):
            if date_str in link['href'] and ('○' in link.text or '△' in link.text):
                # 親要素から施設名を特定（簡易版）
                results.append("空きあり")

        if not results:
            return f"📅 {target_date.strftime('%m/%d')} は現在、空きが見つかりませんでした。"
        
        return f"🎾 {target_date.strftime('%m/%d')} に空き枠の可能性があります！\n詳細確認はこちら：\nhttps://www.pf489.com/machida/dselect.html"

    except Exception as e:
        return f"⚠️ 接続エラー: 町田市のシステムが混雑しているか、メンテナンス中の可能性があります。"

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
    text = event.message.text
    if any(k in text for k in ["今日", "明日", "土曜", "日曜"]):
        days = 1 if "明日" in text else 0
        target_date = datetime.now() + timedelta(days=days)
        
        result_msg = get_vacant_info(target_date)
        
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=result_msg)]
            ))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
