import { useEffect } from 'react';
import { Settings } from 'lucide-react';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { navigation } from './model';
import type { PublisherWorkspace } from './use-workspace';
import { ErrorNotice, PlatformMark } from './workspace-ui';

const help = [
  { id: 'groups', label: '怎么添加另一套账号？', description: '点击左下角的发布组头像，再选「新建发布组」。创建后进入平台账号页，逐个平台登录并确认绑定。' },
  { id: 'sessions', label: '为什么发布目标里找不到平台？', description: '目标只显示当前账号组内已绑定、符合平台范围且支持当前内容类型的平台。在「平台账号」中可以查看绑定状态。' },
  { id: 'publish', label: '怎么为每个平台填写不同内容？', description: '勾选支持差异化发布的平台，然后在素材与文案区切换平台标签页。改过的字段单独提交，其余沿用通用内容。群发前可以并排核对。' },
] as const;

export function WorkspaceUtilities({ workspace }: { workspace: PublisherWorkspace }) {
  const { utility, pending, account, accountAdder, confirmation, groupEditor, error, data } = workspace.state;
  const canShortcut = !!data && !pending && !account && !accountAdder && !confirmation && groupEditor === null && utility !== 'help';
  const update = workspace.update;
  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      if (!canShortcut || event.defaultPrevented || event.isComposing
        || !(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'k') return;
      event.preventDefault();
      update({ utility: 'search', groupMenuOpen: false, error: '' });
    }
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  }, [canShortcut, update]);

  if (!utility) return null;
  const close = (open: boolean) => { if (!open && !pending) update({ utility: null, error: '' }); };
  const groups = new Map(workspace.groups.map(group => [group.id, group]));
  if (utility === 'help') {
    return <Dialog open onOpenChange={close}>
      <DialogContent className="max-h-[calc(100dvh-1.5rem)] overflow-auto">
        <DialogHeader><DialogTitle>帮助</DialogTitle><DialogDescription>账号绑定和群发的常见问题</DialogDescription></DialogHeader>
        <Accordion type="single" collapsible>
          {help.map(item => <AccordionItem key={item.id} value={item.id}>
            <AccordionTrigger>{item.label}</AccordionTrigger>
            <AccordionContent className="text-muted-foreground">{item.description}</AccordionContent>
          </AccordionItem>)}
        </Accordion>
      </DialogContent>
    </Dialog>;
  }
  return <Dialog open onOpenChange={close}>
    <DialogContent showCloseButton={false} className="top-[24vh] max-h-[70vh] translate-y-0 gap-1 overflow-hidden p-0">
      <DialogHeader className="sr-only">
        <DialogTitle>搜索工作台</DialogTitle><DialogDescription>查找发布组、平台账号或工作台页面。</DialogDescription>
      </DialogHeader>
      {error && <div className="p-2"><ErrorNotice>{error}</ErrorNotice></div>}
      <Command loop>
        <CommandInput aria-label="搜索工作台" placeholder="搜索账号组、平台账号或页面…" disabled={!!pending} />
        <CommandList>
          <CommandEmpty>没有找到匹配项</CommandEmpty>
          {workspace.searchableBindings.length > 0 && <CommandGroup heading="平台账号">
            {workspace.searchableBindings.map(binding => {
              const platform = workspace.bindingName(binding);
              const group = groups.get(binding.group_id);
              return <CommandItem key={binding.id} value={binding.id}
                keywords={[platform, binding.platform, binding.label, group?.name || '']}
                disabled={workspace.isBusy} onSelect={() => workspace.jumpToGroup(binding.group_id, binding)}>
                <PlatformMark platform={binding.platform} />
                <span className="min-w-0"><span className="block truncate">{platform} · {binding.label}</span>
                  <span className="block truncate text-xs text-muted-foreground">{group?.name}</span></span>
              </CommandItem>;
            })}
          </CommandGroup>}
          <CommandGroup heading="账号">
            {workspace.groups.map(group => <CommandItem key={group.id} value={group.id} keywords={[group.name, '发布组', '账号']}
              disabled={workspace.isBusy} onSelect={() => workspace.jumpToGroup(group.id)}>{group.name}</CommandItem>)}
          </CommandGroup>
          <CommandGroup heading="跳转">
            {navigation.map(({ id, label, icon: Icon }) => <CommandItem key={id} value={label} keywords={id === 'comments' ? ['评论', '私信'] : undefined}
              onSelect={() => workspace.changeView(id)}><Icon />{label}</CommandItem>)}
            <CommandItem value="设置" onSelect={() => workspace.changeView('settings')}><Settings />设置</CommandItem>
          </CommandGroup>
        </CommandList>
      </Command>
    </DialogContent>
  </Dialog>;
}
