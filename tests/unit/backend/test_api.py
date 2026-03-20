"""
User Config API の単体テスト

各APIエンドポイントについて、正常系・認証エラー・バリデーションエラーの
HTTPレスポンスを検証する。リポジトリレイヤーはFastAPIのdependency_overridesで
モックに置き換える。
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.user_management import api as api_module
from backend.user_management.api import (
    _get_task_repository,
    _get_token_usage_repository,
    _get_user_repository,
    _get_workflow_definition_repository,
    router,
)
from backend.user_management.auth import create_access_token, hash_password


# =====================================================================
# テスト用ヘルパー関数
# =====================================================================

_TEST_JWT_SECRET = "test-secret-for-testing-only-xyz"


def _make_token(username: str, role: str) -> str:
    """テスト用JWTトークンを生成する"""
    with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
        return create_access_token(username, role)


def _admin_headers() -> dict[str, str]:
    """管理者認証ヘッダーを返す"""
    return {"Authorization": f"Bearer {_make_token('admin', 'admin')}"}


def _user_headers() -> dict[str, str]:
    """一般ユーザー認証ヘッダーを返す"""
    return {"Authorization": f"Bearer {_make_token('testuser', 'user')}"}


def _make_mock_user_repo() -> MagicMock:
    """UserRepository のモックを生成する"""
    mock = MagicMock()
    mock.get_user_by_username = AsyncMock(return_value=None)
    mock.list_users = AsyncMock(return_value=[])
    mock.create_user = AsyncMock(return_value={})
    mock.create_user_config = AsyncMock(return_value={})
    mock.update_user = AsyncMock(return_value=None)
    mock.update_user_config = AsyncMock(return_value=None)
    mock.get_user_config = AsyncMock(return_value=None)
    mock.get_decrypted_api_key = AsyncMock(return_value=None)
    mock.get_user_workflow_setting = AsyncMock(return_value=None)
    mock.create_user_workflow_setting = AsyncMock(return_value=None)
    mock.update_user_workflow_setting = AsyncMock(return_value=None)
    return mock


def _make_mock_wf_repo() -> MagicMock:
    """WorkflowDefinitionRepository のモックを生成する"""
    mock = MagicMock()
    mock.list_workflow_definitions = AsyncMock(return_value=[])
    mock.get_workflow_definition = AsyncMock(return_value=None)
    mock.create_workflow_definition = AsyncMock(return_value={})
    mock.update_workflow_definition = AsyncMock(return_value=None)
    mock.delete_workflow_definition = AsyncMock(return_value=False)
    return mock


def _make_mock_task_repo() -> MagicMock:
    """TaskRepository のモックを生成する"""
    mock = MagicMock()
    mock.list_tasks = AsyncMock(return_value=[])
    return mock


def _make_mock_token_repo() -> MagicMock:
    """TokenUsageRepository のモックを生成する"""
    mock = MagicMock()
    return mock


def _make_test_app(
    user_repo=None,
    wf_repo=None,
    task_repo=None,
    token_repo=None,
) -> FastAPI:
    """
    テスト用FastAPIアプリを生成し、リポジトリの依存関係をオーバーライドする。

    Args:
        user_repo: UserRepositoryモック（Noneの場合はデフォルトモック）
        wf_repo: WorkflowDefinitionRepositoryモック
        task_repo: TaskRepositoryモック
        token_repo: TokenUsageRepositoryモック

    Returns:
        依存関係が差し替えられたFastAPIアプリ
    """
    app = FastAPI()
    app.include_router(router)

    _ur = user_repo or _make_mock_user_repo()
    _wr = wf_repo or _make_mock_wf_repo()
    _tr = task_repo or _make_mock_task_repo()
    _tor = token_repo or _make_mock_token_repo()

    app.dependency_overrides[_get_user_repository] = lambda: _ur
    app.dependency_overrides[_get_workflow_definition_repository] = lambda: _wr
    app.dependency_overrides[_get_task_repository] = lambda: _tr
    app.dependency_overrides[_get_token_usage_repository] = lambda: _tor

    return app


# =====================================================================
# 認証エンドポイントのテスト
# =====================================================================


class TestLogin:
    """POST /api/v1/auth/login のテスト"""

    def test_正常なログインでトークンが返ること(self):
        """有効なメールアドレスとパスワードでJWTトークンが返ることを検証する"""
        password = "ValidPass1!"
        hashed = hash_password(password)
        user_repo = _make_mock_user_repo()
        user_repo.get_user_by_username.return_value = {
            "username": "Test User",
            "password_hash": hashed,
            "role": "user",
            "is_active": True,
        }
        app = _make_test_app(user_repo=user_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/auth/login",
                json={"username": "testuser", "password": password},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == 86400

    def test_存在しないユーザーで401が返ること(self):
        """存在しないメールアドレスでHTTP 401が返ることを検証する"""
        user_repo = _make_mock_user_repo()
        user_repo.get_user_by_username.return_value = None
        app = _make_test_app(user_repo=user_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/auth/login",
                json={"username": "nobody", "password": "AnyPass1!"},
            )

        assert resp.status_code == 401

    def test_誤ったパスワードで401が返ること(self):
        """誤ったパスワードでHTTP 401が返ることを検証する"""
        hashed = hash_password("CorrectPass1!")
        user_repo = _make_mock_user_repo()
        user_repo.get_user_by_username.return_value = {
            "password_hash": hashed,
            "role": "user",
            "is_active": True,
        }
        app = _make_test_app(user_repo=user_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/auth/login",
                json={"username": "testuser", "password": "WrongPass1!"},
            )

        assert resp.status_code == 401

    def test_無効化されたアカウントで401が返ること(self):
        """is_active=Falseのアカウントでは認証失敗(401)となることを検証する"""
        password = "ValidPass1!"
        hashed = hash_password(password)
        user_repo = _make_mock_user_repo()
        user_repo.get_user_by_username.return_value = {
            "password_hash": hashed,
            "role": "user",
            "is_active": False,
        }
        app = _make_test_app(user_repo=user_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/auth/login",
                json={"username": "inactive", "password": password},
            )

        assert resp.status_code == 401


# =====================================================================
# ユーザー一覧エンドポイントのテスト
# =====================================================================


class TestListUsers:
    """GET /api/v1/users のテスト"""

    def test_管理者はユーザー一覧を取得できること(self):
        """管理者権限でユーザー一覧が取得できることを検証する"""
        user_repo = _make_mock_user_repo()
        user_repo.list_users.return_value = [
            {
                "username": "User One",
                "role": "user",
                "is_active": True,
                "created_at": None,
            }
        ]
        app = _make_test_app(user_repo=user_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.get("/api/v1/users", headers=_admin_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["username"] == "User One"

    def test_一般ユーザーはユーザー一覧を取得できないこと(self):
        """一般ユーザーがGET /api/v1/usersにアクセスすると403が返ることを検証する"""
        app = _make_test_app()

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.get("/api/v1/users", headers=_user_headers())

        assert resp.status_code == 403

    def test_認証なしでユーザー一覧を取得できないこと(self):
        """認証トークンなしでGET /api/v1/usersにアクセスすると401/403が返ることを検証する"""
        app = _make_test_app()
        client = TestClient(app)
        # Bearer Tokenがない場合、HTTPBearerは401を返す
        resp = client.get("/api/v1/users")
        assert resp.status_code in (401, 403)


# =====================================================================
# ユーザー作成エンドポイントのテスト
# =====================================================================


class TestCreateUser:
    """POST /api/v1/users のテスト"""

    def test_管理者は新規ユーザーを作成できること(self):
        """管理者権限で新規ユーザーが作成できることを検証する"""
        user_repo = _make_mock_user_repo()
        user_repo.create_user.return_value = {
            "username": "New User",
            "role": "user",
            "is_active": True,
            "created_at": None,
        }
        user_repo.create_user_config.return_value = {}
        app = _make_test_app(user_repo=user_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/users",
                headers=_admin_headers(),
                json={
                    "username": "New User",
                    "password": "SecurePass1!",
                    "role": "user",
                },
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "New User"

    def test_弱いパスワードでバリデーションエラーが返ること(self):
        """パスワード要件を満たさない場合に422が返ることを検証する"""
        app = _make_test_app()

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/users",
                headers=_admin_headers(),
                json={
                    "username": "New User",
                    "password": "weak",  # 要件を満たさないパスワード
                    "role": "user",
                },
            )

        assert resp.status_code == 422

    def test_不正なロールでバリデーションエラーが返ること(self):
        """roleが'admin'/'user'以外の場合に422が返ることを検証する"""
        app = _make_test_app()

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/users",
                headers=_admin_headers(),
                json={
                    "username": "New User",
                    "password": "SecurePass1!",
                    "role": "superuser",  # 無効なロール
                },
            )

        assert resp.status_code == 422

    def test_一般ユーザーはユーザー作成できないこと(self):
        """一般ユーザーがPOST /api/v1/usersにアクセスすると403が返ることを検証する"""
        app = _make_test_app()

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/users",
                headers=_user_headers(),
                json={
                    "username": "New User",
                    "password": "SecurePass1!",
                    "role": "user",
                },
            )

        assert resp.status_code == 403

    def test_重複メールアドレスで409が返ること(self):
        """既に存在するメールアドレスで登録すると HTTP 409 が返ることを検証する"""
        import asyncpg

        user_repo = _make_mock_user_repo()
        # create_user が UniqueViolationError を発生させる
        user_repo.create_user.side_effect = asyncpg.UniqueViolationError("duplicate")
        app = _make_test_app(user_repo=user_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/users",
                headers=_admin_headers(),
                json={
                    "username": "Existing User",
                    "password": "SecurePass1!",
                    "role": "user",
                },
            )

        assert resp.status_code == 409


# =====================================================================
# ユーザー設定取得エンドポイントのテスト
# =====================================================================


class TestGetUserConfig:
    """GET /api/v1/config/{username} のテスト"""

    def test_ユーザーは自分の設定を取得できること(self):
        """一般ユーザーが自分自身の設定を取得できることを検証する"""
        user_repo = _make_mock_user_repo()
        user_repo.get_user_by_username.return_value = {
            "username": "Test User",
            "role": "user",
            "is_active": True,
        }
        user_repo.get_user_config.return_value = {
            "username": "testuser",
            "llm_provider": "openai",
            "api_key_encrypted": None,
            "model_name": "gpt-4o",
            "temperature": 0.2,
            "max_tokens": 4096,
        }
        user_repo.get_decrypted_api_key.return_value = None
        app = _make_test_app(user_repo=user_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.get(
                "/api/v1/config/user@example.com", headers=_user_headers()
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "testuser"
        assert "api_key" in data
        assert "api_key_encrypted" not in data

    def test_一般ユーザーは他ユーザーの設定を取得できないこと(self):
        """一般ユーザーが他ユーザーの設定を取得しようとすると403が返ることを検証する"""
        app = _make_test_app()

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.get(
                "/api/v1/config/other@example.com", headers=_user_headers()
            )

        assert resp.status_code == 403

    def test_存在しないユーザーで404が返ること(self):
        """存在しないユーザーの設定を取得しようとすると404が返ることを検証する"""
        user_repo = _make_mock_user_repo()
        user_repo.get_user_by_username.return_value = None
        app = _make_test_app(user_repo=user_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.get(
                "/api/v1/config/admin@example.com", headers=_admin_headers()
            )

        assert resp.status_code == 404

    def test_管理者は任意ユーザーの設定を取得できること(self):
        """管理者が任意のユーザーの設定を取得できることを検証する"""
        user_repo = _make_mock_user_repo()
        user_repo.get_user_by_username.return_value = {
            "role": "user",
            "is_active": True,
        }
        user_repo.get_user_config.return_value = {
            "username": "testuser",
            "llm_provider": "openai",
            "api_key_encrypted": "enc_value",
            "model_name": "gpt-4o",
        }
        user_repo.get_decrypted_api_key.return_value = "sk-decrypted"
        app = _make_test_app(user_repo=user_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.get(
                "/api/v1/config/user@example.com", headers=_admin_headers()
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["api_key"] == "sk-decrypted"


# =====================================================================
# ユーザー更新エンドポイントのテスト
# =====================================================================


class TestUpdateUser:
    """PUT /api/v1/users/{username} のテスト"""

    def test_管理者はユーザー情報を更新できること(self):
        """管理者が他ユーザーのrole/is_activeを変更できることを検証する"""
        user_repo = _make_mock_user_repo()
        user_repo.get_user_by_username.return_value = {
            "username": "Old Name",
            "role": "user",
            "is_active": True,
        }
        user_repo.update_user.return_value = {
            "username": "New Name",
            "role": "admin",
            "is_active": True,
        }
        app = _make_test_app(user_repo=user_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.put(
                "/api/v1/users/user@example.com",
                headers=_admin_headers(),
                json={"username": "New Name", "role": "admin"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "admin"

    def test_一般ユーザーは他ユーザーの設定を変更できないこと(self):
        """一般ユーザーが他ユーザーを更新しようとすると403が返ることを検証する"""
        app = _make_test_app()

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.put(
                "/api/v1/users/other@example.com",
                headers=_user_headers(),
                json={"model_name": "gpt-4"},
            )

        assert resp.status_code == 403

    def test_一般ユーザーはLLM設定を自分で変更できること(self):
        """一般ユーザーが自分自身のLLM設定を変更できることを検証する"""
        user_repo = _make_mock_user_repo()
        user_repo.get_user_by_username.return_value = {
            "username": "Test User",
            "role": "user",
            "is_active": True,
        }
        app = _make_test_app(user_repo=user_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.put(
                "/api/v1/users/user@example.com",
                headers=_user_headers(),
                json={"model_name": "gpt-4"},
            )

        assert resp.status_code == 200

    def test_一般ユーザーはroleを変更できないこと(self):
        """一般ユーザーが自分のroleを変更しようとすると403が返ることを検証する"""
        app = _make_test_app()

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.put(
                "/api/v1/users/user@example.com",
                headers=_user_headers(),
                json={"role": "admin"},  # 一般ユーザーはrole変更不可
            )

        assert resp.status_code == 403

    def test_存在しないユーザーで404が返ること(self):
        """存在しないユーザーを更新しようとすると404が返ることを検証する"""
        user_repo = _make_mock_user_repo()
        user_repo.get_user_by_username.return_value = None
        app = _make_test_app(user_repo=user_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.put(
                "/api/v1/users/nobody@example.com",
                headers=_admin_headers(),
                json={"model_name": "gpt-4"},
            )

        assert resp.status_code == 404


# =====================================================================
# ワークフロー設定エンドポイントのテスト
# =====================================================================


class TestWorkflowSetting:
    """GET/PUT /api/v1/users/{user_id}/workflow_setting のテスト"""

    def test_ユーザーは自分のワークフロー設定を取得できること(self):
        """一般ユーザーが自分のワークフロー設定を取得できることを検証する"""
        user_repo = _make_mock_user_repo()
        user_repo.get_user_workflow_setting.return_value = {
            "username": "testuser",
            "workflow_definition_id": 1,
        }
        app = _make_test_app(user_repo=user_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.get(
                "/api/v1/users/user@example.com/workflow_setting",
                headers=_user_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow_definition_id"] == 1

    def test_一般ユーザーは他ユーザーのワークフロー設定を取得できないこと(self):
        """一般ユーザーが他ユーザーのワークフロー設定を取得しようとすると403が返ることを検証する"""
        app = _make_test_app()

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.get(
                "/api/v1/users/other@example.com/workflow_setting",
                headers=_user_headers(),
            )

        assert resp.status_code == 403

    def test_ワークフロー設定が存在しない場合404が返ること(self):
        """ワークフロー設定が未設定の場合404が返ることを検証する"""
        user_repo = _make_mock_user_repo()
        user_repo.get_user_workflow_setting.return_value = None
        app = _make_test_app(user_repo=user_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.get(
                "/api/v1/users/user@example.com/workflow_setting",
                headers=_user_headers(),
            )

        assert resp.status_code == 404

    def test_ユーザーはワークフロー設定を更新できること(self):
        """一般ユーザーが自分のワークフロー設定を更新できることを検証する（新規作成パス）"""
        user_repo = _make_mock_user_repo()
        user_repo.get_user_workflow_setting.return_value = None
        user_repo.create_user_workflow_setting.return_value = {
            "username": "testuser",
            "workflow_definition_id": 2,
        }
        wf_repo = _make_mock_wf_repo()
        wf_repo.get_workflow_definition.return_value = {
            "id": 2,
            "name": "some_workflow",
            "is_preset": True,
        }
        app = _make_test_app(user_repo=user_repo, wf_repo=wf_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.put(
                "/api/v1/users/user@example.com/workflow_setting",
                headers=_user_headers(),
                json={"workflow_definition_id": 2},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow_definition_id"] == 2
        # 新規作成パスが呼ばれることを確認する
        user_repo.create_user_workflow_setting.assert_awaited_once()

    def test_既存のワークフロー設定を上書き更新できること(self):
        """ワークフロー設定が既に存在する場合は update パスが呼ばれることを検証する"""
        user_repo = _make_mock_user_repo()
        user_repo.get_user_workflow_setting.return_value = {
            "username": "testuser",
            "workflow_definition_id": 1,
        }
        user_repo.update_user_workflow_setting.return_value = {
            "username": "testuser",
            "workflow_definition_id": 3,
        }
        wf_repo = _make_mock_wf_repo()
        wf_repo.get_workflow_definition.return_value = {
            "id": 3,
            "name": "another_workflow",
            "is_preset": False,
        }
        app = _make_test_app(user_repo=user_repo, wf_repo=wf_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.put(
                "/api/v1/users/user@example.com/workflow_setting",
                headers=_user_headers(),
                json={"workflow_definition_id": 3},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow_definition_id"] == 3
        # 更新パスが呼ばれることを確認する
        user_repo.update_user_workflow_setting.assert_awaited_once()

    def test_存在しないワークフロー定義IDで404が返ること(self):
        """存在しないワークフロー定義IDを設定しようとすると404が返ることを検証する"""
        wf_repo = _make_mock_wf_repo()
        wf_repo.get_workflow_definition.return_value = None
        app = _make_test_app(wf_repo=wf_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.put(
                "/api/v1/users/user@example.com/workflow_setting",
                headers=_user_headers(),
                json={"workflow_definition_id": 9999},
            )

        assert resp.status_code == 404


# =====================================================================
# ダッシュボード統計エンドポイントのテスト
# =====================================================================


class TestDashboardStats:
    """GET /api/v1/dashboard/stats のテスト"""

    def test_管理者はダッシュボード統計を取得できること(self):
        """管理者権限でダッシュボード統計が取得できることを検証する"""
        task_repo = _make_mock_task_repo()
        task_repo.list_tasks.return_value = []
        app = _make_test_app(task_repo=task_repo)

        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        # ダッシュボードが実行する3つのSQLクエリの結果を定義する:
        # 1. SELECT COUNT(*) FROM users
        # 2. SELECT COUNT(*) FROM tasks WHERE status='running'
        # 3. SELECT SUM(*) FROM token_usage WHERE ...（今月分）
        mock_user_count = {"cnt": 5}
        mock_running_task_count = {"cnt": 2}
        mock_token_usage = {
            "prompt_tokens": 1000,
            "completion_tokens": 500,
            "total_tokens": 1500,
        }
        mock_conn.fetchrow = AsyncMock(
            side_effect=[
                mock_user_count,
                mock_running_task_count,
                mock_token_usage,
            ]
        )
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}),
            patch.object(api_module, "get_pool", AsyncMock(return_value=mock_pool)),
        ):
            client = TestClient(app)
            resp = client.get("/api/v1/dashboard/stats", headers=_admin_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert data["user_count"] == 5
        assert data["running_task_count"] == 2
        assert "monthly_token_usage" in data
        assert "recent_tasks" in data

    def test_一般ユーザーはダッシュボード統計を取得できないこと(self):
        """一般ユーザーがGET /api/v1/dashboard/statsにアクセスすると403が返ることを検証する"""
        app = _make_test_app()

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.get("/api/v1/dashboard/stats", headers=_user_headers())

        assert resp.status_code == 403


# =====================================================================
# トークン使用量統計エンドポイントのテスト
# =====================================================================


class TestTokenStatistics:
    """GET /api/v1/statistics/tokens のテスト"""

    def test_管理者はトークン統計を取得できること(self):
        """管理者権限でトークン統計が取得できることを検証する"""
        app = _make_test_app()

        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(
            return_value=[
                {
                    "username": "testuser",
                    "call_count": 10,
                    "prompt_tokens": 500,
                    "completion_tokens": 300,
                    "total_tokens": 800,
                },
            ]
        )
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}),
            patch.object(api_module, "get_pool", AsyncMock(return_value=mock_pool)),
        ):
            client = TestClient(app)
            resp = client.get("/api/v1/statistics/tokens", headers=_admin_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert "period_days" in data
        assert "stats" in data
        assert len(data["stats"]) == 1
        assert data["stats"][0]["username"] == "user@example.com"

    def test_一般ユーザーはトークン統計を取得できないこと(self):
        """一般ユーザーがGET /api/v1/statistics/tokensにアクセスすると403が返ることを検証する"""
        app = _make_test_app()

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.get("/api/v1/statistics/tokens", headers=_user_headers())

        assert resp.status_code == 403

    def test_usernameフィルタが動作すること(self):
        """usernameクエリパラメータでフィルタリングできることを検証する"""
        app = _make_test_app()

        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}),
            patch.object(api_module, "get_pool", AsyncMock(return_value=mock_pool)),
        ):
            client = TestClient(app)
            resp = client.get(
                "/api/v1/statistics/tokens?username=testuser",
                headers=_admin_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["username_filter"] == "user@example.com"


# =====================================================================
# ワークフロー定義エンドポイントのテスト
# =====================================================================


class TestWorkflowDefinitions:
    """ワークフロー定義エンドポイントのテスト"""

    def test_認証済みユーザーは定義一覧を取得できること(self):
        """認証済みユーザーがGET /api/v1/workflow_definitionsにアクセスできることを検証する"""
        wf_repo = _make_mock_wf_repo()
        wf_repo.list_workflow_definitions.return_value = [
            {
                "id": 1,
                "name": "standard_mr_processing",
                "display_name": "標準MR処理",
                "description": "テスト定義",
                "is_preset": True,
                "created_by": None,
                "graph_definition": {},
                "agent_definition": {},
                "prompt_definition": {},
                "version": "1.0.0",
                "is_active": True,
                "created_at": None,
                "updated_at": None,
            }
        ]
        app = _make_test_app(wf_repo=wf_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.get("/api/v1/workflow_definitions", headers=_user_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["name"] == "standard_mr_processing"

    def test_システムプリセットは削除できないこと(self):
        """is_preset=Trueの定義を削除しようとすると403が返ることを検証する"""
        wf_repo = _make_mock_wf_repo()
        wf_repo.get_workflow_definition.return_value = {
            "id": 1,
            "name": "standard_mr_processing",
            "is_preset": True,
        }
        app = _make_test_app(wf_repo=wf_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.delete(
                "/api/v1/workflow_definitions/1", headers=_user_headers()
            )

        assert resp.status_code == 403

    def test_存在しない定義の取得で404が返ること(self):
        """存在しないワークフロー定義IDでGETすると404が返ることを検証する"""
        wf_repo = _make_mock_wf_repo()
        wf_repo.get_workflow_definition.return_value = None
        app = _make_test_app(wf_repo=wf_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.get(
                "/api/v1/workflow_definitions/9999", headers=_user_headers()
            )

        assert resp.status_code == 404

    def test_システムプリセットは更新できないこと(self):
        """is_preset=Trueの定義を更新しようとすると403が返ることを検証する"""
        wf_repo = _make_mock_wf_repo()
        wf_repo.get_workflow_definition.return_value = {
            "id": 1,
            "name": "standard_mr_processing",
            "is_preset": True,
        }
        app = _make_test_app(wf_repo=wf_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.put(
                "/api/v1/workflow_definitions/1",
                headers=_user_headers(),
                json={"display_name": "変更試み"},
            )

        assert resp.status_code == 403

    def test_ユーザー作成のワークフロー定義を正常に作成できること(self):
        """認証済みユーザーがワークフロー定義を新規作成できることを検証する"""
        wf_repo = _make_mock_wf_repo()
        wf_repo.create_workflow_definition.return_value = {
            "id": 3,
            "name": "custom_workflow",
            "display_name": "カスタムワークフロー",
            "description": "テスト",
            "is_preset": False,
            "created_by": "user@example.com",
            "graph_definition": {"nodes": []},
            "agent_definition": {},
            "prompt_definition": {},
            "version": "1.0.0",
            "is_active": True,
            "created_at": None,
            "updated_at": None,
        }
        app = _make_test_app(wf_repo=wf_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/workflow_definitions",
                headers=_user_headers(),
                json={
                    "name": "custom_workflow",
                    "display_name": "カスタムワークフロー",
                    "description": "テスト",
                    "graph_definition": {"nodes": []},
                    "agent_definition": {},
                    "prompt_definition": {},
                },
            )

        assert resp.status_code == 201


# =====================================================================
# パスワード変更エンドポイントのテスト
# =====================================================================


class TestChangePassword:
    """PUT /api/v1/users/{username}/password のテスト"""

    def test_ユーザーは自分のパスワードを変更できること(self):
        """一般ユーザーが自分のパスワードを変更できることを検証する"""
        current_password = "OldPass1!"
        hashed = hash_password(current_password)
        user_repo = _make_mock_user_repo()
        user_repo.get_user_by_username.return_value = {
            "password_hash": hashed,
            "role": "user",
            "is_active": True,
        }
        app = _make_test_app(user_repo=user_repo)

        # get_pool の DB アクセスをモック化する
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}),
            patch.object(api_module, "get_pool", AsyncMock(return_value=mock_pool)),
        ):
            client = TestClient(app)
            resp = client.put(
                "/api/v1/users/user@example.com/password",
                headers=_user_headers(),
                json={
                    "current_password": current_password,
                    "new_password": "NewPass1!",
                },
            )

        assert resp.status_code == 200

    def test_一般ユーザーが他ユーザーのパスワードを変更できないこと(self):
        """一般ユーザーが他ユーザーのパスワードを変更しようとすると403が返ることを検証する"""
        user_repo = _make_mock_user_repo()
        app = _make_test_app(user_repo=user_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.put(
                "/api/v1/users/other@example.com/password",
                headers=_user_headers(),
                json={
                    "current_password": "SomePass1!",
                    "new_password": "NewPass1!",
                },
            )

        assert resp.status_code == 403

    def test_弱い新パスワードでバリデーションエラーが返ること(self):
        """新パスワードが要件を満たさない場合に422が返ることを検証する"""
        app = _make_test_app()

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.put(
                "/api/v1/users/user@example.com/password",
                headers=_user_headers(),
                json={
                    "current_password": "OldPass1!",
                    "new_password": "weak",  # 要件を満たさないパスワード
                },
            )

        assert resp.status_code == 422

    def test_管理者は自身の現在パスワードなしで他ユーザーパスワードを変更できること(
        self,
    ):
        """管理者が current_password なしで他ユーザーのパスワードを変更できることを検証する"""
        user_repo = _make_mock_user_repo()
        user_repo.get_user_by_username.return_value = {
            "password_hash": hash_password("OldPass1!"),
            "role": "user",
            "is_active": True,
        }
        app = _make_test_app(user_repo=user_repo)

        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}),
            patch.object(api_module, "get_pool", AsyncMock(return_value=mock_pool)),
        ):
            client = TestClient(app)
            resp = client.put(
                "/api/v1/users/user@example.com/password",
                headers=_admin_headers(),
                json={
                    # current_password なし（管理者代理変更）
                    "new_password": "NewPass1!",
                },
            )

        assert resp.status_code == 200


# =====================================================================
# 圧縮設定バリデーションのテスト
# =====================================================================


class TestCompressionValidation:
    """圧縮設定バリデーションのテスト（§6.1の仕様に基づく）"""

    def test_token_threshold範囲外で422が返ること(self):
        """token_thresholdが1,000〜150,000の範囲外の場合に422が返ることを検証する"""
        app = _make_test_app()

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/users",
                headers=_admin_headers(),
                json={
                    "username": "New User",
                    "password": "SecurePass1!",
                    "role": "user",
                    "token_threshold": 500,
                },
            )

        assert resp.status_code == 422

    def test_token_threshold上限超過で422が返ること(self):
        """token_thresholdが150,000を超える場合に422が返ることを検証する"""
        app = _make_test_app()

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/users",
                headers=_admin_headers(),
                json={
                    "username": "New User",
                    "password": "SecurePass1!",
                    "role": "user",
                    "token_threshold": 200000,
                },
            )

        assert resp.status_code == 422

    def test_keep_recent_messages範囲外で422が返ること(self):
        """keep_recent_messagesが1〜50の範囲外の場合に422が返ることを検証する"""
        app = _make_test_app()

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/users",
                headers=_admin_headers(),
                json={
                    "username": "New User",
                    "password": "SecurePass1!",
                    "role": "user",
                    "keep_recent_messages": 100,
                },
            )

        assert resp.status_code == 422

    def test_min_to_compress範囲外で422が返ること(self):
        """min_to_compressが1〜20の範囲外の場合に422が返ることを検証する"""
        app = _make_test_app()

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/users",
                headers=_admin_headers(),
                json={
                    "username": "New User",
                    "password": "SecurePass1!",
                    "role": "user",
                    "min_to_compress": 30,
                },
            )

        assert resp.status_code == 422

    def test_min_compression_ratio範囲外で422が返ること(self):
        """min_compression_ratioが0.5〜0.95の範囲外の場合に422が返ることを検証する"""
        app = _make_test_app()

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/users",
                headers=_admin_headers(),
                json={
                    "username": "New User",
                    "password": "SecurePass1!",
                    "role": "user",
                    "min_compression_ratio": 0.1,
                },
            )

        assert resp.status_code == 422

    def test_min_compression_ratio上限超過で422が返ること(self):
        """min_compression_ratioが0.95を超える場合に422が返ることを検証する"""
        app = _make_test_app()

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/users",
                headers=_admin_headers(),
                json={
                    "username": "New User",
                    "password": "SecurePass1!",
                    "role": "user",
                    "min_compression_ratio": 0.99,
                },
            )

        assert resp.status_code == 422

    def test_有効な圧縮設定で作成できること(self):
        """範囲内の圧縮設定でユーザーが作成できることを検証する"""
        user_repo = _make_mock_user_repo()
        user_repo.create_user.return_value = {
            "username": "New User",
            "role": "user",
            "is_active": True,
            "created_at": None,
        }
        user_repo.create_user_config.return_value = {}
        app = _make_test_app(user_repo=user_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/users",
                headers=_admin_headers(),
                json={
                    "username": "New User",
                    "password": "SecurePass1!",
                    "role": "user",
                    "token_threshold": 50000,
                    "keep_recent_messages": 20,
                    "min_to_compress": 10,
                    "min_compression_ratio": 0.8,
                },
            )

        assert resp.status_code == 201


# =====================================================================
# タスク実行履歴エンドポイントのテスト
# =====================================================================


class TestTaskHistory:
    """GET /api/v1/tasks のテスト"""

    def test_管理者はタスク一覧を取得できること(self):
        """管理者権限でタスク一覧が取得できることを検証する"""
        task_repo = _make_mock_task_repo()
        task_repo.list_tasks.return_value = [
            {
                "uuid": "uuid-001",
                "task_type": "issue_to_mr",
                "task_identifier": "#42",
                "repository": "owner/repo",
                "username": "testuser",
                "status": "completed",
                "created_at": None,
                "completed_at": None,
            }
        ]
        app = _make_test_app(task_repo=task_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.get("/api/v1/tasks", headers=_admin_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert "tasks" in data
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["uuid"] == "uuid-001"

    def test_一般ユーザーはタスク一覧を取得できないこと(self):
        """一般ユーザーがGET /api/v1/tasksにアクセスすると403が返ることを検証する"""
        app = _make_test_app()

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.get("/api/v1/tasks", headers=_user_headers())

        assert resp.status_code == 403

    def test_ステータスフィルタが動作すること(self):
        """status クエリパラメータでフィルタリングできることを検証する"""
        task_repo = _make_mock_task_repo()
        task_repo.list_tasks.return_value = []
        app = _make_test_app(task_repo=task_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.get("/api/v1/tasks?status=running", headers=_admin_headers())

        assert resp.status_code == 200
        task_repo.list_tasks.assert_awaited_once()
        call_kwargs = task_repo.list_tasks.call_args.kwargs
        assert call_kwargs.get("status") == "running"

    def test_ページネーションが動作すること(self):
        """page・per_page クエリパラメータでページネーションできることを検証する"""
        task_repo = _make_mock_task_repo()
        task_repo.list_tasks.return_value = []
        app = _make_test_app(task_repo=task_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.get(
                "/api/v1/tasks?page=2&per_page=10", headers=_admin_headers()
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 2
        assert data["per_page"] == 10


# =====================================================================
# トークンリフレッシュエンドポイントのテスト
# =====================================================================


class TestAuthRefresh:
    """POST /api/v1/auth/refresh のテスト"""

    def test_有効なトークンで新しいトークンを取得できること(self):
        """有効な Bearer トークンで新しい JWT が発行されることを検証する"""
        user_repo = _make_mock_user_repo()
        user_repo.get_user_by_username.return_value = {
            "username": "Test User",
            "role": "user",
            "is_active": True,
        }
        app = _make_test_app(user_repo=user_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/auth/refresh",
                headers=_user_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_無効化されたアカウントでリフレッシュ失敗すること(self):
        """is_active=Falseのアカウントでリフレッシュすると401が返ることを検証する"""
        user_repo = _make_mock_user_repo()
        user_repo.get_user_by_username.return_value = {
            "role": "user",
            "is_active": False,
        }
        app = _make_test_app(user_repo=user_repo)

        with patch.dict(os.environ, {"JWT_SECRET_KEY": _TEST_JWT_SECRET}):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/auth/refresh",
                headers=_user_headers(),
            )

        assert resp.status_code == 401

    def test_認証なしでリフレッシュできないこと(self):
        """Bearer トークンなしでリフレッシュすると401/403が返ることを検証する"""
        app = _make_test_app()
        client = TestClient(app)
        resp = client.post("/api/v1/auth/refresh")
        assert resp.status_code in (401, 403)
