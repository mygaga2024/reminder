"""多账号模块测试（账号、会话、数据隔离）"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import datetime
import pytest

from app.config import TZ_ENV
from app import users


def make_db():
    return {
        "reminders": [],
        "settings": {
            "language": "zh",
            "dark_mode": True,
            "webhooks": {"wecom": "https://legacy.example.com", "dingtalk": "", "lark": ""}
        },
        "users": {}
    }


class TestPassword:
    def test_hash_and_verify_roundtrip(self):
        user = {}
        user["password_hash"], user["salt"] = users.hash_password("secret123")
        user["iterations"] = users.PASSWORD_ITERATIONS
        assert users.verify_password("secret123", user) is True
        assert users.verify_password("wrong-pass", user) is False

    def test_hash_uses_random_salt(self):
        first, salt_a = users.hash_password("secret123")
        second, salt_b = users.hash_password("secret123")
        assert salt_a != salt_b
        assert first != second

    def test_verify_rejects_incomplete_record(self):
        assert users.verify_password("secret123", {}) is False
        assert users.verify_password("secret123", None) is False

    def test_validate_username_rules(self):
        assert users.validate_username("") is not None
        assert users.validate_username("a") is not None
        assert users.validate_username("bad name") is not None
        assert users.validate_username("小明") is None
        assert users.validate_username("user_01") is None

    def test_validate_password_rules(self):
        assert users.validate_password("123") is not None
        assert users.validate_password("123456", "654321") is not None
        assert users.validate_password("123456") is None


class TestAccounts:
    def test_create_user_defaults(self):
        db = make_db()
        user, error = users.create_user(db, "alice", "secret123")
        assert error is None
        assert user["username"] == "alice"
        assert user["reminders"] == []
        assert user["settings"]["webhooks"]["wecom"] == ""
        assert users.account_count(db) == 1
        assert users.has_accounts(db) is True

    def test_duplicate_username_rejected(self):
        db = make_db()
        users.create_user(db, "alice", "secret123")
        user, error = users.create_user(db, "alice", "another123")
        assert user is None
        assert "已被注册" in error

    def test_authenticate_success_and_failure(self):
        db = make_db()
        users.create_user(db, "alice", "secret123")
        assert users.authenticate(db, "alice", "secret123") == ("alice", None)
        username, error = users.authenticate(db, "alice", "bad-pass")
        assert username is None
        assert error == "账号或密码错误"

    def test_login_lockout_after_repeated_failures(self):
        db = make_db()
        users.create_user(db, "alice", "secret123")
        for _ in range(users.LOGIN_MAX_FAILURES):
            users.authenticate(db, "alice", "bad-pass")
        username, error = users.authenticate(db, "alice", "secret123")
        assert username is None
        assert "登录失败次数过多" in error
        users.clear_login_failures("alice")

    def test_change_password(self):
        db = make_db()
        users.create_user(db, "alice", "secret123")
        assert users.change_password(db, "alice", "wrong", "newpass123") == "原密码不正确"
        assert users.change_password(db, "alice", "secret123", "newpass123") is None
        assert users.authenticate(db, "alice", "newpass123") == ("alice", None)


class TestNickname:
    """账号昵称（仅用于页面显示，不影响登录用户名）"""

    def test_nickname_defaults_to_none(self):
        db = make_db()
        users.create_user(db, "alice", "secret123")
        assert users.get_nickname(db, "alice") is None
        assert users.public_user_info(db, "alice")["nickname"] is None

    def test_set_nickname_trims_and_reads_back(self):
        db = make_db()
        users.create_user(db, "alice", "secret123")
        nickname, error = users.set_nickname(db, "alice", "  小明  ")
        assert error is None
        assert nickname == "小明"
        assert users.get_nickname(db, "alice") == "小明"

    def test_clear_nickname_restores_username(self):
        db = make_db()
        users.create_user(db, "alice", "secret123")
        users.set_nickname(db, "alice", "小明")

        nickname, error = users.set_nickname(db, "alice", "   ")

        assert error is None
        assert nickname is None
        assert users.get_nickname(db, "alice") is None
        assert "nickname" not in db["users"]["alice"]

    def test_nickname_length_limit(self):
        db = make_db()
        users.create_user(db, "alice", "secret123")
        assert users.set_nickname(db, "alice", "长" * users.NICKNAME_MAX_LENGTH)[1] is None
        assert users.set_nickname(db, "alice", "长" * (users.NICKNAME_MAX_LENGTH + 1))[1] is not None

    def test_nickname_rejects_control_characters(self):
        db = make_db()
        users.create_user(db, "alice", "secret123")
        assert users.set_nickname(db, "alice", "小\n明")[1] is not None
        assert users.set_nickname(db, "alice", "小\t明")[1] is not None

    def test_nickname_rejects_non_string(self):
        db = make_db()
        users.create_user(db, "alice", "secret123")
        assert users.set_nickname(db, "alice", None)[1] is not None
        assert users.set_nickname(db, "alice", 123)[1] is not None

    def test_nickname_isolated_per_account(self):
        db = make_db()
        users.create_user(db, "alice", "secret123")
        users.create_user(db, "bob", "secret123")
        users.set_nickname(db, "alice", "小明")

        assert users.get_nickname(db, "alice") == "小明"
        assert users.get_nickname(db, "bob") is None

    def test_set_nickname_unknown_account(self):
        db = make_db()
        assert users.set_nickname(db, "nobody", "小明") == (None, "账号不存在")


class TestSessions:
    def test_session_lifecycle(self):
        db = make_db()
        users.create_user(db, "alice", "secret123")
        token = users.create_session(db, "alice")
        assert users.resolve_session(db, token) == "alice"
        assert users.resolve_session(db, "invalid-token") is None
        assert users.destroy_session(db, token) is True
        assert users.resolve_session(db, token) is None

    def test_token_stored_hashed(self):
        db = make_db()
        users.create_user(db, "alice", "secret123")
        token = users.create_session(db, "alice")
        assert token not in db["sessions"]

    def test_expired_session_purged(self):
        db = make_db()
        users.create_user(db, "alice", "secret123")
        token = users.create_session(db, "alice", days=-1)
        assert users.resolve_session(db, token) is None
        assert users.purge_expired_sessions(db) == 0

    def test_destroy_user_sessions(self):
        db = make_db()
        users.create_user(db, "alice", "secret123")
        token_a = users.create_session(db, "alice")
        token_b = users.create_session(db, "alice")
        assert users.destroy_user_sessions(db, "alice") == 2
        assert users.resolve_session(db, token_a) is None
        assert users.resolve_session(db, token_b) is None

    def test_session_invalid_when_account_gone(self):
        db = make_db()
        users.create_user(db, "alice", "secret123")
        token = users.create_session(db, "alice")
        db["users"].pop("alice")
        assert users.resolve_session(db, token) is None


class TestScope:
    def test_user_scope_isolated(self):
        db = make_db()
        users.create_user(db, "alice", "secret123")
        users.create_user(db, "bob", "secret123")
        users.user_scope(db, "alice")["reminders"].append({"id": "r1", "title": "alice 的任务"})

        assert len(users.user_scope(db, "alice")["reminders"]) == 1
        assert users.user_scope(db, "bob")["reminders"] == []
        assert users.user_scope(db, "nobody") is None

    def test_rebuild_flat_reminders_merges_scopes(self):
        db = make_db()
        db["reminders"] = [{"id": "legacy-1", "title": "遗留任务"}]
        users.create_user(db, "alice", "secret123")
        users.user_scope(db, "alice")["reminders"].append({"id": "r1", "title": "alice 的任务"})

        merged = users.rebuild_flat_reminders(db)
        assert {r["id"] for r in merged} == {"legacy-1", "r1"}
        assert all(r.get("user") is None for r in merged if r["id"] == "legacy-1")
        assert [r["user"] for r in merged if r["id"] == "r1"] == ["alice"]

    def test_remove_reminder_removes_from_owner(self):
        db = make_db()
        users.create_user(db, "alice", "secret123")
        users.user_scope(db, "alice")["reminders"].append({"id": "r1", "title": "alice 的任务"})
        users.rebuild_flat_reminders(db)

        assert users.remove_reminder(db, "r1") == 2
        assert users.user_scope(db, "alice")["reminders"] == []
        assert db["reminders"] == []

    def test_owned_settings_uses_owner_webhooks(self):
        db = make_db()
        users.create_user(db, "alice", "secret123")
        users.user_scope(db, "alice")["settings"]["webhooks"]["wecom"] = "https://alice.example.com"

        owner_settings = users.owned_settings(db, {"id": "r1", "user": "alice"})
        assert owner_settings["webhooks"]["wecom"] == "https://alice.example.com"
        assert users.owned_settings(db, {"id": "legacy"})["webhooks"]["wecom"] == "https://legacy.example.com"

    def test_public_user_info_counts(self):
        db = make_db()
        users.create_user(db, "alice", "secret123")
        scope = users.user_scope(db, "alice")
        scope["reminders"].append({"id": "r1", "status": "pending"})
        scope["reminders"].append({"id": "r2", "status": "completed"})

        info = users.public_user_info(db, "alice")
        assert info["reminders"] == 2
        assert info["pending"] == 1
        assert "password_hash" not in info


class TestLegacyMigration:
    def test_claim_legacy_data(self):
        db = make_db()
        db["reminders"] = [
            {"id": "legacy-1", "title": "遗留任务 1"},
            {"id": "legacy-2", "title": "遗留任务 2"}
        ]
        users.create_user(db, "alice", "secret123")

        claimed = users.claim_legacy_data(db, "alice")

        assert claimed == 2
        assert len(users.user_scope(db, "alice")["reminders"]) == 2
        assert users.legacy_stats(db)["reminders"] == 0
        assert users.user_scope(db, "alice")["settings"]["webhooks"]["wecom"] == "https://legacy.example.com"

    def test_claim_legacy_without_data(self):
        db = make_db()
        users.create_user(db, "alice", "secret123")
        assert users.claim_legacy_data(db, "alice") == 0

    def test_legacy_stats_counts_untagged_only(self):
        db = make_db()
        users.create_user(db, "alice", "secret123")
        db["reminders"] = [{"id": "legacy-1", "title": "遗留"}]
        users.user_scope(db, "alice")["reminders"].append({"id": "r1", "title": "alice", "user": "alice"})
        logs = [{"id": "log-1"}, {"id": "log-2", "user": "alice"}]

        stats = users.legacy_stats(db, logs)
        assert stats["reminders"] == 1
        assert stats["logs"] == 1

    def test_migrate_db_normalizes_and_purges(self):
        db = make_db()
        db["users"] = {
            "alice": {"username": "alice"},
            "broken": "not-a-dict"
        }
        db["sessions"] = {
            "expired": {
                "username": "alice",
                "expires_at": (datetime.datetime.now(TZ_ENV) - datetime.timedelta(days=1)).isoformat()
            }
        }
        db["reminders"] = [{"id": "legacy-1", "title": "遗留"}]

        info = users.migrate_db(db)

        assert info["accounts"] == 0
        assert info["purged_sessions"] == 1
        assert info["legacy_reminders"] == 1
        assert db["users"]["alice"]["reminders"] == []
        assert "sessions" in db
