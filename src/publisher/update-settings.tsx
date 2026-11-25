import { useEffect, useState } from 'react';
import { ArrowDownToLine, LoaderCircle, RefreshCw } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import type { UpdateStatus } from '@/types';

function describe(status: UpdateStatus) {
  switch (status.phase) {
    case 'unsupported': return '当前构建不支持在线更新。';
    case 'checking': return '正在检查更新…';
    case 'current': return '已是最新版本。';
    case 'available': return `发现新版 v${status.available}，可以下载。`;
    case 'downloading': return `正在下载 v${status.available}（${status.progress}%）`;
    case 'ready': return `v${status.available} 已下载并通过校验。`;
    case 'error': return status.error;
    default: return '可检查并下载 Relayfold 更新。';
  }
}

export function UpdateSettings() {
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    const unsubscribe = window.publisher.subscribeUpdates(setStatus);
    void window.publisher.update('status').then(value => {
      if (active) setStatus(previous => previous ?? value);
    }).catch(() => { if (active) setError('无法读取软件更新状态。'); });
    return () => { active = false; unsubscribe(); };
  }, []);

  async function act(action: 'check' | 'download' | 'install') {
    setError('');
    if (action === 'install') setInstalling(true);
    try {
      const result = await window.publisher.update(action);
      if (action !== 'install') setStatus(result);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message.replace(/^Error invoking remote method '[^']+': Error: /, '') : '更新操作失败。');
      setInstalling(false);
    }
  }

  const working = status?.phase === 'checking' || status?.phase === 'downloading';
  const action = status?.phase === 'ready' ? 'install' : status?.phase === 'available' ? 'download' : 'check';
  const label = action === 'install' ? '安装并重启' : action === 'download' ? '下载更新' : '检查更新';
  const ActionIcon = working ? LoaderCircle : action === 'download' ? ArrowDownToLine : RefreshCw;

  return <Card className="workspace-panel">
    <CardHeader>
      <CardTitle className="flex items-center gap-2">软件更新
        {status && <Badge variant="secondary">v{status.current}</Badge>}
      </CardTitle>
      <CardDescription>配置更新通道后，可检查并安装 Windows 版本。</CardDescription>
    </CardHeader>
    <CardContent>
      <p className="text-sm text-muted-foreground" role="status">{status ? describe(status) : error || '正在读取版本…'}</p>
      {status?.phase === 'downloading' && <progress aria-label="更新下载进度" max={100} value={status.progress}
        className="mt-3 h-2 w-full accent-primary" />}
    </CardContent>
    <CardFooter className="justify-end border-t">
      <Button type="button" variant={action === 'check' ? 'outline' : 'default'}
        disabled={!status || status.phase === 'unsupported' || working || installing}
        onClick={() => action === 'install' ? setConfirm(true) : void act(action)}>
        <ActionIcon data-icon="inline-start" className={working ? 'animate-spin' : undefined} />{label}
      </Button>
    </CardFooter>
    <Dialog open={confirm} onOpenChange={value => { if (!installing) setConfirm(value); }}>
      <DialogContent showCloseButton={!installing}>
        <DialogHeader>
          <DialogTitle>安装 Relayfold v{status?.available}</DialogTitle>
          <DialogDescription>安装会重启软件。账号与预约会保留，请先处理正在编辑的草稿。</DialogDescription>
        </DialogHeader>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <DialogFooter>
          <Button type="button" variant="outline" disabled={installing} onClick={() => setConfirm(false)}>稍后</Button>
          <Button type="button" disabled={installing} onClick={() => void act('install')}>
            {installing && <LoaderCircle className="animate-spin" data-icon="inline-start" />}确认重启
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </Card>;
}
