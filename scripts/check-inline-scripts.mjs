import { readFile } from 'node:fs/promises';
const html = await readFile('index.html', 'utf8');
for (const [index, [, source]] of [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].entries()) {
  try { new Function(source); process.stdout.write(`script ${index + 1}: parses\n`); }
  catch (error) { process.stdout.write(`script ${index + 1}: ${error.stack}\n`); process.exitCode = 1; }
}
