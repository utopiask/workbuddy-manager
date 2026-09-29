"""把 release.yml 的「组装发布目录」步骤**真跑一遍**。

为什么值得单独跑：那段 shell 里既有文件搬运，又有「把仓库 gateway/ 内嵌进包内
upstream/」的逻辑 —— 它是用户拿到网关源码的唯一常规渠道。写错了不会报错，只会让
包里的 `upstream/` 悄悄少掉（新装用户于是装不上）。

网关源码来自仓库内的 `gateway/`（Task 1 导入），不再依赖任何网络拉取，因此本脚本
恒按「已内嵌」一种结果校验：包内必须有 upstream/、含关键文件、无 .git、无运行时
数据与凭据；打成 tar 后同样能读到网关源码。

本机没有 `zip`，所以只跑到 `tar czf` 那一步。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    import yaml

    wf_path = ROOT / '.github' / 'workflows' / 'release.yml'
    data = yaml.safe_load(wf_path.read_text(encoding='utf-8'))
    # workflow 已拆成 gateway/python/web/release 多个 job；打包步骤固定在 release job 内。
    job = data['jobs']['release']
    step = next(s for s in job['steps'] if s.get('id') == 'pack')
    script = step['run']
    # 去掉 GitHub 表达式与本机没有的 zip，其余**原样执行**
    for token in ('${{ steps.vars.outputs.tag }}', '${{ needs.resolve.outputs.tag }}'):
        script = script.replace(token, 'v9.9.9-test')
    script = script.replace('${{ github.repository }}', 'utopiask/workbuddy-manager')
    script = '\n'.join(l for l in script.splitlines() if 'zip -qr' not in l)

    work = ROOT / 'dev' / '.pack-test'
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    # 搭一个「checkout 现场」：照 CI 的 checkout 结果复制需要的路径。
    # 不用 git archive + tar 解：本机 tar 对中文文件名会报 Invalid empty pathname
    # （Windows 上的编码怪癖，CI 跑在 Linux 没这问题）。
    repo = work / 'repo'
    repo.mkdir()
    for rel in ('server', 'deploy', 'docs', 'gateway'):
        shutil.copytree(ROOT / rel, repo / rel,
                        ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache'))
    shutil.copytree(ROOT / 'web' / 'out', repo / 'web' / 'out')
    for name in ('.env.example', 'README.md', 'README.en.md', 'CHANGELOG.md', 'LICENSE',
                 'Dockerfile', 'docker-compose.yml'):
        src = ROOT / name
        if src.is_file():
            shutil.copyfile(src, repo / name)

    print('=== 执行组装步骤（zip 那行跳过）===')
    r = subprocess.run(['bash', '-c', script], cwd=repo, capture_output=True,
                       text=True, encoding='utf-8', errors='replace')
    out = r.stdout or ''
    print('\n'.join(out.splitlines()[-12:]))
    if r.stderr:
        print(r.stderr[-1200:], file=sys.stderr)
    if r.returncode != 0:
        print(f'组装步骤退出码 {r.returncode}', file=sys.stderr)
        return 1

    problems: list[str] = []

    def check(ok: bool, label: str, detail: str = '') -> None:
        print(f'  {"✓" if ok else "✗"}  {label}' + (f'\n       {detail}' if detail else ''))
        if not ok:
            problems.append(label)

    stage = repo / 'workbuddy-manager-v9.9.9-test'
    up = stage / 'upstream'
    check(stage.is_dir(), '组装出发布目录', stage.name)

    files = sorted(p for p in up.rglob('*') if p.is_file()) if up.is_dir() else []
    check(up.is_dir() and len(files) > 200, 'upstream/ 已内嵌（来自仓库 gateway/）',
          f'文件数={len(files)}')
    for name in ('docker-compose.yml', 'Dockerfile', 'LICENSE', 'scripts/task_runner.py'):
        check((up / name).is_file(), f'upstream/{name} 就位')
    check(not (up / '.git').exists(), '内嵌的 upstream/ 不含 .git')
    check(not (up / 'config.json').exists() and not (up / 'auths').exists()
          and not (up / 'data').exists(), '内嵌的 upstream/ 不含运行时数据与凭据')

    # 包内根 compose 必须把网关构建上下文从仓库的 ./gateway 改写成 ./upstream ——
    # 包里没有 gateway/ 目录，不改写会让 Docker 用户在发布包里 `docker compose up`
    # 直接报找不到构建上下文（P2：仓库 gateway/ ↔ 发布包 upstream/ 的目录映射）。
    packaged_compose = stage / 'docker-compose.yml'
    compose_text = packaged_compose.read_text(encoding='utf-8') if packaged_compose.is_file() else ''
    check('build: ./upstream' in compose_text, '包内 compose 从 ./upstream 构建网关')
    check('build: ./gateway' not in compose_text, '包内 compose 不再引用 ./gateway')

    check((stage / '.version').is_file(), '.version 已写入')
    check((stage / 'server' / 'main.py').is_file(), 'server/ 已打包')
    check((stage / 'deploy' / 'install.sh').is_file(), 'deploy/install.sh 已打包')

    # 打成 tar 再验一次（发布产物就是这个）。用 tarfile 读清单：本机 tar 的输出
    # 含非 UTF-8 文件名时会让 text 解码失败（harness 的坑，不是包的问题）。
    subprocess.run(['tar', 'czf', f'{stage.name}.tar.gz', stage.name], cwd=repo, check=True)
    import tarfile
    with tarfile.open(repo / f'{stage.name}.tar.gz', 'r:gz') as tf:
        names = set(tf.getnames())
    check(f'{stage.name}/upstream/scripts/task_runner.py' in names,
          '发布 tar 包内含上游源码')

    size = (repo / f'{stage.name}.tar.gz').stat().st_size
    print(f'\n发布包大小：{size / 1024 / 1024:.1f} MB')
    print('=== 结果 ===')
    if problems:
        print(f'✗ {len(problems)} 项未通过：' + '、'.join(problems))
        return 1
    print('ALL CHECKS PASSED（含内嵌网关源码）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
