import { useEffect, useRef, useState } from 'react';
import { FileText, LoaderCircle, MessageSquareText, RefreshCw } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import type { Binding } from '@/types';
import { errorMessage, isConnected } from './model';
import type { PublisherWorkspace } from './use-workspace';
import { ErrorNotice, WorkspaceField, WorkspaceHeading, WorkspaceSelect } from './workspace-ui';

type Note = { id: string; title: string; cover: string };
type ReplyStatus = { status: 'sending' | 'sent' | 'failed' | 'needs_review'; detail: string };
type NoteComment = { id: string; author: string; body: string; created_at: number | null; reply: ReplyStatus | null };
type CommentList = { comments: NoteComment[]; has_more: boolean };
type NoteScope = { group_id: string; binding_id: string; note_id: string };
type Confirmation = { confirmation: string; account: string; note: string; author: string; comment: string; body: string };
type ReplyTarget = { scope: NoteScope; commentId: string; confirmation: Confirmation };
type SendResult = { target: ReplyTarget; reply: ReplyStatus };

const replyLabels = { sending: '正在发送', sent: '已回复', failed: '发送失败', needs_review: '待核对' };

function commentTime(value: number | null) {
  if (value === null) return '';
  const date = new Date(value > 100_000_000_000 ? value : value * 1000);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('zh-CN', { dateStyle: 'short', timeStyle: 'short' });
}

function matches(left: NoteScope, right: NoteScope) {
  return left.group_id === right.group_id && left.binding_id === right.binding_id && left.note_id === right.note_id;
}

function NoteComments({ note, binding, scope, onConfirm, result, sending }: {
  note: Note; binding: Binding; scope: NoteScope; onConfirm: (target: ReplyTarget) => void; result: SendResult | null;
  sending: boolean;
}) {
  const [list, setList] = useState<CommentList>();
  const [revision, refresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [answer, setAnswer] = useState<{ id: string; text: string }>();
  const [preparing, setPreparing] = useState(false);
  const active = useRef(false);

  useEffect(() => {
    active.current = true;
    return () => { active.current = false; };
  }, []);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError('');
    void window.publisher.request<CommentList>('comments.list', scope)
      .then(value => { if (current) setList(value); })
      .catch(cause => { if (current) setError(errorMessage(cause)); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [scope.group_id, scope.binding_id, scope.note_id, revision]);

  async function review() {
    if (!answer?.text.trim() || preparing || sending) return;
    setPreparing(true);
    setError('');
    try {
      const confirmation = await window.publisher.request<Confirmation>('comments.prepare', {
        ...scope, comment_id: answer.id, body: answer.text,
      });
      if (active.current) onConfirm({ scope, commentId: answer.id, confirmation });
    } catch (cause) {
      if (active.current) setError(errorMessage(cause));
    } finally {
      if (active.current) setPreparing(false);
    }
  }

  return <Card className="workspace-panel min-h-0 min-w-0 max-sm:[--card-spacing:--spacing(3)]">
    <CardHeader className="flex shrink-0 flex-row items-start justify-between gap-3">
      <div className="min-w-0 space-y-1">
        <CardTitle className="line-clamp-2 break-words" title={note.title}>{note.title}</CardTitle>
        <CardDescription>小红书 · {binding.label}</CardDescription>
      </div>
      <Button variant="ghost" size="icon-sm" aria-label="刷新评论" disabled={loading}
        onClick={() => refresh(value => value + 1)}><RefreshCw className={loading ? 'animate-spin' : ''} /></Button>
    </CardHeader>
    <CardContent role="region" aria-label="评论列表" tabIndex={0} className="comment-list-scroll grid gap-3">
      {error && <ErrorNotice>{error}</ErrorNotice>}
      {loading && <div role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
        <LoaderCircle className="size-4 animate-spin" />正在加载评论…
      </div>}
      {!loading && list?.comments.length === 0 && <p className="py-8 text-center text-sm text-muted-foreground">这篇笔记还没有评论。</p>}
      {list?.comments.map(comment => {
        const reply = result && matches(result.target.scope, scope) && result.target.commentId === comment.id
          ? result.reply : comment.reply;
        const replyable = !reply || reply.status === 'failed';
        return <article key={comment.id} className="grid gap-2 rounded-lg bg-muted/45 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{comment.author || '小红书用户'}</span>
            <span className="text-xs text-muted-foreground">{commentTime(comment.created_at)}</span>
            {reply && <Badge variant={reply.status === 'failed' ? 'outline' : 'secondary'}>{replyLabels[reply.status]}</Badge>}
          </div>
          <p className="whitespace-pre-wrap break-words text-sm">{comment.body || '此评论没有可显示的文字。'}</p>
          {reply && reply.status !== 'sending' && <p className="text-xs text-muted-foreground">{reply.detail}</p>}
          {replyable && (answer?.id === comment.id ? <div className="grid gap-2 pt-1">
            <WorkspaceField label={`以「${binding.label}」回复`}>
              <Textarea placeholder="输入回复" value={answer.text} maxLength={500} disabled={preparing}
                onChange={event => setAnswer({ ...answer, text: event.target.value })} />
            </WorkspaceField>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" size="sm" disabled={preparing} onClick={() => setAnswer(undefined)}>取消</Button>
              <Button size="sm" disabled={preparing || sending || !answer.text.trim()} onClick={() => void review()}>核对回复</Button>
            </div>
          </div> : <Button variant="ghost" size="sm" className="justify-self-start" disabled={preparing || sending}
            onClick={() => setAnswer({ id: comment.id, text: '' })}>回复</Button>)}
        </article>;
      })}
      {list?.has_more && <p className="text-xs text-muted-foreground">当前显示首批评论。</p>}
    </CardContent>
  </Card>;
}

function MyNotes({ groupId, accounts, onConfirm, result, sending }: {
  groupId: string; accounts: Binding[]; onConfirm: (target: ReplyTarget) => void; result: SendResult | null;
  sending: boolean;
}) {
  const [selectedAccount, setAccount] = useState('');
  const binding = accounts.find(item => item.id === selectedAccount) || accounts[0];
  const [state, setState] = useState<{ bindingId: string; notes: Note[]; selected?: string; loading: boolean; error: string }>();
  const request = useRef(0);
  const current = state?.bindingId === binding?.id ? state : undefined;
  const selected = current?.notes.find(note => note.id === current.selected);
  useEffect(() => () => { request.current++; }, []);

  async function sync() {
    if (!binding) return;
    const version = ++request.current;
    const bindingId = binding.id;
    setState({ bindingId, notes: current?.notes || [], selected: current?.selected, loading: true, error: '' });
    try {
      const notes = await window.publisher.request<Note[]>('comments.notes', { group_id: groupId, binding_id: bindingId });
      if (version === request.current) setState({ bindingId, notes, selected: current?.selected, loading: false, error: '' });
    } catch (cause) {
      if (version === request.current) setState({ bindingId, notes: current?.notes || [], selected: current?.selected,
        loading: false, error: errorMessage(cause) });
    }
  }

  if (!binding) return <Card className="workspace-panel">
    <CardContent className="py-8 text-sm text-muted-foreground">在「平台账号」绑定小红书后，就可以查看这个组的笔记。</CardContent>
  </Card>;
  return <div className="grid min-h-0 min-w-0 flex-1 grid-rows-[minmax(0,1fr)_minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(15rem,0.8fr)_minmax(0,1.35fr)] lg:grid-rows-[minmax(0,1fr)]">
    <Card className="workspace-panel min-h-0 min-w-0 max-sm:[--card-spacing:--spacing(3)]">
      <CardHeader className="shrink-0 gap-3 max-sm:gap-2">
        <div className="space-y-1">
          <CardTitle>我的笔记</CardTitle>
          <CardDescription>同步这个小红书账号主页的近期笔记。</CardDescription>
        </div>
        <div className="flex flex-wrap gap-2">
          <WorkspaceSelect label="小红书账号" value={binding.id} className="min-w-32 flex-1"
            options={accounts.map(account => ({ label: account.label, value: account.id }))}
            onValueChange={value => { request.current++; setAccount(value); setState(undefined); }} />
          <Button variant="outline" disabled={current?.loading} onClick={() => void sync()}>
            <RefreshCw data-icon="inline-start" className={current?.loading ? 'animate-spin' : ''} />
            {current?.loading ? '正在同步' : '同步笔记'}
          </Button>
        </div>
      </CardHeader>
      <CardContent role="region" aria-label="笔记列表" tabIndex={0} className="comment-list-scroll grid gap-1">
        {current?.error && <ErrorNotice>{current.error}</ErrorNotice>}
        {!current && <p className="py-6 text-center text-sm text-muted-foreground">同步后选择一篇笔记查看评论。</p>}
        {current && !current.error && !current.loading && !current.notes.length && <p className="py-6 text-center text-sm text-muted-foreground">没有找到笔记。</p>}
        {current?.notes.map(note => <Button key={note.id} variant={selected?.id === note.id ? 'secondary' : 'ghost'}
          aria-pressed={selected?.id === note.id} disabled={current.loading} className="h-auto min-h-14 justify-start p-2"
          onClick={() => setState({ ...current, selected: note.id })}>
          {note.cover
            ? <img src={note.cover} alt="" loading="lazy" referrerPolicy="no-referrer" className="size-9 shrink-0 rounded-md bg-muted object-cover" />
            : <FileText className="size-5 shrink-0 text-muted-foreground" />}
          <span className="line-clamp-2 whitespace-normal text-left">{note.title}</span>
        </Button>)}
      </CardContent>
    </Card>
    {selected ? <NoteComments key={`${binding.id}:${selected.id}`} note={selected} binding={binding}
      scope={{ group_id: groupId, binding_id: binding.id, note_id: selected.id }} onConfirm={onConfirm} result={result} sending={sending} />
      : <Card className="workspace-panel min-h-0 justify-center"><CardContent className="grid justify-items-center gap-2 text-sm text-muted-foreground">
        <MessageSquareText className="size-6" />选择笔记后查看评论
      </CardContent></Card>}
  </div>;
}

export function CommentsPage({ workspace }: { workspace: PublisherWorkspace }) {
  const group = workspace.group!;
  const accounts = workspace.bindings.filter(binding => binding.platform === 'xiaohongshu' && isConnected(binding));
  const [target, setTarget] = useState<ReplyTarget | null>(null);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<SendResult | null>(null);

  async function send() {
    if (!target || sending) return;
    const confirmed = target;
    setSending(true);
    setTarget(null);
    setResult({ target: confirmed, reply: { status: 'sending', detail: '正在向原评论提交回复。' } });
    try {
      const reply = await window.publisher.request<ReplyStatus>('comments.send', { confirmation: confirmed.confirmation.confirmation });
      setResult({ target: confirmed, reply });
    } catch (cause) {
      setResult({ target: confirmed, reply: { status: 'needs_review', detail: errorMessage(cause) } });
    } finally {
      setSending(false);
    }
  }

  return <>
    <WorkspaceHeading title="评论" description={`${group.name} · 小红书`} />
    {result && <Alert role="status"><AlertDescription>{result.target.confirmation.account} · {result.reply.detail}</AlertDescription></Alert>}
    <MyNotes key={group.id} groupId={group.id} accounts={accounts} result={result} onConfirm={setTarget} sending={sending} />
    <Dialog open={!!target} onOpenChange={open => { if (!open) setTarget(null); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>确认发送小红书回复</DialogTitle>
          <DialogDescription>这条回复会出现在小红书原笔记下。</DialogDescription>
        </DialogHeader>
        {target && <div className="space-y-3 text-sm">
          <p>发送账号 <strong>{target.confirmation.account}</strong></p>
          <p className="break-words">笔记 · {target.confirmation.note}</p>
          <div className="rounded-lg bg-muted p-3">
            <p className="font-medium">{target.confirmation.author || '小红书用户'}</p>
            <p className="whitespace-pre-wrap break-words text-muted-foreground">{target.confirmation.comment}</p>
          </div>
          <p className="whitespace-pre-wrap break-words rounded-lg bg-muted p-3">{target.confirmation.body}</p>
        </div>}
        <DialogFooter>
          <Button variant="outline" onClick={() => setTarget(null)}>返回编辑</Button>
          <Button disabled={sending} onClick={() => void send()}>确认发送</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </>;
}
