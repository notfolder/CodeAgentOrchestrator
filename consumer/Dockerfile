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
COPY config.yaml ./config.yaml
COPY shared/ ./shared/
COPY consumer/ ./consumer/
COPY docs/definitions/ ./docs/definitions/

# Consumerの依存関係をインストール
RUN uv pip install --system -e ./shared -e ./consumer

# /app をワーキングディレクトリとして python -m consumer を実行
CMD ["python", "-m", "consumer"]
