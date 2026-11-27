const { session, WebContentsView } = require('electron');

const destinations = new Map([
  ['private', 'https://www.douyin.com/'],
  ['comments', 'https://creator.douyin.com/creator-micro/interactive/comment'],
]);
const notificationOrigins = new Set([...destinations.values()].map(url => new URL(url).origin));
const bindingPattern = /^[a-f0-9]{32}$/;
const tokenPattern = /^[a-f0-9-]{36}$/;

function officialPage(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password && !url.port
      && (url.hostname === 'douyin.com' || url.hostname.endsWith('.douyin.com'));
  } catch {
    return false;
  }
}

function origin(value) {
  try { return new URL(value).origin; }
  catch { return null; }
}

function createDouyinPane(request) {
  let active;
  let requested;

  function remove() {
    if (!active) return;
    const { owner, view } = active;
    active = undefined;
    if (!owner.isDestroyed()) owner.contentView.removeChildView(view);
    if (!view.webContents.isDestroyed()) view.webContents.close();
  }

  function close(token) {
    if (token !== undefined && requested?.token !== token) return;
    requested = undefined;
    remove();
  }

  function layout(token, rect) {
    const pane = active;
    if (!pane || pane.token !== token || pane.owner.isDestroyed()) return;
    const valid = rect && ['x', 'y', 'width', 'height'].every(name => Number.isFinite(rect[name]));
    if (!valid || rect.visible !== true) {
      pane.view.setVisible(false);
      return;
    }
    const { width: windowWidth, height: windowHeight } = pane.owner.getContentBounds();
    const x = Math.max(0, Math.floor(rect.x));
    const y = Math.max(52, Math.floor(rect.y));
    const width = Math.max(0, Math.min(Math.floor(rect.width), windowWidth - x));
    const height = Math.max(0, Math.min(Math.floor(rect.height), windowHeight - y));
    pane.view.setVisible(width > 0 && height > 0);
    if (width && height) pane.view.setBounds({ x, y, width, height });
  }

  async function open(owner, { token, groupId, bindingId, kind, notifications, rect } = {}) {
    const url = destinations.get(kind);
    if (!url || typeof token !== 'string' || !tokenPattern.test(token) || typeof bindingId !== 'string'
      || !bindingPattern.test(bindingId) || typeof groupId !== 'string') {
      throw new Error('请选择当前组已绑定的抖音账号。');
    }
    const opening = { token };
    requested = opening;
    remove();
    const state = await request('state');
    if (requested !== opening || owner.isDestroyed()) return;
    if (state.active_group_id !== groupId || !state.bindings.some(binding =>
      binding.id === bindingId && binding.group_id === groupId && binding.platform === 'douyin' && !!binding.label)) {
      throw new Error('请选择当前组已绑定的抖音账号。');
    }

    const partition = session.fromPartition(`persist:relayfold-douyin-pane-${bindingId}`);
    const view = new WebContentsView({
      webPreferences: { session: partition, sandbox: true, contextIsolation: true, nodeIntegration: false },
    });
    const contents = view.webContents;
    const pane = { token, owner, view, notifications: notifications === true };
    active = pane;
    const allowedNotification = (sender, permission, source, details) => {
      const requestOrigin = origin(source);
      return active === pane && pane.notifications && sender === contents && permission === 'notifications'
        && details?.isMainFrame !== false && notificationOrigins.has(requestOrigin)
        && requestOrigin === origin(contents.getURL());
    };
    partition.setPermissionCheckHandler(allowedNotification);
    partition.setPermissionRequestHandler((sender, permission, callback, details) => {
      callback(allowedNotification(sender, permission, details.requestingUrl, details));
    });
    const denyDownload = (event, _item, sender) => {
      if (sender === contents) event.preventDefault();
    };
    partition.on('will-download', denyDownload);
    contents.once('destroyed', () => {
      if (active === pane) { active = undefined; requested = undefined; }
      partition.removeListener('will-download', denyDownload);
    });

    contents.setWindowOpenHandler(() => ({ action: 'deny' }));
    const protectNavigation = (event, target) => {
      if (event.isMainFrame !== false && !officialPage(event.url ?? target)) event.preventDefault();
    };
    contents.on('will-navigate', protectNavigation);
    contents.on('will-redirect', protectNavigation);

    const sendStatus = status => {
      if (active === pane && !owner.isDestroyed()) owner.webContents.send('publisher:douyin-pane-status', token, status);
    };
    contents.on('did-start-loading', () => sendStatus('loading'));
    contents.on('did-finish-load', () => sendStatus('ready'));
    contents.on('did-fail-load', (_event, code, _description, _url, mainFrame) => {
      if (mainFrame && code !== -3) sendStatus('error');
    });
    contents.on('render-process-gone', () => sendStatus('error'));
    view.setVisible(false);
    owner.contentView.addChildView(view);
    layout(token, rect);
    void contents.loadURL(url).catch(error => {
      if (error.code !== 'ERR_ABORTED') sendStatus('error');
    });
  }

  return { open, close, layout, notifications(token, enabled) {
    if (active?.token === token) active.notifications = enabled === true;
  }, reload(token) {
    if (active?.token === token) active.view.webContents.reload();
  } };
}

module.exports = { createDouyinPane };
