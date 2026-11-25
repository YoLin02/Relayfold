import { LoaderCircle, ScanLine, Send, Smartphone } from 'lucide-react';
import type { GroupMode } from '@/types';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { MediaPreview } from './media-preview';
import { contentKinds, coverName, customPlatforms, fileName, groupModes, maxAccountsPerAdd, parseTags, type Confirmation } from './model';
import type { PublisherWorkspace } from './use-workspace';
import { formatSchedule, scheduleInput, scheduleTimestamp } from './schedule';
import { ErrorNotice, PlatformMark, WorkspaceField, WorkspaceSelect } from './workspace-ui';

function GroupDialog({ workspace }: { workspace: PublisherWorkspace }) {
  const { groupEditor, pending, error } = workspace.state;
  if (!groupEditor) return null;
  const { group, name, mode } = groupEditor;
  const newName = name.trim();
  const canSave = !!newName && newName !== group?.name && !workspace.isBusy;
  const close = () => workspace.update({ groupEditor: null, error: '' });
  return <Dialog open onOpenChange={open => { if (!open && !pending) close(); }}>
    <DialogContent>
      <DialogHeader>
        <DialogTitle>{group ? '重命名发布组' : '新建发布组'}</DialogTitle>
        <DialogDescription>{group ? `为「${group.name}」输入新名称。` : '为另一套平台账号建立独立的登录会话。'}</DialogDescription>
      </DialogHeader>
      {error && <ErrorNotice>{error}</ErrorNotice>}
      <form className="grid gap-4" onSubmit={event => {
        event.preventDefault();
        if (!canSave) return;
        if (group) {
          void workspace.run('rename-group', () => window.publisher.request('groups.rename', { id: group.id, name: newName }),
            () => workspace.update({ groupEditor: null, notice: `已改名为「${newName}」。` }));
        } else {
          void workspace.run('create-group', () => window.publisher.request('groups.create', { name: newName, mode }), () => {
            workspace.update({ groupEditor: null, view: 'accounts', category: 'all', accountState: 'all', search: '',
              notice: `已创建「${newName}」。${mode === 'custom' ? '可在平台账号页添加账号。' : '绑定平台账号后即可发布。'}` });
          });
        }
      }}>
        <WorkspaceField label="发布组名称"><Input value={name} maxLength={30} placeholder="例如 品牌账号"
          onChange={event => workspace.update({ groupEditor: { ...groupEditor, name: event.target.value } })} /></WorkspaceField>
        {!group && <RadioGroup aria-label="发布组类型" value={mode} disabled={workspace.isBusy}
          onValueChange={value => workspace.update({ groupEditor: { ...groupEditor, mode: value as GroupMode } })}
          className="grid gap-2 sm:grid-cols-2">
          {(Object.entries(groupModes) as [GroupMode, typeof groupModes[GroupMode]][]).map(([value, info]) => (
            <label key={value} className="flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2.5 transition-colors hover:bg-muted/65 has-[[data-state=checked]]:border-ring has-[[data-state=checked]]:bg-muted">
              <RadioGroupItem value={value} aria-label={info.label} className="mt-0.5 shrink-0" />
              <span className="grid gap-1"><span className="text-sm font-medium">{info.label}</span>
                <span className="text-xs text-muted-foreground">{info.description}</span></span>
            </label>
          ))}
        </RadioGroup>}
        <DialogFooter>
          <Button type="button" variant="outline" disabled={!!pending} onClick={close}>取消</Button>
          <Button type="submit" disabled={!canSave}>{group ? '保存名称' : '创建发布组'}</Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>;
}

function AddAccountsDialog({ workspace }: { workspace: PublisherWorkspace }) {
  const { accountAdder, pending, error } = workspace.state;
  if (!accountAdder) return null;
  const { groupId, platform, count } = accountAdder;
  const quantity = Number(count);
  const options = workspace.regionPlatforms.map(item => ({ value: item.id, label: item.label }));
  const selected = options.find(option => option.value === platform);
  const canAdd = !!selected && Number.isInteger(quantity) && quantity >= 1 && quantity <= maxAccountsPerAdd && !workspace.isBusy;
  const close = () => workspace.update({ accountAdder: undefined, error: '' });

  return <Dialog open onOpenChange={open => { if (!open && !pending) close(); }}>
    <DialogContent>
      <DialogHeader><DialogTitle>添加平台账号</DialogTitle>
        <DialogDescription>选择平台和数量。添加后可分别扫码绑定每个账号。</DialogDescription>
      </DialogHeader>
      {error && <ErrorNotice>{error}</ErrorNotice>}
      <form className="grid gap-4" onSubmit={event => {
        event.preventDefault();
        if (!canAdd) return;
        void workspace.run('add-accounts', () => window.publisher.request('accounts.add', { group_id: groupId, platform, count: quantity }),
          () => workspace.update({ accountAdder: undefined, category: 'all', accountState: 'all', search: '',
            notice: `已添加 ${quantity} 个${selected.label}账号。` }));
      }}>
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_7rem]">
          <WorkspaceField label="平台"><WorkspaceSelect value={platform} label="平台"
            options={[{ value: '', label: '选择平台' }, ...options]} disabled={workspace.isBusy} showScrollButtons={false}
            onValueChange={value => workspace.update({ accountAdder: { ...accountAdder, platform: value } })} /></WorkspaceField>
          <WorkspaceField label="账号数量"><Input type="number" min={1} max={maxAccountsPerAdd} step={1}
            value={count} disabled={workspace.isBusy}
            onChange={event => workspace.update({ accountAdder: { ...accountAdder, count: event.target.value } })} /></WorkspaceField>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" disabled={!!pending} onClick={close}>取消</Button>
          <Button type="submit" disabled={!canAdd}>添加账号</Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>;
}

type LoginField = { key: string; label: string; placeholder?: string; hint?: string; password?: boolean };
const cmsFields: LoginField[] = [
  { key: 'api_base', label: 'CMS API 基址', placeholder: 'https://example.com/api/v1' },
  { key: 'api_username', label: 'CMS 用户名' },
  { key: 'cms_site_id', label: 'CMS 站点 ID', hint: '站点接口不返回域名时填写' },
  { key: 'cms_category_id', label: 'CMS 分类 ID', hint: '按站点要求填写' },
];

function AccountDialog({ workspace }: { workspace: PublisherWorkspace }) {
  const { account, error, pending } = workspace.state;
  const close = () => workspace.update({ account: undefined, error: '' });
  const info = account && workspace.platforms[account.binding.platform];
  if (!account || !info) return null;
  const { binding, settings, label, opened } = account;
  const isApi = info.mode === 'api';
  const scan = customPlatforms.has(info.id);
  const group = workspace.groups.find(item => item.id === binding.group_id);
  const name = workspace.bindingName(binding);
  const configure = info.mode === 'custom_browser' && !binding.label;
  const isCmsApi = info.id === 'company_website_v2';
  const fields: LoginField[] = [
    ...(configure || isCmsApi ? [{ key: 'website_url', label: info.id === 'company_website' ? 'CMS 文章管理页' : '目标站点 HTTPS 地址', placeholder: 'https://' }] : []),
    ...(isCmsApi ? cmsFields : []),
    ...(isApi ? [{ key: 'api_password', label: info.id === 'devto' ? 'DEV API Key' : 'CMS 密码', password: true }] : []),
  ];
  return <Dialog open onOpenChange={open => { if (!open && !pending) close(); }}>
    <DialogContent className="max-h-[calc(100dvh-1.5rem)] overflow-auto sm:max-w-lg">
      <DialogHeader>
        <DialogTitle className="text-lg font-semibold">绑定{name}{group?.mode === 'custom' ? '' : '账号'}</DialogTitle>
        <DialogDescription className={isApi ? undefined : 'sr-only'}>
          {isApi ? `${info.note}凭据加密保存在本机。` : '在独立窗口登录并核对账号，再回到这里确认。'}
        </DialogDescription>
      </DialogHeader>
      {group && <div><Badge variant="secondary">{group.name}</Badge></div>}
      {error && <ErrorNotice>{error}</ErrorNotice>}
      <div className="grid gap-3">
        {fields.map(field => <WorkspaceField key={field.key} label={field.label} hint={field.hint}>
          <Input type={field.password ? 'password' : 'text'} autoComplete={field.password ? 'new-password' : 'off'}
            value={settings[field.key] || ''} placeholder={field.placeholder} onChange={event => {
              const value = event.target.value;
              workspace.update(current => current.account ? {
                account: { ...current.account, settings: { ...current.account.settings, [field.key]: value } },
              } : {});
            }} />
        </WorkspaceField>)}
        {!isApi && <div className="flex flex-wrap items-center gap-3 rounded-xl bg-muted/75 p-3">
          {scan ? <ScanLine className="size-5 shrink-0" /> : <Smartphone className="size-5 shrink-0" />}
          <div className="min-w-30 flex-1 space-y-0.5">
            <div className="text-sm font-medium">{scan ? '扫码登录' : '平台登录'}</div>
            <p className="text-xs text-muted-foreground">{scan ? '在独立窗口扫码，登录后返回此处。' : '在独立窗口登录后返回此处。'}</p>
          </div>
          <div className="ml-auto grid justify-items-end gap-1.5">
            <span className="text-xs text-muted-foreground">{opened ? '请登录后确认' : scan ? '等待扫码' : '等待登录'}</span>
            <Button variant="outline" className="bg-background shadow-xs" size="sm" disabled={workspace.isBusy} onClick={() => void workspace.run('open-login',
              () => window.publisher.request(configure ? 'accounts.configure' : 'accounts.open', { id: binding.id, settings }),
              () => workspace.update(current => current.account ? { account: { ...current.account, opened: true } } : {}))}>
              {pending === 'open-login' && <LoaderCircle className="animate-spin" data-icon="inline-start" />}
              {opened ? '重新打开登录窗口' : scan ? '打开扫码窗口' : '打开登录窗口'}
            </Button>
          </div>
        </div>}
        <WorkspaceField label="账号昵称或备注"><Input value={label} maxLength={40} placeholder={`例如 ${info.label}运营号`}
          onChange={event => {
            const label = event.target.value;
            workspace.update(current => current.account ? { account: { ...current.account, label } } : {});
          }} /></WorkspaceField>
      </div>
      <DialogFooter><Button type="button" variant="outline" disabled={!!pending} onClick={close}>取消</Button>
        <Button type="button" disabled={(!isApi && !opened) || !label.trim() || workspace.isBusy}
        onClick={() => void workspace.run('confirm-login', () => window.publisher.request(isApi ? 'accounts.configure' : 'accounts.confirm',
          { id: binding.id, label, settings }), () => workspace.update({ account: undefined, notice: `「${label.trim()}」已绑定到${name}。` }))}>
        确认绑定
      </Button></DialogFooter>
    </DialogContent>
  </Dialog>;
}

function PublishPreview({ confirmation }: { confirmation: Extract<Confirmation, { type: 'publish' }> }) {
  const { draft, kind, destinations } = confirmation;
  return <div className="-m-1 min-h-0 space-y-3 overflow-auto p-1">
    {draft.files.length > 0 && <div className="flex min-w-0 items-center gap-3 rounded-xl bg-muted/75 p-3">
      <MediaPreview path={draft.files[0]} video={kind === 'video'} className="w-19" />
      <div className="min-w-0">
        <div className="text-xs text-muted-foreground">共享素材</div>
        <div className="text-sm wrap-anywhere">{draft.files.map(fileName).join('、')}</div>
      </div>
    </div>}
    <div className="grid gap-3 sm:grid-cols-2 sm:gap-y-0">
      {destinations.map(({ binding, name, content, custom }) => {
        const tags = parseTags(content.tags);
        const cover = custom ? content.cover || (kind === 'image' ? draft.files[0] : undefined) : undefined;
        return <Card role="region" aria-label={`${name}发布预览`} key={binding.id}
          className="workspace-panel review-card min-w-0 gap-0 p-0 only:sm:col-span-2">
          <header className="flex min-w-0 items-center gap-2 px-3 pt-3 pb-2">
            <PlatformMark platform={binding.platform} />
            <h3 className="min-w-0 text-sm font-semibold wrap-anywhere">{name} <span className="font-normal text-muted-foreground">· {binding.label}</span></h3>
          </header>
          <dl className="review-details grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-start gap-2 px-3 pt-1 pb-3 text-xs">
            <dt className="text-muted-foreground">标题</dt>
            <dd className="text-sm font-medium wrap-anywhere">{content.title.trim()}</dd>
            <dt className="text-muted-foreground">正文</dt>
            <dd className="whitespace-pre-wrap wrap-anywhere">{content.description.trim() || '无正文'}</dd>
            <dt className="text-muted-foreground">标签</dt>
            <dd className="flex min-w-0 flex-wrap gap-1">{tags.length ? tags.map(tag =>
              <Badge key={tag} variant="secondary" className="max-w-full whitespace-normal wrap-anywhere">#{tag}{' '}</Badge>) : '无标签'}</dd>
            <dt className="text-muted-foreground">封面</dt>
            <dd className="flex min-w-0 flex-wrap items-center gap-2 wrap-anywhere">
              {cover && <MediaPreview path={cover} className="w-15" />}
              {custom ? coverName(kind, content.cover, draft.files) : '平台默认'}
            </dd>
          </dl>
        </Card>;
      })}
    </div>
  </div>;
}

function confirmationCopy(confirmation: Confirmation, workspace: PublisherWorkspace) {
  if (confirmation.type === 'schedule-change') {
    return { title: '改期定时发布', description: `为《${confirmation.task.title}》这批任务选择新的发布时间。`, action: '保存时间' };
  }
  if (confirmation.type === 'schedule-cancel') {
    return { title: '取消定时发布', description: `取消《${confirmation.task.title}》这批任务的定时发布。`, action: '确认取消' };
  }
  if (confirmation.type === 'delete-group') {
    return { title: '删除发布组', description: `删除「${confirmation.group.name}」及该组的账号绑定和本地发布记录。此操作无法撤销。`,
      action: '确认删除' };
  }
  if (confirmation.type === 'delete-account') {
    const { binding } = confirmation;
    const name = workspace.bindingName(binding);
    const account = binding.label && binding.label !== name ? `${name} · ${binding.label}` : name;
    const custom = workspace.groups.find(group => group.id === binding.group_id)?.mode === 'custom';
    return { title: '删除平台账号',
      description: `${custom ? `将「${account}」移出本组，并清理本机登录会话。` :
        `清理「${account}」的本机登录会话，可重新绑定该平台。`}历史发布记录仍可查看。`,
      action: '确认删除' };
  }
  if (confirmation.type === 'delete-task') {
    const { task } = confirmation;
    return { title: '删除发布记录',
      description: `删除《${task.title}》在${workspace.bindingName(task)}的本地记录和诊断。删除无法撤销，平台作品仍可在后台查看。若这是该批次最后一条记录，也会清理应用保存的素材副本。`,
      action: '确认删除' };
  }
  if (confirmation.type === 'publish') {
    const { group, destinations, kind } = confirmation;
    const wechat = destinations.some(({ binding }) => binding.platform === 'wechat_mp');
    return { title: '核对发布内容', description: `${group.name} · ${contentKinds[kind].label} · ${destinations.length} 个账号${wechat ? ' · 微信公众号保存草稿' : ''}`,
      action: confirmation.scheduledFor === undefined ? '确认并群发' : '确认定时发布' };
  }
  if (confirmation.type === 'review') {
    const { task, result } = confirmation;
    return { title: result === 'found' ? '确认平台已收稿' : '确认平台未收稿',
      description: `请确认你已在${workspace.bindingName(task)}「${task.target_label}」后台核对《${task.title}》。`,
      action: result === 'found' ? '标记已提交' : '允许重试' };
  }
  return { title: `新建${workspace.bindingName(confirmation.binding)}会话`,
    description: '新会话需要重新绑定。已在队列中等待原账号的任务会停止。', action: '新建会话' };
}

function ScheduleField({ value, disabled, onChange }: { value: string; disabled: boolean; onChange: (value: string) => void }) {
  const timestamp = scheduleTimestamp(value);
  return <WorkspaceField label="发布时间"
    hint={timestamp ? formatSchedule(timestamp) : Intl.DateTimeFormat().resolvedOptions().timeZone}>
    <Input type="datetime-local" required min={scheduleInput()} value={value} disabled={disabled}
      onChange={event => onChange(event.target.value)} />
  </WorkspaceField>;
}

function ConfirmDialog({ workspace }: { workspace: PublisherWorkspace }) {
  const { confirmation, pending, error } = workspace.state;
  if (!confirmation) return null;
  const close = () => workspace.update({ confirmation: undefined, error: '' });
  const copy = confirmationCopy(confirmation, workspace);
  const publishing = confirmation.type === 'publish';
  const scheduledFor = publishing || confirmation.type === 'schedule-change' ? confirmation.scheduledFor : undefined;
  const validSchedule = scheduledFor === undefined || scheduleTimestamp(scheduledFor) !== null;
  const updateSchedule = (value: string | undefined) => {
    if (confirmation.type === 'publish') workspace.update({ confirmation: { ...confirmation, scheduledFor: value }, error: '' });
    if (confirmation.type === 'schedule-change' && value !== undefined) {
      workspace.update({ confirmation: { ...confirmation, scheduledFor: value }, error: '' });
    }
  };
  return <Dialog open onOpenChange={open => { if (!open && !pending) close(); }}>
    <DialogContent className={publishing ? 'flex max-h-[calc(100dvh-1.5rem)] flex-col sm:max-w-3xl' : undefined}>
      <DialogHeader className="shrink-0"><DialogTitle className={publishing ? 'text-lg font-semibold' : undefined}>{copy.title}</DialogTitle>
        <DialogDescription>{copy.description}</DialogDescription></DialogHeader>
      {confirmation.type === 'publish' && <PublishPreview confirmation={confirmation} />}
      {(publishing || confirmation.type === 'schedule-change') && <div className="grid shrink-0 gap-3 rounded-lg bg-muted/65 p-3">
        {publishing && <RadioGroup aria-label="发布时间方式" value={scheduledFor === undefined ? 'now' : 'later'}
          disabled={workspace.isBusy} className="flex flex-wrap gap-x-5 gap-y-2"
          onValueChange={value => updateSchedule(value === 'later' ? scheduleInput(5) : undefined)}>
          <label className="flex items-center gap-2 text-sm"><RadioGroupItem value="now" />立即发布</label>
          <label className="flex items-center gap-2 text-sm"><RadioGroupItem value="later" />定时发布</label>
        </RadioGroup>}
        {scheduledFor !== undefined && <>
          <ScheduleField value={scheduledFor} disabled={workspace.isBusy} onChange={updateSchedule} />
          <p className="text-xs text-muted-foreground">关闭窗口后会在托盘继续运行。请保持电脑唤醒；超过预约时间 1 分钟后会标记为已错过。</p>
        </>}
      </div>}
      {error && <ErrorNotice>{error}</ErrorNotice>}
      <DialogFooter className="shrink-0">
        <Button type="button" variant="outline" disabled={!!pending} onClick={close}>{publishing ? '返回编辑' : '取消'}</Button>
        <Button type="button" variant={confirmation.type === 'replace' || confirmation.type === 'delete-group'
          || confirmation.type === 'delete-account' || confirmation.type === 'delete-task'
          || confirmation.type === 'schedule-cancel' ? 'destructive' : 'default'}
          disabled={workspace.isBusy || !validSchedule} onClick={workspace.confirm}>
          {pending === 'confirm' ? <LoaderCircle className="animate-spin" data-icon="inline-start" /> : publishing && <Send data-icon="inline-start" />}{copy.action}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}

export function WorkspaceDialogs({ workspace }: { workspace: PublisherWorkspace }) {
  return <><GroupDialog workspace={workspace} />
    <AddAccountsDialog workspace={workspace} /><AccountDialog workspace={workspace} /><ConfirmDialog workspace={workspace} /></>;
}
