import { ArrowLeft, Clipboard, MessageSquareText, RefreshCw, Save, Search } from 'lucide-react';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import type { Binding } from '@/types';
import { commentSyncTime } from './comment-data';
import { MessageAccountPicker } from './message-account-picker';
import { errorMessage, isConnected } from './model';
import type { PublisherWorkspace } from './use-workspace';
import { ErrorNotice, WorkspaceField } from './workspace-ui';

type Conversation = { id: string; name: string; preview: string; time: string; unread: number; kind: 'c2c' | 'group' };
type Inbox = { conversations: Conversation[]; synced_at: number | null; personal_pending: boolean };
type ChatMessage = { id: string; direction: 'in' | 'out' | 'system'; type: 'text' | 'image' | 'note'; body: string; time: string };
type Thread = { messages: ChatMessage[]; has_older: boolean; synced_at: number; unread: number };
type MessageScope = { group_id: string; binding_id: string; conversation_id: string };
const draftLimit = 4000;

function PrivateDraft({ scope }: { scope: MessageScope }) {
  const [body, setBody] = useState('');
  const [saved, setSaved] = useState<string>();
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const { group_id, binding_id, conversation_id } = scope;

  useEffect(() => {
    let active = true;
    void window.publisher.request<string>('messages.draft', { group_id, binding_id, conversation_id }).then(draft => {
      if (active) { setBody(draft); setSaved(draft); }
    }).catch(cause => { if (active) setError(errorMessage(cause)); });
    return () => { active = false; };
  }, [group_id, binding_id, conversation_id]);

  async function save() {
    setSaving(true);
    setStatus('');
    setError('');
    const draft = body.trim() ? body : '';
    try {
      await window.publisher.request('messages.saveDraft', { ...scope, body: draft });
      setBody(draft);
      setSaved(draft);
      setStatus(draft ? '草稿已保存到本机。' : '已清空这条会话的草稿。');
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
      setStatus('已复制回复。');
    } catch {
      setError('复制失败，可以选中文字后按 Ctrl+C。');
    }
  }

  return <div className="grid shrink-0 gap-2 border-t px-3 pt-2 sm:px-4">
    <WorkspaceField label="回复草稿" hint={`${body.length} / ${draftLimit}`}>
      <Textarea maxLength={draftLimit} value={body} placeholder="输入这条会话的回复草稿"
        disabled={saved === undefined || saving} className="max-h-24 min-h-12 resize-none"
        onChange={event => { setBody(event.target.value); setStatus(''); }} />
    </WorkspaceField>
    <div className="flex flex-wrap items-center justify-end gap-2">
      <span role="status" className="mr-auto text-xs text-muted-foreground">{status || '草稿保存在本机。'}</span>
      <Button type="button" variant="outline" size="sm" disabled={!body.trim()} onClick={() => void copy()}>
        <Clipboard data-icon="inline-start" />复制
      </Button>
      <Button type="button" size="sm" disabled={saved === undefined || saving || body === saved} onClick={() => void save()}>
        <Save data-icon="inline-start" />{saving ? '正在保存…' : '保存草稿'}
      </Button>
    </div>
    {error && <ErrorNotice>{error}</ErrorNotice>}
  </div>;
}

function ChatHistory({ thread, loading, onOlder }: { thread?: Thread | null; loading: boolean; onOlder: () => void }) {
  const view = useRef<HTMLDivElement>(null);
  const prior = useRef({ first: '', last: '', height: 0 });
  useLayoutEffect(() => {
    const pane = view.current;
    if (!pane || !thread?.messages.length) return;
    const first = thread.messages[0].id;
    const last = thread.messages.at(-1)!.id;
    const prev = prior.current;
    if (prev.last === last && prev.first && prev.first !== first) pane.scrollTop += pane.scrollHeight - prev.height;
    else if (prev.last !== last) pane.scrollTop = pane.scrollHeight;
    prior.current = { first, last, height: pane.scrollHeight };
  }, [thread]);

  return <CardContent ref={view} role="region" aria-label="聊天记录" tabIndex={0} className="comment-list-scroll grid gap-2.5 px-3 sm:px-4">
    {thread?.has_older && <Button variant="ghost" size="sm" className="justify-self-center text-muted-foreground"
      disabled={loading} onClick={onOlder}>加载更早消息</Button>}
    {loading && <p role="status" className="py-1 text-center text-xs text-muted-foreground">正在读取小红书聊天…</p>}
    {thread === null && !loading && <p className="py-5 text-center text-sm text-muted-foreground">暂未缓存这条会话。</p>}
    {thread?.messages.length === 0 && !loading && <p className="py-5 text-center text-sm text-muted-foreground">这条会话还没有可显示的消息。</p>}
    {thread?.messages.map((message, index) => <div key={message.id} className="grid min-w-0 gap-2">
      {message.time && message.time !== thread.messages[index - 1]?.time &&
        <span className="text-center text-xs text-muted-foreground">{message.time}</span>}
      <div className={cn('min-w-0 max-w-[90%] whitespace-pre-wrap break-words rounded-2xl px-3 py-2 text-sm',
        message.direction === 'out' ? 'justify-self-end rounded-br-md bg-primary text-primary-foreground'
          : message.direction === 'in' ? 'justify-self-start rounded-bl-md bg-muted'
          : 'justify-self-center px-0 py-1 text-center text-xs text-muted-foreground')}>
        {message.type === 'note' && <span className="mb-0.5 block text-xs opacity-75">分享笔记</span>}
        {message.body}
      </div>
    </div>)}
  </CardContent>;
}

function AccountMessages({ binding }: { binding: Binding }) {
  const scope = { group_id: binding.group_id, binding_id: binding.id };
  const [inbox, setInbox] = useState<Inbox>();
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<Conversation>();
  const [thread, setThread] = useState<Thread | null>();
  const [pending, setPending] = useState<'inbox' | 'thread'>();
  const [inboxError, setInboxError] = useState('');
  const [threadError, setThreadError] = useState('');
  const ready = isConnected(binding);

  useEffect(() => {
    let active = true;
    void window.publisher.request<Inbox>('messages.snapshot', {
      group_id: binding.group_id, binding_id: binding.id,
    }).then(snapshot => { if (active) setInbox(snapshot); })
      .catch(cause => { if (active) setInboxError(errorMessage(cause)); });
    return () => { active = false; };
  }, [binding.group_id, binding.id]);

  async function sync() {
    setPending('inbox');
    setInboxError('');
    try {
      const snapshot = await window.publisher.request<Inbox>('messages.sync', scope);
      setInbox(snapshot);
      if (selected && !snapshot.conversations.some(item => item.id === selected.id)) {
        setSelected(undefined);
        setThread(undefined);
        setThreadError('');
      }
    } catch (cause) {
      setInboxError(errorMessage(cause));
    } finally {
      setPending(undefined);
    }
  }

  async function read(conversation: Conversation, older = false) {
    if (pending) return;
    const changed = selected?.id !== conversation.id;
    const target = { ...scope, conversation_id: conversation.id };
    setSelected(conversation);
    setThreadError('');
    setPending('thread');
    try {
      if (changed) {
        setThread(undefined);
        setThread(await window.publisher.request<Thread | null>('messages.cachedThread', target));
      }
      if (ready) {
        const result = await window.publisher.request<Thread>('messages.thread', { ...target, older });
        setThread(result);
        setInbox(previous => previous && ({ ...previous, conversations: previous.conversations.map(item =>
          item.id === conversation.id ? { ...item, unread: result.unread } : item) }));
      }
    } catch (cause) {
      setThreadError(errorMessage(cause));
    } finally {
      setPending(undefined);
    }
  }

  const term = query.trim().toLocaleLowerCase();
  const matches = inbox?.conversations.filter(item => item.name.toLocaleLowerCase().includes(term));

  return <div className="grid min-h-0 min-w-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[minmax(15rem,0.8fr)_minmax(0,1.5fr)]">
    <Card className={cn('workspace-panel min-h-0 min-w-0 gap-3', selected && 'max-lg:hidden')}>
      <CardHeader className="shrink-0 gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>私信会话</CardTitle>
          <Button type="button" variant="outline" size="sm" disabled={!ready || !!pending || !inbox}
            onClick={() => void sync()}><RefreshCw data-icon="inline-start" className={pending === 'inbox' ? 'animate-spin' : ''} />
            {pending === 'inbox' ? '正在同步…' : '同步私信'}
          </Button>
        </div>
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <Input className="pl-8" aria-label="搜索私信会话" placeholder="搜索联系人或群聊" value={query} onChange={event => setQuery(event.target.value)} />
        </div>
        {inbox?.synced_at && <p className="text-xs text-muted-foreground">上次同步 {commentSyncTime(inbox.synced_at)}</p>}
      </CardHeader>
      <CardContent role="region" aria-label="私信会话列表" tabIndex={0} className="comment-list-scroll grid gap-1 px-2">
        {inboxError && <ErrorNotice>{inboxError}</ErrorNotice>}
        {inbox?.personal_pending && <p role="status" className="p-2 text-xs text-muted-foreground">
          小红书单聊列表暂未加载。已缓存的单聊仍可查看，可以稍后重新同步。
        </p>}
        {!ready && <p className="p-2 text-xs text-muted-foreground">请在平台账号页重新验证后同步。</p>}
        {!inboxError && !matches?.length && <p className="p-4 text-sm text-muted-foreground">
          {!inbox ? '正在读取本地会话…' : term ? '没有匹配的会话。'
            : inbox.synced_at ? '暂未找到会话。' : '点击「同步私信」读取小红书会话。'}
        </p>}
        {matches?.map(item => <Button type="button" key={item.id} variant={selected?.id === item.id ? 'secondary' : 'ghost'}
          aria-pressed={selected?.id === item.id} disabled={!!pending}
          className="h-auto min-w-0 justify-start p-2.5" onClick={() => void read(item)}>
          <span className="grid size-9 shrink-0 place-items-center rounded-full bg-muted text-sm">{Array.from(item.name)[0]}</span>
          <span className="min-w-0 flex-1 space-y-0.5 text-left">
            <span className="flex items-center gap-2"><span className="min-w-0 flex-1 truncate font-medium">{item.name}</span>
              <span className="shrink-0 text-xs font-normal text-muted-foreground">{item.time}</span></span>
            <span className="flex items-center gap-2"><span className="min-w-0 flex-1 truncate text-xs font-normal text-muted-foreground">{item.preview || '暂无消息预览'}</span>
              {item.unread > 0 && <Badge className="px-1.5" aria-label={`${item.unread} 条未读`}>{item.unread}</Badge>}</span>
          </span>
        </Button>)}
      </CardContent>
    </Card>
    {selected ? <Card key={selected.id} className="workspace-panel min-h-0 min-w-0 gap-2.5">
      <CardHeader className="flex shrink-0 items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Button type="button" variant="ghost" size="icon-sm" className="lg:hidden" aria-label="返回会话列表"
            onClick={() => { if (!pending) { setSelected(undefined); setThread(undefined); } }} disabled={!!pending}><ArrowLeft /></Button>
          <div className="min-w-0"><CardTitle className="truncate">{selected.name}</CardTitle>
            <p className="truncate text-xs text-muted-foreground">小红书 · {binding.label}</p></div>
        </div>
        <Button type="button" variant="ghost" size="icon-sm" aria-label="刷新聊天"
          disabled={!ready || !!pending} onClick={() => void read(selected)}><RefreshCw className={pending === 'thread' ? 'animate-spin' : ''} /></Button>
      </CardHeader>
      {threadError && <div className="shrink-0 px-4"><ErrorNotice>{threadError}</ErrorNotice></div>}
      <ChatHistory thread={thread} loading={pending === 'thread'} onOlder={() => void read(selected, true)} />
      <PrivateDraft scope={{ ...scope, conversation_id: selected.id }} />
    </Card> : <Card className="workspace-panel hidden min-h-0 justify-center lg:flex">
      <CardContent className="grid justify-items-center gap-2 text-center text-sm text-muted-foreground">
        <MessageSquareText className="size-6" aria-hidden="true" />
        <p>选择会话查看聊天</p><p className="text-xs">打开会话可能会在小红书标记为已读。</p>
      </CardContent>
    </Card>}
  </div>;
}

export function PrivateMessages({ workspace }: { workspace: PublisherWorkspace }) {
  const group = workspace.group!;
  const key = `relayfold:private-message-account:${group.id}`;
  const [accountId, setAccountId] = useState(() => localStorage.getItem(key));
  const accounts = workspace.bindings.filter(binding => binding.platform === 'xiaohongshu' && binding.label);
  const selected = accounts.find(binding => binding.id === accountId) || accounts[0];
  const name = (binding: Binding) => group.mode === 'custom'
    ? `${binding.label} · ${workspace.bindingName(binding)}`
    : binding.label;

  if (!selected) return <Card className="workspace-panel">
    <CardHeader><CardTitle>这个组还没有绑定小红书账号</CardTitle></CardHeader>
    <CardContent><Button variant="outline" onClick={() => workspace.changeView('accounts')}>前往平台账号</Button></CardContent>
  </Card>;

  return <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
    <div className="flex shrink-0 flex-wrap items-center justify-between gap-2">
      <p className="text-xs text-muted-foreground">手动同步私信 · 打开会话可能标记已读</p>
      <MessageAccountPicker label="切换私信账号" workspace={workspace} accounts={accounts} selected={selected} name={name}
        onSelect={binding => { localStorage.setItem(key, binding.id); setAccountId(binding.id); }} />
    </div>
    <AccountMessages key={selected.id} binding={selected} />
  </div>;
}
