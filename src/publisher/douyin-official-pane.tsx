import { ArrowLeft, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { useSidebar } from '@/components/ui/sidebar';
import type { Binding } from '@/types';
import { errorMessage } from './model';
import type { PublisherWorkspace } from './use-workspace';
import { ErrorNotice } from './workspace-ui';

type Status = 'loading' | 'ready' | 'error';

export function DouyinOfficialPane({ account, name, kind, workspace, onClose }: {
  account: Binding;
  name: string;
  kind: 'private' | 'comments';
  workspace: PublisherWorkspace;
  onClose: () => void;
}) {
  const { openMobile } = useSidebar();
  const target = useRef<HTMLDivElement>(null);
  const [token] = useState(() => crypto.randomUUID());
  const key = `relayfold:douyin-web-notifications:${account.id}`;
  const [notifications, setNotifications] = useState(() => localStorage.getItem(key) === 'on');
  const [status, setStatus] = useState<Status>('loading');
  const [error, setError] = useState('');
  const { utility, account: accountDialog, accountAdder, confirmation, groupEditor, groupMenuOpen, pending } = workspace.state;
  const shown = !openMobile && !utility && !accountDialog && !accountAdder && !confirmation && !groupEditor
    && !groupMenuOpen && pending !== 'group' && status !== 'error';
  const visible = useRef(shown);
  const notificationPreference = useRef(notifications);
  const { id: bindingId, group_id: groupId } = account;

  const measure = useCallback(() => {
    const bounds = target.current?.getBoundingClientRect();
    return bounds && {
      x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height, visible: visible.current,
    };
  }, []);

  useEffect(() => {
    let active = true;
    const sync = () => {
      if (active) void window.publisher.douyinPane('layout', { token, rect: measure() }).catch(() => {});
    };
    const unsubscribe = window.publisher.subscribeDouyinPane((source, status) => {
      if (active && source === token) setStatus(status);
    });
    const observer = new ResizeObserver(sync);
    if (target.current) observer.observe(target.current);
    window.addEventListener('resize', sync);
    window.addEventListener('scroll', sync, true);
    void window.publisher.douyinPane('open', {
      token, groupId, bindingId, kind, notifications: notificationPreference.current, rect: measure(),
    }).then(sync).catch(cause => {
      if (active) { setError(errorMessage(cause)); setStatus('error'); }
    });
    return () => {
      active = false;
      unsubscribe();
      observer.disconnect();
      window.removeEventListener('resize', sync);
      window.removeEventListener('scroll', sync, true);
      void window.publisher.douyinPane('close', { token }).catch(() => {});
    };
  }, [bindingId, groupId, kind, measure, token]);

  useEffect(() => {
    visible.current = shown;
    void window.publisher.douyinPane('layout', { token, rect: measure() }).catch(() => {});
  }, [measure, shown, token]);

  async function changeNotifications(enabled: boolean) {
    try {
      await window.publisher.douyinPane('notifications', { token, enabled });
      localStorage.setItem(key, enabled ? 'on' : 'off');
      notificationPreference.current = enabled;
      setNotifications(enabled);
    } catch (cause) {
      setError(errorMessage(cause));
    }
  }

  async function reload() {
    setError('');
    try { await window.publisher.douyinPane('reload', { token }); }
    catch (cause) { setError(errorMessage(cause)); }
  }

  return <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2">
    <div className="flex shrink-0 flex-wrap items-center justify-between gap-2">
      <div className="flex min-w-0 items-center gap-2">
        <Button variant="ghost" size="sm" type="button" onClick={onClose}><ArrowLeft data-icon="inline-start" />返回工作台</Button>
        <span className="truncate text-xs text-muted-foreground" title={name}>{name}</span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
          <Checkbox checked={notifications} onCheckedChange={next => void changeNotifications(next === true)} />
          允许网页通知
        </label>
        <Button type="button" variant="outline" size="icon-sm" aria-label="重新加载抖音网页" onClick={() => void reload()}><RefreshCw /></Button>
      </div>
    </div>
    <p className="shrink-0 text-xs text-muted-foreground">
      {kind === 'private' ? '登录后点抖音网页上的「消息」。' : '在抖音创作者中心查看和回复作品评论。'}
      {notifications ? ' 此页保持打开时，抖音网页发出的通知可由 Windows 显示。' : ' 首次使用请在官方页面登录并核对账号。'}
    </p>
    <div ref={target} aria-label="内嵌抖音网页" className="workspace-panel grid min-h-0 flex-1 place-items-center overflow-hidden rounded-xl bg-background p-4">
      {status === 'error' ? <ErrorNotice>{error || '抖音页面没有加载成功。可以重新加载，或返回后通过浏览器打开。'}</ErrorNotice>
        : <p role="status" className="text-sm text-muted-foreground">{status === 'loading' ? '正在加载抖音…' : '抖音网页已加载。'}</p>}
    </div>
  </div>;
}
