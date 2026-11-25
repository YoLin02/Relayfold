const { createPublicKey, verify } = require('node:crypto');

const runtime = 'windows-x64-electron45.4.1-python314-v2';
const versionPattern = /^(?:0|[1-9]\d{0,5})\.(?:0|[1-9]\d{0,5})\.(?:0|[1-9]\d{0,5})$/;
const manifestName = 'latest.json';
const manifestLimit = 16 * 1024;
const bundleLimit = 64 * 1024 * 1024;

function readUpdateChannel(env = process.env) {
  const host = env.RELAYFOLD_UPDATE_SSH_HOST;
  const directory = env.RELAYFOLD_UPDATE_SSH_DIRECTORY;
  const key = env.RELAYFOLD_UPDATE_PUBLIC_KEY;
  if (!host || !/^[a-zA-Z0-9][a-zA-Z0-9_.-]*$/.test(host) ||
      !directory || !/^\/(?:[a-zA-Z0-9_.-]+\/)*[a-zA-Z0-9_.-]+$/.test(directory) ||
      directory.split('/').some(part => part === '.' || part === '..') || !key) {
    return null;
  }
  try {
    const publicKey = createPublicKey({ key: Buffer.from(key, 'base64'), format: 'der', type: 'spki' });
    return publicKey.asymmetricKeyType === 'ed25519' ? { host, directory, publicKey } : null;
  } catch {
    return null;
  }
}

function compareVersions(left, right) {
  const values = right.split('.').map(Number);
  return left.split('.').map((value, index) => Number(value) - values[index]).find(Boolean) || 0;
}

function readRelease(bytes, publicKey, currentVersion) {
  if (bytes.length > manifestLimit) throw new Error('更新清单超出大小限制。');
  const { release, signature } = JSON.parse(bytes.toString('utf8'));
  if (!release || typeof signature !== 'string' ||
      !verify(null, Buffer.from(JSON.stringify(release)), publicKey, Buffer.from(signature, 'base64'))) {
    throw new Error('更新签名校验失败。');
  }
  const { version, file, bytes: size, sha256 } = release;
  if (!versionPattern.test(version) || file !== `Relayfold-${version}.zip` ||
      !Number.isSafeInteger(size) || size <= 0 || size > bundleLimit || !/^[a-f0-9]{64}$/.test(sha256)) {
    throw new Error('更新清单格式无效。');
  }
  if (release.runtime !== runtime && (!currentVersion || compareVersions(version, currentVersion) > 0)) {
    throw new Error('此更新包含新的运行环境，请下载完整 Windows 便携包。');
  }
  return release;
}

module.exports = { runtime, manifestName, manifestLimit, bundleLimit, compareVersions, readRelease, readUpdateChannel, versionPattern };
