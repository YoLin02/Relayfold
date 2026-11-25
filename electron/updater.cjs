const { execFile, spawn } = require('node:child_process');
const { createHash } = require('node:crypto');
const { createWriteStream, mkdirSync, readFileSync, renameSync, writeFileSync } = require('node:fs');
const { mkdir, mkdtemp, rename, rm, writeFile } = require('node:fs/promises');
const path = require('node:path');
const { Transform } = require('node:stream');
const { pipeline } = require('node:stream/promises');
const { promisify } = require('node:util');
const { compareVersions, manifestLimit, manifestName, readRelease, versionPattern } = require('./update-release.cjs');

const execute = promisify(execFile);
const marker = '.release.json';

function sshFile(channel, name, read, timeout) {
  const ssh = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'OpenSSH', 'ssh.exe');
  const child = spawn(ssh, [
    '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=8',
    '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2', '-o', 'ClearAllForwardings=yes',
    '-o', 'ForwardAgent=no', '-o', 'ForwardX11=no', channel.host, `cat -- ${channel.directory}/${name}`,
  ], { windowsHide: true, stdio: ['ignore', 'pipe', 'ignore'] });
  const done = new Promise(resolve => {
    child.once('error', () => resolve(false));
    child.once('close', code => resolve(code === 0));
  });
  const timer = setTimeout(() => child.kill(), timeout);
  return (async () => {
    try {
      const result = await read(child.stdout);
      if (!await done) throw new Error('无法读取更新。请检查 SSH 连接和发布目录。');
      return result;
    } finally {
      clearTimeout(timer);
      if (child.exitCode === null) child.kill();
    }
  })();
}

async function readManifest(stream) {
  let length = 0;
  const chunks = [];
  for await (const chunk of stream) {
    length += chunk.length;
    if (length > manifestLimit) throw new Error('更新清单超出大小限制。');
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

function cachedRelease(folder, version, publicKey) {
  if (typeof version !== 'string' || !versionPattern.test(version)) return null;
  const root = path.join(folder, 'versions', version);
  try {
    const release = readRelease(readFileSync(path.join(root, marker)), publicKey);
    const app = JSON.parse(readFileSync(path.join(root, 'app', 'package.json'), 'utf8'));
    return release.version === version && app.version === version ? { release, root } : null;
  } catch {
    return null;
  }
}

function readActive(folder) {
  try {
    const result = JSON.parse(readFileSync(path.join(folder, 'active.json'), 'utf8'));
    return result && typeof result === 'object' ? result : {};
  } catch {
    return {};
  }
}

function writeActive(folder, record) {
  mkdirSync(folder, { recursive: true });
  const temporary = path.join(folder, 'active.tmp');
  writeFileSync(temporary, JSON.stringify(record), { flush: true });
  renameSync(temporary, path.join(folder, 'active.json'));
}

function selectLaunch(folder, bundledVersion, publicKey) {
  const active = readActive(folder);
  const usable = version => {
    const candidate = cachedRelease(folder, version, publicKey);
    return candidate && compareVersions(candidate.release.version, bundledVersion) > 0 ? candidate : null;
  };
  const current = usable(active.version);
  if (current && !active.booting) {
    if (!active.pending) return current;
    writeActive(folder, { ...active, booting: true });
    return {
      ...current,
      confirm: () => writeActive(folder, { version: active.version, fallback: active.fallback }),
    };
  }
  if (active.version) {
    const fallback = usable(active.fallback);
    writeActive(folder, fallback ? { version: fallback.release.version } : {});
    return fallback;
  }
  return null;
}

class Updater {
  constructor({ folder, current, channel, python, extractor, onChange }) {
    Object.assign(this, { folder, channel, python, extractor, onChange });
    this.status = { current, phase: channel ? 'idle' : 'unsupported', available: null, progress: 0, error: '' };
    this.release = null;
    this.manifest = null;
  }

  set(change) {
    this.status = { ...this.status, ...change };
    this.onChange(this.status);
    return this.status;
  }

  fail(error) {
    return this.set({ phase: 'error', error: error.message || '更新操作失败。' });
  }

  async check() {
    if (['unsupported', 'checking', 'downloading', 'ready'].includes(this.status.phase)) return this.status;
    this.set({ phase: 'checking', available: null, progress: 0, error: '' });
    try {
      this.manifest = await sshFile(this.channel, manifestName, readManifest, 20000);
      this.release = readRelease(this.manifest, this.channel.publicKey, this.status.current);
      const { version, sha256 } = this.release;
      if (compareVersions(version, this.status.current) <= 0) return this.set({ phase: 'current' });
      const staged = cachedRelease(this.folder, version, this.channel.publicKey);
      return this.set({ phase: staged?.release.sha256 === sha256 ? 'ready' : 'available', available: version });
    } catch (error) {
      return this.fail(error);
    }
  }

  async download() {
    if (this.status.phase !== 'available') return this.status;
    const { file, bytes, version, sha256 } = this.release;
    this.set({ phase: 'downloading', progress: 0, error: '' });
    let temp;
    try {
      const versions = path.join(this.folder, 'versions');
      await mkdir(versions, { recursive: true });
      temp = await mkdtemp(path.join(this.folder, 'stage-'));
      const bundle = path.join(temp, 'update.zip');
      const unpacked = path.join(temp, 'payload');
      const digest = createHash('sha256');
      let received = 0;
      const meter = new Transform({
        transform: (chunk, _, done) => {
          received += chunk.length;
          if (received > bytes) return done(new Error('更新下载超过签名清单中的文件大小。'));
          digest.update(chunk);
          const percent = Math.floor(received / bytes * 100);
          if (percent !== this.status.progress) this.set({ progress: percent });
          done(null, chunk);
        },
      });
      await sshFile(this.channel, file, stream => pipeline(stream, meter, createWriteStream(bundle, { flags: 'wx' })), 180000);
      if (received !== bytes || digest.digest('hex') !== sha256) throw new Error('更新包校验失败。');
      await mkdir(unpacked);
      await execute(this.python, ['-B', this.extractor, bundle, unpacked], { timeout: 60000, windowsHide: true })
        .catch(() => { throw new Error('无法解压更新包。请检查本机磁盘空间或联系发布维护者。'); });
      const app = JSON.parse(readFileSync(path.join(unpacked, 'app', 'package.json'), 'utf8'));
      if (app.version !== version) throw new Error('更新包中的程序版本与签名清单不一致。');
      await writeFile(path.join(unpacked, marker), this.manifest, { flag: 'wx', flush: true });
      await rename(unpacked, path.join(versions, version));
      return this.set({ phase: 'ready', progress: 100 });
    } catch (error) {
      return this.fail(error);
    } finally {
      if (temp) await rm(temp, { recursive: true, force: true }).catch(() => {});
    }
  }

  activate() {
    const version = this.status.available;
    if (this.status.phase !== 'ready' || !cachedRelease(this.folder, version, this.channel.publicKey)) {
      throw new Error('请先下载并校验更新。');
    }
    writeActive(this.folder, { version, fallback: this.status.current, pending: true });
  }
}

module.exports = { selectLaunch, Updater };
