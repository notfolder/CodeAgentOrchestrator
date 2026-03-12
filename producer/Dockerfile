# Producer サービス用 Dockerfile
# ビルドコンテキストはリポジトリルート（context: .）を想定
FROM python:3.11-slim

# uvをインストール
RUN pip install uv

WORKDIR /app

# ワークスペース全体をコピー
COPY pyproject.toml ./
COPY shared/ ./shared/
COPY producer/ ./producer/

# Producerの依存関係をインストール
RUN uv pip install --system -e ./shared -e ./producer

WORKDIR /app/producer

CMD ["python", "-m", "producer"]
