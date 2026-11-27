import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { webkit } from '@playwright/test';

export async function preflightBrowser(browserType = webkit) {
  const browser = await browserType.launch();
  await browser.close();
}

async function main() {
  try {
    await preflightBrowser();
  } catch (error) {
    const detail = error instanceof Error ? error.stack || error.message : String(error);
    process.stderr.write(`UI browser preflight failed; the Playwright suite was not started.\n${detail}\n`);
    process.exitCode = 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  await main();
}
