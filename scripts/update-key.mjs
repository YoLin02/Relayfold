import { generateKeyPairSync } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const keyDirectory = path.join(process.env.LOCALAPPDATA || '', 'Relayfold Release');
const keyFile = path.join(keyDirectory, 'update-signing-key.dpapi');

function dpapi(action, input) {
  const script = `
    Add-Type -AssemblyName System.Security
    $bytes = [Convert]::FromBase64String([Console]::In.ReadToEnd())
    $result = [Security.Cryptography.ProtectedData]::${action}(
      $bytes, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
    [Console]::Out.Write([Convert]::ToBase64String($result))
  `;
  const result = spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], {
    input: input.toString('base64'), encoding: 'utf8', windowsHide: true,
  });
  if (result.status !== 0 || !result.stdout?.trim()) throw new Error('Windows DPAPI key operation failed.');
  return Buffer.from(result.stdout.trim(), 'base64');
}

export function readSigningKey() {
  return dpapi('Unprotect', readFileSync(keyFile));
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  if (process.argv[2] !== 'init' || !process.env.LOCALAPPDATA) throw new Error('Run on Windows with the init argument.');
  const { privateKey, publicKey } = generateKeyPairSync('ed25519', {
    privateKeyEncoding: { type: 'pkcs8', format: 'pem' },
    publicKeyEncoding: { type: 'spki', format: 'der' },
  });
  mkdirSync(keyDirectory, { recursive: true });
  writeFileSync(keyFile, dpapi('Protect', Buffer.from(privateKey)), { flag: 'wx' });
  console.log(publicKey.toString('base64'));
}
