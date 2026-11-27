import { spawn } from 'node:child_process';
import { mkdtempSync, realpathSync, rmSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { getPythonCandidates } from './run-python-tests.mjs';

export function startUiTestApiServer({
  environment = process.env,
  processEvents = process,
  spawnChild = spawn,
  python = getPythonCandidates()[0],
  createDataDirectory = () => realpathSync(mkdtempSync(path.join(tmpdir(), 'officekit-ui-test-data-'))),
  removeDataDirectory = directory => rmSync(directory, { recursive: true, force: true }),
} = {}) {
  const dataDirectory = createDataDirectory();
  const apiPort = environment.OFFICEKIT_UI_TEST_API_PORT || '19873';
  let child;
  let stopped = false;
  let cleaned = false;
  const cleanup = () => {
    if (cleaned) return;
    cleaned = true;
    removeDataDirectory(dataDirectory);
  };
  const stop = signal => {
    if (stopped) return;
    stopped = true;
    child?.kill(signal);
  };

  try {
    child = spawnChild(python, [
      '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', apiPort,
      '--log-level', 'warning', '--no-access-log',
    ], {
      stdio: 'inherit',
      env: { ...environment, OFFICEKIT_DATA_DIR: dataDirectory },
    });
  } catch (error) {
    cleanup();
    processEvents.stderr.write(`Could not start the isolated OfficeKit UI test API: ${error.message}\n`);
    processEvents.exitCode = 1;
    return { dataDirectory, cleanup, child: null, stop };
  }

  processEvents.once('exit', cleanup);
  processEvents.once('SIGINT', () => stop('SIGINT'));
  processEvents.once('SIGTERM', () => stop('SIGTERM'));
  child.on('error', error => {
    processEvents.stderr.write(`Could not start the isolated OfficeKit UI test API: ${error.message}\n`);
    cleanup();
    processEvents.exitCode = 1;
  });
  child.on('close', (code, signal) => {
    cleanup();
    processEvents.exitCode = code ?? (signal ? 1 : 0);
  });
  return { dataDirectory, cleanup, child, stop };
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  startUiTestApiServer();
}
