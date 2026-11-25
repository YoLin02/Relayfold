import type { AccentTheme } from '@/types';

export const accentThemes = [
  { id: 'neutral', name: '默认', description: '黑白灰' },
  { id: 'sky', name: '浅蓝', description: '浅蓝工作区 · 蓝色点缀' },
  { id: 'cyan', name: '青蓝', description: '呼应图标的亮青折带' },
  { id: 'violet', name: '蓝紫', description: '呼应图标的蓝紫折带' },
] as const satisfies readonly { id: AccentTheme; name: string; description: string }[];
