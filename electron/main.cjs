const { app, BrowserWindow, dialog, ipcMain, Menu, nativeImage, Notification, shell, Tray } = require('electron');
const { spawn } = require('node:child_process');
const { existsSync } = require('node:fs');
const { stat } = require('node:fs/promises');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { createInterface } = require('node:readline');
const { productName } = require('../package.json');
const { createDouyinPane } = require('./douyin-pane.cjs');

function start({ appRoot, dataDir, python, worker, createUpdater, confirmStartup, recoverStartup }) {

  let window;
  let tray;
  let child;
  let workerReady;
  let shuttingDown = false;
  let quitting = false;
  let workerStopped = false;
  let installing = false;
  let sequence = 0;
  let commentDestination;
  let balloonDestination;
  const commentNotifications = new Map();
  const pending = new Map();
  const previewableFiles = new Set();
  const thumbnails = new Map();
  const douyinPane = createDouyinPane(request);
  const requestTimeouts = {
    'tasks.create': 300000,
    'comments.inbox': 180000,
    'comments.children': 110000,
    'comments.more': 110000,
    'comments.locate': 150000,
    'comments.send': 150000,
    'messages.thread': 115000,
    'materials.resolve': 80000,
  };
  const methods = new Set([
    'state', 'groups.create', 'groups.select', 'groups.rename', 'groups.delete', 'accounts.open', 'accounts.manage', 'accounts.confirm',
    'accounts.check', 'accounts.add', 'accounts.replace', 'accounts.delete', 'accounts.configure', 'tasks.create', 'tasks.retry', 'tasks.review',
    'tasks.reschedule', 'tasks.cancelSchedule', 'tasks.diagnostics', 'tasks.history', 'tasks.delete',
    'settings.region', 'settings.theme', 'settings.commentMode', 'settings.commentAccount',
    'settings.commentCache', 'comments.notes', 'comments.list', 'comments.inbox', 'comments.prepare', 'comments.send',
    'comments.summary', 'comments.snapshot', 'comments.inboxSnapshot', 'comments.cover', 'comments.read',
    'comments.children', 'comments.more', 'comments.locate',
    'messages.snapshot', 'messages.sync', 'messages.cachedThread', 'messages.thread', 'messages.draft', 'messages.saveDraft',
    'messages.douyinDraft', 'messages.saveDouyinDraft',
    'materials.snapshot', 'materials.import', 'materials.resolve', 'materials.download', 'materials.cancel', 'materials.retry',
    'materials.caption.get', 'materials.caption.start', 'materials.caption.cancel', 'materials.caption.save',
    'materials.script.review', 'materials.script.mark',
    'materials.render.cancel',
  ]);

  function notify() {
    if (window && !window.isDestroyed()) window.webContents.send('publisher:changed');
  }

  function startWorker() {
    workerReady = new Promise((resolve, reject) => {
      child = spawn(python, ['-B', '-u', worker, '--data-dir', dataDir], {
        cwd: appRoot, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
      });
      const startup = setTimeout(() => {
        reject(new Error('本地 Worker 启动超时。'));
        child.kill();
      }, 20000);
      const die = () => {
        workerStopped = true;
        clearTimeout(startup);
        const error = new Error('本地发布进程已断开。请退出并重新打开软件。');
        reject(error);
        for (const request of pending.values()) {
          clearTimeout(request.timer);
          request.reject(error);
        }
        pending.clear();
        notify();
      };
      child.once('error', die);
      child.once('exit', die);
      child.stderr.on('data', line => {
        if (!app.isPackaged) process.stderr.write(line);
      });
      child.stdin.on('error', die);
      createInterface({ input: child.stdout }).on('line', line => {
        let message;
        try { message = JSON.parse(line); } catch { return; }
        if (message.event === 'ready') {
          clearTimeout(startup);
          resolve();
          return;
        }
        if (message.event === 'changed') {
          notify();
          return;
        }
        if (message.event === 'comments') {
          if (window && !window.isDestroyed()) window.webContents.send('publisher:comments-changed', message.group_id);
          return;
        }
        if (message.event === 'materials') {
          if (window && !window.isDestroyed()) window.webContents.send('publisher:materials-changed');
          return;
        }
        if (message.event === 'comment-alert') {
          showCommentNotification(message);
          return;
        }
        const request = pending.get(message.id);
        if (!request) return;
        clearTimeout(request.timer);
        pending.delete(message.id);
        if (message.error) request.reject(new Error(message.error));
        else request.resolve(message.result);
      });
    });
    workerReady.catch(() => {});
  }

  async function request(method, args) {
    await workerReady;
    if (workerStopped || !child.stdin.writable) throw new Error('本地发布进程已断开，请重新打开软件。');
    return new Promise((resolve, reject) => {
      const id = ++sequence;
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new Error('操作响应超时，请在任务记录中核对结果。'));
      }, requestTimeouts[method] ?? 90000);
      pending.set(id, { resolve, reject, timer });
      child.stdin.write(`${JSON.stringify({ id, method, args })}\n`);
    });
  }

  function createWindow() {
    window = new BrowserWindow({
      width: 1200, height: 840, minWidth: 460, minHeight: 570,
      title: productName, backgroundColor: '#ffffff',
      icon: path.join(__dirname, 'relayfold.ico'),
      titleBarStyle: 'hidden',
      titleBarOverlay: { color: '#ffffff', symbolColor: '#171717', height: 52 },
      autoHideMenuBar: true,
      webPreferences: {
        preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true,
        sandbox: true, nodeIntegration: false,
      },
    });
    window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    window.webContents.on('will-navigate', event => event.preventDefault());
    window.webContents.on('did-start-loading', () => douyinPane.close());
    const loaded = window.loadFile(path.join(appRoot, 'dist', 'index.html'));
    if (confirmStartup) {
      const retry = recoverStartup;
      const confirm = confirmStartup;
      confirmStartup = undefined;
      Promise.all([workerReady, loaded]).then(confirm).catch(retry);
    }
    window.on('close', event => {
      if (quitting || !tray) return;
      event.preventDefault();
      window.hide();
    });
    window.on('closed', () => {
      douyinPane.close();
      window = null;
      previewableFiles.clear();
      thumbnails.clear();
    });
  }

  function showWindow() {
    if (!window) createWindow();
    if (window.isMinimized()) window.restore();
    window.show();
    window.focus();
  }

  function openComment(destination) {
    commentDestination = destination;
    showWindow();
    window.webContents.send('publisher:comment-destination');
  }

  function showCommentNotification({ destination, count, account }) {
    if (quitting || !destination || !count) return;
    const title = '小红书评论';
    const body = `${account || '小红书账号'}收到 ${count} 条新评论`;
    const icon = path.join(__dirname, 'relayfold.ico');
    const balloon = () => {
      if (!tray || quitting) return;
      balloonDestination = destination;
      tray.displayBalloon({ title, content: body, icon });
    };
    if (!Notification.isSupported()) {
      balloon();
      return;
    }
    const key = destination.binding_id;
    commentNotifications.get(key)?.close();
    try {
      const notification = new Notification({ title, body, icon });
      commentNotifications.set(key, notification);
      const release = () => {
        if (commentNotifications.get(key) === notification) commentNotifications.delete(key);
      };
      notification.on('click', () => { release(); openComment(destination); });
      notification.on('close', release);
      notification.on('failed', () => { release(); balloon(); });
      notification.show();
    } catch {
      commentNotifications.delete(key);
      balloon();
    }
  }

  function createTray() {
    if (process.platform !== 'win32') return;
    tray = new Tray(path.join(__dirname, 'relayfold.ico'));
    tray.setToolTip(productName);
    tray.setContextMenu(Menu.buildFromTemplate([
      { label: `打开 ${productName}`, click: showWindow },
      { type: 'separator' },
      { label: `退出 ${productName}`, click: () => app.quit() },
    ]));
    tray.on('click', showWindow);
    tray.on('balloon-click', () => {
      if (balloonDestination) openComment(balloonDestination);
      balloonDestination = undefined;
    });
  }

  function isPublisherFrame(event) {
    return window && event.sender === window.webContents && event.senderFrame && !event.senderFrame.parent;
  }

  function verifySender(event) {
    if (!isPublisherFrame(event)) {
      throw new Error('无法从此窗口执行本地操作。');
    }
  }

  function allowPreview(file) {
    if (typeof file === 'string' && path.isAbsolute(file) && /\.(mp4|mov|jpe?g|png|webp)$/i.test(file)) {
      previewableFiles.add(file);
    }
  }

  async function previewMedia(file) {
    if (!previewableFiles.has(file)) return null;
    try {
      const info = await stat(file);
      if (!info.isFile()) return null;
      const existing = thumbnails.get(file);
      if (existing?.time === info.mtimeMs && existing.size === info.size) return await existing.image;
      const image = nativeImage.createThumbnailFromPath(file, { width: 272, height: 160 })
        .then(value => value.isEmpty() ? null : value.toDataURL()).catch(() => null);
      thumbnails.set(file, { time: info.mtimeMs, size: info.size, image });
      if (thumbnails.size > 40) thumbnails.delete(thumbnails.keys().next().value);
      return await image;
    } catch {
      return null;
    }
  }

  app.on('second-instance', () => { if (app.isReady() && !quitting) showWindow(); });
  app.whenReady().then(() => {
    const updater = createUpdater(status => {
      if (window && !window.isDestroyed()) window.webContents.send('publisher:update-changed', status);
    });
    ipcMain.handle('publisher:update', async (event, action) => {
      verifySender(event);
      if (action === 'status') return updater.status;
      if (installing) throw new Error('Relayfold 正在重启。');
      if (action === 'check') return updater.check();
      if (action === 'download') return updater.download();
      if (action !== 'install') throw new Error('未知的更新操作。');
      if (pending.size) throw new Error('有本地操作正在执行，请稍后安装更新。');
      installing = true;
      try {
        const { tasks } = await request('state');
        if (tasks.some(task => ['queued', 'running', 'submitting', 'verifying'].includes(task.status)
          || (task.status === 'scheduled' && task.scheduled_at * 1000 <= Date.now() + 120000))) {
          throw new Error('有发布正在处理，或两分钟内有预约。请等任务处理完再安装更新。');
        }
        updater.activate();
        app.relaunch();
        setImmediate(() => app.quit());
        return updater.status;
      } catch (error) {
        installing = false;
        throw error;
      }
    });
    ipcMain.handle('publisher:request', (event, method, args) => {
      verifySender(event);
      if (!methods.has(method)) throw new Error('未知的本地操作。');
      if (installing) throw new Error('Relayfold 正在重启。');
      return request(method, args);
    });
    ipcMain.handle('publisher:select-media', async (event, kind) => {
      verifySender(event);
      if (!['video', 'image', 'cover'].includes(kind)) throw new Error('不支持的素材类型。');
      const video = kind === 'video';
      const result = await dialog.showOpenDialog(window, {
        title: video ? '选择本地视频' : kind === 'cover' ? '选择本地封面' : '选择本地图片',
        properties: kind === 'image' ? ['openFile', 'multiSelections'] : ['openFile'],
        filters: [video ? { name: '视频', extensions: ['mp4', 'mov'] } : { name: '图片', extensions: ['jpg', 'jpeg', 'png', 'webp'] }],
      });
      if (result.canceled) return [];
      result.filePaths.forEach(allowPreview);
      return result.filePaths;
    });
    ipcMain.handle('publisher:select-comment-cache', async event => {
      verifySender(event);
      const { directory } = await request('comments.summary');
      const result = await dialog.showOpenDialog(window, {
        title: '选择评论缓存目录', defaultPath: directory, properties: ['openDirectory', 'createDirectory'],
      });
      return result.filePaths[0] ?? null;
    });
    ipcMain.handle('publisher:material-action', async (event, action, args) => {
      verifySender(event);
      if (installing) throw new Error('Relayfold 正在重启。');
      if (action === 'select') {
        const result = await dialog.showOpenDialog(window, {
          title: '导入本地视频', properties: ['openFile', 'multiSelections'],
          filters: [{ name: '视频', extensions: ['mp4', 'mov', 'mkv', 'webm', 'avi', 'm4v'] }],
        });
        return result.canceled ? [] : result.filePaths;
      }
      if (action === 'directory') {
        const { directory } = await request('materials.snapshot');
        const result = await dialog.showOpenDialog(window, {
          title: '选择素材下载目录', defaultPath: directory, properties: ['openDirectory', 'createDirectory'],
        });
        if (result.canceled || !result.filePaths[0]) return null;
        await request('materials.directory', { path: result.filePaths[0] });
        return result.filePaths[0];
      }
      if (action === 'import-srt') {
        const result = await dialog.showOpenDialog(window, {
          title: '导入 SRT 字幕', properties: ['openFile'],
          filters: [{ name: 'SubRip 字幕', extensions: ['srt'] }],
        });
        if (result.canceled || !result.filePaths[0]) return null;
        return request('materials.srt.import', { path: result.filePaths[0] });
      }
      if (typeof args?.id !== 'string' || !/^[a-f0-9]{32}$/.test(args.id)) throw new Error('请选择有效的素材。');
      const asset = await request('materials.asset', { id: args.id });
      if (action === 'import-word') {
        const result = await dialog.showOpenDialog(window, {
          title: '导入 Word 脚本', properties: ['openFile'],
          filters: [{ name: 'Word 脚本', extensions: ['docx'] }],
        });
        if (result.canceled || !result.filePaths[0]) return undefined;
        return request('materials.script.import', { id: args.id, path: result.filePaths[0] });
      }
      if (action === 'preview') return asset.available && /\.(mp4|mov|webm|mkv|m4v)$/i.test(asset.path)
        ? pathToFileURL(asset.path).href : null;
      if (action === 'export-caption') {
        const { cues } = await request('materials.caption.get', { id: args.id });
        if (!cues.length) throw new Error('这条素材没有可导出的字幕。');
        const parsed = path.parse(asset.path);
        const result = await dialog.showSaveDialog(window, {
          title: '导出 SRT 字幕', defaultPath: path.join(asset.available ? parsed.dir : app.getPath('documents'), parsed.name + '-字幕.srt'),
          filters: [{ name: 'SubRip 字幕', extensions: ['srt'] }],
        });
        if (result.canceled || !result.filePath) return null;
        await request('materials.caption.export', { id: args.id, destination: result.filePath });
        return result.filePath;
      }
      if (!asset.available) throw new Error('素材文件已移动或删除。');
      if (action === 'synthesize') {
        if (!args.source || !['saved', 'srt'].includes(args.source.kind)) throw new Error('请选择字幕来源。');
        const parsed = path.parse(asset.path);
        const name = Array.from(parsed.name).slice(0, 100).join('') + '-字幕版';
        let destination = path.join(parsed.dir, name + '.mp4');
        for (let edit = 2; existsSync(destination); edit++) {
          destination = path.join(parsed.dir, name + '-' + edit + '.mp4');
        }
        const result = await dialog.showSaveDialog(window, {
          title: '保存合成视频', defaultPath: destination,
          filters: [{ name: 'MP4 视频', extensions: ['mp4'] }],
        });
        if (result.canceled || !result.filePath) return false;
        await request('materials.render.begin', { id: args.id, source: args.source, destination: result.filePath });
        return true;
      }
      if (action === 'reveal') return shell.showItemInFolder(asset.path);
      if (action === 'publish') {
        if (!/\.(mp4|mov)$/i.test(asset.path)) throw new Error('发布支持 MP4 和 MOV。');
        allowPreview(asset.path);
        return asset.path;
      }
      throw new Error('未知的素材操作。');
    });
    ipcMain.handle('publisher:comment-destination', event => {
      verifySender(event);
      const destination = commentDestination;
      commentDestination = undefined;
      return destination ?? null;
    });
    ipcMain.handle('publisher:open-comment-source', async (event, destination) => {
      verifySender(event);
      if (installing) throw new Error('Relayfold 正在重启。');
      const noteId = destination?.note_id;
      if (typeof noteId !== 'string' || !/^[a-f0-9]{24}$/i.test(noteId)) throw new Error('原帖标识无效。');
      const link = new URL(await request('comments.sourceLink', destination));
      if (link.origin !== 'https://www.xiaohongshu.com' || link.pathname !== `/explore/${noteId}` ||
        link.username || link.password || link.hash) throw new Error('无法打开这篇小红书原帖。');
      await shell.openExternal(link.href);
    });
    ipcMain.handle('publisher:open-douyin-messages', async (event, kind) => {
      verifySender(event);
      if (kind === 'private') return shell.openExternal('https://imdesktop.douyin.com/');
      if (kind === 'comments') return shell.openExternal('https://creator.douyin.com/creator-micro/interactive/comment');
      throw new Error('未知的抖音消息入口。');
    });
    ipcMain.handle('publisher:douyin-pane', (event, action, args) => {
      verifySender(event);
      if (action === 'open') return douyinPane.open(window, args);
      if (typeof args?.token !== 'string') throw new Error('抖音页面已关闭。');
      if (action === 'close') return douyinPane.close(args.token);
      if (action === 'layout') return douyinPane.layout(args.token, args.rect);
      if (action === 'reload') return douyinPane.reload(args.token);
      if (action === 'notifications') return douyinPane.notifications(args.token, args.enabled);
      throw new Error('未知的抖音页面操作。');
    });
    ipcMain.on('publisher:register-preview', (event, file) => {
      if (isPublisherFrame(event)) allowPreview(file);
    });
    ipcMain.handle('publisher:media-preview', (event, file) => {
      verifySender(event);
      return previewMedia(file);
    });
    startWorker();
    createWindow();
    createTray();
    if (updater.status.phase !== 'unsupported') {
      setTimeout(() => { if (!quitting && !installing) void updater.check(); }, 12000).unref();
      setInterval(() => { if (!quitting && !installing) void updater.check(); }, 6 * 60 * 60 * 1000).unref();
    }
  });
  app.on('window-all-closed', () => { app.quit(); });
  app.on('before-quit', event => {
    quitting = true;
    douyinPane.close();
    if (!child || child.exitCode !== null || shuttingDown) return;
    event.preventDefault();
    shuttingDown = true;
    const fallback = setTimeout(() => {
      child.kill();
      app.quit();
    }, 4500);
    child.once('exit', () => {
      clearTimeout(fallback);
      app.quit();
    });
    if (child.stdin.writable) child.stdin.end('{"method":"shutdown"}\n');
    else child.kill();
  });
}

module.exports = { start };
