const { app, BrowserWindow, dialog, ipcMain, Menu, nativeImage, Tray } = require('electron');
const { spawn } = require('node:child_process');
const { stat } = require('node:fs/promises');
const path = require('node:path');
const { createInterface } = require('node:readline');
const { productName } = require('../package.json');

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
  const pending = new Map();
  const previewableFiles = new Set();
  const thumbnails = new Map();
  const methods = new Set([
    'state', 'groups.create', 'groups.select', 'groups.rename', 'groups.delete', 'accounts.open', 'accounts.manage', 'accounts.confirm',
    'accounts.check', 'accounts.add', 'accounts.replace', 'accounts.delete', 'accounts.configure', 'tasks.create', 'tasks.retry', 'tasks.review',
    'tasks.reschedule', 'tasks.cancelSchedule', 'tasks.diagnostics', 'tasks.history', 'tasks.delete',
    'settings.region', 'settings.theme',
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
      }, method === 'tasks.create' ? 300000 : 90000);
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
