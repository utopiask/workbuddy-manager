"""GET 结果缓存（前端逻辑，借 Node 执行）。见 `web/lib/get-cache.ts`。

为什么用 Python 包一层：本仓库的测试套件是 Python 的，而这段逻辑在前端。
没有 Node（或版本太旧）时**跳过**而不是失败。
"""
from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / 'web' / 'lib' / 'get-cache.test.mjs'
_NODE = shutil.which('node')

# Node 的 type stripping 从 22.6 起才有
_MIN_MAJOR = 22


def _node_major() -> int | None:
    if not _NODE:
        return None
    try:
        out = subprocess.run([_NODE, '--version'], capture_output=True,
                             text=True, timeout=15).stdout.strip()
        return int(out.lstrip('v').split('.')[0])
    except Exception:  # noqa: BLE001
        return None


_MAJOR = _node_major()


class GetCacheBehaviourTest(unittest.TestCase):
    @unittest.skipUnless(_NODE, '未安装 node，跳过前端逻辑测试')
    @unittest.skipUnless(_MAJOR is not None and _MAJOR >= _MIN_MAJOR,
                         f'需要 node ≥ {_MIN_MAJOR}（type stripping），当前 {_MAJOR}')
    def test_get_cache_behaviour(self) -> None:
        self.assertTrue(_SCRIPT.is_file(), f'缺少测试脚本: {_SCRIPT}')

        def run_once() -> subprocess.CompletedProcess:
            return subprocess.run(
                [_NODE, '--experimental-strip-types', str(_SCRIPT)],
                capture_output=True, text=True, timeout=120, cwd=str(_ROOT),
            )

        proc = run_once()
        # Node 偶发进程级崩溃（与被测逻辑无关）：只对异常退出码重试一次；
        # rc=1（脚本自己判失败）不重试。
        if proc.returncode not in (0, 1):
            proc = run_once()
        out = (proc.stdout or '') + (proc.stderr or '')
        self.assertEqual(proc.returncode, 0, f'GET 缓存行为不符合预期：\n{out}')
        self.assertIn('all passed', out, f'脚本没有跑到通过：\n{out}')


if __name__ == '__main__':
    unittest.main()
