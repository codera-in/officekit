import { defineConfig } from '@playwright/test';
import { randomBytes } from 'node:crypto';
import { getPythonCandidates } from './scripts/run-python-tests.mjs';

// Inherited by workers; never use the developer's desktop token or port.
process.env.OFFICEKIT_UI_TEST_TOKEN ||= randomBytes(32).toString('hex');
process.env.OFFICEKIT_UI_TEST_NATIVE_GRANT_TOKEN ||= randomBytes(32).toString('hex');
const token = process.env.OFFICEKIT_UI_TEST_TOKEN;
const nativeGrantToken = process.env.OFFICEKIT_UI_TEST_NATIVE_GRANT_TOKEN;
const apiPort = process.env.OFFICEKIT_UI_TEST_API_PORT || '19873';
const uiPort = process.env.OFFICEKIT_UI_TEST_UI_PORT || '19874';
const python = getPythonCandidates()[0];
const quotedPython = process.platform === 'win32'
  ? `"${python.replaceAll('"', '""')}"`
  : `'${python.replaceAll("'", "'\\''")}'`;

export default defineConfig({
  testDir: './ui-tests',
  testMatch: '**/*.spec.mjs',
  globalSetup: './ui-tests/global-entitlement.setup.mjs',
  outputDir: '.test-artifacts/ui',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  workers: 1,
  retries: 0,
  reporter: 'list',
  use: {
    browserName: 'webkit',
    baseURL: `http://127.0.0.1:${uiPort}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    acceptDownloads: true,
  },
  projects: [
    { name: 'desktop-webkit', use: { viewport: { width: 1440, height: 1000 } } },
    { name: 'compact-webkit', use: { viewport: { width: 900, height: 900 } } },
  ],
  webServer: [
    {
      command: 'node scripts/ui-test-api-server.mjs',
      env: {
        OFFICEKIT_API_TOKEN: token,
        OFFICEKIT_UI_TEST_TOKEN: token,
        OFFICEKIT_UI_TEST_ORIGIN: `http://127.0.0.1:${uiPort}`,
        OFFICEKIT_NATIVE_GRANT_TOKEN: nativeGrantToken,
      },
      url: `http://127.0.0.1:${apiPort}/api/health`,
      headers: { Authorization: `Bearer ${token}` },
      timeout: 45_000,
      reuseExistingServer: false,
      gracefulShutdown: { signal: 'SIGTERM', timeout: 5_000 },
    },
    {
      command: `${quotedPython} -m http.server ${uiPort} --bind 127.0.0.1 --directory dist-ui`,
      url: `http://127.0.0.1:${uiPort}`,
      // A cold CI runner can take longer than 15 s to start its first Python process.
      timeout: 60_000,
      reuseExistingServer: false,
      gracefulShutdown: { signal: 'SIGTERM', timeout: 5_000 },
    },
  ],
});
