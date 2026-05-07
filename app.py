import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, abort
from datetime import datetime, timedelta
import threading

app = Flask(__name__)

# LINE設定（環境変数はそのまま使用）
access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
channel_secret = os.environ.get('LINE_CHANNEL_SECRET')
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, PushMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent
configuration = Configuration(access_token=access_token)
handler = WebhookHandler(channel_secret)

def get_machida_tennis_info(target_date):
    """セッションを維持しながら町田市の空き情報を解析する"""
    date_str = target_date.strftime('%Y%m%d')
    session = requests.Session()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    try:
        # 1. 玄関（トップページ）にアクセスしてセッションCookieを取得
        session.get("https://www.pf489.com/machida/web/Wp_TopMenu.aspx", headers=headers, timeout=15)
        
        # 2. 空き照会ページへ直接アクセス（施設ID: 10-20番が主要テニスコート）
        search_url = f"https://www.pf489.com/machida/web/Wg_ShisetsubetsuAkiJoukyou.aspx?S_DATE={date_str}&S_KBN=1&S_SISID=10,11,12,13,14,15,16,17,18,19,20"
        response = session.get(search_url, headers=headers, timeout=20)
        
        soup = BeautifulSoup(response.text, 'html.parser')
        results = []

        # 施設名と空き状況が含まれるテーブルを探す
        # 町田市のシステムは dlJikantai というIDの中に時間帯別のデータがある
        jikantai_tables = soup.find_all('table', id=lambda x: x and 'dlJikantai' in x)
        
        if not jikantai_tables:
            # 施設別テーブルが見つからない場合、日別テーブル（dlShisetsu）を試行
            jikantai_tables = soup.find_all('table', id=lambda x: x and 'dlShisetsu' in x)

        for table in jikantai_tables:
            # 施設名を探す（テーブルより上にある名前タグ）
            parent_container = table.find_parent('td')
            park_name = "テニスコート"
            if parent_container:
                name_tag = parent_container.find_previous('a')
                if name_tag:
                    park_name = name_tag.get_text(strip=True)

            # 行をループして「○」を探す
            rows = table.find_all('tr')
            for row in rows:
                if '○' in row.text or '△' in row.text:
                    # 簡易的に空きがある行の内容を抽出
                    content = row.get_text(separator=' ', strip=True)
                    # 不要な文字列を除去して整形
                    clean_content = content.replace('予約', '').replace('選択', '').strip()
                    results.append(f"📍{park_name}\n   └ {clean_content}")

        if not results:
            return f"📅 {target_date.strftime('%m/%d')} は「○」が見つかりませんでした。"
        
        # 重複を除去して最大15件表示
        unique_results = list(dict.fromkeys(results))[:15]
        return f"🎾 {target_date.strftime('%m/%d')} の空き情報を発見しました！\n\n" + "\n\n".join(unique_results)

    except Exception as e:
        return f"⚠️ 接続に失敗しました。少し時間を置いて試してください。"

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
        # 日付判定
        if "明日" in msg:
            target_date = datetime.now() + timedelta(days=1)
        elif "土曜" in msg:
            days_ahead = (5 - datetime.now().weekday()) % 7
            target_date = datetime.now() + timedelta(days=days_ahead)
        elif "日曜" in msg:
            days_ahead = (6 - datetime.now().weekday()) % 7
            target_date = datetime.now() + timedelta(days=days_ahead)
        else:
            target_date = datetime.now()
            
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=f"🎾 町田市システムにログインして {target_date.strftime('%m/%d')} を精査中です...")]
            ))
        
        def task():
            result = get_machida_tennis_info(target_date)
            push_line(user_id, result)
        
        threading.Thread(target=task).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
