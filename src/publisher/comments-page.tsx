import { useEffect, useRef, useState } from 'react';
import { FileText, LoaderCircle, MessageSquareText, RefreshCw } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { Binding } from '@/types';
import { commentSyncTime, markCommentRead, useCommentSnapshot, type CommentSnapshot, type Note, type OriginalComment } from './comment-data';
import { CommentInbox } from './comment-inbox';
import { CommentThread, type ReplyControls, type ReplyStatus, type ReplyTarget, type SendResult } from './comment-thread';
import { MessageAccountPicker } from './message-account-picker';
import { errorMessage, isConnected } from './model';
import type { PublisherWorkspace } from './use-workspace';
import { ErrorNotice } from './workspace-ui';

function NoteComments({ noteId, account, binding, targetComment, titleHint, ...reply }: ReplyControls & {
  noteId: string; account: string; binding: Binding; targetComment?: string; titleHint?: string;
}) {
  const { group_id, id: binding_id } = binding;
  const scope = { group_id, binding_id, note_id: noteId };
  const snapshot = useCommentSnapshot<CommentSnapshot>('comments.snapshot', group_id, binding_id, noteId);
  const note = snapshot?.data?.note;
  const thread = snapshot?.data?.thread;
  const sync = snapshot?.data?.thread_sync;
  const [requestError, setRequestError] = useState('');
  const [requested, setRequested] = useState(false);
  const automaticallyChecked = useRef(false);
  const focused = useRef<string>(undefined);
  const [locating, setLocating] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const target = thread?.comments.flatMap(comment => [comment, ...(comment.children ?? [])]).find(comment => comment.id === targetComment);

  async function refresh(commentId?: string) {
    setRequestError('');
    setRequested(true);
    try {
      if (commentId) await window.publisher.request('comments.locate', { ...scope, comment_id: commentId });
      else await window.publisher.request('comments.list', scope);
    } catch (cause) {
      setRequestError(errorMessage(cause));
    } finally {
      setRequested(false);
    }
  }

  useEffect(() => {
    if (!snapshot?.data || snapshot.data.deleted || automaticallyChecked.current) return;
    automaticallyChecked.current = true;
    if (targetComment) return;
    if (!thread || thread.comments.some(comment => comment.children_count === undefined || comment.ip_location === undefined) ||
      Date.now() - thread.updated_at * 1000 > 5 * 60 * 1000) void refresh();
  }, [snapshot?.data, thread]);

  useEffect(() => {
    if (!targetComment || !snapshot?.data || snapshot.data.deleted || target) return;
    let active = true;
    setLocating(true);
    void window.publisher.request('comments.locate', { ...scope, comment_id: targetComment })
      .catch(cause => { if (active) setRequestError(errorMessage(cause)); })
      .finally(() => { if (active) setLocating(false); });
    return () => { active = false; setLocating(false); };
  }, [targetComment, !!snapshot?.data, snapshot?.data?.deleted, !!target, group_id, binding_id, noteId]);

  useEffect(() => {
    if (!target || focused.current === target.id) return;
    focused.current = target.id;
    const frame = requestAnimationFrame(() => {
      const row = document.getElementById(`comment-thread-${target.id}`);
      row?.scrollIntoView({ block: 'nearest' });
      row?.focus({ preventScroll: true });
    });
    if (target.unread) void markCommentRead(scope, target.id).catch(cause => setRequestError(errorMessage(cause)));
    return () => cancelAnimationFrame(frame);
  }, [target, group_id, binding_id, noteId]);

  async function loadMore() {
    setLoadingMore(true);
    setRequestError('');
    try {
      await window.publisher.request('comments.more', scope);
    } catch (cause) {
      setRequestError(errorMessage(cause));
    } finally {
      setLoadingMore(false);
    }
  }

  const loading = !snapshot || requested || locating || !!sync?.running;
  const error = requestError || snapshot?.error || sync?.error || (snapshot?.data?.deleted ? '原笔记已删除。' : '');
  const title = titleHint || note?.title || '笔记评论';

  return <Card className="workspace-panel comment-panel">
    <CardHeader className="flex shrink-0 flex-row items-start justify-between gap-3">
      <div className="min-w-0 space-y-1">
        <CardTitle className="line-clamp-2 break-words" title={title}>{title}</CardTitle>
        <CardDescription>小红书 · {account}{thread && ` · 上次同步 ${commentSyncTime(thread.updated_at)}`}</CardDescription>
      </div>
      <Button variant="ghost" size="icon-sm" aria-label="刷新评论" disabled={loading || snapshot?.data?.deleted}
        onClick={() => void refresh(targetComment && !target ? targetComment : undefined)}><RefreshCw className={loading ? 'animate-spin' : ''} /></Button>
    </CardHeader>
    <CardContent role="region" aria-label="评论列表" tabIndex={0} className="comment-list-scroll grid gap-3">
      {error && <ErrorNotice>{error}</ErrorNotice>}
      {loading && <div role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
        <LoaderCircle className="size-4 animate-spin" />
        {thread && targetComment && !target ? '正在定位这条回复…' : thread ? '正在更新评论…' : '正在加载原帖评论…'}
      </div>}
      {!loading && !error && thread?.comments.length === 0 && <p className="py-8 text-center text-sm text-muted-foreground">这篇笔记还没有评论。</p>}
      {thread && <CommentThread comments={thread.comments} account={account} scope={scope} focusComment={targetComment} {...reply} />}
      {thread?.has_more && <Button variant="outline" size="sm" className="justify-self-center"
        disabled={loadingMore || loading} onClick={() => void loadMore()}>
        {loadingMore ? '正在加载更多评论…' : '加载更多评论'}
      </Button>}
    </CardContent>
  </Card>;
}

function NoteCover({ note, binding, updated }: { note: Note; binding: Binding; updated?: number | null }) {
  const anchor = useRef<HTMLSpanElement>(null);
  const [image, setImage] = useState<string | null>(null);
  useEffect(() => {
    if (!note.has_cover || !anchor.current) return;
    let active = true;
    const observer = new IntersectionObserver(entries => {
      if (!entries.some(entry => entry.isIntersecting)) return;
      observer.disconnect();
      void window.publisher.request<string | null>('comments.cover', {
        group_id: binding.group_id, binding_id: binding.id, note_id: note.id,
      }).then(value => { if (active && value) setImage(value); }).catch(() => {});
    }, { rootMargin: '80px' });
    observer.observe(anchor.current);
    return () => { active = false; observer.disconnect(); };
  }, [binding.id, binding.group_id, note.has_cover, note.id, updated]);

  return <span ref={anchor} className="grid size-11 shrink-0 place-items-center overflow-hidden rounded-md bg-muted text-muted-foreground">
    {image ? <img src={image} alt="" className="size-full object-cover" onError={() => setImage(null)} />
      : <FileText className="size-4" aria-hidden="true" />}
  </span>;
}

function MyNotes({ binding, account, original, ...reply }: ReplyControls & {
  binding: Binding; account: string; original?: OriginalComment;
}) {
  const targetNote = original?.note_id;
  const key = `relayfold:comment-note:${binding.group_id}:${binding.id}`;
  const [selectedId, selectNote] = useState(() => targetNote || localStorage.getItem(key) || undefined);
  const [requestError, setRequestError] = useState('');
  const [requested, setRequested] = useState(false);
  const snapshot = useCommentSnapshot<CommentSnapshot>('comments.snapshot', binding.group_id, binding.id);
  const notes = snapshot?.data?.notes;
  const loading = requested || !!snapshot?.data?.notes_sync?.running;
  const error = requestError || snapshot?.error || snapshot?.data?.notes_sync?.error;
  const selected = selectedId && (notes?.some(note => note.id === selectedId) || selectedId === targetNote) ? selectedId : undefined;

  async function sync() {
    if (loading) return;
    setRequested(true);
    setRequestError('');
    try {
      await window.publisher.request('comments.notes', { group_id: binding.group_id, binding_id: binding.id });
    } catch (cause) {
      setRequestError(errorMessage(cause));
    } finally {
      setRequested(false);
    }
  }

  return <div className="comment-columns">
    <Card className="workspace-panel comment-panel">
      <CardHeader className="flex shrink-0 flex-wrap items-center justify-between gap-2">
        <div className="space-y-1">
          <CardTitle>我的笔记</CardTitle>
          {snapshot?.data?.notes_at && <CardDescription>上次同步 {commentSyncTime(snapshot.data.notes_at)}</CardDescription>}
        </div>
        <Button variant="outline" size="sm" disabled={loading} onClick={() => void sync()}>
          <RefreshCw data-icon="inline-start" className={loading ? 'animate-spin' : ''} />
          {loading ? '正在同步' : '同步笔记'}
        </Button>
      </CardHeader>
      <CardContent role="region" aria-label="笔记列表" tabIndex={0} className="comment-list-scroll grid gap-1">
        {error && <ErrorNotice>{error}</ErrorNotice>}
        {original && !notes?.some(note => note.id === targetNote) && <Button
          variant={selected === targetNote ? 'secondary' : 'ghost'} aria-pressed={selected === targetNote}
          className="h-auto min-h-14 justify-start p-2" onClick={() => selectNote(targetNote)}>
          <span className="grid size-11 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground"><FileText /></span>
          <span className="min-w-0 flex-1 text-left">
            <span className="block truncate">{original.note_title}</span>
            <span className="block text-xs text-muted-foreground">来自收件箱</span>
          </span>
        </Button>}
        {!error && !notes?.length && <p className="py-6 text-center text-sm text-muted-foreground">
          {loading || !snapshot ? '正在读取笔记…' : notes ? '没有找到笔记。' : '同步后选择一篇笔记查看评论。'}
        </p>}
        {notes?.map(note => <Button key={note.id} variant={selected === note.id ? 'secondary' : 'ghost'}
          aria-pressed={selected === note.id} className="h-auto min-h-14 justify-start p-2"
          onClick={() => { selectNote(note.id); localStorage.setItem(key, note.id); }}>
          <NoteCover note={note} binding={binding} updated={snapshot?.data?.notes_at} />
          <span className="line-clamp-2 flex-1 whitespace-normal text-left">{note.title}</span>
          {note.unread > 0 && <span className="text-xs tabular-nums text-primary" title={`${note.unread} 条未读评论`}>{note.unread}</span>}
        </Button>)}
      </CardContent>
    </Card>
    {selected ? <NoteComments key={selected} noteId={selected} binding={binding} account={account}
      targetComment={selected === targetNote ? original?.comment_id : undefined}
      titleHint={selected === targetNote ? original?.note_title : undefined} {...reply} />
      : <Card className="workspace-panel comment-panel justify-center"><CardContent className="grid justify-items-center gap-2 text-sm text-muted-foreground">
        <MessageSquareText className="size-6" aria-hidden="true" />选择笔记后查看评论
      </CardContent></Card>}
  </div>;
}

export function CommentsPage({ workspace }: { workspace: PublisherWorkspace }) {
  const group = workspace.group!;
  const accounts = workspace.bindings.filter(binding => binding.platform === 'xiaohongshu' && isConnected(binding));
  const remembered = workspace.state.data?.comment_accounts?.[group.id];
  const destination = workspace.state.commentDestination?.group_id === group.id ? workspace.state.commentDestination : undefined;
  const [tab, setTab] = useState('received');
  const [original, setOriginal] = useState<OriginalComment>();
  const originalHere = original?.group_id === group.id ? original : undefined;
  const selected = accounts.find(binding => binding.id === (originalHere?.binding_id ?? remembered)) || accounts[0];
  useEffect(() => { if (destination) setTab('received'); }, [destination]);
  const [target, setTarget] = useState<ReplyTarget | null>(null);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<SendResult | null>(null);
  const controls: ReplyControls = { onConfirm: setTarget, result, sending };
  const accountName = (binding: Binding) => group.mode === 'custom'
    ? `${binding.label} · ${workspace.bindingName(binding)}`
    : binding.label;

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
    {result && <Alert role="status"><AlertDescription>{result.target.confirmation.account} · {result.reply.detail}</AlertDescription></Alert>}
    <Tabs value={tab} onValueChange={setTab} className="min-h-0 flex-1">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2">
        <TabsList aria-label="评论视图">
          <TabsTrigger value="received">收到评论</TabsTrigger>
          <TabsTrigger value="full">完整评论</TabsTrigger>
        </TabsList>
        {tab === 'full' && selected && <MessageAccountPicker key={group.id} label="切换评论账号"
          workspace={workspace} accounts={accounts} selected={selected} name={accountName}
          onSelect={binding => { setOriginal(undefined); workspace.selectCommentAccount(binding); }} />}
      </div>
      <TabsContent value="received" className="flex min-h-0 flex-1 flex-col">
        <CommentInbox groupId={group.id} accounts={accounts} accountName={accountName} destination={destination}
          onOpenThread={value => { setOriginal(value); setTab('full'); }} {...controls} />
      </TabsContent>
      <TabsContent value="full" className="flex min-h-0 flex-1 flex-col">
        {selected ? <MyNotes key={JSON.stringify([selected.id, originalHere?.note_id, originalHere?.comment_id])}
          binding={selected} account={accountName(selected)} original={originalHere} {...controls} />
          : <Card className="workspace-panel">
            <CardContent className="py-8 text-sm text-muted-foreground">在「平台账号」绑定小红书后，就可以查看这个组的笔记。</CardContent>
          </Card>}
      </TabsContent>
    </Tabs>
    <Dialog open={!!target} onOpenChange={open => { if (!open) setTarget(null); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>确认发送小红书回复</DialogTitle>
          <DialogDescription>这条回复会出现在小红书原笔记下。</DialogDescription>
        </DialogHeader>
        {target && <div className="space-y-3 text-sm">
          <p>发送账号 <strong>{target.confirmation.account}</strong></p>
          <p className="text-muted-foreground">{target.confirmation.group}</p>
          <p className="break-words">笔记 · {target.confirmation.note}</p>
          <div className="rounded-lg bg-muted p-3">
            <p className="font-medium">{target.confirmation.author || '小红书用户'}</p>
            <p className="whitespace-pre-wrap break-words text-muted-foreground">{target.confirmation.comment}</p>
          </div>
          <p className="whitespace-pre-wrap break-words rounded-lg bg-muted p-3">{target.confirmation.body}</p>
          {target.confirmation.previous_attempt_unknown && <Alert><AlertDescription>
            上次发送结果仍待核对。确认后会发送这次编辑的回复。
          </AlertDescription></Alert>}
        </div>}
        <DialogFooter>
          <Button variant="outline" onClick={() => setTarget(null)}>返回编辑</Button>
          <Button disabled={sending} onClick={() => void send()}>确认发送</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </>;
}
