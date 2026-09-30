"""停用「一键更新」（`WB_DISABLE_UPDATE=1`）。

动机：管理端绑到自有仓库、但那里还没有 Release 时，版本检查与一键更新会一直失败；
或者部署方根本不想让面板具备自我更新能力。此时应当**明确停用**，而不是留下一个每次
都会失败/空转的入口。

锁定的性质：

  · 一键更新动作由**服务端**拒绝（409）——不依赖前端是否把按钮藏起来，
    否则「停用」只是一层可以绕过的皮；
  · 版本检查**不发网络请求**（GitHub 未认证配额有限），直接返回 disabled 标记，
    免得界面上一片红色报错；
  · 状态接口暴露 `update_disabled`，界面据此隐藏入口并说明原因。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from server import config, db, security  # noqa: E402
from server.services import updater  # noqa: E402


def _patch_disabled(value: bool):
    """config.DISABLE_UPDATE 是新加的开关，用 create=True 让 RED 阶段是断言失败而不是报错。"""
    return mock.patch.object(config, 'DISABLE_UPDATE', value, create=True)


class DisableUpdateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        d = Path(cls._tmp.name)
        cls._orig = (config.DB_PATH, config.USERS_FILE, config.STATIC_DIR, config.DATA_DIR)
        config.DB_PATH = d / 'disable-update.db'
        config.USERS_FILE = d / 'users.json'
        config.STATIC_DIR = d / 'no-static'
        config.DATA_DIR = d / 'data'
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        config.USERS_FILE.write_text(json.dumps({
            'secret': 'S' * 64,
            'users': [{'username': 'admin', 'role': 'admin',
                       'pwd_hash': security.make_hash('admin-pw')}],
            'api_keys': [],
        }), encoding='utf-8')
        db._conn = None
        db.connect()
        from server.main import app
        cls.c = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        if db._conn is not None:
            db._conn.close()
        db._conn = None
        (config.DB_PATH, config.USERS_FILE, config.STATIC_DIR,
         config.DATA_DIR) = cls._orig
        cls._tmp.cleanup()

    def setUp(self) -> None:
        security._fail.clear()
        security._user_fail.clear()
        self.c.cookies.clear()
        r = self.c.post('/api/login', json={'username': 'admin', 'password': 'admin-pw'})
        self.assertEqual(r.status_code, 200, r.text)

    def test_update_action_is_refused_when_disabled(self) -> None:
        # 把更新脚本指到不存在的路径：即使「停用」这道闸门将来被改坏，本用例也
        # **不可能真的拉起一次更新**（那会去改仓库/打 GitHub）。这样断言 409 里的
        # 文案就只可能来自停用分支本身。
        missing = Path('/nonexistent/deploy/update.py')
        with _patch_disabled(True), \
                mock.patch.object(updater, '_updater_script', lambda: missing):
            r = self.c.post('/api/system/update', json={'target': 'manager'})
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn('停用', r.json().get('detail', ''))

    def test_check_update_makes_no_network_call_when_disabled(self) -> None:
        def _boom(*a, **k):  # noqa: ANN002, ANN003
            raise AssertionError('停用后不应再去检测版本（会打 GitHub API）')

        with _patch_disabled(True), mock.patch.object(updater, 'check_updates', _boom):
            r = self.c.get('/api/system/check-update')
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIs(body.get('disabled'), True)
        self.assertIs(body.get('has_any'), False)

    def test_status_exposes_the_flag(self) -> None:
        with _patch_disabled(True):
            on = self.c.get('/api/system/update-status').json()
        with _patch_disabled(False):
            off = self.c.get('/api/system/update-status').json()
        self.assertIs(on.get('update_disabled'), True)
        self.assertIs(off.get('update_disabled'), False)


if __name__ == '__main__':
    unittest.main()
