import { Check, CircleHelp, Pencil, Plus, Search, Settings, Trash2, UsersRound, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuTrigger } from '@/components/ui/context-menu';
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupAction, SidebarGroupContent,
  SidebarGroupLabel, SidebarHeader, SidebarMenu, SidebarMenuBadge, SidebarMenuButton, SidebarMenuItem,
  useSidebar,
} from '@/components/ui/sidebar';
import { navigation } from './model';
import type { PublisherWorkspace } from './use-workspace';
import { WorkspaceBrand } from './workspace-ui';

export function WorkspaceSidebar({ workspace }: { workspace: PublisherWorkspace }) {
  const { isMobile, setOpenMobile } = useSidebar();
  const { groups, group, state, activeTasks, isBusy, boundGroups } = workspace;
  const close = () => { if (isMobile) setOpenMobile(false); };
  return <Sidebar collapsible="icon">
    <SidebarHeader className="h-13 shrink-0 flex-row items-center justify-between border-b border-sidebar-border/80 px-4 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0 md:workspace-window-drag">
      <WorkspaceBrand />
      {isMobile && <Button variant="ghost" size="icon-sm" aria-label="关闭侧栏" onClick={close}><X /></Button>}
    </SidebarHeader>
    <SidebarContent>
      <SidebarGroup className="pt-3">
        <SidebarGroupLabel>工作台</SidebarGroupLabel>
        <SidebarGroupContent>
          <SidebarMenu>
            {navigation.map(({ id, label, icon: Icon }) => <SidebarMenuItem key={id}>
              <SidebarMenuButton type="button" className="gap-2.5 data-active:font-semibold" isActive={state.view === id} tooltip={label} aria-current={state.view === id ? 'page' : undefined}
                onClick={() => { workspace.changeView(id); close(); }}>
                <Icon aria-hidden="true" /><span>{label}</span>
              </SidebarMenuButton>
              {id === 'history' && activeTasks > 0 && <SidebarMenuBadge>{activeTasks}</SidebarMenuBadge>}
            </SidebarMenuItem>)}
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>
      <SidebarGroup className="mt-3">
        <SidebarGroupLabel>账号</SidebarGroupLabel>
        <SidebarGroupAction type="button"
          aria-label="新建发布组" title="新建发布组" disabled={isBusy}
          onClick={() => { close(); workspace.update({ groupEditor: { name: '', mode: 'regular' }, error: '' }); }}><Plus /></SidebarGroupAction>
        <SidebarGroupContent>
          <SidebarMenu>
            {groups.map(item => {
              const active = item.id === group?.id;
              return <SidebarMenuItem key={item.id}>
                <ContextMenu modal={false}>
                  <ContextMenuTrigger asChild disabled={isBusy}>
                    <SidebarMenuButton type="button" className="gap-2.5 data-active:font-semibold" isActive={active} tooltip={item.name} aria-label={item.name}
                      aria-pressed={active} disabled={isBusy} onClick={() => { workspace.selectGroup(item.id); close(); }}>
                      <UsersRound aria-hidden="true" className="hidden group-data-[collapsible=icon]:block" />
                      <span className="min-w-0 flex-1 truncate group-data-[collapsible=icon]:hidden">{item.name}</span>
                      {active && <Check aria-hidden="true" className="ml-auto size-3.5 text-muted-foreground group-data-[collapsible=icon]:hidden" />}
                      {!active && !boundGroups.has(item.id) && <span className="shrink-0 text-[11px] text-muted-foreground group-data-[collapsible=icon]:hidden">待绑定</span>}
                    </SidebarMenuButton>
                  </ContextMenuTrigger>
                  <ContextMenuContent className="min-w-36">
                    <ContextMenuItem onSelect={() => {
                      close();
                      workspace.update({ groupEditor: { group: item, name: item.name, mode: item.mode }, error: '' });
                    }}><Pencil />重命名</ContextMenuItem>
                    <ContextMenuItem variant="destructive" disabled={groups.length === 1}
                      onSelect={() => { close(); workspace.showConfirmation({ type: 'delete-group', group: item }); }}>
                      <Trash2 />删除
                    </ContextMenuItem>
                  </ContextMenuContent>
                </ContextMenu>
              </SidebarMenuItem>;
            })}
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>
    </SidebarContent>
    <SidebarFooter className="px-2.5 pb-3">
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton type="button" tooltip="设置" isActive={state.view === 'settings'}
            aria-current={state.view === 'settings' ? 'page' : undefined} onClick={() => { workspace.changeView('settings'); close(); }}>
            <Settings /><span>设置</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton type="button" tooltip="帮助" aria-label="帮助" onClick={() => {
            close();
            workspace.update({ utility: 'help', error: '' });
          }}>
            <CircleHelp /><span>帮助</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton type="button" tooltip="搜索" aria-label="搜索" aria-keyshortcuts="Control+k" onClick={() => {
            close();
            workspace.update({ utility: 'search', error: '' });
          }}>
            <Search /><span className="flex-1">搜索</span>
            <kbd className="rounded border bg-background px-1 text-[10px] text-muted-foreground group-data-[collapsible=icon]:hidden">Ctrl K</kbd>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </SidebarFooter>
  </Sidebar>;
}
