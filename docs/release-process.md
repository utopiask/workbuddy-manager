# 发布流程（维护者手册）

本仓库把网关 `workbuddy2api` 收编为一等组件：源码在仓库 `gateway/`，与面板一起
构建、测试、打包与发布。发布链路因此收敛成一句话 —— **一个版本号、一个 tag，
网关源码由 CI 直接打进发布包**（包内沿用 `upstream/` 目录名）。

## 网关源码的归属与维护

- **来源**：`gateway/` 是原作者 Sliverkiss 的 `workbuddy2api`（MIT，见
  `gateway/LICENSE`）。该上游原仓库已被其作者删除，本仓库以**单次导入提交**收入
  源码快照，不合并其 git 历史（原始历史不可还原）。来源与维护约定写在
  `gateway/UPSTREAM-SRC.txt`。
- **许可**：MIT，版权归原作者。继续使用、修改、再分发都**必须保留**版权与
  许可声明，不得删除或改写版权行（`Copyright (c) 2026 Sliverkiss`）。
- **维护**：自导入起由本仓库维护与演进，不再依赖任何外部上游快照或载体 Release。
- **改动网关代码**：直接改仓库 `gateway/`，本地 `docker compose up -d --build`
  验证。改的是别人的 MIT 代码，务必保留其 `LICENSE` 与版权声明。
- **发版**：CI 从仓库 `gateway/` 复制成发布包内的 `upstream/`（并改写包内 compose
  的构建上下文）。源码因此天然落在签名产物里，不再单独分发。

## 两条耦合路径（Phase 2 才会消除）

管理端与网关之间有两条耦合路径，改网关代码时这两条都必须想到：

1. **转发路径**（网关 `/v1/*` → 上游）：改到**入站协议/响应形状**就必须同步改面板。
2. **直连路径**（管理端**绕过网关直连腾讯**）：扫码登录、签到、查积分、地区注册、
   trial、探测。这条路与网关各写一份参照实现，**改一边不会自动改另一边**。

第 2 类最容易漏：两边接口都返回 200，行为却已经不一致。

## 发版与签名

签名**默认可选**：不签名的 Release 也能发布、安装，更新器会在报告里留下一条
`warn` 级「该 Release 未签名（缺少 `.tar.gz.sig`）」提示，保证可审计；**签名存在时
永远强校验**，被篡改或不匹配一律拒绝安装。要恢复「缺签名即拒绝」的老行为，在
部署侧设 `WB_REQUIRE_SIGNATURE=1`。密钥管理与「为什么私钥不进 CI」见
[release-signing.md](release-signing.md)。

## 更新日志的写法：写给用户，不是写给同事

`CHANGELOG.md` 的每一条都会**原样出现在用户看得见的地方**：GitHub Release 页面
的正文（CI 从 CHANGELOG 抽取）、应用内「设置 → 更新日志」页。读者是**使用者**，
不是维护者。

这个坑反复踩过：修完一个自己引入的缺陷后，很容易顺手把排障过程写进去 ——
函数名、模块路径、「我错在哪」「已做反向验证」「用例变红」，以及大段的设计权衡
推演。这些对用户毫无价值，还会把「升级后我要做什么」这个真正有用的信息淹掉。
1.0.42 ~ 1.0.49 全线存在这个问题，所以现在有测试守着（见下）。

**写**：

- 用户会遇到什么现象、升级后有什么变化
- 引用报错时**照抄界面上那句原文**（用户就是拿它来搜的）
- 用户要动手的东西：环境变量、配置项、命令
- 「为什么这么设计」里**影响用户决策**的那部分（如「上限不再跟随上游配置，
  改用环境变量 X」）

**不写**：

- 函数名、模块路径、变量名、测试名、内部术语（事件循环、线程池……）
- 排障过程与自我检讨（「根因是我……」「已做反向验证」）
- 代码评审式的取舍推演（内部权衡放代码注释，提交信息里可以写）

**判据**：一个只用产品、不读代码的人，能否看懂这条对他有什么影响。

**唯一的例外**：用户界面上的**报错原文**要照抄（含内部术语也没关系）——
守卫测试按「该词是否出现在用户可见的文案里」自动放行。

守卫在 `server/tests/test_changelog.py::ChangelogIsUserFacingTest`：扫全部版本段落，
检测内部标识符、排障叙事、以及未被用户文案引用的框架术语。写错了跑测试就会报出来，
**发版前那次 `unittest discover` 是最后一道闸**。

## issue 回复的写法：同样写给用户

上面那条规矩同样适用于 issue 回复，而且更严：回复挂在**公开** issue 下面，读者不只是
报告者本人 —— 更多是后来搜到自己那条报错、点进来的普通用户。他想知道的只有两件事：
**这问题修了没有**、**我要不要做什么**。

我的惯性正好相反：写回复时刚写完代码和提交信息，顺手把同一套东西搬了过来 —— 内部
函数名、「我上一轮引入的错」「已验证 N 条单测」、以及报告者没问到的边界推演。报告者
看得懂，搜进来的用户一脸茫然。#45、#46 两条最典型，原文长这样：

> 三条建议都采纳了（commit `f20e6f9`，下个版本生效）……抽出 `keysvc.model_allowed`，
> 调用侧与列表裁剪都用它……**这里有个反直觉的坑，差点做成假警报**……
> 验证：全量 1222 条通过；e2e 全过；浏览器验收 14 项全过。

同一件事，写给用户的版本：

> 已经改好了，**下个版本（1.0.61）生效**，不需要你做任何操作。
>
> 白名单现在会同时**收窄 `/v1/models` 返回的列表**，与调用时的放行判据完全一致
> （此前只管调用、不管列表，两者会对不上：客户端看到「能选」，选中却报「模型不在
> 密钥白名单内」）。在「密钥」页填写白名单时输错了名字，输入框下方会**当场提示**，
> 不用等到调用失败才发现。
>
> 两处容易踩的边界也一并处理了：白名单里写**别名**（设置页「模型映射」里配过的名字）
> 会保留在列表里；`cn:` / `global:` 前缀可写可不写。模型清单还没取到时不会误报，
> 只提示能确定的部分。

**写**：

- 一句话结论：**修了没有**；修了就说清哪个版本生效（写到具体版本号，别只说「下个版本」）
- 用户要动手的步骤 —— 在哪个页面点什么、填什么
- 会影响用户的行为变化，尤其是「升级后你会看到什么不一样」
- 报告者的分析确实帮上忙时，一句致谢；不必逐条点评

**不写**：

- 内部标识符：函数名、模块路径、字段名、内部接口路径、提交哈希
- 排障过程与自我检讨（「差点做成假警报」「一个自己踩的坑，记一下」）
- 测试与验收清单（多少条通过、做了哪些反证）—— 那是提交信息的位置
- 报告者没问到的边界情况的推演；确有必要就写进文档，回复里一句带过

**判据**：一个搜到这条 issue、但不读代码的用户，能否看懂「我受不受影响、要不要做什么」。

**长度**：结论 + 步骤，十行以内。回复越长，上面那条判据越难得证。

**例外**（与更新日志同一原则）：界面上的**报错原文**照抄，含内部术语也没关系，
用户就是拿它来搜的。

### 口吻：像维护者本人在说话，别像客服

同一条信息，措辞不同读起来差别很大。要避免的是那种「模板腔」——它对用户没有
任何信息量，还会把真话稀释掉：

> ❌ 感谢您的反馈！我们已经修复了该问题，希望这能帮助到您。需要注意的是，……
> 如有任何疑问，请随时与我们联系。

同样内容，人话版：

> 修好了，1.0.63 里。只读账号现在跟管理员看到的是同一份积分；查不到实时值时会
> 标「上游快照」，也不会再标红了。有问题再开。

几条具体的：

- 别用「感谢您的反馈 / 希望有帮助 / 如有疑问随时联系 / 给您带来不便」这类句式
- 别用「首先……其次……最后」，也别把两句话硬拆成项目符号（项目符号留给真清单）
- 少用加粗和破折号：一条回复里最多一两处加粗，其余靠句子本身说清
- 不必复述用户已经写过的东西，直接说结论
- 「有问题再说 / 有情况回一声」是自然的收尾，不是敷衍

`dev/check_issue_reply.py` 是发帖前的自检：草稿存成文件跑一遍，它会指出内部标识符、
测试清单、检讨式叙事、客套模板腔和超长段落（用 `--issue` 传入报告原文，可豁免你
引用的那几句）。
规范本身由 `server/tests/test_issue_reply_style.py` 钉着 —— 上面那条真实回复当反例，
它必须报出来；改好的短回复必须放行。

## 发版步骤

```bash
# 1) 改版本号与更新日志（「未发布」→「[x.y.z] - 日期」）
#    server/main.py 的 version、CHANGELOG.md
python -m unittest discover -s server/tests -t .   # 全绿才继续

# 2) 提交并推送
git add -A && git commit -m "chore(release): vX.Y.Z"
git push origin main

# 3) 打 tag（CI 会构建并创建 Release，**CI 不签名**）
git tag vX.Y.Z && git push origin vX.Y.Z

# 4) 等 CI 完成后，在本机对**最终产物**签名并上传
gh release download vX.Y.Z --repo ithtelab/workbuddy-manager --pattern '*.tar.gz'
ssh-keygen -Y sign -f ~/.ssh/workbuddy-release -n file workbuddy-manager-vX.Y.Z.tar.gz
gh release upload vX.Y.Z workbuddy-manager-vX.Y.Z.tar.gz.sig \
  --repo ithtelab/workbuddy-manager

# 5) 重新下载验证（不要用刚签名的那份，要重新拉）
#    比对 sha256 → 用 deploy/update.py 的 check_signature 验签 → 解开核对版本号
```

不签名也能发布：默认放行未签名包（只在更新日志里留一条 `warn`）。但**推荐按上面
步骤签名**——部署侧只要设了 `WB_REQUIRE_SIGNATURE=1`，缺 `.sig` 就会被拒绝安装；
而且签名存在时永远强校验，签一次就多一层保障。

## 多人协作时的分工

仓库有 write 权限的协作者**可以直接推 tag**，推了就触发 CI 建 Release——但
他们**签不了名**（私钥只在维护者本机，这是设计如此）。所以协作发版的分工是
「**协作者准备，维护者签字**」：

**协作者可以独立完成的部分**

```bash
# 改 .version 与 server/main.py 的 version、CHANGELOG.md 加段落
python -m unittest discover -s server/tests -t .   # 全绿
# 走 PR 合入 main，再推 tag
git tag vX.Y.Z && git push origin vX.Y.Z
```

**维护者收尾（只有这三步）**

```bash
gh release download vX.Y.Z --repo ithtelab/workbuddy-manager --pattern '*.tar.gz'
ssh-keygen -Y sign -f ~/.ssh/workbuddy-release -n file workbuddy-manager-vX.Y.Z.tar.gz
gh release upload vX.Y.Z workbuddy-manager-vX.Y.Z.tar.gz.sig \
  --repo ithtelab/workbuddy-manager
```

签名前核对密钥没拿错：`ssh-keygen -lf ~/.ssh/workbuddy-release.pub` 应输出
`SHA256:xmHLJDKH/vYtAp59XwXPVE4A/CwXAOpxTlYh7KC677Y`。

**协作者发完版、维护者没签之前，设了 `WB_REQUIRE_SIGNATURE=1` 的部署会拒绝更新**
——这不是故障，是防线在工作（默认配置则放行并在日志里提示未签名）。发现 Release
缺 `.sig` 时，按上面三步补签即可，不必重跑 CI。

> tag 与 main 分支都有保护规则（见下节）：协作者不能创建/删除 `v*` tag，
> 也不能直接往 main 推。这不是不信任，而是让「能改代码」与「能发布可信产物」
> 保持分离——这正是签名机制要解决的问题。

## 仓库保护规则

用 **ruleset**（不是旧的 branch protection）配置，因为 tag 保护只有 ruleset 支持。

| 规则 | 作用 |
|---|---|
| `protect-tags` (id 23464783) | `refs/tags/**` 的创建/删除/移动仅 admin 可做 |
| `protect-main` (id 23465105) | main 禁止删除与强推，且**必须走 PR**（至少 1 个批准） |

```bash
# 查看
gh api repos/ithtelab/workbuddy-manager/rulesets \
  --jq '.[] | "\(.id) \(.name) \(.target)"'
```

### bypass_actors 的 actor_id 是未公开的映射，别猜

`bypass_actors` 里的 `actor_id` 对 `RepositoryRole` 而言**没有被 GitHub 官方文档
记录**，而且**不是顺序编号**——按直觉填会出事：

| 角色 | actor_id |
|---|---|
| maintain | 2 |
| write | 4 |
| **admin** | **5** |

（有人按「read=1, triage=2, write=3, maintain=4, admin=5」推断后填了 4，
结果**任何 write 权限的人都能绕过**规则。）

这里用的是 `5`（admin）。这个值可以用 GraphQL 直接把角色名读出来核对——
REST 接口只回显整数，GraphQL 会给出 `repositoryRoleName`：

```bash
gh api graphql -f query='{ repository(owner:"ithtelab", name:"workbuddy-manager") {
  rulesets(first:10){ nodes { name target bypassActors(first:20){
    nodes { repositoryRoleDatabaseId repositoryRoleName bypassMode } } } } } }'
```

应输出 `admin(id=5)/ALWAYS`。**改动这条规则后请重新核对一次**：写错的后果是
保护静默失效，而界面上看起来一切正常。

> 用角色而不是具体用户，是为了以后增减管理员时不用改规则。

## 为什么签名不能自动化

私钥不进 CI：恶意 PR 合并后可以改 workflow 的任意步骤，密钥放那里等于直接
交给攻击者。签名必须由维护者在本机执行。详见 [release-signing.md](release-signing.md)。

## 如果网络不稳

下载产物时若**体积小于 GitHub 报告的大小**，是下载被截断（本机代理不稳），
不是产物被动过——用 `curl -C -` 续传后重新比对 sha256 即可。
验签会正确拒绝截断的文件，这是设计如此。
