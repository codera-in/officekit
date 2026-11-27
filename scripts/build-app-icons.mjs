import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import zlib from 'node:zlib';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const iconDir = path.join(root, 'src-tauri', 'icons');
const masterSize = 1024;
const colors = {
  violet: { rgba: [79, 70, 229, 255], hex: '#4f46e5' },
  white: { rgba: [255, 255, 255, 255], hex: '#ffffff' },
  amber: { rgba: [245, 158, 11, 255], hex: '#f59e0b' },
  paper: { rgba: [224, 231, 255, 255], hex: '#e0e7ff' },
};
const iconShapes = [
  { type: 'rect', x: 0, y: 0, width: 1024, height: 1024, radius: 224, color: 'violet' },
  // The O is a knockout in the white loop; the three strokes to its right form K.
  { type: 'rect', x: 108, y: 220, width: 376, height: 584, radius: 176, color: 'white' },
  { type: 'rect', x: 214, y: 326, width: 164, height: 372, radius: 70, color: 'violet' },
  { type: 'line', x1: 570, y1: 250, x2: 570, y2: 774, thickness: 82, color: 'white' },
  { type: 'line', x1: 578, y1: 510, x2: 852, y2: 242, thickness: 82, color: 'white' },
  { type: 'line', x1: 578, y1: 510, x2: 852, y2: 782, thickness: 82, color: 'white' },
  { type: 'rect', x: 696, y: 858, width: 172, height: 32, radius: 16, color: 'amber' },
];

function insideRoundRect(x, y, left, top, width, height, radius) {
  const cx = Math.max(left + radius, Math.min(x, left + width - radius));
  const cy = Math.max(top + radius, Math.min(y, top + height - radius));
  const dx = x - cx;
  const dy = y - cy;
  return dx * dx + dy * dy <= radius * radius;
}

function paintRect(buffer, x, y, width, height, radius, color) {
  const x0 = Math.max(0, Math.floor(x));
  const y0 = Math.max(0, Math.floor(y));
  const x1 = Math.min(masterSize, Math.ceil(x + width));
  const y1 = Math.min(masterSize, Math.ceil(y + height));
  for (let py = y0; py < y1; py += 1) {
    for (let px = x0; px < x1; px += 1) {
      if (!insideRoundRect(px + 0.5, py + 0.5, x, y, width, height, radius)) continue;
      const offset = (py * masterSize + px) * 4;
      buffer.set(color, offset);
    }
  }
}

function paintLine(buffer, x1, y1, x2, y2, thickness, color) {
  const half = thickness / 2;
  const dx = x2 - x1;
  const dy = y2 - y1;
  const lengthSq = dx * dx + dy * dy;
  const minX = Math.max(0, Math.floor(Math.min(x1, x2) - half));
  const maxX = Math.min(masterSize, Math.ceil(Math.max(x1, x2) + half));
  const minY = Math.max(0, Math.floor(Math.min(y1, y2) - half));
  const maxY = Math.min(masterSize, Math.ceil(Math.max(y1, y2) + half));
  for (let py = minY; py < maxY; py += 1) {
    for (let px = minX; px < maxX; px += 1) {
      const tx = px + 0.5 - x1;
      const ty = py + 0.5 - y1;
      const t = Math.max(0, Math.min(1, (tx * dx + ty * dy) / lengthSq));
      const ex = x1 + t * dx;
      const ey = y1 + t * dy;
      if ((px + 0.5 - ex) ** 2 + (py + 0.5 - ey) ** 2 > half * half) continue;
      const offset = (py * masterSize + px) * 4;
      buffer.set(color, offset);
    }
  }
}

function drawMaster() {
  const pixels = new Uint8Array(masterSize * masterSize * 4);
  // Keep the macOS-style rounded silhouette in the pixels so privacy lists do not show square corners.
  for (const shape of iconShapes) {
    if (shape.type === 'rect') {
      paintRect(pixels, shape.x, shape.y, shape.width, shape.height, shape.radius, colors[shape.color].rgba);
    } else {
      paintLine(pixels, shape.x1, shape.y1, shape.x2, shape.y2, shape.thickness, colors[shape.color].rgba);
    }
  }
  return pixels;
}

function svgArtwork() {
  const marks = iconShapes.map(shape => {
    if (shape.type === 'rect') {
      return `<rect x="${shape.x}" y="${shape.y}" width="${shape.width}" height="${shape.height}" rx="${shape.radius}" fill="${colors[shape.color].hex}"/>`;
    }
    return `<line x1="${shape.x1}" y1="${shape.y1}" x2="${shape.x2}" y2="${shape.y2}" stroke="${colors[shape.color].hex}" stroke-width="${shape.thickness}" stroke-linecap="round"/>`;
  });
  return `<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 1024 1024" data-mark="officekit-monogram">${marks.join('')}</svg>\n`;
}

function resizeBox(source, size) {
  const output = Buffer.alloc(size * size * 4);
  const ratio = masterSize / size;
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const x0 = Math.floor(x * ratio);
      const y0 = Math.floor(y * ratio);
      const x1 = Math.min(masterSize, Math.ceil((x + 1) * ratio));
      const y1 = Math.min(masterSize, Math.ceil((y + 1) * ratio));
      const sums = [0, 0, 0, 0];
      let samples = 0;
      for (let sy = y0; sy < y1; sy += 1) {
        for (let sx = x0; sx < x1; sx += 1) {
          const offset = (sy * masterSize + sx) * 4;
          for (let c = 0; c < 4; c += 1) sums[c] += source[offset + c];
          samples += 1;
        }
      }
      const offset = (y * size + x) * 4;
      for (let c = 0; c < 4; c += 1) output[offset + c] = Math.round(sums[c] / samples);
    }
  }
  return output;
}

const crcTable = new Uint32Array(256);
for (let n = 0; n < 256; n += 1) {
  let c = n;
  for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  crcTable[n] = c >>> 0;
}

function crc32(buffer) {
  let crc = 0xffffffff;
  for (const byte of buffer) crc = crcTable[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function pngChunk(type, data) {
  const name = Buffer.from(type, 'ascii');
  const header = Buffer.alloc(4);
  header.writeUInt32BE(data.length, 0);
  const checksum = Buffer.alloc(4);
  checksum.writeUInt32BE(crc32(Buffer.concat([name, data])), 0);
  return Buffer.concat([header, name, data, checksum]);
}

function encodePng(size, rgba) {
  const scanlines = Buffer.alloc(size * (size * 4 + 1));
  for (let y = 0; y < size; y += 1) {
    const row = y * (size * 4 + 1);
    scanlines[row] = 0;
    Buffer.from(rgba.buffer, rgba.byteOffset + y * size * 4, size * 4).copy(scanlines, row + 1);
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8;
  ihdr[9] = 6;
  const compressed = zlib.deflateSync(scanlines, { level: 9 });
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    pngChunk('IHDR', ihdr),
    pngChunk('IDAT', compressed),
    pngChunk('IEND', Buffer.alloc(0)),
  ]);
}

const master = drawMaster();
fs.writeFileSync(path.join(iconDir, 'officekit-icon.svg'), svgArtwork());
const sizes = [16, 20, 24, 29, 30, 32, 40, 44, 48, 58, 60, 64, 71, 76, 80, 83, 87, 89, 107, 120, 128, 142, 150, 152, 167, 180, 256, 284, 310, 512, 1024];
const pngs = new Map();
for (const size of sizes) pngs.set(size, encodePng(size, resizeBox(master, size)));
const write = (name, size) => fs.writeFileSync(path.join(iconDir, name), pngs.get(size));

write('icon.png', 512);
// Keep the repository-level icon used by desktop metadata and release assets in sync.
fs.writeFileSync(path.join(root, 'app-icon.png'), pngs.get(512));
write('32x32.png', 32);
write('64x64.png', 64);
write('128x128.png', 128);
write('128x128@2x.png', 256);
for (const [filename, size] of Object.entries({
  'Square30x30Logo.png': 30,
  'Square44x44Logo.png': 44,
  'Square71x71Logo.png': 71,
  'Square89x89Logo.png': 89,
  'Square107x107Logo.png': 107,
  'Square142x142Logo.png': 142,
  'Square150x150Logo.png': 150,
  'Square284x284Logo.png': 284,
  'Square310x310Logo.png': 310,
  'StoreLogo.png': 512,
})) write(filename, size);

const icoSizes = [16, 32, 48, 64, 128, 256];
const icoHeader = Buffer.alloc(6);
icoHeader.writeUInt16LE(0, 0);
icoHeader.writeUInt16LE(1, 2);
icoHeader.writeUInt16LE(icoSizes.length, 4);
let icoOffset = icoHeader.length + icoSizes.length * 16;
const icoEntries = [];
for (let index = 0; index < icoSizes.length; index += 1) {
  const size = icoSizes[index];
  const png = pngs.get(size);
  const entry = Buffer.alloc(16);
  entry[0] = size === 256 ? 0 : size;
  entry[1] = size === 256 ? 0 : size;
  entry.writeUInt16LE(1, 4);
  entry.writeUInt16LE(32, 6);
  entry.writeUInt32LE(png.length, 8);
  entry.writeUInt32LE(icoOffset, 12);
  icoEntries.push(entry);
  icoOffset += png.length;
}
fs.writeFileSync(path.join(iconDir, 'icon.ico'), Buffer.concat([icoHeader, ...icoEntries, ...icoSizes.map(size => pngs.get(size))]));

const cli = path.join(root, 'node_modules', '@tauri-apps', 'cli', 'tauri.js');
if (!fs.existsSync(cli)) {
  throw new Error('Tauri CLI is required for valid macOS ICNS generation. Run npm ci before building app icons.');
}
const generatedIcons = fs.mkdtempSync(path.join(os.tmpdir(), 'officekit-tauri-icons-'));
try {
  const result = spawnSync(process.execPath, [cli, 'icon', path.join(root, 'app-icon.png'), '--output', generatedIcons], {
    cwd: root,
    encoding: 'utf8',
  });
  if (result.error || result.status !== 0) {
    throw new Error(`Tauri could not generate the macOS app icon: ${result.stderr || result.error}`);
  }
  fs.copyFileSync(path.join(generatedIcons, 'icon.icns'), path.join(iconDir, 'icon.icns'));
} finally {
  fs.rmSync(generatedIcons, { recursive: true, force: true });
}

const iosDir = path.join(iconDir, 'ios');
if (fs.existsSync(iosDir)) {
  const iosAssets = {
    'AppIcon-20x20@1x.png': 20,
    'AppIcon-20x20@2x.png': 40,
    'AppIcon-20x20@2x-1.png': 40,
    'AppIcon-20x20@3x.png': 60,
    'AppIcon-29x29@1x.png': 29,
    'AppIcon-29x29@2x.png': 58,
    'AppIcon-29x29@2x-1.png': 58,
    'AppIcon-29x29@3x.png': 87,
    'AppIcon-40x40@1x.png': 40,
    'AppIcon-40x40@2x.png': 80,
    'AppIcon-40x40@2x-1.png': 80,
    'AppIcon-40x40@3x.png': 120,
    'AppIcon-60x60@2x.png': 120,
    'AppIcon-60x60@3x.png': 180,
    'AppIcon-76x76@1x.png': 76,
    'AppIcon-76x76@2x.png': 152,
    'AppIcon-83.5x83.5@2x.png': 167,
    'AppIcon-512@2x.png': 1024,
  };
  for (const [filename, size] of Object.entries(iosAssets)) {
    const bytes = encodePng(size, resizeBox(master, size));
    fs.writeFileSync(path.join(iosDir, filename), bytes);
  }
}

process.stdout.write(`Generated ${pngs.size} PNG sizes, the shared app icon, and a Tauri-encoded macOS bundle icon from the OfficeKit monogram.\n`);
