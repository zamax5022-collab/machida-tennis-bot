# Python 3.11のスリム版を使用
FROM python:3.11-slim

# 必要なパッケージのインストール
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    curl \
    lsb-release \
    && rm -rf /var/lib/apt/lists/*

# Google Chromeのインストール（apt-keyを使わない最新の書き方）
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y \
    google-chrome-stable \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# 作業ディレクトリの設定
WORKDIR /app

# 必要なPythonライブラリをコピーしてインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードをコピー
COPY . .

# Gunicornで起動
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000"]
