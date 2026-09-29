"""账号导入导出（备份 / 恢复）。

## 需求现场

维护者要给自己的一批账号做备份：在账号列表里**勾选任意几个账号**（可跨分组）
导出成一个文件；换机、重装面板或灾难恢复时，把文件导回来就能继续用。

## 这里钉住的几条（写测试前先想清楚，后面每条都有用例）

  · 导出**逐字段**保留原始账号文件——尤其 `device_token` 这类设备风控凭据。
    它不在上游 account/auth 的常规字段里，若照着已知字段重组就会**静默丢掉**，
    表现为换机后账号「能用但风控形态降级」，很难查。
  · 导出记录每个账号来自哪个**分组**：跨分组导出后，导入才能落回正确的位置。
  · 禁用账号（`workbuddy-<uid>.json.disabled`）导出后**仍是禁用态**。
  · 备注按 uid 一起走（备注存在面板库里，不在上游账号文件里）。
  · 导入是**增量**：已存在的按 skip / overwrite 处理；非法条目不阻断其余。
  · 文件含完整凭据，所以只有管理员能导出/导入，且两件事都留审计。
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# 导入 server.* 之前先钉住数据目录：下面的 HTTP 用例会 import server.main，
# 而 config 的默认路径由 WB_DATA_DIR 算出。不设置的话会落到仓库工作目录上。
os.environ.setdefault('WB_DATA_DIR', tempfile.mkdtemp(prefix='wb-acct-http-'))

from server import config, db, upstreamsvc  # noqa: E402
from server.routers import accounts as A  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from unittest import mock  # noqa: E402

U1 = 'exp00001-0000-0000-0000-000000000001'
U2 = 'exp00002-0000-0000-0000-000000000002'


def _b64(obj: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip('=')


def _write_auth(d: Path, uid: str, nickname: str, *, device_token: str = '',
                realm: str = 'cn', name: str | None = None) -> str:
    """落一个与上游同构的账号文件，返回文件名。"""
    d.mkdir(parents=True, exist_ok=True)
    exp = int(time.time()) + 86400 * 30
    token = f"{_b64({'alg': 'none'})}.{_b64({'iat': int(time.time()), 'exp': exp, 'uid': uid})}.sig"
    payload = {
        'account': {'uid': uid, 'nickname': nickname, 'enterpriseId': 'e'},
        'auth': {'accessToken': token, 'refreshToken': 'rt-' + uid, 'expiresAt': exp,
                 'domain': 'copilot.tencent.com', 'realm': realm},
    }
    if device_token:
        payload['device_token'] = device_token
    fname = name or f'workbuddy-{uid}.json'
    (d / fname).write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return fname


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._db, self._auth = config.DB_PATH, config.AUTH_DIR
        config.DB_PATH = root / 'manager.db'
        config.AUTH_DIR = root / 'auths'
        config.AUTH_DIR.mkdir(parents=True, exist_ok=True)
        db._conn = None
        db.connect()

    def tearDown(self) -> None:
        try:
            if db._conn is not None:
                db._conn.close()
        except Exception:  # noqa: BLE001
            pass
        db._conn = None
        config.DB_PATH, config.AUTH_DIR = self._db, self._auth
        try:
            self._tmp.cleanup()
        except PermissionError:
            pass


class ExportTest(_Case):
    def test_exports_selected_account_fields(self) -> None:
        f1 = _write_auth(config.AUTH_DIR, U1, '甲', device_token='dev-甲')
        f2 = _write_auth(config.AUTH_DIR, U2, '乙')
        db.set_account_note(U2, '备用号')
        (config.AUTH_DIR / f2).rename(config.AUTH_DIR / (f2 + '.disabled'))

        out = asyncio.run(A.account_export(
            {'items': [
                {'upstream_id': None, 'filename': f1},
                {'upstream_id': None, 'filename': f2 + '.disabled'},
            ]},
            user={'role': 'admin'}))

        self.assertEqual(out['format'], 'workbuddy-manager/accounts-backup')
        self.assertEqual(out['version'], 1)
        accts = {a['uid']: a for a in out['accounts']}
        self.assertEqual(set(accts), {U1, U2})

        self.assertEqual(accts[U1]['nickname'], '甲')
        self.assertFalse(accts[U1]['disabled'])
        self.assertEqual(accts[U1]['realm'], 'cn')
        # 关键：device_token 逐字段保留
        self.assertEqual(accts[U1]['content']['device_token'], 'dev-甲')
        self.assertTrue(accts[U1]['content']['auth']['accessToken'])

        self.assertTrue(accts[U2]['disabled'])
        self.assertEqual(accts[U2]['note'], '备用号')

    def test_records_source_group(self) -> None:
        g = upstreamsvc.create_upstream('B组', 'http://b.example:7863',
                                        auth_dir=str(config.AUTH_DIR / 'b'))
        f1 = _write_auth(config.AUTH_DIR / 'b', U1, '甲')

        out = asyncio.run(A.account_export(
            {'items': [{'upstream_id': g['id'], 'filename': f1}]},
            user={'role': 'admin'}))

        entry = out['accounts'][0]
        self.assertEqual(entry['group']['id'], g['id'])
        self.assertEqual(entry['group']['name'], 'B组')

    def test_disabled_detected_from_disk_not_stale_name(self) -> None:
        """界面持有旧文件名（刚停用、心跳未刷新）时也要导出成禁用态。"""
        f1 = _write_auth(config.AUTH_DIR, U1, '甲')
        (config.AUTH_DIR / f1).rename(config.AUTH_DIR / (f1 + '.disabled'))

        out = asyncio.run(A.account_export(
            {'items': [{'upstream_id': None, 'filename': f1}]},  # 传的是旧名（无后缀）
            user={'role': 'admin'}))

        self.assertTrue(out['accounts'][0]['disabled'])


# ── 导入 ────────────────────────────────────────────────────────────────

def _entry(uid: str, nickname: str, *, device_token: str = '', disabled: bool = False,
           group: dict | None = None, note: str = '', realm: str = 'cn',
           access_token: str | None = None) -> dict:
    content = {
        'account': {'uid': uid, 'nickname': nickname, 'enterpriseId': 'e'},
        'auth': {'accessToken': access_token if access_token is not None else 'tok-' + uid,
                 'refreshToken': 'rt-' + uid, 'expiresAt': int(time.time()) + 999,
                 'domain': 'copilot.tencent.com', 'realm': realm},
    }
    if device_token:
        content['device_token'] = device_token
    return {'uid': uid, 'nickname': nickname, 'realm': realm, 'disabled': disabled,
            'group': group or {'id': None, 'name': '默认上游'},
            'note': note, 'content': content}


def _bundle(entries: list[dict]) -> dict:
    return {'format': 'workbuddy-manager/accounts-backup', 'version': 1,
            'exported_at': '2026-09-29T00:00:00+08:00', 'accounts': entries}


class ImportTest(_Case):
    def _imp(self, body: dict) -> tuple[dict, mock.Mock]:
        """调用导入端点，并把「触发上游重载」替换成 Mock（不让测试碰上游）。"""
        with mock.patch.object(A.reload, 'request_reload_or_restart') as m:
            out = asyncio.run(A.account_import(body, user={'role': 'admin'}))
        return out, m

    def test_writes_new_accounts_verbatim(self) -> None:
        out, _ = self._imp({'bundle': _bundle([_entry(U1, '甲', device_token='dev-甲')])})
        self.assertEqual(out['imported'], 1)
        p = config.AUTH_DIR / f'workbuddy-{U1}.json'
        raw = json.loads(p.read_text(encoding='utf-8'))
        self.assertEqual(raw['device_token'], 'dev-甲')          # 未知字段保留
        self.assertEqual(raw['auth']['accessToken'], 'tok-' + U1)
        self.assertEqual(raw['account']['nickname'], '甲')

    def test_disabled_entry_stays_disabled(self) -> None:
        self._imp({'bundle': _bundle([_entry(U2, '乙', disabled=True)])})
        self.assertTrue((config.AUTH_DIR / f'workbuddy-{U2}.json.disabled').exists())
        self.assertFalse((config.AUTH_DIR / f'workbuddy-{U2}.json').exists())

    def test_skips_existing_by_default(self) -> None:
        _write_auth(config.AUTH_DIR, U1, '旧的')
        out, _ = self._imp({'bundle': _bundle([_entry(U1, '新的')])})
        self.assertEqual((out['imported'], out['skipped'], out['overwritten']), (0, 1, 0))
        raw = json.loads((config.AUTH_DIR / f'workbuddy-{U1}.json').read_text(encoding='utf-8'))
        self.assertEqual(raw['account']['nickname'], '旧的')

    def test_overwrites_when_asked(self) -> None:
        _write_auth(config.AUTH_DIR, U1, '旧的')
        out, _ = self._imp({'bundle': _bundle([_entry(U1, '新的')]), 'mode': 'overwrite'})
        self.assertEqual((out['imported'], out['skipped'], out['overwritten']), (0, 0, 1))
        raw = json.loads((config.AUTH_DIR / f'workbuddy-{U1}.json').read_text(encoding='utf-8'))
        self.assertEqual(raw['account']['nickname'], '新的')

    def test_applies_notes(self) -> None:
        self._imp({'bundle': _bundle([_entry(U1, '甲', note='张叔叔')])})
        self.assertEqual(db.account_notes().get(U1), '张叔叔')

    def test_invalid_entries_do_not_block_the_rest(self) -> None:
        bad_uid = _entry('../../evil', '坏')
        bad_tok = _entry(U2, '无令牌', access_token='')
        good = _entry(U1, '好')
        out, _ = self._imp({'bundle': _bundle([bad_uid, bad_tok, good])})
        self.assertEqual(out['imported'], 1)
        self.assertEqual(len(out['failed']), 2)
        self.assertTrue((config.AUTH_DIR / f'workbuddy-{U1}.json').exists())
        # 路径穿越的条目绝不能落盘
        self.assertEqual(list(config.AUTH_DIR.glob('*.json')), [config.AUTH_DIR / f'workbuddy-{U1}.json'])

    def test_rejects_foreign_bundle(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            self._imp({'bundle': {'format': 'something-else', 'version': 1, 'accounts': []}})
        self.assertEqual(ctx.exception.status_code, 400)

    def test_restore_groups_matches_by_name(self) -> None:
        g = upstreamsvc.create_upstream('B组', 'http://b.example:7863',
                                        auth_dir=str(config.AUTH_DIR / 'b'))
        entry = _entry(U1, '甲', group={'id': 999, 'name': 'B组'})
        out, _ = self._imp({'bundle': _bundle([entry]), 'restore_groups': True})
        self.assertEqual(out['imported'], 1)
        self.assertTrue((config.AUTH_DIR / 'b' / f'workbuddy-{U1}.json').exists())
        self.assertFalse((config.AUTH_DIR / f'workbuddy-{U1}.json').exists())

    def test_restore_groups_falls_back_to_target(self) -> None:
        g = upstreamsvc.create_upstream('目标组', 'http://t.example:7863',
                                        auth_dir=str(config.AUTH_DIR / 't'))
        entry = _entry(U1, '甲', group={'id': 1, 'name': '早就删掉的组'})
        out, _ = self._imp({'bundle': _bundle([entry]), 'upstream_id': g['id'],
                            'restore_groups': True})
        self.assertEqual(out['imported'], 1)
        self.assertTrue((config.AUTH_DIR / 't' / f'workbuddy-{U1}.json').exists())


class RoundTripTest(_Case):
    def test_export_then_import_into_new_group(self) -> None:
        f1 = _write_auth(config.AUTH_DIR, U1, '甲', device_token='dev-甲')
        exported = asyncio.run(A.account_export(
            {'items': [{'upstream_id': None, 'filename': f1}]}, user={'role': 'admin'}))
        g = upstreamsvc.create_upstream('新机', 'http://n.example:7863',
                                        auth_dir=str(config.AUTH_DIR / 'new'))
        with mock.patch.object(A.reload, 'request_reload_or_restart'):
            asyncio.run(A.account_import(
                {'bundle': exported, 'upstream_id': g['id']}, user={'role': 'admin'}))
        p = config.AUTH_DIR / 'new' / f'workbuddy-{U1}.json'
        raw = json.loads(p.read_text(encoding='utf-8'))
        self.assertEqual(raw['device_token'], 'dev-甲')
        self.assertEqual(raw['auth']['refreshToken'], 'rt-' + U1)


class RouteTest(unittest.TestCase):
    """上面所有用例都是**直接调用路由函数**，绕过 FastAPI 的装饰器与参数绑定。

    所以再加一条：确认两个端点确实以 POST 挂在预期的路径上（装饰器路径写错、
    方法写成 GET 都查不出来，但真实请求会 404/405）。
    """

    def test_routes_registered(self) -> None:
        routes = {(r.path, tuple(sorted(getattr(r, 'methods', None) or [])))
                  for r in A.router.routes}
        self.assertIn(('/api/accounts/export', ('POST',)), routes)
        self.assertIn(('/api/accounts/import', ('POST',)), routes)


class HttpTest(_Case):
    """走一次真实的 FastAPI 栈：路由 + JSON body 绑定 + 响应序列化。

    上面的用例都直接调用路由函数，绕过了 FastAPI 的参数绑定与依赖注入。这条补上，
    并顺带确认「非管理员会被 403 挡住」这条安全性质（直接调函数时依赖不生效，
    查不出漏挂 require_admin）。
    """

    @classmethod
    def setUpClass(cls) -> None:
        from server.main import app
        from server import security as sec
        cls.app, cls.sec = app, sec

    def _client(self):
        from fastapi.testclient import TestClient
        return TestClient(self.app)

    def test_export_and_import_roundtrip_over_http(self) -> None:
        self.app.dependency_overrides[self.sec.require_admin] = \
            lambda: {'username': 't', 'role': 'admin'}
        try:
            f1 = _write_auth(config.AUTH_DIR, U1, '甲', device_token='d1')
            c = self._client()

            r = c.post('/api/accounts/export',
                       json={'items': [{'upstream_id': None, 'filename': f1}]})
            self.assertEqual(r.status_code, 200, r.text)
            bundle = r.json()
            self.assertEqual([a['uid'] for a in bundle['accounts']], [U1])

            r2 = c.post('/api/accounts/import',
                        json={'bundle': bundle, 'mode': 'overwrite'})
            self.assertEqual(r2.status_code, 200, r2.text)
            self.assertEqual(r2.json()['overwritten'], 1)
        finally:
            self.app.dependency_overrides.pop(self.sec.require_admin, None)

    def test_non_admin_is_forbidden(self) -> None:
        # 不覆盖 require_admin，只把 current_user 换成一个只读账号 —— 真实的
        # require_admin 于是应当拒绝（判据见它的实现：role != admin）。
        self.app.dependency_overrides[self.sec.current_user] = \
            lambda: {'username': 'v', 'role': 'viewer'}
        try:
            r = self._client().post(
                '/api/accounts/export',
                json={'items': [{'upstream_id': None, 'filename': 'workbuddy-x.json'}]})
            self.assertEqual(r.status_code, 403, r.text)
        finally:
            self.app.dependency_overrides.pop(self.sec.current_user, None)
