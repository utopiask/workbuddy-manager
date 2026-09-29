'use client';

/**
 * 「导出账号」弹窗（账号页）。
 *
 * ## 为什么是弹窗、而不是在列表上直接勾选
 *
 * 账号列表是**按分组**展示的（顶部分组切换条一次只显示一组），而备份的诉求是
 * 「把几个号攒成一个文件」——这几个号完全可能散在不同分组里。所以这里自己把
 * **所有分组**的账号并起来给用户挑，一次导出成一个文件。
 *
 * ## 只读
 *
 * 导出**不改动任何账号**：读的是各分组账号目录里的原始文件（服务端 export
 * 端点），连备注都只是读面板库。导出后本地状态与上游状态逐字节不变。
 *
 * ## 文件里是明文凭据
 *
 * 备份包含 accessToken / refreshToken / device_token。弹窗里明确写出这一点，
 * 并给出下载后的文件名，避免用户随手丢进聊天窗口。
 */
import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {Download, Search} from 'lucide-react';

import {accountApi, errText} from '@/lib/api';
import {useT} from '@/lib/i18n/provider';
import {notify} from '@/lib/toast';
import type {Account, UpstreamEndpoint} from '@/lib/types';
import {Button} from '@/components/ui/button';
import {Input} from '@/components/ui/input';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/animate-ui/radix/dialog';
import {SkeletonBar} from '@/components/common/states/SkeletonBar';

/** 一行 = 「哪个分组的哪个账号」。key 必须同时含分组，否则不同组同名文件会撞。 */
type Row = {group: UpstreamEndpoint; account: Account};

const rowKey = (r: Row): string => `${r.group.id ?? 'default'}::${r.account.file}`;

/** 导出文件名带日期，方便「哪天的备份」一眼可辨。 */
function fileName(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `workbuddy-accounts-${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}.json`;
}

export function ExportAccountsDialog({
  open,
  onOpenChange,
  groups,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  /** 全部分组（含默认行）；每行有本地账号目录才有可导出的账号 */
  groups: UpstreamEndpoint[];
}) {
  const t = useT();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);

  // groups 是页面每次渲染重建的数组（心跳刷新会换新引用）。若把它写进 effect 的
  // 依赖，弹窗打开期间会随心跳反复重取账号；而 groups 为空时那个 `|| []` 更是
  // **每次渲染都是新数组**，会变成取数 → 渲染 → 再取数的死循环。所以这里用 ref
  // 读最新值，effect 只在「打开」这一刻触发一次（= 打开时的分组快照，够用）。
  const groupsRef = useRef(groups);
  groupsRef.current = groups;

  const load = useCallback(async () => {
    setRows(null);
    const perGroup = await Promise.all(
      groupsRef.current.map(async (g): Promise<Row[]> => {
        try {
          const res = await accountApi.list(g.is_default ? null : g.id);
          return (res.accounts ?? []).map((a) => ({group: g, account: a}));
        } catch {
          // 某一组读不到（未配目录 / 上游异常）不该让整个备份做不成：
          // 其余组照常可导，缺的那组在界面上就是「没有可选项」。
          return [];
        }
      }),
    );
    setRows(perGroup.flat());
  }, []);

  useEffect(() => {
    if (open) {
      setPicked(new Set());
      setQ('');
      void load();
    }
  }, [open, load]);

  const filtered = useMemo(() => {
    if (!rows) return [];
    const needle = q.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((r) =>
      `${r.account.nickname} ${r.account.uid}`.toLowerCase().includes(needle));
  }, [rows, q]);

  /** 按分组归拢（保持 groups 的顺序），只保留过滤后还有内容的组。 */
  const sections = useMemo(() => {
    const out: {group: UpstreamEndpoint; rows: Row[]}[] = [];
    for (const g of groups) {
      const rs = filtered.filter((r) => r.group.id === g.id && r.group.is_default === g.is_default);
      if (rs.length) out.push({group: g, rows: rs});
    }
    return out;
  }, [filtered, groups]);

  function toggle(key: string) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function submit() {
    if (!rows || picked.size === 0 || busy) return;
    setBusy(true);
    try {
      const items = rows
        .filter((r) => picked.has(rowKey(r)))
        .map((r) => ({
          upstream_id: r.group.is_default ? null : r.group.id,
          filename: r.account.file,
        }));
      const bundle = await accountApi.exportAccounts(items);
      const blob = new Blob([JSON.stringify(bundle, null, 2)], {type: 'application/json'});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = fileName();
      a.click();
      URL.revokeObjectURL(url);
      notify.ok(t('accounts.exportDone', {n: bundle.accounts.length}));
      onOpenChange(false);
    } catch (e) {
      notify.err(errText(e));
    } finally {
      setBusy(false);
    }
  }

  const allKeys = filtered.map(rowKey);
  const allPicked = allKeys.length > 0 && allKeys.every((k) => picked.has(k));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[520px]" showCloseButton>
        <DialogHeader>
          <DialogTitle>{t('accounts.exportTitle')}</DialogTitle>
          <DialogDescription>{t('accounts.exportDesc')}</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-3">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder={t('accounts.exportSearch')}
                className="h-9 pl-8"
              />
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="shrink-0 rounded-full"
              disabled={allKeys.length === 0}
              onClick={() => setPicked(allPicked ? new Set() : new Set(allKeys))}
            >
              {allPicked ? t('accounts.exportClear') : t('accounts.exportSelectAll')}
            </Button>
          </div>

          <div className="max-h-[46vh] overflow-y-auto rounded-xl ring-1 ring-border/60">
            {rows === null ? (
              <div className="space-y-2 p-3">
                {Array.from({length: 4}, (_, i) => (
                  <SkeletonBar key={i} className="h-8 w-full" />
                ))}
              </div>
            ) : sections.length === 0 ? (
              <div className="px-3 py-8 text-center text-xs text-muted-foreground">
                {t('accounts.exportEmpty')}
              </div>
            ) : (
              sections.map(({group, rows: rs}) => (
                <div key={`${group.id ?? 'default'}`} className="border-b border-border/40 last:border-b-0">
                  <div className="bg-muted/60 px-3 py-1.5 text-[11px] font-medium text-muted-foreground">
                    {group.is_default ? t('accounts.groupDefault') : group.name}
                  </div>
                  {rs.map((r) => {
                    const key = rowKey(r);
                    const name = r.account.nickname || r.account.uid;
                    return (
                      <label
                        key={key}
                        className="flex cursor-pointer items-center gap-2.5 px-3 py-2 hover:bg-muted/40"
                      >
                        <input
                          type="checkbox"
                          checked={picked.has(key)}
                          onChange={() => toggle(key)}
                          className="size-4 shrink-0 accent-primary"
                        />
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm">{name}</div>
                          <div className="truncate font-mono text-[10px] text-muted-foreground">
                            {r.account.uid}
                          </div>
                        </div>
                        {/* 与账号页同一套判定：面板改名停用、上游状态位停用、
                            上游按错误自动禁用，三种都算「已停用」。只读
                            `disabled` 会漏掉前两种——恰恰是最常见的两种。 */}
                        {r.account.disabled_by_panel === true
                          || r.account.manual_disabled === true
                          || r.account.disabled === true ? (
                          <span className="shrink-0 text-[10px] text-muted-foreground">
                            {t('accounts.exportDisabledTag')}
                          </span>
                        ) : null}
                      </label>
                    );
                  })}
                </div>
              ))
            )}
          </div>

          <p className="text-[11px] text-muted-foreground">
            {t('accounts.exportSelected', {n: picked.size})}
          </p>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" className="rounded-full" onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button
            className="rounded-full"
            disabled={busy || picked.size === 0}
            onClick={submit}
          >
            <Download className="h-4 w-4" />
            {t('accounts.exportConfirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
