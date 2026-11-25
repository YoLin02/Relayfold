export const historyPeriods = [
  { value: 'all', label: '全部时间' },
  { value: 'today', label: '今天' },
  { value: 'week', label: '最近 7 天' },
  { value: 'month', label: '最近 30 天' },
  { value: 'custom', label: '自定义日期' },
] as const;

export type HistoryFilter = {
  period: typeof historyPeriods[number]['value'];
  from: string;
  to: string;
};

export const defaultHistoryFilter: HistoryFilter = { period: 'all', from: '', to: '' };

export function historyBounds(filter: HistoryFilter, now = new Date()) {
  if (filter.period === 'all') return { start: null, end: null };
  if (filter.period === 'custom') {
    const start = filter.from ? new Date(`${filter.from}T00:00:00`) : null;
    const last = filter.to ? new Date(`${filter.to}T00:00:00`) : null;
    if ((start && !Number.isFinite(start.getTime())) || (last && !Number.isFinite(last.getTime())) ||
        (start && last && start > last)) return null;
    last?.setDate(last.getDate() + 1);
    return { start: start?.toISOString() ?? null, end: last?.toISOString() ?? null };
  }
  const days = { today: 1, week: 7, month: 30 }[filter.period];
  const year = now.getFullYear(), month = now.getMonth(), day = now.getDate();
  return {
    start: new Date(year, month, day - days + 1).toISOString(),
    end: new Date(year, month, day + 1).toISOString(),
  };
}
