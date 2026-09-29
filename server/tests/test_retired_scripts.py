import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class RetiredScriptsTest(unittest.TestCase):
    def test_gone(self):
        for rel in ('dev/pack_upstream_src.py',
                    'dev/archive_upstream_snapshot.py',
                    'deploy/check-upstream.sh'):
            self.assertFalse((ROOT / rel).exists(), f'{rel} 应已退役')
