'use client';

/**
 * 「导入账号备份」弹窗（账号页）。
 *
 * ## 增量，不覆盖式还原
 *
 * 导入**只增不删**：备份里没有的现有账号原封不动。同 uid 已存在时由用户选
 * 「跳过（保留现有）」或「覆盖（用备份替换）」——把选择权交出来而不是替用户猜，
 * 因为覆盖会换掉 accessToken / refreshToken，可能让该号在别处的登录失效。
 *
 * ## 单条失败不阻断
 *
 * 备份可能来自更早的版本、或被手工改过。非法条目（uid 形态、缺 accessToken）
 * 由服务端逐条拒收并回报原因，其余照常导入——而不是整包失败让用户无从下手。
 *
 * ## 按分组恢复
 *
 * 跨分组导出的备份里每条都记着自己的来源分组。勾上「按备份中的分组恢复」就按
 * 分组**名**落回（分组被删/改名时落到上面选的目标分组），适合整机迁移。
 *
 * 客户端只做「看起来像不像本面板的备份」的预检，真正的校验在服务端。
 */
import {useEffect, useRef, useState} from 'react';
import {FileUp, TriangleAlert} from 'lucide-react';

import {accountApi, errText} from '@/lib/api';
import {useT} from '@/lib/i18n/provider';
import {notify} from '@/lib/toast';
import type {AccountBackup, AccountImportResult, UpstreamEndpoint} from '@/lib/types';
import {Button} from '@/components/ui/button';
import {Label} from '@/components/ui/label';
import {Switch} from '@/components/ui/switch';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/animate-ui/radix/dialog';

/** 默认分组在 Select 里的值（后端约定：0 / null = 默认分组） */
const DEFAULT_VALUE = '__default__';
const FORMAT = 'workbuddy-manager/accounts-backup';

export function ImportAccountsDialog({
  open,
  onOpenChange,
  groups,
  defaultUpstreamId,
  onImported,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  /** 全部分组（含默认行）；无本地目录的组不能作为目标 */
  groups: UpstreamEndpoint[];
  /** 打开时默认选中的目标分组（当前正在看的组）；null = 默认分组 */
  defaultUpstreamId: number | null;
  onImported?: () => void;
}) {
  const t = useT();
  const [bundle, setBundle] = useState<AccountBackup | null>(null);
  const [fileName, setFileName] = useState('');
  const [parseErr, setParseErr] = useState('');
  const [target, setTarget] = useState(DEFAULT_VALUE);
  const [mode, setMode] = useState<'skip' | 'overwrite'>('skip');
  const [restore, setRestore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AccountImportResult | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setBundle(null);
    setFileName('');
    setParseErr('');
    setMode('skip');
    setRestore(false);
    setResult(null);
    // 默认落到「当前正在看的分组」：从哪一组的页面发起的恢复，多半就想还原到哪
    setTarget(defaultUpstreamId == null ? DEFAULT_VALUE : String(defaultUpstreamId));
  }, [open, defaultUpstreamId]);

  async function onPick(file: File | undefined) {
    if (!file) return;
    setParseErr('');
    setResult(null);
    setFileName(file.name);
    try {
      const parsed = JSON.parse(await file.text()) as AccountBackup;
      if (!parsed || parsed.format !== FORMAT || !Array.isArray(parsed.accounts)) {
        setBundle(null);
        setParseErr(t('accounts.importBadFile'));
        return;
      }
      setBundle(parsed);
    } catch {
      setBundle(null);
      setParseErr(t('accounts.importBadFile'));
    }
  }

  async function submit() {
    if (!bundle || busy) return;
    setBusy(true);
    try {
      const r = await accountApi.importAccounts({
        bundle,
        upstream_id: target === DEFAULT_VALUE ? null : Number(target),
        mode,
        restore_groups: restore,
      });
      setResult(r);
      onImported?.();
      if (r.imported + r.overwritten > 0) notify.ok(t('accounts.importDone'));
    } catch (e) {
      notify.err(errText(e));
    } finally {
      setBusy(false);
    }
  }

  // 目标候选：没有本地账号目录的组收不了账号（后端会 409），直接不给选。
  const candidates = groups.filter((g) => !!g.auth_dir);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[460px]" showCloseButton>
        <DialogHeader>
          <DialogTitle>{t('accounts.importTitle')}</DialogTitle>
          <DialogDescription>{t('accounts.importDesc')}</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-3">
          <input
            ref={fileRef}
            type="file"
            accept=".json,application/json"
            className="hidden"
            onChange={(e) => void onPick(e.target.files?.[0])}
          />
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              className="rounded-full"
              onClick={() => fileRef.current?.click()}
            >
              <FileUp className="h-4 w-4" />
              {bundle ? t('accounts.importRepick') : t('accounts.importPick')}
            </Button>
            {fileName ? (
              <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground" title={fileName}>
                {fileName}
              </span>
            ) : null}
          </div>

          {parseErr ? (
            <p className="text-xs text-destructive">{parseErr}</p>
          ) : bundle ? (
            <p className="text-xs text-muted-foreground">
              {t('accounts.importParsed', {n: bundle.accounts.length})}
            </p>
          ) : null}

          <div className="space-y-1.5">
            <Label className="text-[11px] text-muted-foreground">
              {t('accounts.importTargetLabel')}
            </Label>
            <Select value={target} onValueChange={setTarget}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {candidates.map((g) => (
                  <SelectItem
                    key={g.is_default ? DEFAULT_VALUE : String(g.id)}
                    value={g.is_default ? DEFAULT_VALUE : String(g.id)}
                  >
                    {g.is_default ? t('accounts.groupDefault') : g.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 space-y-0.5">
              <Label className="text-[11px]">{t('accounts.importRestoreGroups')}</Label>
              <p className="text-[11px] leading-4 text-muted-foreground">
                {t('accounts.importRestoreGroupsHint')}
              </p>
            </div>
            <Switch checked={restore} onCheckedChange={setRestore} className="mt-0.5 shrink-0" />
          </div>

          <div className="space-y-1.5">
            <Label className="text-[11px] text-muted-foreground">
              {t('accounts.importModeLabel')}
            </Label>
            <Select value={mode} onValueChange={(v) => setMode(v as 'skip' | 'overwrite')}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="skip">{t('accounts.importModeSkip')}</SelectItem>
                <SelectItem value="overwrite">{t('accounts.importModeOverwrite')}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {mode === 'overwrite' && !result ? (
            <div className="flex items-start gap-2 rounded-xl bg-amber-500/10 px-3 py-2 text-[11px] leading-4 text-amber-700 ring-1 ring-amber-500/20 dark:text-amber-400">
              <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{t('accounts.importOverwriteWarn')}</span>
            </div>
          ) : null}

          {result ? (
            <div className="space-y-1.5 rounded-xl bg-muted px-3 py-2.5">
              <p className="text-xs font-medium">
                {t('accounts.importSummary', {
                  imported: result.imported,
                  overwritten: result.overwritten,
                  skipped: result.skipped,
                })}
              </p>
              {result.failed.length > 0 ? (
                <div className="space-y-1">
                  <p className="text-[11px] font-medium text-destructive">
                    {t('accounts.importFailedLabel', {n: result.failed.length})}
                  </p>
                  <ul className="space-y-0.5">
                    {result.failed.slice(0, 10).map((f, i) => (
                      <li key={`${f.uid}-${i}`} className="truncate text-[11px] text-muted-foreground">
                        <span className="font-mono">{f.uid || '?'}</span> · {f.reason}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : null}
        </DialogBody>
        <DialogFooter>
          {result ? (
            <Button className="rounded-full" onClick={() => onOpenChange(false)}>
              {t('accounts.importClose')}
            </Button>
          ) : (
            <>
              <Button variant="outline" className="rounded-full" onClick={() => onOpenChange(false)}>
                {t('common.cancel')}
              </Button>
              <Button className="rounded-full" disabled={busy || !bundle} onClick={submit}>
                {busy ? t('accounts.importing') : t('accounts.importConfirm')}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
