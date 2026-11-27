import { ArrowUpRight, Clipboard, MessageSquareText, MessagesSquare, Save } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import type { Binding } from '@/types';
import { DouyinOfficialPane } from './douyin-official-pane';
import { MessageAccountPicker } from './message-account-picker';
import { errorMessage } from './model';
import type { PublisherWorkspace } from './use-workspace';
import { ErrorNotice, WorkspaceField } from './workspace-ui';

const destinations = {
  private: {
    title: '抖音私信', icon: MessagesSquare, button: '打开抖音聊天官网',
    description: '通过官方 Windows 客户端查看会话和回复。请在客户端核对登录账号。',
  },
  comments: {
    title: '抖音作品评论', icon: MessageSquareText, button: '打开创作者中心',
    description: '在创作者中心查看和回复作品评论。请先核对网页登录账号。',
  },
} as const;

function DouyinDraft({ binding, name }: { binding: Binding; name: string }) {
  const { group_id, id: binding_id } = binding;
  const [body, setBody] = useState('');
  const [saved, setSaved] = useState<string>();
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    void window.publisher.request<string>('messages.douyinDraft', { group_id, binding_id }).then(draft => {
      if (active) { setBody(draft); setSaved(draft); }
    }).catch(cause => { if (active) setError(errorMessage(cause)); });
    return () => { active = false; };
  }, [group_id, binding_id]);

  async function save() {
    setSaving(true);
    setError('');
    setStatus('');
    const draft = body.trim() ? body : '';
    try {
      await window.publisher.request('messages.saveDouyinDraft', { group_id, binding_id, body: draft });
      setBody(draft);
      setSaved(draft);
      setStatus(draft ? '草稿已保存到本机。' : '草稿已清空。');
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setSaving(false);
    }
  }

  async function copy() {
    setError('');
    setStatus('');
    try {
      await navigator.clipboard.writeText(body);
      setStatus('已复制草稿。');
    } catch {
      setError('复制失败，可以选择文字后按 Ctrl+C。');
    }
  }

  return <Card className="workspace-panel min-w-0">
    <CardHeader>
      <CardTitle>私信草稿</CardTitle>
      <CardDescription className="break-words">{name} · 仅保存在本机</CardDescription>
    </CardHeader>
    <CardContent className="grid gap-3">
      <WorkspaceField label="回复草稿" hint={`${body.length} / 4000`}>
        <Textarea maxLength={4000} value={body} disabled={saved === undefined || saving}
          className="min-h-24 resize-y" placeholder="整理一条准备发送的私信"
          onChange={event => { setBody(event.target.value); setStatus(''); }} />
      </WorkspaceField>
      <div className="flex flex-wrap items-center justify-end gap-2">
        {status && <span role="status" className="mr-auto text-xs text-muted-foreground">{status}</span>}
        <Button type="button" variant="outline" size="sm" disabled={!body.trim()} onClick={() => void copy()}>
          <Clipboard data-icon="inline-start" />复制
        </Button>
        <Button type="button" size="sm" disabled={saved === undefined || saving || body === saved} onClick={() => void save()}>
          <Save data-icon="inline-start" />{saving ? '正在保存…' : '保存草稿'}
        </Button>
      </div>
      {error && <ErrorNotice>{error}</ErrorNotice>}
    </CardContent>
  </Card>;
}

export function DouyinMessages({ workspace, kind }: { workspace: PublisherWorkspace; kind: keyof typeof destinations }) {
  const group = workspace.group!;
  const storageKey = `relayfold:douyin-message-account:${group.id}`;
  const [accountId, setAccountId] = useState(() => localStorage.getItem(storageKey));
  const [embedded, setEmbedded] = useState(false);
  const [error, setError] = useState('');
  const accounts = workspace.bindings.filter(binding => binding.platform === 'douyin' && binding.label);
  const account = accounts.find(binding => binding.id === accountId) || accounts[0];
  const name = (binding: Binding) => group.mode === 'custom'
    ? `${binding.label} · ${workspace.bindingName(binding)}` : binding.label;
  const { title, description, button, icon: Icon } = destinations[kind];

  async function openOfficial() {
    setError('');
    try { await window.publisher.openDouyinMessages(kind); }
    catch (cause) { setError(errorMessage(cause)); }
  }

  if (embedded && account) return <DouyinOfficialPane key={account.id} account={account} name={name(account)} kind={kind}
    workspace={workspace} onClose={() => setEmbedded(false)} />;

  return <div className="comment-list-scroll grid gap-3 pr-1">
    {account && <div className="flex flex-wrap items-center justify-between gap-2">
      <span className="text-xs text-muted-foreground">当前抖音账号</span>
      <MessageAccountPicker workspace={workspace} accounts={accounts} selected={account} name={name}
        label="切换抖音账号" onSelect={binding => { localStorage.setItem(storageKey, binding.id); setAccountId(binding.id); }} />
    </div>}
    <div className={`grid min-w-0 items-start gap-4 ${kind === 'private' ? 'md:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]' : 'max-w-lg'}`}>
      <Card className="workspace-panel min-w-0">
        <CardHeader>
          <div className="mb-2 grid size-9 place-items-center rounded-lg bg-muted"><Icon className="size-4" aria-hidden="true" /></div>
          <CardTitle>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          <div className="flex flex-wrap gap-2">
            {account && <Button type="button" onClick={() => setEmbedded(true)}>在 Relayfold 中打开</Button>}
            <Button type="button" variant="outline" onClick={() => void openOfficial()}>{button}<ArrowUpRight data-icon="inline-end" /></Button>
          </div>
          {error && <ErrorNotice>{error}</ErrorNotice>}
        </CardContent>
      </Card>
      {kind === 'private' && (account ? <DouyinDraft key={account.id} binding={account} name={name(account)} />
        : <Card className="workspace-panel">
          <CardHeader><CardTitle>绑定抖音账号</CardTitle>
            <CardDescription>绑定后可按账号保存私信草稿。</CardDescription></CardHeader>
          <CardContent><Button type="button" variant="outline" onClick={() => workspace.changeView('accounts')}>前往平台账号</Button></CardContent>
        </Card>)}
    </div>
  </div>;
}
