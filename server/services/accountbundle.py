"""账号备份包（导出 / 导入）的格式与校验。

## 文件格式（version 1）

```json
{
  "format": "workbuddy-manager/accounts-backup",
  "version": 1,
  "exported_at": "2026-09-29T17:00:00+08:00",
  "accounts": [
    {
      "uid": "00000000-0000-0000-0000-000000000000",
      "nickname": "示例账号",
      "realm": "cn",
      "disabled": false,
      "group": {"id": 2, "name": "示例分组"},
      "note": "示例备注",
      "content": { "...原始账号文件 JSON，逐字段保留..." }
    }
  ]
}
```

## 为什么 `content` 存整份原始文件、而不是挑字段重组

账号文件里除了上游认识的 `account` / `auth`，还有顶层 `device_token` 这类设备
风控凭据，以及将来可能出现的新字段。`tencent.write_auth_file` 是按已知字段
**重组**的，用它导入会把这些字段静默丢掉——表现为「换机后账号能用，但风控形态
降级」。备份的价值就在于逐字段还原，所以这里存整份、导入时整份写回。

## 为什么单独成一个模块

格式常量、uid 白名单、版本校验都是导入与导出**共用**的契约；放在路由里会让
两处分头维护同一套规则，最容易出现「导出放宽、导入收紧」的不一致。这里集中一份。
"""
from __future__ import annotations

import datetime
import re

FORMAT = 'workbuddy-manager/accounts-backup'
VERSION = 1

# uid 白名单与 tencent.write_auth_file 同口径：uid 会拼进文件名并落到 auths
# 目录，来自外部输入，因此必须限死字符集，否则 `../x` 之类会拐出目录。
UID_RE = re.compile(r'[0-9A-Za-z_-]{1,80}')


def entry_filename(uid: str, disabled: bool = False) -> str:
    """由 uid 推出落盘文件名（`.disabled` 表示禁用态）。非法 uid 抛 ValueError。"""
    uid = str(uid or '')
    if not UID_RE.fullmatch(uid):
        raise ValueError(f'账号 uid 形态异常，已拒绝（{uid[:40]!r}）')
    name = f'workbuddy-{uid}.json'
    return name + '.disabled' if disabled else name


def build(entries: list[dict], *, now: datetime.datetime | None = None) -> dict:
    """把条目列表包成备份信封。"""
    stamp = (now or datetime.datetime.now().astimezone()).replace(microsecond=0)
    return {
        'format': FORMAT,
        'version': VERSION,
        'exported_at': stamp.isoformat(),
        'accounts': list(entries),
    }


def parse(raw: object) -> list[dict]:
    """校验信封并返回 accounts 列表。格式不对抛 ValueError（消息给用户看）。"""
    if not isinstance(raw, dict):
        raise ValueError('备份文件格式不对：顶层不是 JSON 对象')
    if raw.get('format') != FORMAT:
        raise ValueError('这不是 WorkBuddy Manager 的账号备份文件（format 不匹配）')
    try:
        version = int(raw.get('version') or 0)
    except (TypeError, ValueError):
        version = -1
    if version != VERSION:
        raise ValueError(f'备份文件版本不支持（需要 {VERSION}，收到 {raw.get("version")!r}）')
    accounts = raw.get('accounts')
    if not isinstance(accounts, list):
        raise ValueError('备份文件缺少 accounts 列表')
    return accounts
