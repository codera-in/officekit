import { setTimeout } from 'node:timers/promises';

// macOS may still be inspecting the mounted application after API fixtures pass.
// Only normal ejects are retried; a busy mount must never be force-removed.
export async function ejectSmokeImage(mountPoint, run, sleep = setTimeout) {
  let attempt = 0;
  while (true) {
    try {
      run('diskutil', ['eject', mountPoint]);
      return;
    } catch (error) {
      if (attempt === 4) throw error;
      await sleep(1000 * 2 ** attempt++);
    }
  }
}
