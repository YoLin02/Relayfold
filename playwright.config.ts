import { defineConfig } from '@playwright/test';
import { basename, join } from 'node:path';
import { loadEnv } from 'vite';

const { RELAYFOLD_BUILD_ROOT } = loadEnv('test', process.cwd(), 'RELAYFOLD_');

export default defineConfig({
  testDir: './tests',
  outputDir: RELAYFOLD_BUILD_ROOT ? join(RELAYFOLD_BUILD_ROOT, 'tests', basename(process.cwd())) : './test-results',
  timeout: 120000,
  expect: { timeout: 15000 },
  use: { actionTimeout: 15000 },
  workers: 1,
  reporter: 'list',
});
