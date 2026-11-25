import { execFileSync } from 'node:child_process';
import { createHash, randomUUID, sign } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readSigningKey } from './update-key.mjs';

const require = createRequire(import.meta.url);
const { runtime, manifestName, readRelease, readUpdateChannel, versionPattern } = require('../electron/update-release.cjs');
const { version } = require('../package.json');
const [directory, command] = process.argv.slice(2);
if (!directory || (command && command !== '--publish') || !versionPattern.test(version)) {
  throw new Error('Usage: node scripts/release-update.mjs OUTPUT_DIRECTORY [--publish]');
}
const channel = readUpdateChannel();
if (!channel) throw new Error('Configure the local Relayfold update channel before building a signed update.');
const { host, directory: remoteDirectory, publicKey } = channel;

const output = path.resolve(directory);
const project = fileURLToPath(new URL('../', import.meta.url));
const file = `Relayfold-${version}.zip`;
const bundle = path.join(output, file);
const manifest = path.join(output, manifestName);
mkdirSync(output, { recursive: true });
execFileSync(process.env.ZT_PYTHON || 'python', ['-B', path.join(project, 'scripts', 'pack-update.py'), project, bundle], { stdio: 'inherit' });
const bytes = readFileSync(bundle);
const release = { version, runtime, file, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') };
const signature = sign(null, Buffer.from(JSON.stringify(release)), readSigningKey()).toString('base64');
const contents = Buffer.from(JSON.stringify({ release, signature }));
readRelease(contents, publicKey);
writeFileSync(manifest, contents);

if (command === '--publish') {
  const sshOptions = [
    '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=8',
    '-o', 'ForwardAgent=no', '-o', 'ForwardX11=no',
  ];
  const ssh = script => execFileSync('ssh', ['-T', ...sshOptions, host, script], { stdio: 'inherit', timeout: 30000 });
  const upload = `${remoteDirectory}/.upload-${randomUUID()}`;
  ssh(`set -eu; umask 077; mkdir -p -- ${remoteDirectory}; mkdir -- ${upload}`);
  execFileSync('scp', [...sshOptions, bundle, manifest, `${host}:${upload}/`], { stdio: 'inherit', timeout: 180000 });
  ssh(`set -eu; umask 077; actual=$(sha256sum ${upload}/${file} | cut -d ' ' -f 1); test "$actual" = "${release.sha256}";
    if [ -e ${remoteDirectory}/${file} ]; then
      cmp -s ${upload}/${file} ${remoteDirectory}/${file};
    else
      ln -- ${upload}/${file} ${remoteDirectory}/${file};
    fi;
    mv -- ${upload}/${manifestName} ${remoteDirectory}/${manifestName};
    rm -- ${upload}/${file};
    rmdir -- ${upload}`);
  console.log(`Published signed update v${version}`);
} else {
  console.log(`Built signed update v${version} at ${output}`);
}
