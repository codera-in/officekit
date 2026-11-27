import { mkdir, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';

const root = '/tmp/officekit-hdrplus';
const bursts = [
  ['0006_20160722_115157_431', 7], ['0006_20160727_185921_651', 4],
  ['0009_20160702_154921_383', 7], ['0030_20151121_161242_822', 5],
  ['0039_20141005_130438_317', 10], ['0043_20160825_193900_964', 3],
  ['0047_20160609_110125_873', 7], ['0127_20161018_111029_303', 7],
  ['0132_20160917_175200_202', 3], ['0155_20160923_180141_698', 3],
  ['0218_20141031_195419_627', 10], ['0272_20160515_130708_549', 3],
  ['0382_20150912_125455_388', 8], ['0543_20150918_131451_875', 8],
  ['0919_20150905_181412_593', 10],
];
const objects = bursts.flatMap(([name, count]) =>
  Array.from({ length: count }, (_, index) => ({ name, index })),
);

for (let offset = 0; offset < objects.length; offset += 4) {
  const batch = objects.slice(offset, offset + 4);
  const results = await Promise.all(batch.map(async ({ name, index }) => {
    const filename = `payload_N${String(index).padStart(3, '0')}.dng`;
    const directory = path.join(root, name);
    const destination = path.join(directory, filename);
    try {
      return (await stat(destination)).size;
    } catch {}
    const url = `https://storage.googleapis.com/hdrplusdata/20171106_subset/bursts/${name}/${filename}`;
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Download failed (${response.status}): ${name}/${filename}`);
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (!bytes.byteLength || bytes.byteLength > 32 * 1024 * 1024) throw new Error(`Unexpected fixture size: ${name}/${filename}`);
    await mkdir(directory, { recursive: true });
    await writeFile(destination, bytes, { flag: 'wx' });
    return bytes.byteLength;
  }));
  const downloaded = results.reduce((sum, bytes) => sum + bytes, 0);
  process.stdout.write(`${Math.min(offset + batch.length, objects.length)}/${objects.length} frames (${downloaded} bytes in batch)\n`);
}
