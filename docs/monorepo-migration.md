# Monorepo 迁移 runbook（一次性）

本文是把网关 `workbuddy2api` 并入 `workbuddy-manager` 私有仓库后的**一次性迁移手册**，
对应设计 `docs/superpowers/specs/2026-09-29-workbuddy-monorepo-design.md` §6。

Phase 1 **不改变任何运行时行为**：面板仍是唯一入口（`:7864`），网关仍是内部数据面
（`:7863`），账号数据（`config.json` / `auths/` / `data/`）**零迁移**。迁移做的事只有三件：
仓库转私有、合入 monorepo 改造、按新链路重发一次包并在目标机覆盖安装一次。

> **执行顺序与安全红线**
> - **先在非生产机器按 §2 完整走一遍**（staging），记录对比表；生产最后做。
> - 全程**不得删除或覆盖** `/opt/workbuddy2api/{config.json,auths,data}`。
>   安装脚本只增改代码；这三样即使逐字节变了，也要先查清原因再继续。
> - 本文命令除注明「目标机」外，均在**仓库根目录**执行。
> - `config.json` 含 `api_key`，`auths/` 含账号凭据 —— 任何备份、哈希清单都不要提交或外传。

---

## 0. 迁移前基线（在目标机、执行 §4 之前）

先取基线并留档，供 §5 对比。所有命令用 root：

```bash
sudo -i
cd /opt/workbuddy2api

# ① config.json（含 api_key）与账号目录、数据目录的哈希清单
sha256sum config.json | tee /root/wb-migration-pre.sha256
find auths -maxdepth 1 -type f -name '*.json' -print0 \
  | sort -z | xargs -0 sha256sum >> /root/wb-migration-pre.sha256
find data -type f -print0 | sort -z | xargs -0 sha256sum >> /root/wb-migration-pre.sha256

# ② 账号数（auths 里每个账号一个 JSON 文件）
ls -1 auths/*.json | wc -l | tee /root/wb-account-count-pre.txt
curl -s http://127.0.0.1:7863/healthz | tee /root/wb-healthz-pre.json   # {...,"healthy":N,"total":N}

# ③ 运行中的容器与版本
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | tee /root/wb-docker-pre.txt
cat /opt/workbuddy-manager/.version 2>/dev/null | tee /root/wb-version-pre.txt
```

`total` 即为网关看到的账号总数；`healthy` 为当前可用数。基线存好后**不要**在迁移过程中
再取基线。

---

## 1. Step ① 仓库转私有

转私有是后续所有改动的前提（公开镜像上游代码的顾虑随之解除）。

```bash
# 方案 A：把现有公开仓库直接转私有（推荐，历史与 issue 都保留）
gh repo edit ithtelab/workbuddy-manager \
  --visibility private --accept-visibility-change-consequences
gh repo view ithtelab/workbuddy-manager --json nameWithOwner,visibility \
  -q '.nameWithOwner + " -> " + .visibility'      # 期望 ... -> PRIVATE

# 方案 B：新建私有仓库（旧公开仓库原样保留）
gh repo create ithtelab/workbuddy-manager-private --private \
  --description "WorkBuddy Manager + gateway (monorepo)"
git remote set-url origin git@github.com:ithtelab/workbuddy-manager-private.git
```

注意：

- 转私有会**摘掉公开 fork、清空 star/watch**，并开始消耗 Actions 配额；
- **私有仓库的 Release 资产需要鉴权**（内置更新器不带凭据，见 §8 已知限制）；
- 若走方案 B，后续命令里的 `ithtelab/workbuddy-manager` 全部替换为
  `ithtelab/workbuddy-manager-private`（含 `WB_MANAGER_REPO` 与本文下载命令）。

---

## 2. Step ② 合入 Task 1–9

Task 1–9 的改动在分支 `feat/monorepo` 上。合入前先把它推到私有的 origin，再走 PR
（`main` 有 ruleset：必须 PR + 至少 1 个批准）。

```bash
git checkout feat/monorepo
git push -u origin feat/monorepo

# PR（main 受保护，不能直推）
gh pr create --base main --head feat/monorepo \
  --title "feat: import gateway into monorepo (Phase 1)" \
  --body "将网关收进仓库 gateway/，统一构建 / CI / 发版；运行时行为不变。"
gh pr merge --merge --admin        # admin 可绕过；或等批准后正常合并

# 合并后本地同步并跑三套闸门
git checkout main && git pull --ff-only
make test        # gateway: go test ./...   server: unittest discover   web: build
```

`make test` 三套必须全绿再进 Step ③（新 CI 也以此为发版闸门）。仓库根 `Makefile` 是
本地与 CI 共用的入口。

---

## 3. Step ③ 推 `vX.Y.Z` tag，走新 CI 出包

新 CI（`.github/workflows/release.yml`）由 `v*` tag 触发：`gateway` / `python` / `web`
三个并行闸门全绿后，`release` job 组装发布包并创建 Release。包内**自带**网关源码
（仓库 `gateway/` → 包内 `upstream/`），装的时候不需要联网取任何源码。

```bash
# 1) 升版本：.version、server/main.py 的 version、CHANGELOG.md 新增段落
#    （CHANGELOG 是写给用户看的，见 docs/release-process.md）
make test                                   # 全绿才继续
git add -A && git commit -m "chore(release): vX.Y.Z"
git push origin main

# 2) 打 tag → 触发 CI
git tag vX.Y.Z && git push origin vX.Y.Z
gh run watch --exit-status \
  "$(gh run list --workflow=release.yml -L1 --json databaseId -q '.[0].databaseId')"

# 3) 确认产物（应含 .tar.gz 与 .zip；.sig 可选）
gh release view vX.Y.Z --repo ithtelab/workbuddy-manager --json assets \
  -q '.assets[].name'
```

**签名（可选，按默认策略）**：签名默认可选，不签也能发布与安装；但**签名存在时永远强校验**。
要发布后补签：

```bash
gh release download vX.Y.Z --repo ithtelab/workbuddy-manager --pattern '*.tar.gz'
ssh-keygen -lf ~/.ssh/workbuddy-release.pub      # 核对指纹再签，避免拿错密钥
ssh-keygen -Y sign -f ~/.ssh/workbuddy-release -n file workbuddy-manager-vX.Y.Z.tar.gz
gh release upload vX.Y.Z workbuddy-manager-vX.Y.Z.tar.gz.sig \
  --repo ithtelab/workbuddy-manager
```

要**强制**「缺签名即拒绝」的部署，在目标机设 `WB_REQUIRE_SIGNATURE=1`（见 §7）。

---

## 4. Step ④ 目标机用新 `deploy/install.sh` 覆盖安装一次

在**目标机**（root）执行。发布包下载用已认证的 `gh`（私有仓库必需）：

```bash
sudo -i
cd /root
gh release download vX.Y.Z --repo ithtelab/workbuddy-manager \
  --pattern 'workbuddy-manager-vX.Y.Z.tar.gz' --clobber

# 有 .sig 时，解压前先验签（脚本在包内 deploy/，只解出它即可）
if [ -f workbuddy-manager-vX.Y.Z.tar.gz.sig ]; then
  tar xzf workbuddy-manager-vX.Y.Z.tar.gz \
    workbuddy-manager-vX.Y.Z/deploy/verify-release.sh
  bash workbuddy-manager-vX.Y.Z/deploy/verify-release.sh \
    workbuddy-manager-vX.Y.Z.tar.gz
fi

tar xzf workbuddy-manager-vX.Y.Z.tar.gz
cd workbuddy-manager-vX.Y.Z
sudo bash deploy/install.sh
```

`install.sh` 在本机的行为（已存在部署时）：

- 检测到 `/opt/workbuddy2api/config.json` → 打印「已存在上游部署，**保留现有配置与账号**」，
  确保网关容器在运行；**不会覆盖** `config.json` / `auths/` / `data/`；
- 把面板代码（`server/`、`deploy/`、`web/out/`、README/CHANGELOG）同步进
  `/opt/workbuddy-manager`，重装依赖并重注册 systemd `workbuddy-web`；
- 结束后打印访问地址与初始密码。

> 网关**代码**的随包同步与重建由 §6 的「一键更新」完成（`install.sh` 对已存在的上游只保证
> 容器在跑，不改代码）。Phase 1 网关源码与本机现有那份同源，行为不变，因此不重建也无影响。

---

## 5. Step ⑤ 核对 `/opt/workbuddy2api/{config.json,auths,data}` 未变

在目标机（root），重复 §0 的取数，改成 `-post`：

```bash
cd /opt/workbuddy2api
sha256sum config.json | tee /root/wb-migration-post.sha256
find auths -maxdepth 1 -type f -name '*.json' -print0 \
  | sort -z | xargs -0 sha256sum >> /root/wb-migration-post.sha256
find data -type f -print0 | sort -z | xargs -0 sha256sum >> /root/wb-migration-post.sha256
ls -1 auths/*.json | wc -l | tee /root/wb-account-count-post.txt
curl -s http://127.0.0.1:7863/healthz | tee /root/wb-healthz-post.json
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | tee /root/wb-docker-post.txt
cat /opt/workbuddy-manager/.version | tee /root/wb-version-post.txt

# 逐字节对比（应无差异）
diff -u /root/wb-migration-pre.sha256 /root/wb-migration-post.sha256 && echo "哈希一致 ✓"
diff -u /root/wb-account-count-pre.txt /root/wb-account-count-post.txt && echo "账号数一致 ✓"
```

### 升级前后对比表（请操作人填写）

| 项目 | 升级前 | 升级后 | 一致？ | 备注 |
|---|---|---|---|---|
| 面板版本 `.version` | | | | 应变为 `vX.Y.Z` |
| `config.json` sha256 | | | | 含 `api_key`，必须一致 |
| `auths/` 文件数 | | | | 账号数 |
| `auths/` 哈希清单 sha256 | | | | `sha256sum wb-migration-*.sha256` |
| `data/` 哈希清单 sha256 | | | | `sha256sum wb-migration-*.sha256` |
| `/healthz` `total` | | | | 网关看到的账号总数 |
| `/healthz` `healthy` | | | | 可用账号数 |
| 容器 `workbuddy2api` 状态 | | | | 升级后应为 running/healthy |
| systemd `workbuddy-web` | | | | `systemctl is-active workbuddy-web` |

**预期**：账号、配置、数据零丢失；面板与网关均可用。

> 关于「逐字节一致」：网关运行期会主动刷新 token、写 `data/state.json`，因此 `auths/` 内
> 个别文件的字节或 `data/` 哈希**可能**随运行时间自然变化。若 `diff` 有差异，先判断是不是
> 运行期写入（对比时间戳、看网关日志），再确定是否由迁移引入；账号数与 `config.json`
> 是硬指标，必须完全一致。

---

## 6. Step ⑥ 冒烟（手动、在 staging 执行）

> 本节是**手动 staging 步骤**，不在生产直接跑。每项记录结果。

### 6.1 面板登录

```bash
curl -s -o /dev/null -w 'healthz %{http_code}\n' http://127.0.0.1:7864/api/healthz   # 期望 200
# 浏览器打开 http://<服务器IP>:7864，账号 admin
# 忘记初始密码：
journalctl -u workbuddy-web | grep -A3 '初始管理员'
```

### 6.2 `/v1/models`

- **install.sh 部署**（网关在本机 `7863`）：

  ```bash
  API_KEY=$(python3 -c \
    "import json;print(json.load(open('/opt/workbuddy2api/config.json'))['api_key'])")
  curl -s -H "Authorization: Bearer $API_KEY" http://127.0.0.1:7863/v1/models \
    | python3 -m json.tool | head
  ```

- **纯 compose 部署**（网关不发布到宿主，经面板调用，用面板密钥）：

  ```bash
  curl -s -H "Authorization: Bearer <面板密钥>" http://127.0.0.1:7864/v1/models \
    | python3 -m json.tool | head
  ```

期望返回模型列表；若报 `no_healthy_account` 等，先看账号数与网关日志。

### 6.3 一次真实对话

```bash
curl -s http://127.0.0.1:7863/v1/chat/completions \
  -H "Authorization: Bearer $API_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"<从 /v1/models 里选一个>",
       "messages":[{"role":"user","content":"只回复 pong"}],"max_tokens":16}'
```

期望返回一次正常补全（非 5xx、非 `no_healthy_account`）。流式（`"stream":true`）可选再验证一次。

### 6.4 一次一键更新

- 界面：**设置 → 系统更新 → 全部更新**，观察进度与日志；
- 或命令行：

  ```bash
  sudo /opt/workbuddy-manager/venv/bin/python \
    /opt/workbuddy-manager/deploy/update.py --target both
  ```

期望：更新成功；账号授权、网关配置、密钥与日志数据都保留；更新报告里有一条签名状态
（默认未签名时为 `warn`，见 §7）。随后重复 §5 的对比表，确认三样数据仍一致。

---

## 7. Docker（compose）部署路径

纯 Docker 部署（不经过 `install.sh` / systemd）由根 `docker-compose.yml` 编排两个服务：
面板 `workbuddy-manager` 是唯一对外入口（`127.0.0.1:7864`），网关 `workbuddy2api`
只在 compose 内网。

**首次准备（`config.json` 必须是文件，否则 docker 会把它建成目录、网关起不来）：**

```bash
mkdir -p workbuddy2api-data/auths workbuddy2api-data/data
cp gateway/config.example.json workbuddy2api-data/config.json    # 仓库内
# 发布包内网关源码在 upstream/，改用：
#   cp upstream/config.example.json workbuddy2api-data/config.json
# 然后编辑 workbuddy2api-data/config.json 的 api_key 等

# bind mount 属主需为容器内 uid 10001，否则面板显示「0 个账号」
chown -R 10001:10001 workbuddy2api-data/auths workbuddy2api-data/data
# 首次自动创建的 ./data 归 root，容器以 10001 运行会打不开 sqlite：
chown -R 10001:10001 ./data

docker compose up -d --build     # 面板 + 网关一起起来
```

- 子路径部署：`docker compose build --build-arg BASE_PATH=/...` 与 `WB_BASE_PATH` 必须一致；
- 多账号池分组：默认 compose 只起默认分组实例；额外分组按 `docker-compose.yml` 顶部注释
  用 `docker-compose.override.yml` 再起一个实例，**不要**把分组压成单实例；
- 网关配置改动需重启网关容器才生效（`config.json` 以只读挂入）。

---

## 8. 签名策略（默认可选）

- **默认（未设环境变量）**：未签名的 Release 也能安装；更新器只在报告里留一条 `warn`
  级「该 Release 未签名（缺少 `.tar.gz.sig`）」，保证可审计。
- **签名存在时永远强校验**：被篡改或不匹配一律拒绝安装。
- **强制签名**：部署侧设 `WB_REQUIRE_SIGNATURE=1`，缺 `.sig` 即拒绝（恢复旧行为）。
  - systemd 部署：加进 `/etc/systemd/system/workbuddy-web.service` 的 `Environment=`；
  - compose 部署：加进面板服务的 `environment:`。
- **逃生门**：`WB_SKIP_SIGNATURE=1` 跳过验签（会在日志显式告警），仅在换密钥等紧急情况用。
- 手动安装前建议先 `bash deploy/verify-release.sh <包>.tar.gz`（无 `.sig` 时它按缺签名报错，
  默认策略下可跳过此步、直接安装）。
- 密钥指纹：`ssh-keygen -lf ~/.ssh/workbuddy-release.pub` 应输出
  `SHA256:xmHLJDKH/vYtAp59XwXPVE4A/CwXAOpxTlYh7KC677Y`（细节见 `docs/release-signing.md`）。

---

## 9. 前置自检（可在本仓库离线执行）

迁移前，在仓库内确认 runbook 引用的文件与命令都在：

```bash
docker compose config -q                                  # 非破坏性解析，期望 exit 0
test -f deploy/install.sh && test -f gateway/config.example.json && test -f docker-compose.yml
command -v git docker && docker compose version
.venv/bin/python -m unittest server.tests.test_compose_services \
  server.tests.test_release_workflow -v                   # compose 结构 + 发版工作流
```

---

## 10. 回滚

- **面板**：更新器在替换前会备份到 `/opt/workbuddy-manager/data/` 下的备份目录；也可用上一
  个 Release 包重跑 `install.sh`（同样不触碰 `config.json` / `auths/` / `data/`）。
- **网关**：`git checkout` 或换回上一份源码后，在 `/opt/workbuddy2api` 执行
  `docker compose up -d --build`。
- **仓库可见性**：需要时可 `gh repo edit ... --visibility public` 再转回公开。
- 任何回滚都**不要**删除 `/opt/workbuddy2api/{config.json,auths,data}`。

---

## 11. 已知限制（迁移后需留意）

1. **私有仓库 + 内置更新器的鉴权缺口**：`deploy/update.py` 与 `server/services/updater.py`
   都是**不带凭据**地请求 `https://api.github.com/repos/ithtelab/workbuddy-manager/...`。
   仓库转私有后，版本检测会显示「未找到 Release」、一键更新无法下载发布包。
   Phase 1 未加入 token 支持。因此 §6.4 的一键更新冒烟要么在一个**可访问的更新源**上做
   （staging 用公开仓库），要么先为更新器补上凭据支持，否则该项应记为「阻塞」而不是「通过」。
   手动安装（§4，用已认证的 `gh` 下载）不受影响。
2. **多账号池分组**：默认 compose 只起默认分组；多分组需 `docker-compose.override.yml`，
   不要把分组压成单实例。
3. **`WB_UPSTREAM_DIR` 指向数据目录**：compose 拓扑下，面板里原「更新上游源码」不可用；
   更新网关代码用「一键更新」或仓库 `git pull && docker compose up -d --build`。
