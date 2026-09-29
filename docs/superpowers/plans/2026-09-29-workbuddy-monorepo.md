# WorkBuddy Monorepo（Phase 1）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Go 网关作为一等公民并入私有的 `workbuddy-manager` 仓库，统一构建 / CI / 版本 / 发版与部署，退役「外部上游快照」周转机制，运行时行为不变。

**Architecture:** 仓库内新增 `gateway/`（原上游 Go 源码，独立 go module）；`server/`（Python 面板）与 `web/`（Next.js）不动。运行时仍是两个进程：面板 `:7864` 对外、网关 `:7863` 仅内部。发布链路从「打包脚本 → 载体 Release → CI 注入 → 安装脚本同步」简化为「CI 从仓库 `gateway/` 直接塞进发布包」。

**Tech Stack:** Go 1.22.5、Python 3.11+（FastAPI）、Next.js 15（Node 22）、GitHub Actions、Docker Compose。

**Spec:** `docs/superpowers/specs/2026-09-29-workbuddy-monorepo-design.md`

## Global Constraints

- 仓库转为**私有**；Phase 1 不改变任何运行时行为。
- Go 版本以 `gateway/go.mod`（`go 1.22.5`）为准；Node 固定 22；Python 3.11+。
- `gateway/LICENSE` 必须保留原作者 MIT 版权与声明，不得删除或改写版权行。
- **任何脚本都不得删除或覆盖** `/opt/workbuddy2api/config.json`、`/opt/workbuddy2api/auths/`、`/opt/workbuddy2api/data/`。
- 发布包内网关目录名**保持 `upstream/`**（低改动静止，避免动 `update.py` 同步路径）；仓库内开发目录为 `gateway/`。此映射必须在打包步骤注释里写明。
- 既有守卫测试保持绿：`server/tests/test_changelog.py`、`server/tests/test_issue_reply_style.py`、`server/tests/test_readme_i18n.py`、`server/tests/test_issue55_compose_and_deploy_sync.py`。
- 提交风格沿用仓库现有 `feat:/fix:/chore(release):` 约定；每个 Task 至少一次提交。

## Review Focus

- **旧版部署升级路径**：已装用户用新 `update.py` 升级时，`/opt/workbuddy2api/{config.json,auths,data}` 必须原样保留；旧版更新器「不替换 `deploy/`」的历史缺陷不得导致升级卡死（Task 7）。
- **多账号池分组**：面板配置多个上游实例（`:7865` 等）时，单 compose 不得把分组压成单实例（Task 8）。
- **打包失败的下限行为**：打包步骤异常时，必须告警且**不产出缺少网关源码的空包**（Task 4）。
- **签名可选后的信任边界**：默认允许安装未签名 Release，但要留下可审计提示；已签名包仍强校验（Task 7）。
- **Windows 原生部署**：`deploy/windows-native/*`、`start.ps1`、`service-tools.ps1` 中的网关路径/来源需同步，否则 Windows 用户装不上（Task 6）。

---

### Task 1: 导入网关源码为 `gateway/`

**Files:**
- Create: `gateway/**`（自维护者本地归档导入，287 个文件量级）
- Create: `gateway/LICENSE`（原作者 MIT，原文保留）
- Modify: `gateway/UPSTREAM-SRC.txt` → 改写为来源与维护说明（见下）
- Modify: `.gitignore`（若需，忽略 `gateway/config.json`、`gateway/auths/`、`gateway/data/`）

**Interfaces:**
- Produces: 一个可独立构建的 Go module（`module workbuddy2api`，供后续 Task 打包与 CI 引用）。

- [ ] **Step 1: 导入前先验证源码可构建**

从本地归档目录执行：
```bash
SRC=/path/to/workbuddy2api-archive
cd "$SRC" && go build ./... && go test ./... 
```
Expected: 全部通过。若失败，先停下确认归档版本，**不要导入**。

- [ ] **Step 2: 提交为单次导入**

```bash
cp -r "$SRC" gateway
rm -rf gateway/.git gateway/config.json gateway/auths gateway/data
cp gateway/LICENSE gateway/LICENSE   # 确认存在
git add gateway
git commit -m "feat(gateway): import workbuddy2api source as first-class component"
```
（不合并上游 git 历史——原始历史不可还原。）

- [ ] **Step 3: 改写来源说明**

把 `gateway/UPSTREAM-SRC.txt` 内容替换为：来源（原作者 `Sliverkiss/workbuddy2api`）、原仓库已删除、现由本仓库维护、MIT 许可与版权归属、以及「运行时数据（config.json/auths/data）不随代码提交」。

- [ ] **Step 4: 验证**

Run: `cd gateway && go vet ./... && go test ./...`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add gateway/UPSTREAM-SRC.txt .gitignore
git commit -m "docs(gateway): note provenance and MIT attribution"
```

---

### Task 2: 根 `Makefile`

**Files:**
- Create: `Makefile`

**Interfaces:**
- Produces: `make test`、`make build`、`make gateway`、`make web` 目标，供本地与 CI 共用。

- [ ] **Step 1: 写 Makefile**

```make
.PHONY: test gateway web
test: 
	cd gateway && go vet ./... && go test ./...
	python3 -m unittest discover -s server/tests -t .
gateway:
	cd gateway && go build -o ../bin/wb2api ./cmd/server  # bin/ 由 .gitignore 忽略
web:
	cd web && npm ci && npm run build:export
```
（`test` 目标暂不含 web 构建，避免本地缺 Node 时无法跑后端测试；web 由 CI 单独 job 覆盖。）

- [ ] **Step 2: 验证**

Run: `make test`
Expected: Go 与 Python 测试全通过。

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "chore(build): add root Makefile for unified build/test"
```

---

### Task 3: CI 拆分 job 并加入 Go 测试闸门

**Files:**
- Modify: `.github/workflows/release.yml`
- Test: `server/tests/test_release_workflow.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `gateway/`。
- Produces: workflow 中名为 `gateway` / `python` / `web` 的 job；`release` job `needs: [gateway, python, web]`。

- [ ] **Step 1: 写失败测试**

```python
# server/tests/test_release_workflow.py
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m unittest server.tests.test_release_workflow -v`
Expected: FAIL（`gateway` job 不存在）。

- [ ] **Step 3: 改造 workflow**

把当前单 `release` job 拆为：`gateway`（`actions/setup-go@v5`，`go-version-file: gateway/go.mod`，`go vet ./... && go test ./...`）、`python`（现有后端测试步骤）、`web`（现有前端构建步骤）、`release`（`needs: [gateway, python, web]`，接收前面 job 的 artifact：`web/out`、Python 无需产物）。保持 Node 22。

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m unittest server.tests.test_release_workflow -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/release.yml server/tests/test_release_workflow.py
git commit -m "ci: gate release on go + python + web jobs"
```

---

### Task 4: 打包改用仓库 `gateway/`，移除载体 Release 拉取

**Files:**
- Modify: `.github/workflows/release.yml`（`id: pack` 步骤）
- Modify: `dev/check_release_pack.py`
- Test: `server/tests/test_release_workflow.py`（追加断言）

**Interfaces:**
- Consumes: Task 1 的 `gateway/`。
- Produces: 发布包内 `upstream/` 目录（由 `gateway/` 映射而来），供 `install.sh` / `update.py` 沿用。

- [ ] **Step 1: 追加失败测试**

在 `ReleaseWorkflowTest` 增加：
```python
    def test_pack_maps_gateway_without_carrier(self):
        wf = (ROOT/'.github'/'workflows'/'release.yml').read_text(encoding='utf-8')
        self.assertNotIn('upstream-src', wf, '仍在从载体 Release 拉取上游源码')
        self.assertNotIn('workbuddy2api-src.tar.gz', wf)
        steps = self.data['jobs']['release']['steps']
        pack = next(s for s in steps if s.get('id') == 'pack')['run']
        self.assertIn('gateway', pack)
        self.assertIn('upstream', pack, '仍需产出包内 upstream/ 目录')
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m unittest server.tests.test_release_workflow.ReleaseWorkflowTest.test_pack_maps_gateway_without_carrier -v`
Expected: FAIL（`upstream-src` 仍存在）。

- [ ] **Step 3: 改打包步骤**

把「上游源码随包分发」整段 `curl upstream-src` 逻辑替换为从仓库复制：
```bash
cp -r gateway "$STAGE/upstream"
rm -rf "$STAGE/upstream/.git" "$STAGE/upstream/config.json" \
       "$STAGE/upstream/auths" "$STAGE/upstream/data"
# 打包失败必须致命：不允许产出缺网关源码的发布包
test -f "$STAGE/upstream/docker-compose.yml" || { echo "::error::gateway/ 未正确打包"; exit 1; }
echo "已内嵌网关源码：$(find "$STAGE/upstream" -type f | wc -l) 个文件"
```
（对应 Review Focus：打包失败不得产出空包。）

- [ ] **Step 4: 更新 `dev/check_release_pack.py`**

删去「载体拉取成功/失败两模式」分支：不再需要代理，恒为成功；断言改为「包内 `upstream/` 来自仓库 `gateway/`，文件数 > 200，含 `docker-compose.yml`/`Dockerfile`/`LICENSE`/`scripts/task_runner.py`，不含 `.git` 与运行时数据」。同时把 checkout 现场复制里加上 `gateway`。

- [ ] **Step 5: 验证**

Run: `python3 -m unittest server.tests.test_release_workflow -v && python3 dev/check_release_pack.py`
Expected: 全 PASS，且无需代理。

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/release.yml dev/check_release_pack.py server/tests/test_release_workflow.py
git commit -m "ci(pack): embed gateway/ from repo; drop upstream-src carrier"
```

---

### Task 5: 退役周转脚本

**Files:**
- Delete: `dev/pack_upstream_src.py`、`dev/archive_upstream_snapshot.py`、`deploy/check-upstream.sh`
- Modify: 引用它们处的注释/文档（`deploy/README.md`、`docs/release-process.md` 见 Task 9）

- [ ] **Step 1: 写失败测试**

```python
# server/tests/test_retired_scripts.py
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

class RetiredScriptsTest(unittest.TestCase):
    def test_gone(self):
        for rel in ('dev/pack_upstream_src.py',
                    'dev/archive_upstream_snapshot.py',
                    'deploy/check-upstream.sh'):
            self.assertFalse((ROOT/rel).exists(), f'{rel} 应已退役')
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m unittest server.tests.test_retired_scripts -v`
Expected: FAIL。

- [ ] **Step 3: 删除并清引用**

删除三个脚本；`grep -rn "pack_upstream_src\|archive_upstream_snapshot\|check-upstream" --exclude-dir=.git .` 清理代码/注释引用（文档引用留给 Task 9）。

- [ ] **Step 4: 验证**

Run: `python3 -m unittest server.tests.test_retired_scripts -v && python3 -m unittest discover -s server/tests -t .`
Expected: PASS（含 `test_issue55_compose_and_deploy_sync.py`：其「added_only」用例仍以 `check-upstream.sh` 作为「新增文件」示例——若删除后该用例引用了不存在的路径，改为使用任意字符串，不破坏语义）。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: retire upstream snapshot packaging scripts"
```

---

### Task 6: `install.sh` 与 Windows 脚本对齐新来源

**Files:**
- Modify: `deploy/install.sh`
- Modify: `deploy/windows-native/*`、`start.ps1`、`service-tools.ps1`（如引用上游来源）
- Test: `server/tests/test_docker_deploy.py`、`server/tests/test_windows_scripts.py`

**Interfaces:**
- Consumes: 发布包内 `upstream/`（Task 4）。

- [ ] **Step 1: 先运行现有测试建立基线**

Run: `python3 -m unittest server.tests.test_docker_deploy server.tests.test_windows_scripts -v`
Expected: PASS（作为改动前的基线）。

- [ ] **Step 2: 改 `install.sh`**

保留 `UPSTREAM_SRC → 包内 upstream/ → 已存在 git → UPSTREAM_REPO` 的优先级不变；仅移除对「来源是外部载体」的措辞与 `check-upstream.sh` 的调用（若存在）。同步逻辑（只增改代码、不动 config/auths/data）**保持原样**。

- [ ] **Step 3: 核对 Windows 路径**

检查 `deploy/windows-native/`、`start.ps1`、`service-tools.ps1` 是否硬编码上游来源/目录；若有，改为从发布包内 `upstream/` 取。

- [ ] **Step 4: 验证**

Run: `python3 -m unittest server.tests.test_docker_deploy server.tests.test_windows_scripts server.tests.test_issue55_compose_and_deploy_sync -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add deploy/install.sh deploy/windows-native start.ps1 service-tools.ps1
git commit -m "fix(install): source gateway from release package upstream/"
```

---

### Task 7: `update.py` 签名降为可选

**Files:**
- Modify: `deploy/update.py`
- Test: `server/tests/test_release_signature.py`、`server/tests/test_update_e2e.py`、`server/tests/test_update_lifecycle.py`

**Interfaces:**
- Produces: 默认允许安装未签名 Release，并在报告中留下可审计提示；`WB_REQUIRE_SIGNATURE=1` 时恢复强制。

- [ ] **Step 1: 写失败测试**

在 `test_release_signature.py` 增加：
```python
    def test_unsigned_allowed_by_default(self):
        # 默认：未签名不阻断更新，但报告里出现「未签名」提示
        ...  # 复用该文件现有的加载/报告辅助
    def test_unsigned_rejected_when_required(self):
        # WB_REQUIRE_SIGNATURE=1：恢复强校验，未签名必须拒绝
        ...
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m unittest server.tests.test_release_signature -v`
Expected: 新用例 FAIL（当前强制验签）。

- [ ] **Step 3: 改 `update.py`**

验签处：`WB_REQUIRE_SIGNATURE=1` 或签名存在时执行现有强校验；否则跳过并以 `warn` 级别记录「未签名，已按配置允许安装」。**其余更新流程（含 `deploy/` 同步、备份、compose 探测）不改**。

- [ ] **Step 4: 更新受影响的既有断言**

`test_update_e2e.py` / `test_update_lifecycle.py` 中「缺 `.sig` 必被拒绝」的断言改为「默认放行 + 提示；设置 `WB_REQUIRE_SIGNATURE=1` 才拒绝」。

- [ ] **Step 5: 验证**

Run: `python3 -m unittest server.tests.test_release_signature server.tests.test_update_e2e server.tests.test_update_lifecycle server.tests.test_updater_status -v`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add deploy/update.py server/tests/test_release_signature.py server/tests/test_update_e2e.py server/tests/test_update_lifecycle.py
git commit -m "feat(update): signature optional by default (WB_REQUIRE_SIGNATURE=1 to enforce)"
```

---

### Task 8: 单 compose 两个服务

**Files:**
- Modify: `docker-compose.yml`（根，现仅 manager）
- Modify: `.env.example`（`WB2API_BASE` 说明改内网服务名）
- Test: `server/tests/test_compose_services.py`（新建）

**Interfaces:**
- Consumes: `gateway/Dockerfile`（Task 1）。
- Produces: compose 服务 `workbuddy2api`（无宿主端口，仅内网）与 `workbuddy-manager`（`:7864`）。

- [ ] **Step 1: 写失败测试**

```python
# server/tests/test_compose_services.py
import unittest, yaml
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

class ComposeServicesTest(unittest.TestCase):
    def setUp(self):
        self.c = yaml.safe_load((ROOT/'docker-compose.yml').read_text(encoding='utf-8'))
        self.svc = self.c['services']

    def test_has_gateway_service(self):
        self.assertIn('workbuddy2api', self.svc)

    def test_gateway_not_published_to_host(self):
        # 网关只能被面板经内网访问，不得映射宿主端口（保持 127.0.0.1 内部语义）
        self.assertFalse(self.svc['workbuddy2api'].get('ports'))

    def test_panel_points_to_gateway_service(self):
        env = self.svc['workbuddy-manager']['environment']
        vals = env if isinstance(env, list) else [f'{k}={v}' for k, v in env.items()]
        self.assertTrue(any('WB2API_BASE=http://workbuddy2api:7863' in v for v in vals))
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m unittest server.tests.test_compose_services -v`
Expected: FAIL。

- [ ] **Step 3: 加服务**

在根 compose 增加：
```yaml
  workbuddy2api:
    build: ./gateway
    container_name: workbuddy2api
    restart: unless-stopped
    environment: [ "TZ=Asia/Shanghai" ]
    volumes:
      - ./workbuddy2api-data/auths:/app/auths
      - ./workbuddy2api-data/data:/app/data
      - ./workbuddy2api-data/config.json:/app/config.json
    # 不写 ports：仅内网
```
并把 `workbuddy-manager.environment.WB2API_BASE` 改为 `http://workbuddy2api:7863`，二者置于同一网络。

- [ ] **Step 4: 保留多账号池分组的可扩展性**

不改动 `server/upstreamsvc.py`；在 compose 文件顶部注释写明「额外分组实例用 `docker-compose.override.yml` 再起 `workbuddy2api-b` 等，面板 `上游` 设置里指向其实例」。（对应 Review Focus：分组不被压成单实例。）

- [ ] **Step 5: 验证**

Run: `python3 -m unittest server.tests.test_compose_services server.tests.test_issue55_compose_and_deploy_sync server.tests.test_docker_deploy -v && docker compose config -q`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml .env.example server/tests/test_compose_services.py
git commit -m "feat(compose): orchestrate panel + gateway as one stack"
```

---

### Task 9: 许可与文档

**Files:**
- Create: `gateway/NOTICE`（如需，与 `LICENSE` 并存）
- Modify: `docs/release-process.md`、`README.md`、`README.en.md`、`deploy/README.md`

- [ ] **Step 1: 改写 `docs/release-process.md`**

删除「不要把上游代码提交进本仓库，也不要另开公开镜像」与「源码怎么到达用户（载体 Release）」两节；改为：网关源码在仓库 `gateway/`，发版时 CI 直接打入发布包内 `upstream/`；单一版本号与 tag；签名默认可选。保留「两条耦合路径」的既有提醒（Phase 2 才会消除）。

- [ ] **Step 2: 更新 README「关系」段**

把「与 workbuddy2api 的关系 / 上游」改写为「本仓库的网关 `gateway/`」，说明归属与 MIT 许可。

- [ ] **Step 3: 更新 `deploy/README.md`**

「〇、上游源码从哪来」改为「网关源码来自发布包 / 仓库 `gateway/`」；删除 `UPSTREAM_REPO` 相关的「从上游仓库克隆」表述（若仍支持自定义来源，保留 `UPSTREAM_SRC`）。

- [ ] **Step 4: 验证文案守卫**

Run: `python3 -m unittest server.tests.test_readme_i18n server.tests.test_changelog server.tests.test_issue_reply_style -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add gateway/NOTICE docs/release-process.md README.md README.en.md deploy/README.md
git commit -m "docs: gateway is now a first-class component of this repo"
```

---

### Task 10: 迁移 runbook 与端到端冒烟

**Files:**
- Create: `docs/monorepo-migration.md`
- 无源码改动

- [ ] **Step 1: 写 runbook**

步骤：① 仓库转私有；② 合入 Task 1–9；③ 按新 CI 推 `vX.Y.Z` 出包；④ 目标机 `deploy/install.sh` 覆盖安装；⑤ 核对 `/opt/workbuddy2api/{config.json,auths,data}` 未变（记录安装前后 `sha256` 与账号数）；⑥ 冒烟：面板登录、`/v1/models`、一次真实对话、一次一键更新。

- [ ] **Step 2: 冒烟验证（staging）**

在**非生产**机器执行 runbook ①–⑥，记录：
- 升级前：`docker ps`、账号数、`config.json` sha256
- 升级后：同上，且全部一致
Expected: 账号、配置、数据零丢失；面板与网关均可用。

- [ ] **Step 3: Commit**

```bash
git add docs/monorepo-migration.md
git commit -m "docs: monorepo migration runbook and smoke checks"
```

---

## 自检结果

- **Spec 覆盖**：§3 结构→T1；§5 构建/CI→T2/T3；§5 发布→T4/T5；§6 部署/迁移→T6/T8/T10；§5 签名可选→T7；§7 许可文档→T9；§6 单 compose→T8。
- **Review Focus 落点**：升级路径→T7/T10；多账号池→T8 Step 4；打包失败下限→T4 Step 3；签名边界→T7；Windows→T6 Step 3。
- **类型/命名一致**：`gateway/`（仓库内）↔ `upstream/`（包内）映射在 T4 固定；`WB_REQUIRE_SIGNATURE` 全计划统一。
- **Phase 2**（统一腾讯直连逻辑，面板为唯一实现）**不在本计划**，另立 spec 与计划。
