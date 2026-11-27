// Design-only preview export: assemble generated 4x4 pose sheets into looping GIFs.
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { resolve } from 'node:path';
const run = promisify(execFile);
const root = resolve(import.meta.dirname, '..');
const kinds = ['water', 'stretch', 'eyes'];
await Promise.all(kinds.map(async kind => {
  const source = resolve(root, `design/assets/ergonomics-${kind}-animation-v1.png`);
  const output = resolve(root, `design/assets/ergonomics-${kind}-animation-v1.gif`);
  const filter = '[0:v]trim=end_frame=16,crop=w=iw/4:h=ih/4:x=mod(n\\,4)*iw/4:y=floor(n/4)*ih/4,scale=256:256:flags=lanczos,split[a][b];[a]palettegen=reserve_transparent=1[p];[b][p]paletteuse=alpha_threshold=128';
  await run('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-n', '-loop', '1', '-framerate', '4', '-i', source, '-filter_complex', filter, '-frames:v', '16', '-loop', '0', output], { timeout: 30000 });
  process.stdout.write(`Prepared ${kind}: ${output}\n`);
}));
