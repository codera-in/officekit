import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const script = fs.readFileSync(path.join(root, 'scripts/smoke-macos-dmg.mjs'), 'utf8');
const sidecarSmoke = fs.readFileSync(path.join(root, 'scripts/smoke-backend-sidecar.mjs'), 'utf8');

test('mounted DMG smoke ejects its image with diskutil and removes the temporary mountpoint only after eject', () => {
  assert.match(script, /if \(mounted\) await ejectSmokeImage\(mountPoint, run\)/);
  assert.match(fs.readFileSync(path.join(root, 'scripts/dmg-eject-retry.mjs'), 'utf8'), /run\('diskutil',\s*\['eject',\s*mountPoint\]\)/);
  assert.match(script, /if\s*\(!mounted\)\s*fs\.rmSync\(mountPoint,\s*\{\s*recursive:\s*true,\s*force:\s*true\s*\}\)/);
  assert.doesNotMatch(script, /run\('hdiutil',\s*\['detach'/);
});

test('mounted DMG smoke reserves an isolated loopback port and passes it to the packaged sidecar', () => {
  assert.match(script, /function reserveSmokePort\(\)/);
  assert.match(script, /server\.listen\(0, '127\.0\.0\.1'/);
  assert.match(script, /OFFICEKIT_API_PORT:\s*String\(smokePort\)/);
  assert.doesNotMatch(script, /assertSmokePortIsAvailable|OfficeKit local API port 8000 is already in use/);
  assert.match(sidecarSmoke, /let API_ORIGIN = `http:\/\/127\.0\.0\.1:\$\{smokePortValue\}`/);
  assert.match(sidecarSmoke, /input\.replaceAll\(DEFAULT_API_ORIGIN, API_ORIGIN\)/);
  assert.match(sidecarSmoke, /OFFICEKIT_API_PORT must be a decimal TCP port/);
});

test('mounted DMG smoke verifies the privacy explanation required for microphone permission', () => {
  assert.match(script, /NSMicrophoneUsageDescription/);
  assert.match(script, /OfficeKit uses the microphone for on-device dictation\. Audio is processed locally/);
});

test('mounted DMG smoke checks the Parakeet deployment minimum and Swift runtime path', () => {
  assert.match(script, /LSMinimumSystemVersion/);
  assert.match(script, /otool/);
  assert.match(script, /Swift runtime search path required by FluidAudio/);
});

test('mounted DMG smoke verifies the Vision OCR helper deployment target', () => {
  assert.match(script, /officekit-vision-ocr/);
  assert.match(script, /LC_BUILD_VERSION/);
  assert.match(script, /Vision OCR helper must target macOS 14\.0/);
});

test('mounted DMG smoke verifies optional MP3 output without changing the selected source', () => {
  assert.match(script, /hostFfmpeg\(\)/);
  assert.match(script, /targetFormat: 'mp3'/);
  assert.match(script, /libmp3lame|not available in this build/);
  assert.match(script, /audio-tone\.mp3/);
  assert.match(script, /createHash\('sha256'\)/);
  assert.match(script, /Packaged MP3 output did not return the expected signature and codec attributes/);
});

test('mounted DMG smoke exercises the packaged uncrop-pdf CLI preset', () => {
  assert.match(script, /--preset', 'uncrop-pdf'/);
  assert.match(script, /uncrop-pdf preset/);
});

test('mounted DMG smoke exercises typed CLI settings in an isolated home directory', () => {
  assert.match(script, /--settings', 'schema'/);
  assert.match(script, /--settings', 'set'/);
  assert.match(script, /--settings', 'get'/);
  assert.match(script, /--settings', 'clear'/);
  assert.match(script, /settingsEnvironment/);
});

test('mounted DMG smoke exercises the typed Clop-style convert verb without changing the source', () => {
  assert.match(script, /'convert', '--operation-id', 'image-convert'/);
  assert.ok(script.includes("'--options-json', '{\"targetFormat\":\"webp\",\"quality\":75}'"));
  assert.match(script, /Packaged typed convert verb did not create a valid WebP copy while preserving its source/);
});

test('mounted DMG smoke executes safe inline pipeline DSL without replacing source files', () => {
  assert.match(script, /'pipeline', 'run', 'convert\(to: webp\)'/);
  assert.match(script, /Packaged inline pipeline did not produce a WebP copy while preserving its source/);
});

test('mounted DMG smoke verifies lossless WebP conversion through the packaged DSL', () => {
  assert.match(script, /convert\(to: webp, lossless: true\)/);
  assert.match(script, /attributes\?\.lossless !== true/);
  assert.match(script, /Packaged lossless WebP conversion did not create a marked copy while preserving its source/);
});

test('mounted DMG smoke verifies inline filename filters preserve selected and skipped sources', () => {
  assert.match(script, /if\(regex: "\^dog", minFileSize: 1B\) -> convert\(to: webp\)/);
  assert.match(script, /Packaged inline filename filter did not select and skip files safely/);
});

test('mounted DMG smoke fails closed for image-DPI filters without explicit metadata', () => {
  assert.match(script, /if\(dpiGreaterThan: 1\) -> convert\(to: webp\)/);
  assert.match(script, /Packaged image-DPI filter did not fail closed on files without explicit DPI metadata/);
});

test('mounted DMG smoke publishes inline fork snapshots and the continued pipeline result', () => {
  assert.match(script, /convert\(to: webp\) -> fork\(\) -> optimise\(compression: 70\)/);
  assert.match(script, /dog-on-road-fork-1\.webp/);
  assert.match(script, /Packaged inline fork did not publish its intermediate and final copies while preserving the source/);
});

test('mounted DMG smoke saves Clop-style typed pipeline steps as a paused local pipeline', () => {
  assert.match(script, /'pipeline', 'add', 'Smoke inline pipeline', 'convert\(to: webp\)', '--file-type', 'image'/);
  assert.match(script, /Packaged Clop-style pipeline add did not save and run typed steps safely/);
});

test('mounted DMG smoke maps inline targetSize to a bounded output copy', () => {
  assert.match(script, /'pipeline', 'run', 'targetSize\(size: 10MB\)'/);
  assert.match(script, /Packaged inline targetSize did not publish a size-bounded copy while preserving its source/);
});

test('mounted DMG smoke exports bounded PDF pages through the typed pipeline', () => {
  assert.match(script, /extractPagesAsImages\(format: png, quality: high, dpi: 120\)/);
  assert.match(script, /Packaged extractPagesAsImages did not publish an ordered image archive while preserving its source/);
});

test('mounted DMG smoke applies changeSpeed to audio while preserving the source', () => {
  assert.match(script, /'changeSpeed\(factor: 2\.0\)'/);
  assert.match(script, /Packaged audio changeSpeed did not halve the duration in a separate M4A copy while preserving its source/);
});

test('mounted DMG smoke lowers audio bitrate without upscaling or changing the source', () => {
  assert.match(script, /function writeToneWav\(filePath/);
  assert.match(script, /'pipeline', 'run', 'lowerBitrate\(kbps: 96\)'/);
  assert.match(script, /attributes\?\.bitrate_kbps !== 96/);
  assert.match(script, /attributes\?\.no_upscale !== true/);
  assert.match(script, /lowerBitrateDuration - 4/);
  assert.match(script, /lowerBitrateSourceHash/);
});

test('mounted DMG smoke applies a video watermark as a separate audio preserving copy', () => {
  assert.match(script, /watermark\(image: .*position: topLeft, opacity: 1\.0, scale: 0\.2\)/);
  assert.match(script, /'video-watermark'/);
  assert.match(script, /Packaged video watermark pipeline did not publish a new MOV while preserving its source/);
});

test('mounted DMG smoke verifies optional H.264, VP9, and software HEVC video encoders', () => {
  assert.match(script, /target: 'mp4', extension: 'mp4', codec: 'h264'/);
  assert.match(script, /target: 'webm', extension: 'webm', codec: 'vp9'/);
  assert.match(script, /target: 'x265', extension: 'mp4', codec: 'hevc'/);
  assert.match(script, /conversion did not produce the requested video codec and retain audio/);
  assert.match(script, /optimise\(compression: 55\)/);
  assert.match(script, /attributes\?\.compression !== 55/);
  assert.match(script, /H\.264 compression factor 55 passed/);
  assert.match(script, /'optimise', '--compression', '55'/);
  assert.match(script, /Clop-style --compression 55 flag passed/);
  assert.match(script, /Optional FFmpeg video conversion or compression changed its selected original/);
});

test('mounted DMG smoke verifies adaptive and numeric image compression copies', () => {
  assert.match(script, /'optimise', '--compression', 'adaptive'/);
  assert.match(script, /'optimise', '--compression', '55'/);
  assert.match(script, /selected_format/);
  assert.match(script, /adaptive\/numeric and lossless image conversion/);
  assert.match(script, /Packaged image compression controls did not create valid separate copies while preserving their source/);
});

test('mounted DMG smoke caps video frame rate through the typed pipeline operation', () => {
  assert.match(script, /'pipeline', 'run', 'capFps\(fps: 15\)'/);
  assert.match(script, /'video-fps', videoDownscaleInput, videoCapFpsPath, '15'/);
  assert.match(script, /Packaged capFps pipeline did not create a separate copy while preserving its source/);
});

test('mounted DMG smoke resolves inline aspect-ratio crop geometry from each source', () => {
  assert.match(script, /'pipeline', 'run', 'crop\(aspectRatio: 1:1\) -> convert\(to: webp\)'/);
  assert.match(script, /Packaged inline aspect-ratio crop did not create a source-preserving WebP copy/);
});

test('mounted DMG smoke runs Vision smart crop through the packaged inline pipeline', () => {
  assert.match(script, /crop\(aspectRatio: 1:1, smartCrop: true\)/);
  assert.match(script, /Packaged Vision smart crop did not create a source-preserving image copy/);
});

test('mounted DMG smoke resolves inline factor downscale from source dimensions', () => {
  assert.match(script, /'pipeline', 'run', 'downscale\(factor: 0\.5\) -> convert\(to: webp\)'/);
  assert.match(script, /Packaged inline factor downscale did not create a source-preserving WebP copy/);
});

test('mounted DMG smoke verifies factor-based video downscale dimensions and identity copies', () => {
  assert.match(script, /'downscale', '--factor', '0\.5'/);
  assert.match(script, /media-smoke-verify\.swift'\), 'video-resize'/);
  assert.match(script, /video downscale factor 1 did not create a byte-identical copy/);
});

test('mounted DMG smoke exposes and runs factor-based video downscale through MCP', () => {
  assert.match(script, /'downscale-video'/);
  assert.match(script, /preset: 'downscale-video', factor: 0\.5/);
  assert.match(script, /Packaged MCP video downscale did not create a separate copy/);
});
