export function scheduleInput(minutesAhead = 0) {
  const minute = 60_000;
  const date = new Date(Math.ceil(Date.now() / minute) * minute + minutesAhead * minute);
  return localInputValue(date);
}

function localInputValue(date: Date) {
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

export function scheduleTimestamp(value: string) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime()) || date.getTime() <= Date.now() || localInputValue(date) !== value) return null;
  return Math.floor(date.getTime() / 1000);
}

export function formatSchedule(timestamp: number) {
  return new Date(timestamp * 1000).toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    hour12: false, timeZoneName: 'short',
  });
}
