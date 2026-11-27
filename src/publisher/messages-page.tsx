import { MessageSquareText, MessagesSquare } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { CommentsPage } from './comments-page';
import { DouyinMessages } from './douyin-messages';
import { PrivateMessages } from './private-messages';
import type { PublisherWorkspace } from './use-workspace';
import { WorkspaceHeading, WorkspaceSelect } from './workspace-ui';

const platforms = [{ value: 'douyin', label: '抖音' }, { value: 'xiaohongshu', label: '小红书' }] as const;
type MessagePlatform = typeof platforms[number]['value'];

export function MessagesPage({ workspace }: { workspace: PublisherWorkspace }) {
  const group = workspace.group!;
  const [selected, setSelected] = useState<MessagePlatform>();
  const [view, setView] = useState<string>();
  const destination = workspace.state.commentDestination;
  const bound = workspace.state.data?.bindings ?? [];
  const platform = selected ?? (bound.some(binding => binding.platform === 'xiaohongshu' && binding.label)
    && !bound.some(binding => binding.platform === 'douyin' && binding.label) ? 'xiaohongshu' : 'douyin');
  const currentView = view ?? (platform === 'douyin' ? 'private' : 'comments');

  useEffect(() => {
    if (destination?.group_id === group.id) {
      setSelected('xiaohongshu');
      setView('comments');
    }
  }, [destination, group.id]);

  return <>
    <div className="flex shrink-0 flex-wrap items-end justify-between gap-2">
      <WorkspaceHeading title="消息" description={`${group.name} · ${workspace.nameOf(platform)}`} />
      <WorkspaceSelect label="切换消息平台" value={platform} options={platforms} onValueChange={next => {
        if (next !== 'douyin' && next !== 'xiaohongshu') return;
        setSelected(next);
        setView(undefined);
      }} />
    </div>
    <Tabs value={currentView} onValueChange={setView} className="min-h-0 flex-1">
      <TabsList variant="line" aria-label="消息类型" className="mb-2 shrink-0 self-start">
        <TabsTrigger value="comments" className="px-3"><MessageSquareText />评论</TabsTrigger>
        <TabsTrigger value="private" className="px-3"><MessagesSquare />私信</TabsTrigger>
      </TabsList>
      <TabsContent value="comments" className="flex min-h-0 min-w-0 flex-1 flex-col gap-2">
        {platform === 'douyin' ? <DouyinMessages key={group.id} kind="comments" workspace={workspace} />
          : <CommentsPage workspace={workspace} />}
      </TabsContent>
      <TabsContent value="private" className="flex min-h-0 min-w-0 flex-1 flex-col">
        {platform === 'douyin' ? <DouyinMessages key={group.id} kind="private" workspace={workspace} />
          : <PrivateMessages key={group.id} workspace={workspace} />}
      </TabsContent>
    </Tabs>
  </>;
}
