# Producer サービス用 Dockerfile
# ビルドコンテキストはリポジトリルート（context: .）を想定
FROM python:3.11-slim

# uvをインストール
RUN pip install uv

WORKDIR /app

# ワークスペース全体をコピー
COPY pyproject.toml ./
COPY config.yaml ./config.yaml
COPY shared/ ./shared/
COPY producer/ ./producer/

# Producerの依存関係をインストール
RUN uv pip install --system -e ./shared -e ./producer

# /app をワーキングディレクトリとして python -m producer を実行
CMD ["python", "-m", "producer"]
