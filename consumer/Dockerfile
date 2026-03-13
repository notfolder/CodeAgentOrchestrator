# Consumer サービス用 Dockerfile
# ビルドコンテキストはリポジトリルート（context: .）を想定
FROM python:3.11-slim

# uvをインストール
RUN pip install uv

# Docker CLIのインストール（Docker-outside-of-Docker用）
RUN apt-get update && apt-get install -y \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ワークスペース全体をコピー
COPY pyproject.toml ./
COPY shared/ ./shared/
COPY consumer/ ./consumer/

# Consumerの依存関係をインストール
RUN uv pip install --system -e ./shared -e ./consumer

WORKDIR /app/consumer

CMD ["python", "-m", "consumer"]
