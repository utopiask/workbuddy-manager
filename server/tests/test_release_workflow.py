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
