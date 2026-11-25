import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 120000,
  expect: { timeout: 15000 },
  use: { actionTimeout: 15000 },
  workers: 1,
  reporter: 'list',
});
