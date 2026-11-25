import { Globe2, LoaderCircle, MapPin } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { cn } from '@/lib/utils';
import type { AccentTheme, PlatformRegion } from '@/types';
import { accentThemes } from './appearance';
import { platformRegions } from './model';
import { UpdateSettings } from './update-settings';
import type { PublisherWorkspace } from './use-workspace';
import { WorkspaceHeading } from './workspace-ui';

const regionIcons = { domestic: MapPin, international: Globe2 };

function AppearanceSettings({ workspace }: { workspace: PublisherWorkspace }) {
  const { settingsTheme, pending } = workspace.state;
  const selected = settingsTheme ?? workspace.theme;
  const dirty = selected !== workspace.theme;
  const saving = pending === 'settings-theme';

  return <form onSubmit={event => { event.preventDefault(); workspace.saveTheme(); }}>
    <Card className="workspace-panel">
      <CardHeader>
        <CardTitle id="appearance-label">外观</CardTitle>
        <CardDescription>选择点缀色即时预览，保存后下次打开仍会使用。</CardDescription>
      </CardHeader>
      <CardContent>
        <RadioGroup aria-labelledby="appearance-label" value={selected} disabled={saving} className="sm:grid-cols-2"
          onValueChange={value => workspace.update({ settingsTheme: value as AccentTheme, notice: '', error: '' })}>
          {accentThemes.map(option => <label key={option.id} className={cn(
            'flex cursor-pointer items-center gap-3 rounded-lg border p-3 transition-colors hover:bg-accent/65',
            selected === option.id && 'border-primary/35 bg-accent',
          )}>
            <span aria-hidden="true" data-accent-theme={option.id}
              className="theme-option-swatch size-9 shrink-0 rounded-md border" />
            <span className="min-w-0 flex-1">
              <span id={`accent-theme-${option.id}`} className="block text-sm font-medium">{option.name}</span>
              <span className="mt-0.5 block text-xs text-muted-foreground">{option.description}</span>
            </span>
            <RadioGroupItem value={option.id} aria-labelledby={`accent-theme-${option.id}`} />
          </label>)}
        </RadioGroup>
      </CardContent>
      <CardFooter className="justify-end gap-2 border-t">
        {dirty && <Button type="button" variant="outline" disabled={saving}
          onClick={() => workspace.update({ settingsTheme: null, error: '' })}>取消预览</Button>}
        <Button type="submit" disabled={!dirty || workspace.isBusy}>
          {saving && <LoaderCircle className="animate-spin" data-icon="inline-start" />}保存主题
        </Button>
      </CardFooter>
    </Card>
  </form>;
}

function PlatformSettings({ workspace }: { workspace: PublisherWorkspace }) {
  const { settingsRegion, pending } = workspace.state;
  const selected = settingsRegion ?? workspace.region;
  const dirty = selected !== workspace.region;
  const saving = pending === 'settings-region';

  return <form onSubmit={event => { event.preventDefault(); workspace.saveRegion(); }}>
      <Card className="workspace-panel">
        <CardHeader>
          <CardTitle id="platform-region-label">平台范围</CardTitle>
          <CardDescription>选择发布目标和平台账号页显示的平台。发布记录会保留两个范围的任务。</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          <RadioGroup aria-labelledby="platform-region-label" value={selected} disabled={saving} className="sm:grid-cols-2"
            onValueChange={value => workspace.update({ settingsRegion: value as PlatformRegion, notice: '', error: '' })}>
            {(Object.keys(platformRegions) as PlatformRegion[]).map(region => {
              const option = platformRegions[region];
              const Icon = regionIcons[region];
              return <label key={region} className={cn(
                'flex cursor-pointer items-center gap-3 rounded-lg border p-3 transition-colors hover:bg-muted/60',
                selected === region && 'border-foreground/25 bg-muted',
              )}>
                <span className="flex size-9 shrink-0 items-center justify-center rounded-md border bg-background text-muted-foreground">
                  <Icon className="size-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span id={`region-${region}`} className="block text-sm font-medium">{option.label}</span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">{option.examples}</span>
                </span>
                <RadioGroupItem value={region} aria-labelledby={`region-${region}`} />
              </label>;
            })}
          </RadioGroup>
          <p className="text-xs text-muted-foreground">自定义企业官网在两种范围都可用。</p>
        </CardContent>
        <CardFooter className="justify-end gap-2 border-t">
          {dirty && <Button type="button" variant="outline" disabled={saving}
            onClick={() => workspace.update({ settingsRegion: null, error: '' })}>取消更改</Button>}
          <Button type="submit" disabled={!dirty || workspace.isBusy}>
            {saving && <LoaderCircle className="animate-spin" data-icon="inline-start" />}保存设置
          </Button>
        </CardFooter>
      </Card>
  </form>;
}

export function SettingsPage({ workspace }: { workspace: PublisherWorkspace }) {
  return <div className="grid max-w-3xl gap-5">
    <WorkspaceHeading title="设置" />
    <AppearanceSettings workspace={workspace} />
    <PlatformSettings workspace={workspace} />
    <UpdateSettings />
  </div>;
}
