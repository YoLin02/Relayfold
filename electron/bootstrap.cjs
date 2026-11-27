const { app } = require('electron');
const { existsSync, mkdirSync } = require('node:fs');
const path = require('node:path');
const { productName, version } = require('../package.json');
const { selectLaunch, Updater } = require('./updater.cjs');
const { readUpdateChannel } = require('./update-release.cjs');

app.setName(productName);
if (process.platform === 'win32') {
  app.setAppUserModelId(app.isPackaged ? 'Relayfold.Publisher' : process.execPath);
  app.commandLine.appendSwitch('disable-lcd-text');
}

const dataDir = process.env.ZT_PUBLISHER_DATA_DIR
  ? path.resolve(process.env.ZT_PUBLISHER_DATA_DIR)
  : path.join(app.getPath('appData'), 'ZT Local Publisher');
mkdirSync(dataDir, { recursive: true });
app.setPath('userData', dataDir);

function start() {
  const channel = app.isPackaged && process.platform === 'win32' && process.arch === 'x64'
    ? readUpdateChannel() : null;
  const bundledApp = app.getAppPath();
  const bundledRoot = app.isPackaged ? process.resourcesPath : bundledApp;
  const captionHome = path.join(bundledRoot, 'caption-models');
  if (app.isPackaged && !process.env.RELAYFOLD_CAPTION_HOME && existsSync(captionHome)) {
    process.env.RELAYFOLD_CAPTION_HOME = captionHome;
  }
  const folder = path.join(dataDir, 'updates');
  let update = channel ? selectLaunch(folder, version, channel.publicKey) : null;
  let appRoot = update ? path.join(update.root, 'app') : bundledApp;
  let launch;
  try {
    launch = require(path.join(appRoot, 'electron', 'main.cjs')).start;
    if (typeof launch !== 'function') throw new Error('Application entry point is invalid.');
  } catch (error) {
    if (!update?.confirm) throw error;
    update = selectLaunch(folder, version, channel.publicKey);
    appRoot = update ? path.join(update.root, 'app') : bundledApp;
    launch = require(path.join(appRoot, 'electron', 'main.cjs')).start;
  }

  const python = app.isPackaged
    ? path.join(bundledRoot, 'python', 'python.exe')
    : process.env.ZT_PYTHON || 'python';
  const worker = (!app.isPackaged && process.env.ZT_WORKER_SCRIPT)
    || path.join(update?.root || bundledRoot, 'worker', 'main.py');
  launch({
    appRoot, dataDir, python, worker,
    createUpdater: onChange => new Updater({
      folder, current: update?.release.version || version, channel, python, onChange,
      extractor: path.join(bundledApp, 'electron', 'extract-update.py'),
    }),
    confirmStartup: update?.confirm,
    recoverStartup: update?.confirm ? () => {
      app.relaunch();
      app.quit();
    } : undefined,
  });
}

if (app.requestSingleInstanceLock()) start();
else app.quit();
