import { CircleCheck, LoaderCircle } from 'lucide-react';
import { useEffect, useLayoutEffect, useRef, type CSSProperties } from 'react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Breadcrumb, BreadcrumbItem, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator } from '@/components/ui/breadcrumb';
import { Card, CardContent } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar';
import { Skeleton } from '@/components/ui/skeleton';
import { TooltipProvider } from '@/components/ui/tooltip';
import { PublishPage } from './publisher/publish-page';
import { AccountsPage, HistoryPage } from './publisher/records-pages';
import { SettingsPage } from './publisher/settings-page';
import { MessagesPage } from './publisher/messages-page';
import { VideoDownloadPage } from './publisher/video-download-page';
import { VideoProcessingPage } from './publisher/video-processing-page';
import { usePublisherWorkspace, type PublisherWorkspace } from './publisher/use-workspace';
import { WorkspaceDialogs } from './publisher/workspace-dialogs';
import { WorkspaceSidebar } from './publisher/workspace-sidebar';
import { ErrorNotice, WorkspaceBrand } from './publisher/workspace-ui';
import { navigation } from './publisher/model';
import { WorkspaceUtilities } from './publisher/workspace-utilities';

const pages = {
  'video-download': VideoDownloadPage, 'video-processing': VideoProcessingPage,
  publish: PublishPage, accounts: AccountsPage, history: HistoryPage, comments: MessagesPage, settings: SettingsPage,
};

function WorkspaceHeader({ workspace }: { workspace: PublisherWorkspace }) {
  const { group, state: { view } } = workspace;
  const title = view === 'settings' ? '设置' : navigation.find(item => item.id === view)?.label;
  return <header className="workspace-window-header z-20 flex h-13 shrink-0 items-center justify-between gap-3 border-b border-border/75 bg-background px-3 sm:px-5">
    <div className="flex min-w-0 items-center gap-2.5">
      <SidebarTrigger aria-label="切换侧栏" />
      <WorkspaceBrand className="md:hidden" />
      <Separator orientation="vertical" className="data-[orientation=vertical]:h-4" />
      <Breadcrumb className="min-w-0">
        <BreadcrumbList className="flex-nowrap">
          <BreadcrumbItem className="hidden shrink-0 sm:inline-flex">工作台</BreadcrumbItem>
          <BreadcrumbSeparator className="hidden sm:list-item" />
          <BreadcrumbItem className="min-w-0"><BreadcrumbPage className="truncate font-medium">{title}</BreadcrumbPage></BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>
    </div>
    {group && view !== 'settings' && <Badge variant="secondary" className="max-w-24 truncate md:hidden">{group.name}</Badge>}
  </header>;
}

function LoadingWorkspace() {
  return <div role="status" aria-label="正在加载本地数据" className="grid gap-4">
    <Skeleton className="h-8 w-32" />
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(15.5rem,0.49fr)]">
      {[0, 1].map(item => <Card key={item}><CardContent className="grid gap-3">
        <Skeleton className="h-4 w-28" /><Skeleton className="h-20 w-full" />
      </CardContent></Card>)}
    </div>
  </div>;
}

export function App() {
  const workspace = usePublisherWorkspace();
  const { state, group, othersInProgress } = workspace;
  const Page = pages[state.view];
  const viewport = useRef<HTMLDivElement>(null);
  const contained = state.view === 'comments' || state.view === 'video-processing';

  useEffect(() => { viewport.current?.scrollTo(0, 0); }, [state.view, group?.id]);
  useLayoutEffect(() => {
    document.documentElement.dataset.accentTheme = workspace.visibleTheme;
  }, [workspace.visibleTheme]);

  return <TooltipProvider delayDuration={300}>
    <SidebarProvider className="publisher-shell h-dvh min-h-0 overflow-hidden" style={{ '--sidebar-width': '13.75rem' } as CSSProperties}>
      <WorkspaceSidebar workspace={workspace} />
      <SidebarInset className="workspace-stage min-h-0 min-w-0">
        <WorkspaceHeader workspace={workspace} />
        <div ref={viewport} data-slot="workspace-viewport"
          className={`min-h-0 flex-1 ${contained ? 'overflow-hidden' : 'overflow-y-auto overscroll-contain'}`}>
          <div className={`mx-auto w-full max-w-[84rem] min-w-0 gap-4 px-4 pt-5 pb-8 sm:px-6 sm:pt-7 lg:px-7 ${contained ? 'flex h-full min-h-0 flex-col max-sm:pb-4' : 'grid'}`}>
            {state.connectionError && <ErrorNotice>{state.connectionError}</ErrorNotice>}
            {state.error && !state.account && !state.accountAdder && !state.confirmation && state.groupEditor === null && <ErrorNotice>{state.error}</ErrorNotice>}
            {state.notice && <Alert role="status"><CircleCheck /><AlertDescription>{state.notice}</AlertDescription></Alert>}
            {othersInProgress > 0 && <Alert role="status">
              <LoaderCircle className="animate-spin" /><AlertDescription>其他发布组有 {othersInProgress} 条任务在运行，目标账号已固定。</AlertDescription>
            </Alert>}
            {group ? <Page workspace={workspace} /> : !state.connectionError && <LoadingWorkspace />}
          </div>
        </div>
      </SidebarInset>
      <WorkspaceDialogs workspace={workspace} />
      <WorkspaceUtilities workspace={workspace} />
    </SidebarProvider>
  </TooltipProvider>;
}
