import { Check, ChevronUp, CircleHelp, Pencil, Plus, Search, Settings, Trash2, X } from 'lucide-react';
import { useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupContent,
  SidebarGroupLabel, SidebarHeader, SidebarMenu, SidebarMenuBadge, SidebarMenuButton, SidebarMenuItem,
  useSidebar,
} from '@/components/ui/sidebar';
import { cn } from '@/lib/utils';
import type { Group } from '@/types';
import { editingTools, publishingTools, workbench, type navigation } from './model';
import type { PublisherWorkspace } from './use-workspace';
import { WorkspaceBrand } from './workspace-ui';

function GroupAvatar({ name, className }: { name: string; className?: string }) {
  const initial = name.match(/\s([A-Za-z0-9])$/u)?.[1] || Array.from(name.trim())[0] || '组';
  return <span aria-hidden="true" className={cn('grid size-8 shrink-0 place-items-center rounded-lg bg-primary/10 text-xs font-semibold text-primary', className)}>
    {initial.toUpperCase()}
  </span>;
}

function GroupSwitcher({ workspace, closeSidebar }: { workspace: PublisherWorkspace; closeSidebar: () => void }) {
  const { group, groups, isBusy, state, update } = workspace;
  if (!group) return null;

  function edit(item?: Group) {
    closeSidebar();
    update({ groupMenuOpen: false, groupEditor: item ? { group: item, name: item.name, mode: item.mode } : { name: '', mode: 'regular' }, error: '' });
  }

  return <Popover open={state.groupMenuOpen} onOpenChange={groupMenuOpen => update({ groupMenuOpen })}>
    <PopoverTrigger asChild>
      <SidebarMenuButton type="button" size="lg" aria-label={`切换发布组，当前 ${group.name}`} tooltip="切换发布组"
        className="gap-2 data-[state=open]:bg-sidebar-accent group-data-[collapsible=icon]:p-0!" disabled={isBusy}>
        <GroupAvatar name={group.name} />
        <span className="min-w-0 flex-1 leading-tight group-data-[collapsible=icon]:hidden">
          <span className="block truncate font-medium">{group.name}</span>
          <span className="block truncate text-xs text-muted-foreground">当前发布组</span>
        </span>
        <ChevronUp aria-hidden="true" className="text-muted-foreground group-data-[collapsible=icon]:hidden" />
      </SidebarMenuButton>
    </PopoverTrigger>
    <PopoverContent align="start" side="top" sideOffset={8} aria-label="切换发布组"
      className="flex w-64 max-w-[calc(100vw-1rem)] max-h-(--radix-popover-content-available-height) flex-col p-1.5">
      <p className="px-2 pt-1.5 pb-1 text-xs font-medium text-muted-foreground">切换发布组</p>
      <ul className="min-h-0 overflow-y-auto overscroll-contain" aria-label="发布组列表">
        {groups.map(item => <li key={item.id} className="flex items-center gap-0.5">
          <Button type="button" variant="ghost" aria-label={item.name} aria-pressed={item.id === group.id} disabled={isBusy}
            className="h-auto min-w-0 flex-1 justify-start gap-2 px-1.5 py-1.5 text-left"
            onClick={() => { update({ groupMenuOpen: false }); workspace.selectGroup(item.id); closeSidebar(); }}>
            <GroupAvatar name={item.name} className="size-7" />
            <span className="min-w-0 flex-1 truncate">{item.name}</span>
            {item.id === group.id && <Check aria-hidden="true" className="text-primary" />}
          </Button>
          <Button type="button" variant="ghost" size="icon-xs" aria-label={`重命名 ${item.name}`} title={`重命名 ${item.name}`}
            disabled={isBusy} onClick={() => edit(item)}><Pencil /></Button>
          <Button type="button" variant="ghost" size="icon-xs" aria-label={`删除 ${item.name}`} title={`删除 ${item.name}`}
            disabled={isBusy || groups.length === 1} onClick={() => {
              closeSidebar();
              update({ groupMenuOpen: false });
              workspace.showConfirmation({ type: 'delete-group', group: item });
            }}><Trash2 /></Button>
        </li>)}
      </ul>
      <div className="mt-1 border-t pt-1">
        <Button type="button" variant="ghost" className="w-full justify-start" disabled={isBusy} onClick={() => edit()}>
          <Plus data-icon="inline-start" />新建发布组
        </Button>
      </div>
    </PopoverContent>
  </Popover>;
}

export function WorkspaceSidebar({ workspace }: { workspace: PublisherWorkspace }) {
  const { isMobile, openMobile, setOpenMobile } = useSidebar();
  const { state, activeTasks, update } = workspace;
  const close = () => { if (isMobile) setOpenMobile(false); };
  useEffect(() => {
    if (isMobile && !openMobile && state.groupMenuOpen) update({ groupMenuOpen: false });
  }, [isMobile, openMobile, state.groupMenuOpen, update]);

  function item({ id, label, icon: Icon }: typeof navigation[number]) {
    return <SidebarMenuItem key={id}>
      <SidebarMenuButton type="button" className="gap-2.5 data-active:font-semibold" isActive={state.view === id} tooltip={label}
        aria-current={state.view === id ? 'page' : undefined} onClick={() => { workspace.changeView(id); close(); }}>
        <Icon aria-hidden="true" /><span>{label}</span>
      </SidebarMenuButton>
      {id === 'history' && activeTasks > 0 && <SidebarMenuBadge>{activeTasks}</SidebarMenuBadge>}
      {id === 'comments' && !!state.commentSettings?.unread && <SidebarMenuBadge
        aria-label={`${state.commentSettings.unread} 条未读评论`} className="text-primary">
        {state.commentSettings.unread > 99 ? '99+' : state.commentSettings.unread}
      </SidebarMenuBadge>}
    </SidebarMenuItem>;
  }

  return <Sidebar collapsible="icon">
    <SidebarHeader className="h-13 shrink-0 flex-row items-center justify-between border-b border-sidebar-border/80 px-4 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0 md:workspace-window-drag">
      <WorkspaceBrand />
      {isMobile && <Button variant="ghost" size="icon-sm" aria-label="关闭侧栏" onClick={close}><X /></Button>}
    </SidebarHeader>
    <SidebarContent className="group-data-[collapsible=icon]:overflow-x-hidden group-data-[collapsible=icon]:overflow-y-auto">
      <nav aria-label="工作台导航">
        <SidebarGroup className="pt-3"><SidebarMenu>{item(workbench)}</SidebarMenu></SidebarGroup>
        <SidebarGroup>
          <SidebarGroupLabel>剪辑工具</SidebarGroupLabel>
          <SidebarGroupContent><SidebarMenu>{editingTools.map(item)}</SidebarMenu></SidebarGroupContent>
        </SidebarGroup>
        <SidebarGroup>
          <SidebarGroupLabel>发布与账号</SidebarGroupLabel>
          <SidebarGroupContent><SidebarMenu>{publishingTools.map(item)}</SidebarMenu></SidebarGroupContent>
        </SidebarGroup>
      </nav>
    </SidebarContent>
    <SidebarFooter className="px-2.5 pb-2.5">
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton type="button" tooltip="设置" isActive={state.view === 'settings'}
            aria-current={state.view === 'settings' ? 'page' : undefined} onClick={() => { workspace.changeView('settings'); close(); }}>
            <Settings /><span>设置</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton type="button" tooltip="帮助" aria-label="帮助" onClick={() => {
            close(); workspace.update({ utility: 'help', error: '' });
          }}><CircleHelp /><span>帮助</span></SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton type="button" tooltip="搜索" aria-label="搜索" aria-keyshortcuts="Control+k" onClick={() => {
            close(); workspace.update({ utility: 'search', error: '' });
          }}>
            <Search /><span className="flex-1">搜索</span>
            <kbd className="rounded border bg-background px-1 text-[10px] text-muted-foreground group-data-[collapsible=icon]:hidden">Ctrl K</kbd>
          </SidebarMenuButton>
        </SidebarMenuItem>
        {workspace.group && <SidebarMenuItem className="mt-1 border-t border-sidebar-border pt-1.5">
          <GroupSwitcher workspace={workspace} closeSidebar={close} />
        </SidebarMenuItem>}
      </SidebarMenu>
    </SidebarFooter>
  </Sidebar>;
}
