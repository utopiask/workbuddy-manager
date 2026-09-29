# WorkBuddy Monorepo 设计（Phase 1）

- 日期：2026-09-29
- 状态：待评审
- 范围：仅 Phase 1（把网关并入私有一等公民仓库）。Phase 2（统一腾讯直连逻辑）另立 spec。
- 前置决定（已与维护者确认）：
  1. 目标形态 = 单一私有仓库（monorepo），两个运行时进程不变。
  2. 网关目录命名 `gateway/`。
  3. 运行时拓扑（面板对外 `:7864`、网关仅内部 `:7863`）**不变**。
  4. 部署 = 单 compose 两个服务；`docker.sock` 在 Phase 1 保留。
  5. 交付 = 发布包只带网关源码，安装时构建。
  6. 单一版本号、一个 tag；签名降为可选；退役 `upstream-src` 载体链路。
  7. 只需服务维护者自己的部署，发布/安装机制可自由重塑。

---

## 1. 背景与动机

当前 `workbuddy-manager`（面板）与 `workbuddy2api`（Go 网关）是两个独立代码体：

- 面板：公开仓库 `utopiask/workbuddy-manager`，Python FastAPI + Next.js + 大量测试。
- 网关：原上游仓库 `Sliverkiss/workbuddy2api` **自 2026-09-23 起不可访问、已被作者删除**，
  源码由维护者以「本地归档」形式留存，经 `dev/pack_upstream_src.py` 打成
  `workbuddy2api-src.tar.gz`，上传到固定 pre-release 载体（tag `upstream-src`），
  再由面板 CI 在发版时注入到发布包的 `upstream/` 目录。

这套机制导致的问题：

1. **源码没有独立版本控制**：网关只活在压缩包与 Release 附件里，无仓库、无逐版本历史。
2. **交付链路绕**：打包脚本 → 载体 Release → CI 注入 → 安装脚本再同步，任何一环出错都难查。
3. **两份 compose、两套流程**：面板与网关各自 compose，靠脚本接力安装。
4. **文档策略与事实背离**：手册要求「不把上游代码提交进本仓库」，但维护者实际上已在持续
   修改并维护这份代码（如 2026-09-28 对 scheduler 的修复）。

维护者已决定：**把仓库转私有**，并承认对网关代码的维护责任，从而将网关作为一等公民收进
同一仓库。转私有后，「公开镜像上游代码」的顾虑不再成立，策略层面的阻塞解除。

## 2. 目标与非目标

**目标**

- 一个私有 git 仓库同时容纳面板与网关，一个版本号、一个 tag、一次发版。
- 运行时架构与行为**零变化**（面板仍是唯一入口，网关仍是内部数据面）。
- 显著简化发布与安装链路，删除为「外部快照」而存在的整套周转机制。
- 保留网关的 MIT 许可与原作者版权声明。
- 保证现有账号数据（`config.json` / `auths/` / `data/`）在迁移后原样可用。

**非目标（Phase 1 不做）**

- 不把网关与面板合并为单进程 / 单镜像（那是方案 B，后续可选）。
- **不统一**两条耦合路径的重复实现——统一腾讯直连逻辑属于 **Phase 2**，另立 spec。
- 不重写任何一侧的语言。
- 不做网关 git 历史还原（原始逐版本历史已不可还原，采用单次导入提交）。

## 3. 目标仓库结构

```
workbuddy-manager/                (私有)
├─ gateway/                       ★新增：Go 网关（原上游快照），自成一个 go module
│   ├─ cmd/  internal/  scripts/
│   ├─ go.mod  go.sum  Dockerfile  config.example.json
│   └─ LICENSE                    （保留原作者 MIT 版权与声明）
├─ server/                        Python 面板后端（保持不动）
├─ web/                           Next.js 前端源码（保持不动）
├─ deploy/                        安装 / 更新脚本（改造，见 §6）
├─ dev/                           内部工具（pack_upstream_src.py 退役）
├─ docs/                          文档（release-process.md 改写）
├─ CHANGELOG.md  .version
├─ docker-compose.yml             ★改造为同时编排两个服务
└─ Makefile                       ★新增：统一三套工具链的构建入口
```

## 4. 组件边界与运行时拓扑（不变）

| 组件 | 角色 | 语言 | 对外暴露 |
|---|---|---|---|
| `gateway/` | 数据面：账号池 / 加权选号 / 熔断冷却 / 会话粘性 / 流式（SSE） | Go | 仅 `:7863`，compose 内网 |
| `server/` | 控制面 + 反代：鉴权 / 密钥分发 / 配额 / IP 管控 / 统计 / 协议适配 | Python | `:7864`（经反向代理） |
| `web/` | 管理界面 | Next.js（静态导出 `out/`） | 由面板托管 |

- 客户端仍**只连面板**，输入「面板地址 + 面板密钥」。
- 网关仍是**可独立运行的二进制**，多账号池分组能力保留：分组需要多实例时，用 compose
  override 再起 `workbuddy2api-b`（`:7865` …），`upstreamsvc` 配置方式不变。
- 面板 ↔ 网关的耦合点维持现状：HTTP 转发（`WB2API_BASE`）、共享文件目录
  （`config.json` / `auths/`）、`docker.sock`（重载 / 读日志）。

## 5. 构建、CI 与版本

**统一构建入口**：仓库根 `Makefile`，本地与 CI 共用同一套命令。

```
make test      # gateway: go test ./...   server: python -m unittest discover   web: build
make build     # gateway 二进制/镜像 + web/out
make package   # 组装发布包
```

**CI**：单个 workflow，`v*` tag 触发。三个并行 job：

- `gateway`：`go vet` + `go test ./...` + `go build`
- `python`：`python -m unittest discover -s server/tests -t .`
- `web`：`npm ci && npm run build`

三个 job 全绿后，进入 `package` job 产出发布包（此前只有 Python 测试守门，现三套测试
同时成为发版闸门）。

**版本**：`.version` 作为唯一版本来源，同时驱动面板与网关（网关二进制经 `-ldflags`
注入版本号）；`CHANGELOG.md` 仍为一份。

**发布**：一个 tag `vX.Y.Z` 即产出发布包。**删除** `upstream-src` 载体 Release 与 CI
注入 `upstream/` 的逻辑。**签名从「强制」降为「可选」**：保留 `deploy/update.py` 的
签名校验能力，但不再把缺失 `.sig` 作为拒绝更新/发版的硬门槛。

## 6. 部署、安装与迁移

**单 compose（根 `docker-compose.yml`）**：

```
services:
  workbuddy-web:   # 面板：server + web/out，对外 :7864
  workbuddy2api:   # 网关：仅 compose 内网，面板经 http://workbuddy2api:7863 访问
```

`docker.sock` 在 Phase 1 保留（面板依赖它重载网关 / 读日志）；在方案 B（单镜像）时移除。

**脚本改造**：

| 脚本 | 现状 | 合并后 |
|---|---|---|
| `deploy/install.sh` | 取 `upstream/` 或 `UPSTREAM_SRC` | 从仓库 / 包内 `gateway/` 取，其余不变 |
| `deploy/update.py` | 校验并同步 `upstream-src` 载体 | 去掉载体逻辑；签名校验降为可选 |
| `dev/pack_upstream_src.py` | 打 `workbuddy2api-src.tar.gz` | **退役** |
| `deploy/check-upstream.sh` | 核对上游提交 | **退役**（网关在仓库内） |

**安装语义**：`install.sh` 从 `gateway/` 同步**代码**到 `/opt/workbuddy2api`，再
`docker compose up -d --build`；同步只增改代码，**绝不触碰** `/opt/workbuddy2api/{config.json,
auths,data}` 三样。面板的安装（systemd `workbuddy-web.service`）不变。

**维护者自身迁移步骤（一次性）**：

1. 将 `utopiask/workbuddy-manager` 转为私有，或新建私有仓库。
2. 将网关源码以**单次导入提交**放入 `gateway/`（不合并历史）。
3. 合入 §3–§6 的目录与脚本改造，推 `vX.Y.Z` tag 走新 CI 出包。
4. 目标机用新 `install.sh` 覆盖安装一次；`/opt/workbuddy2api/{config.json,auths,data}`
   原样保留，无需数据迁移。
5. 此后统一「一个仓库、一个 tag、一条 compose」。

## 7. 测试与文档

- 三套测试纳入统一 CI 并发版闸门（见 §5）。
- `gateway/LICENSE` 保留原作者 MIT 版权与声明，README 注明来源与许可。
- 改写 `docs/release-process.md`：删除「不把上游代码提交进本仓库、不另开公开镜像」一节
  （策略已随转私有失效），更新发版步骤为单一 tag。
- 更新 README 中「与 workbuddy2api 的关系」为「本仓库的网关」。

## 8. 风险与待决

- **`update.py` / `install.sh` 改造风险**：两者体量大、带签名与幂等逻辑，改造需以现有
  实测部署回归验证。
- **双工具链 CI**：Go + Python + Node 三段构建，需确保缓存与失败可见性。
- **Windows 侧脚本**：仓库含 `start.ps1` / `service-tools.ps1` 等，网关源码路径引用需一并核对。
- **签名**：本 spec 定为「可选」；若后续仍要发布给他人，需重新评估是否恢复强制签名。
- **待决**：Phase 1 是否顺带加「转发路径」的契约测试（成本低、收益直接）；建议在实施计划中作为可选任务。

## 9. Phase 2 预告（不在本 spec 范围）

统一「面板绕过网关直连腾讯」与「网关内部直连腾讯」的重复实现。已确认方向：**面板为唯一实现**——
控制面接管签到 / 积分 / 模型目录 / trial / 地区 / 探测的直连；网关**退役** scheduler 与
`cmd/{login,checkin,credit,trial,activity}`，仅保留**请求路径内**的 token 被动刷新
（与面板的闲置主动续期属不同关注点）。该子系统独立设计、独立验证，另立 spec。
