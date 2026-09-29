import unittest, yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ReleaseWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.data = yaml.safe_load((ROOT/'.github'/'workflows'/'release.yml').read_text(encoding='utf-8'))

    def test_has_three_gate_jobs(self):
        for name in ('gateway', 'python', 'web'):
            self.assertIn(name, self.data['jobs'], f'缺少 job: {name}')

    def test_release_waits_for_gates(self):
        rel = self.data['jobs']['release']
        needs = rel.get('needs') or []
        for name in ('gateway', 'python', 'web'):
            self.assertIn(name, needs)

    def test_gateway_job_runs_go_test(self):
        steps = self.data['jobs']['gateway']['steps']
        runs = '\n'.join(s.get('run','') for s in steps)
        self.assertIn('go test', runs)

    def test_all_jobs_build_from_resolved_ref(self):
        # 手动补发已有 tag 时，闸门 job 必须与 release 打包同一个 ref，
        # 否则前端/Python 取自分支 HEAD、server/ 取自 tag，产生版本错配。
        resolve = self.data['jobs'].get('resolve')
        self.assertIsNotNone(resolve, '缺少 resolve job')
        self.assertIn('tag', resolve.get('outputs') or {}, 'resolve 未输出 tag')
        expected = '${{ needs.resolve.outputs.tag }}'
        for name in ('gateway', 'python', 'web', 'release'):
            job = self.data['jobs'][name]
            self.assertIn('resolve', job.get('needs') or [], f'{name} 未依赖 resolve')
            checkouts = [s for s in job['steps']
                         if str(s.get('uses', '')).startswith('actions/checkout')]
            self.assertTrue(checkouts, f'{name} 缺少 checkout 步骤')
            ref = (checkouts[0].get('with') or {}).get('ref')
            self.assertEqual(ref, expected, f'{name} 的 checkout ref 未按解析出的 tag')

    def test_pack_maps_gateway_without_carrier(self):
        wf = (ROOT/'.github'/'workflows'/'release.yml').read_text(encoding='utf-8')
        self.assertNotIn('upstream-src', wf, '仍在从载体 Release 拉取上游源码')
        self.assertNotIn('workbuddy2api-src.tar.gz', wf)
        steps = self.data['jobs']['release']['steps']
        pack = next(s for s in steps if s.get('id') == 'pack')['run']
        self.assertIn('gateway', pack)
        self.assertIn('upstream', pack, '仍需产出包内 upstream/ 目录')

    def test_pack_rewrites_gateway_build_context_for_package(self):
        """仓库内开发目录 gateway/ 在发布包里叫 upstream/（Task 8 / Ruling P2）。

        根 compose 里网关照 `build: ./gateway` 构建；发布包里没有 gateway/ 目录，
        不改写的话 Docker 用户在包内 `docker compose up` 会因找不到构建上下文
        直接失败。打包步骤必须把包内 compose 改写成 `build: ./upstream`。
        """
        steps = self.data['jobs']['release']['steps']
        pack = next(s for s in steps if s.get('id') == 'pack')['run']
        self.assertIn('docker-compose.yml', pack, '打包步骤没碰包内 compose')
        # 必须真的执行替换（sed 之类），不能只在注释里提一句
        self.assertRegex(pack, r'sed[^\n]*gateway[^\n]*upstream',
                         '打包步骤没有把包内 compose 的网关构建上下文改写为 upstream')
        self.assertIn('build: ./upstream', pack, '未断言改写结果')
