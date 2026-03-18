# Backend（User Config API）サービス用 Dockerfile
# ビルドコンテキストはリポジトリルート（context: .）を想定
FROM python:3.11-slim

# uvをインストール
RUN pip install uv

WORKDIR /app

# ワークスペース全体をコピー
COPY pyproject.toml ./
COPY shared/ ./shared/
COPY backend/ ./backend/
COPY docs/definitions/ ./docs/definitions/

# Backendの依存関係をインストール
RUN uv pip install --system -e ./shared -e ./backend

# PYTHONPATH を設定して shared・user_management を正しくインポートできるようにする
# - /app       : from shared.xxx import ... を解決（/app/shared/__init__.py）
# - /app/backend: from user_management.xxx import ... を解決
ENV PYTHONPATH=/app:/app/backend

WORKDIR /app/backend

CMD ["uvicorn", "user_management.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
