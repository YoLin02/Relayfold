import { useState } from 'react';
import { ChevronsUpDown } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import type { Binding } from '@/types';
import type { PublisherWorkspace } from './use-workspace';
import { PlatformIcon } from './workspace-ui';

export function MessageAccountPicker({ workspace, accounts, selected, name, onSelect, label }: {
  workspace: PublisherWorkspace; accounts: Binding[]; selected: Binding; name: (binding: Binding) => string;
  onSelect: (binding: Binding) => void; label: string;
}) {
  const [open, setOpen] = useState(false);
  const platforms = [...new Set(accounts.map(binding => binding.platform))];

  return <Popover open={open} onOpenChange={setOpen}>
    <PopoverTrigger asChild>
      <Button type="button" variant="outline" aria-label={label} disabled={workspace.isBusy}
        className="max-w-full min-w-0 justify-start data-open:bg-muted">
        <PlatformIcon platform={selected.platform} />
        <span className="min-w-0 truncate">{workspace.nameOf(selected.platform)} · {name(selected)}</span>
        <ChevronsUpDown className="text-muted-foreground" />
      </Button>
    </PopoverTrigger>
    <PopoverContent align="end" aria-label={label}
      className="flex max-h-(--radix-popover-content-available-height) w-[max(16rem,var(--radix-popover-trigger-width))] max-w-[calc(100vw-1rem)] overflow-hidden">
      <Command className="h-auto min-h-0">
        <CommandInput aria-label="搜索账号昵称或编号" placeholder="搜索账号昵称或编号" />
        <CommandList>
          <CommandEmpty className="text-muted-foreground">没有找到匹配的账号。</CommandEmpty>
          {platforms.map(platform => <CommandGroup key={platform} heading={workspace.nameOf(platform)}>
            {accounts.filter(binding => binding.platform === platform).map(binding => <CommandItem key={binding.id} value={binding.id}
              keywords={[binding.label, workspace.bindingName(binding)]} data-checked={binding.id === selected.id} onSelect={() => {
                setOpen(false);
                if (binding.id !== selected.id) onSelect(binding);
              }}>
              <PlatformIcon platform={binding.platform} />
              <span className="min-w-0 truncate">{name(binding)}</span>
            </CommandItem>)}
          </CommandGroup>)}
        </CommandList>
      </Command>
    </PopoverContent>
  </Popover>;
}
