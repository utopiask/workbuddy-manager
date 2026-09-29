"""根 compose 必须是「面板 + 网关」两个服务的一体编排。

Phase 1 的运行时拓扑不变：**只有面板对外（127.0.0.1:7864），网关只在 compose
内网**。所以这里钉住三件事：

  · `workbuddy2api` 服务存在，且**不映射任何宿主端口**（一旦写了 ports，网关就会
    直接暴露出去——它持有账号池的全部凭据，绝不能这样）；
  · 面板经**服务名** `http://workbuddy2api:7863` 访问网关，而不是绕宿主回环
    （`host.docker.internal`）——后者要求宿主另起网关，不再是「一个栈」；
  · 面板与网关共享同一份本地数据目录（配置与 auths），账号管理才继续可用。
"""
import unittest

import yaml

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ComposeServicesTest(unittest.TestCase):
    def setUp(self):
        self.c = yaml.safe_load((ROOT / 'docker-compose.yml').read_text(encoding='utf-8'))
        self.svc = self.c['services']

    @staticmethod
    def _env(svc) -> list[str]:
        env = svc.get('environment')
        if isinstance(env, list):
            return [str(v) for v in env]
        return [f'{k}={v}' for k, v in (env or {}).items()]

    def test_has_gateway_service(self):
        self.assertIn('workbuddy2api', self.svc)

    def test_gateway_not_published_to_host(self):
        # 网关只能被面板经内网访问，不得映射宿主端口（保持 127.0.0.1 内部语义）
        self.assertFalse(self.svc['workbuddy2api'].get('ports'))

    def test_panel_points_to_gateway_service(self):
        env = self.svc['workbuddy-manager']['environment']
        vals = env if isinstance(env, list) else [f'{k}={v}' for k, v in env.items()]
        self.assertTrue(any('WB2API_BASE=http://workbuddy2api:7863' in v for v in vals))

    def test_gateway_builds_from_repo_gateway_dir(self):
        """仓库开发目录是 `gateway/`；发布包内会被改名成 `upstream/`（由 release
        流程重写，见 test_release_workflow 与 dev/check_release_pack.py）。"""
        self.assertEqual(self.svc['workbuddy2api'].get('build'), './gateway')

    def test_services_share_a_network(self):
        """两个服务必须在同一网络里，面板才能用服务名解析到网关。"""
        nets = self.c.get('networks') or {}
        gw = set(self.svc['workbuddy2api'].get('networks') or [])
        mgr = set(self.svc['workbuddy-manager'].get('networks') or [])
        self.assertTrue(gw and mgr, f'缺少显式网络：gateway={gw} manager={mgr}')
        self.assertTrue(gw & mgr, '面板与网关不在同一网络，服务名解析不到')
        for name in gw & mgr:
            self.assertIn(name, nets, f'引用了未声明的网络：{name}')

    def test_panel_shares_gateway_data_dir(self):
        """面板必须挂到与网关**同一份**本地数据目录（容器内仍是 /opt/workbuddy2api，
        与 WB_UPSTREAM_DIR 的默认口径一致），否则「设置」页写不到网关的 config.json，
        扫码添加账号也落不到网关的 auths/。"""
        vols = [str(v) for v in (self.svc['workbuddy-manager'].get('volumes') or [])]
        self.assertTrue(any(v.startswith('./workbuddy2api-data:') for v in vols),
                        '面板未共享网关的本地数据目录')
        self.assertTrue(any('/opt/workbuddy2api' in v for v in vols),
                        '面板缺少上游目录挂载点（WB_UPSTREAM_DIR 默认值）')
