import { spawn, spawnSync } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { installSmokeEntitlement } from './smoke-backend-sidecar.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const fixture = path.join(root, 'tests/fixtures/similar-images/cc0/dog-on-road.jpg');
const audioMp3Fixture = path.join(root, 'tests/fixtures/media/audio-tone.mp3');
const expectedOperations = [
  'image-optimize', 'image-fit-size', 'image-convert', 'image-resize', 'image-crop',
  'image-strip-metadata', 'image-watermark', 'image-watermark-overlay', 'video-optimize', 'video-fit-size',
  'video-crop', 'video-resize', 'video-speed', 'video-mute', 'video-strip-metadata', 'video-to-gif', 'pdf-lossless-compress',
  'video-hevc-convert', 'video-watermark-overlay',
  'pdf-visual-optimize', 'pdf-fit-size', 'pdf-crop', 'pdf-uncrop', 'audio-optimize', 'audio-convert',
  'audio-fit-size', 'audio-normalize', 'audio-artwork',
];
let activeSidecar = null;
let sidecarStderr = '';

function reservePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      if (!address || typeof address === 'string') {
        server.close(() => reject(new Error('Could not reserve a sidecar port.')));
        return;
      }
      server.close(error => error ? reject(error) : resolve(address.port));
    });
  });
}

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

function writeWav(destination, channels = 1) {
  const sampleRate = 44_100;
  const samples = sampleRate;
  const bytesPerFrame = channels * 2;
  const data = Buffer.alloc(samples * bytesPerFrame);
  for (let index = 0; index < samples; index += 1) {
    for (let channel = 0; channel < channels; channel += 1) {
      const frequency = 220 + channel * 37;
      data.writeInt16LE(Math.round(Math.sin(2 * Math.PI * frequency * index / sampleRate) * 10_000), (index * channels + channel) * 2);
    }
  }
  const header = Buffer.alloc(44);
  header.write('RIFF', 0);
  header.writeUInt32LE(36 + data.length, 4);
  header.write('WAVEfmt ', 8);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);
  header.writeUInt16LE(channels, 22);
  header.writeUInt32LE(sampleRate, 24);
  header.writeUInt32LE(sampleRate * bytesPerFrame, 28);
  header.writeUInt16LE(bytesPerFrame, 32);
  header.writeUInt16LE(16, 34);
  header.write('data', 36);
  header.writeUInt32LE(data.length, 40);
  fs.writeFileSync(destination, Buffer.concat([header, data]));
}

function generateVideo(destination) {
  const generator = path.join(root, 'scripts/media-smoke-video.swift');
  const result = spawnSync('swift', [generator, destination], {
    cwd: root, encoding: 'utf8', timeout: 90_000,
  });
  if (result.error || result.status !== 0) {
    throw new Error(`Could not generate the local video acceptance fixture: ${result.stderr || result.error?.message || result.stdout}`);
  }
}

async function waitForHealth(origin, token, child) {
  const deadline = Date.now() + 90_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null || child.signalCode !== null) {
      throw new Error(`Packaged sidecar exited before readiness (${child.exitCode ?? child.signalCode}).`);
    }
    try {
      const response = await fetch(`${origin}/api/health`, {
        headers: { Authorization: `Bearer ${token}` },
        signal: AbortSignal.timeout(500),
      });
      if (response.ok) return;
    } catch (_) {
      // Sidecar startup can race its first health request.
    }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Packaged sidecar did not become healthy within 90 seconds (exit=${child.exitCode ?? child.signalCode ?? 'running'})${sidecarStderr ? `; ${sidecarStderr.trim().slice(-1200)}` : '; no sidecar stderr was captured'}.`);
}

async function request(origin, route, { token, nativeToken, method = 'GET', body, expectedStatus = 200 } = {}) {
  const headers = { Authorization: `Bearer ${token}`, Origin: 'tauri://localhost' };
  if (nativeToken) headers['X-OfficeKit-Native-Grant'] = nativeToken;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let response;
  try {
    response = await fetch(`${origin}${route}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(15_000),
    });
  } catch (error) {
    const state = activeSidecar
      ? `sidecar exit=${activeSidecar.exitCode ?? activeSidecar.signalCode ?? 'running'}`
      : 'sidecar unavailable';
    throw new Error(`${method} ${route} failed: ${error.message} (${state})${sidecarStderr ? `; ${sidecarStderr.trim().slice(-1200)}` : ''}`, { cause: error });
  }
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json') ? await response.json() : await response.arrayBuffer();
  requireCondition(response.status === expectedStatus,
    `${method} ${route} returned ${response.status}, expected ${expectedStatus}.`);
  return { response, payload };
}

async function waitForJob(origin, id, auth) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    const { payload } = await request(origin, `/api/media-jobs/${id}`, auth);
    if (['ready', 'partial', 'failed', 'cancelled'].includes(payload.state)) return payload;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('Packaged media job did not finish within 30 seconds.');
}

async function waitForFile(predicate, label, timeoutMs = 25_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const value = predicate();
    if (value) return value;
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  throw new Error(`Timed out waiting for ${label}.`);
}

async function submitSelectionJob(origin, auth, source, operationId, options) {
  const { payload: selection } = await request(origin, '/api/file-selections', {
    ...auth, method: 'POST', expectedStatus: 201, body: { paths: [source], access: 'read' },
  });
  const { payload: manifest } = await request(origin, `/api/file-selections/${selection.id}`, auth);
  requireCondition(manifest.files.length === 1 && manifest.access === 'read', 'The packaged selection did not remain read-only.');
  const created = await request(origin, '/api/media-jobs', {
    ...auth, method: 'POST', expectedStatus: 202,
    body: { items: [{ source: { kind: 'selection', selectionId: selection.id, fileId: manifest.files[0].id }, operations: [{ operationId, options }] }] },
  });
  return { selection, job: await waitForJob(origin, created.payload.id, auth) };
}

async function verifyNativeArtifact(origin, token, job, mimePrefix, signature, label) {
  requireCondition(job.state === 'ready' && job.items[0].state === 'ready',
    `The packaged ${label} conversion did not complete (${job.state}/${job.items[0]?.state}, code=${job.items[0]?.errorCode ?? 'none'}, attributes=${JSON.stringify(job.items[0]?.attributes ?? {})}).`);
  requireCondition(!Object.hasOwn(job.items[0], 'path'), `A local ${label} source path crossed the media job response boundary.`);
  const artifact = await fetch(`${origin}/api/media-artifacts/${job.items[0].artifactId}`, {
    headers: { Authorization: `Bearer ${token}`, Origin: 'tauri://localhost' },
    signal: AbortSignal.timeout(15_000),
  });
  requireCondition(artifact.status === 200 && artifact.headers.get('cache-control') === 'no-store' &&
    artifact.headers.get('content-type')?.startsWith(mimePrefix), `The packaged ${label} artifact response violated its local contract.`);
  const bytes = Buffer.from(await artifact.arrayBuffer());
  requireCondition(bytes.length === job.items[0].outputBytes && bytes.length > 0 && signature(bytes),
    `The packaged ${label} artifact was incomplete or had an unexpected container signature.`);
  return bytes;
}

function verifyDecodedOutput(kind, bytes, destination, verifierArgs = [destination]) {
  fs.writeFileSync(destination, bytes, { flag: 'wx' });
  const verifier = path.join(root, 'scripts/media-smoke-verify.swift');
  const result = spawnSync('swift', [verifier, kind, ...verifierArgs], {
    cwd: root, encoding: 'utf8', timeout: 90_000,
  });
  requireCondition(!result.error && result.status === 0,
    `The packaged ${kind} output could not be decoded: ${result.stderr || result.error?.message || result.stdout}`);
}

function verifyAv1DecodedOutput(bytes, destination) {
  fs.writeFileSync(destination, bytes, { flag: 'wx' });
  const ffmpeg = ['/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg'].find(candidate => fs.existsSync(candidate));
  requireCondition(ffmpeg, 'The advertised AV1 encoder has no matching local FFmpeg decoder.');
  const result = spawnSync(ffmpeg, [
    '-nostdin', '-hide_banner', '-loglevel', 'error', '-protocol_whitelist', 'file,pipe',
    '-f', 'mov', '-i', destination, '-map', '0:v:0', '-frames:v', '1', '-f', 'null', '-',
  ], { cwd: root, encoding: 'utf8', timeout: 90_000 });
  requireCondition(!result.error && result.status === 0,
    `The packaged AV1 output could not be decoded by local FFmpeg: ${result.stderr || result.error?.message || result.stdout}`);
}

async function smoke(binary) {
  requireCondition(fs.existsSync(binary), `Packaged sidecar is missing: ${binary}`);
  const tempRoot = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'officekit-media-package-smoke-')));
  const home = path.join(tempRoot, 'home');
  fs.mkdirSync(home);
  const source = path.join(tempRoot, 'source.jpg');
  fs.copyFileSync(fixture, source);
  const original = fs.readFileSync(source);
  const originalHash = createHash('sha256').update(original).digest('hex');
  const token = randomUUID();
  const nativeToken = randomUUID();
  const port = await reservePort();
  const origin = `http://127.0.0.1:${port}`;
  const child = spawn(binary, [], {
    cwd: tempRoot,
    stdio: ['ignore', 'ignore', 'pipe'],
    env: {
      ...process.env,
      HOME: home,
      OFFICEKIT_API_PORT: String(port),
      OFFICEKIT_API_TOKEN: token,
      OFFICEKIT_NATIVE_GRANT_TOKEN: nativeToken,
    },
  });
  activeSidecar = child;
  sidecarStderr = '';
  child.stderr.setEncoding('utf8');
  child.stderr.on('data', chunk => { sidecarStderr = (sidecarStderr + chunk).slice(-4000); });
  const auth = { token, nativeToken };
  let avifVerified = false;
  let jxlVerified = false;
  let audioFlacVerified = false;
  let av1Verified = false;
  try {
    await waitForHealth(origin, token, child);

    const unauthenticated = await fetch(`${origin}/api/media-capabilities`);
    requireCondition(unauthenticated.status === 401, 'Media capabilities did not require local API authentication.');

    // Locked until the native shell pushes an entitlement: prove that, then install one as the shell does.
    const locked = await request(origin, '/api/media-capabilities', { ...auth, expectedStatus: 403 });
    requireCondition(locked.payload?.error?.code === 'license_required', 'A locked packaged sidecar did not answer license_required.');
    await installSmokeEntitlement({ origin, token, grantToken: nativeToken });

    const { payload: capabilities } = await request(origin, '/api/media-capabilities', auth);
    const operations = capabilities.media.flatMap(group => group.operations);
    requireCondition(operations.length === expectedOperations.length, `The packaged operation catalog does not include all ${expectedOperations.length} operations.`);
    requireCondition(expectedOperations.every(id => operations.some(operation => operation.id === id)),
      'The packaged operation catalog is missing one or more advertised operations.');
    for (const operationId of ['image-optimize', 'video-optimize', 'video-crop', 'video-resize', 'video-speed', 'video-mute', 'video-strip-metadata', 'video-to-gif', 'audio-optimize', 'audio-normalize', 'audio-artwork']) {
      requireCondition(operations.find(operation => operation.id === operationId)?.available === true,
        `The ${operationId} adapter is unavailable in this macOS package.`);
    }
    const deniedSelection = await request(origin, '/api/file-selections', {
      ...auth, nativeToken: randomUUID(), method: 'POST', expectedStatus: 403,
      body: { paths: [source], access: 'read' },
    });
    requireCondition(deniedSelection.payload.detail.includes('granted'), 'Native file access did not require its scoped grant.');

    const { payload: pipeline } = await request(origin, '/api/media-pipelines', {
      ...auth, method: 'POST', expectedStatus: 201,
      body: { name: 'Package acceptance recipe', media: 'image', operations: [{ operationId: 'image-optimize', options: { quality: 82 } }] },
    });
    requireCondition(pipeline.state === 'paused', 'A packaged saved pipeline did not start paused.');
    const pipelinePath = path.join(home, 'Library', 'Application Support', 'OfficeKit', 'media-pipelines.json');
    const validPipelineBytes = fs.readFileSync(pipelinePath);
    fs.writeFileSync(pipelinePath, '{broken');
    const recovery = await request(origin, '/api/media-pipelines', { ...auth, expectedStatus: 503 });
    requireCondition(recovery.payload.detail.includes('left unchanged'), 'Corrupt settings did not report safe recovery.');
    requireCondition(fs.readFileSync(pipelinePath, 'utf8') === '{broken', 'Corrupt settings were silently replaced.');
    fs.writeFileSync(pipelinePath, validPipelineBytes);

    const watchFolder = path.join(tempRoot, 'watched-folder');
    fs.mkdirSync(watchFolder);
    fs.copyFileSync(source, path.join(watchFolder, 'existing.jpg'));
    const existingWatchOutput = path.join(watchFolder, 'existing_prepared.jpg');
    fs.writeFileSync(existingWatchOutput, Buffer.from('user-owned-existing-output'));
    const outputCollision = path.join(watchFolder, 'new-watch_prepared.jpg');
    const collisionBytes = Buffer.from('user-owned-collision-output');
    fs.writeFileSync(outputCollision, collisionBytes);
    const { payload: watchSelection } = await request(origin, '/api/file-selections', {
      ...auth, method: 'POST', expectedStatus: 201,
      body: { paths: [watchFolder], access: 'read-write' },
    });
    const watchManifest = await request(origin, `/api/file-selections/${watchSelection.id}`, auth);
    requireCondition(watchManifest.payload.access === 'read-write' && watchManifest.payload.files.length === 3,
      `The packaged watched-folder grant returned access=${watchManifest.payload.access} and ${watchManifest.payload.files.length} files.`);
    const createdWatch = await request(origin, '/api/media-folder-watches', {
      ...auth, method: 'POST', expectedStatus: 201,
      body: { selectionId: watchSelection.id, pipelineId: pipeline.id },
    });
    const watch = createdWatch.payload;
    requireCondition(watch.state === 'watching' && watch.folderName === 'watched-folder' &&
      !JSON.stringify(watch).includes(watchFolder), 'The watched-folder response disclosed a path or wrong grant state.');
    await request(origin, `/api/media-pipelines/${pipeline.id}`, { ...auth, method: 'DELETE', expectedStatus: 409 });
    const watchedSource = path.join(watchFolder, 'new-watch.jpg');
    fs.copyFileSync(source, watchedSource);
    const watchedSourceHash = createHash('sha256').update(fs.readFileSync(watchedSource)).digest('hex');
    const watchedOutput = await waitForFile(() => fs.existsSync(path.join(watchFolder, 'new-watch_prepared (2).jpg'))
      ? path.join(watchFolder, 'new-watch_prepared (2).jpg') : null, 'collision-safe watched-folder output');
    const watchedBytes = fs.readFileSync(watchedOutput);
    verifyDecodedOutput('image', watchedBytes, path.join(tempRoot, 'watched-output-verify.jpg'));
    requireCondition(fs.readFileSync(outputCollision).equals(collisionBytes), 'Watched-folder automation replaced an existing output.');
    requireCondition(createHash('sha256').update(fs.readFileSync(watchedSource)).digest('hex') === watchedSourceHash,
      'Watched-folder automation changed its selected source.');
    const watchState = await request(origin, '/api/media-folder-watches', auth);
    requireCondition(watchState.payload.length === 1 && watchState.payload[0].processedCount === 1 &&
      watchState.payload[0].recentOutcomes.at(-1)?.state === 'ready' &&
      watchState.payload[0].recentOutcomes.at(-1)?.outputName === path.basename(watchedOutput) &&
      !JSON.stringify(watchState.payload).includes(watchFolder),
    'The packaged watched-folder service did not report a successful recent outcome.');
    const pausedWatch = await request(origin, `/api/media-folder-watches/${watch.id}`, {
      ...auth, method: 'PATCH', expectedStatus: 200, body: { paused: true },
    });
    requireCondition(pausedWatch.payload.state === 'paused', 'The packaged watched-folder service did not pause.');
    await request(origin, `/api/media-folder-watches/${watch.id}`, { ...auth, method: 'DELETE', expectedStatus: 204 });
    requireCondition((await request(origin, '/api/media-folder-watches', auth)).payload.length === 0,
      'Removing a folder grant did not stop its packaged watcher.');
    await request(origin, `/api/file-selections/${watchSelection.id}`, { ...auth, method: 'DELETE', expectedStatus: 204 });
    await request(origin, `/api/media-pipelines/${pipeline.id}`, { ...auth, method: 'DELETE', expectedStatus: 204 });

    const imageRun = await submitSelectionJob(origin, auth, source, 'image-optimize', { quality: 82 });
    const prepared = await verifyNativeArtifact(origin, token, imageRun.job, 'image/jpeg',
      bytes => bytes[0] === 0xff && bytes[1] === 0xd8, 'image');
    verifyDecodedOutput('image', prepared, path.join(tempRoot, 'prepared.jpg'));
    requireCondition(createHash('sha256').update(fs.readFileSync(source)).digest('hex') === originalHash,
      'The packaged media operation changed its selected original.');

    const imageConvert = operations.find(operation => operation.id === 'image-convert');
    if (imageConvert.formats.includes('avif')) {
      const avifRun = await submitSelectionJob(origin, auth, source, 'image-convert', { targetFormat: 'avif', quality: 78 });
      await verifyNativeArtifact(origin, token, avifRun.job, 'image/avif',
        bytes => bytes.subarray(4, 8).toString('ascii') === 'ftyp' && bytes.includes(Buffer.from('avif')), 'AVIF image');
      avifVerified = true;
      requireCondition(createHash('sha256').update(fs.readFileSync(source)).digest('hex') === originalHash,
        'The packaged AVIF conversion changed its selected original.');
      await request(origin, `/api/file-selections/${avifRun.selection.id}`, { ...auth, method: 'DELETE', expectedStatus: 204 });
    }
    if (imageConvert.formats.includes('jxl')) {
      const jxlRun = await submitSelectionJob(origin, auth, source, 'image-convert', { targetFormat: 'jxl', quality: 82 });
      const jxlBytes = await verifyNativeArtifact(origin, token, jxlRun.job, 'image/jxl',
        bytes => bytes.includes(Buffer.from('jxl ')) || (bytes[0] === 0xff && bytes[1] === 0x0a), 'JPEG XL image');
      const jxlPath = path.join(tempRoot, 'converted.jxl');
      fs.writeFileSync(jxlPath, jxlBytes, { flag: 'wx' });
      const decodedJxlRun = await submitSelectionJob(origin, auth, jxlPath, 'image-optimize', { quality: 80 });
      await verifyNativeArtifact(origin, token, decodedJxlRun.job, 'image/jxl',
        bytes => bytes.includes(Buffer.from('jxl ')) || (bytes[0] === 0xff && bytes[1] === 0x0a), 'decoded JPEG XL image');
      await request(origin, `/api/file-selections/${decodedJxlRun.selection.id}`, { ...auth, method: 'DELETE', expectedStatus: 204 });
      jxlVerified = true;
      requireCondition(createHash('sha256').update(fs.readFileSync(source)).digest('hex') === originalHash,
        'The packaged JPEG XL conversion changed its selected original.');
      await request(origin, `/api/file-selections/${jxlRun.selection.id}`, { ...auth, method: 'DELETE', expectedStatus: 204 });
    }

    const oversizedPath = path.join(tempRoot, 'over-limit.jpg');
    const oversizedHandle = fs.openSync(oversizedPath, 'wx');
    fs.ftruncateSync(oversizedHandle, 64 * 1024 * 1024 + 1);
    fs.closeSync(oversizedHandle);
    const { payload: oversizedSelection } = await request(origin, '/api/file-selections', {
      ...auth, method: 'POST', expectedStatus: 201, body: { paths: [oversizedPath], access: 'read' },
    });
    const { payload: oversizedManifest } = await request(origin, `/api/file-selections/${oversizedSelection.id}`, auth);
    const tooLarge = await request(origin, '/api/media-jobs', {
      ...auth, method: 'POST', expectedStatus: 413,
      body: { items: [{ source: { kind: 'selection', selectionId: oversizedSelection.id, fileId: oversizedManifest.files[0].id }, operations: [{ operationId: 'image-optimize', options: {} }] }] },
    });
    requireCondition(tooLarge.payload.detail.includes('64 MiB'), 'The packaged sidecar did not enforce its input resource bound.');
    await request(origin, `/api/file-selections/${oversizedSelection.id}`, { ...auth, method: 'DELETE', expectedStatus: 204 });

    const audioSource = path.join(tempRoot, 'tone.wav');
    writeWav(audioSource);
    const audioHash = createHash('sha256').update(fs.readFileSync(audioSource)).digest('hex');
    const audioRun = await submitSelectionJob(origin, auth, audioSource, 'audio-convert', { targetFormat: 'm4a', bitrateKbps: 128 });
    const preparedAudio = await verifyNativeArtifact(origin, token, audioRun.job, 'audio/mp4',
      bytes => bytes.subarray(4, 8).toString('ascii') === 'ftyp', 'audio');
    verifyDecodedOutput('audio', preparedAudio, path.join(tempRoot, 'prepared.m4a'));
    requireCondition(createHash('sha256').update(fs.readFileSync(audioSource)).digest('hex') === audioHash,
      'The packaged audio operation changed its selected original.');
    const mp3Source = path.join(tempRoot, 'tone-source.mp3');
    fs.copyFileSync(audioMp3Fixture, mp3Source);
    const mp3Hash = createHash('sha256').update(fs.readFileSync(mp3Source)).digest('hex');
    const mp3Run = await submitSelectionJob(origin, auth, mp3Source, 'audio-convert', { targetFormat: 'm4a', bitrateKbps: 128 });
    const preparedMp3 = await verifyNativeArtifact(origin, token, mp3Run.job, 'audio/mp4',
      bytes => bytes.subarray(4, 8).toString('ascii') === 'ftyp', 'MP3 input conversion');
    verifyDecodedOutput('audio', preparedMp3, path.join(tempRoot, 'from-mp3.m4a'));
    requireCondition(createHash('sha256').update(fs.readFileSync(mp3Source)).digest('hex') === mp3Hash,
      'The packaged MP3 input operation changed its selected original.');
    if (capabilities.media.flatMap(group => group.operations).find(operation => operation.id === 'audio-convert')?.formats.includes('flac')) {
      const flacRun = await submitSelectionJob(origin, auth, audioSource, 'audio-convert', { targetFormat: 'flac', bitrateKbps: 128 });
      requireCondition(flacRun.job.items[0].attributes?.codec === 'flac' && flacRun.job.items[0].attributes?.lossless === true &&
        !Object.hasOwn(flacRun.job.items[0].attributes || {}, 'bitrate_kbps'),
      'The packaged FLAC operation reported misleading bitrate metadata.');
      const flac = await verifyNativeArtifact(origin, token, flacRun.job, 'audio/flac',
        bytes => bytes.subarray(0, 4).toString('ascii') === 'fLaC', 'FLAC audio');
      const flacSource = path.join(tempRoot, 'prepared.flac');
      verifyDecodedOutput('audio', flac, flacSource);
      requireCondition(createHash('sha256').update(fs.readFileSync(audioSource)).digest('hex') === audioHash,
        'The packaged FLAC operation changed its selected original.');
      const flacSourceHash = createHash('sha256').update(fs.readFileSync(flacSource)).digest('hex');
      const flacInputRun = await submitSelectionJob(origin, auth, flacSource, 'audio-convert', { targetFormat: 'm4a', bitrateKbps: 128 });
      const decodedFlac = await verifyNativeArtifact(origin, token, flacInputRun.job, 'audio/mp4',
        bytes => bytes.subarray(4, 8).toString('ascii') === 'ftyp', 'FLAC input conversion');
      verifyDecodedOutput('audio', decodedFlac, path.join(tempRoot, 'from-flac.m4a'));
      requireCondition(createHash('sha256').update(fs.readFileSync(flacSource)).digest('hex') === flacSourceHash,
        'The packaged FLAC input operation changed its selected original.');
      audioFlacVerified = true;
    }

    const normalizeRun = await submitSelectionJob(origin, auth, audioSource, 'audio-normalize', { targetLufs: -14 });
    const normalizedAudio = await verifyNativeArtifact(origin, token, normalizeRun.job, 'audio/mp4',
      bytes => bytes.subarray(4, 8).toString('ascii') === 'ftyp', 'normalized audio');
    const loudness = normalizeRun.job.items[0].attributes;
    requireCondition(loudness.target_lufs === -14 && loudness.target_met === true &&
      Math.abs(loudness.output_lufs + 14) <= 0.5 &&
      ((typeof loudness.true_peak_dbfs === 'number' && loudness.true_peak_dbfs <= -1.5 && loudness.true_peak_ceiling_dbfs === -2) ||
       (typeof loudness.sample_peak_dbfs === 'number' && loudness.sample_peak_dbfs <= -1.5 && loudness.peak_ceiling_dbfs === -2)) &&
      !JSON.stringify(loudness).includes(tempRoot), 'The packaged loudness result missed its target or exposed a local path.');
    verifyDecodedOutput('audio', normalizedAudio, path.join(tempRoot, 'normalized.m4a'));
    requireCondition(createHash('sha256').update(fs.readFileSync(audioSource)).digest('hex') === audioHash,
      'Audio normalization changed its selected original.');

    const surroundSource = path.join(tempRoot, 'surround-5-1.wav');
    writeWav(surroundSource, 6);
    const surroundHash = createHash('sha256').update(fs.readFileSync(surroundSource)).digest('hex');
    const surroundRun = await submitSelectionJob(origin, auth, surroundSource, 'audio-normalize', { targetLufs: -16 });
    const surroundAudio = await verifyNativeArtifact(origin, token, surroundRun.job, 'audio/mp4',
      bytes => bytes.subarray(4, 8).toString('ascii') === 'ftyp', '5.1 normalized audio');
    const surroundMetrics = surroundRun.job.items[0].attributes;
    requireCondition(typeof surroundMetrics.true_peak_dbfs === 'number' && surroundMetrics.true_peak_dbfs <= -1.5 &&
      surroundMetrics.true_peak_ceiling_dbfs === -2 && surroundMetrics.target_met === true &&
      Math.abs(surroundMetrics.output_lufs + 16) <= 0.5,
      'Multichannel normalization did not report verified true-peak and loudness metrics.');
    verifyDecodedOutput('audio-channels', surroundAudio, path.join(tempRoot, 'normalized-5-1.m4a'),
      [path.join(tempRoot, 'normalized-5-1.m4a'), '6']);
    requireCondition(createHash('sha256').update(fs.readFileSync(surroundSource)).digest('hex') === surroundHash,
      'Multichannel audio normalization changed its selected original.');

    const audioArtworkSource = path.join(tempRoot, 'audio-artwork-source.m4a');
    const artworkFixture = spawnSync('swift', [
      path.join(root, 'scripts/media-smoke-audio-artwork.swift'), audioSource, source, audioArtworkSource,
    ], { cwd: root, encoding: 'utf8', timeout: 90_000 });
    requireCondition(!artworkFixture.error && artworkFixture.status === 0,
      `Could not create an embedded-artwork fixture: ${artworkFixture.stderr || artworkFixture.error?.message || artworkFixture.stdout}`);
    const artworkSourceHash = createHash('sha256').update(fs.readFileSync(audioArtworkSource)).digest('hex');
    const artworkRun = await submitSelectionJob(origin, auth, audioArtworkSource, 'audio-artwork', { maxEdge: 128 });
    const artworkBytes = await verifyNativeArtifact(origin, token, artworkRun.job, 'audio/mp4',
      bytes => bytes.subarray(4, 8).toString('ascii') === 'ftyp', 'audio artwork');
    const artworkOutput = path.join(tempRoot, 'audio-artwork-output.m4a');
    verifyDecodedOutput('audio-artwork', artworkBytes, artworkOutput, [artworkOutput, '128']);
    requireCondition(createHash('sha256').update(fs.readFileSync(audioArtworkSource)).digest('hex') === artworkSourceHash,
      'The packaged audio artwork operation changed its selected original.');

    const videoSource = path.join(tempRoot, 'sample.mov');
    generateVideo(videoSource);
    const videoHash = createHash('sha256').update(fs.readFileSync(videoSource)).digest('hex');
    const videoRun = await submitSelectionJob(origin, auth, videoSource, 'video-optimize', { targetFormat: 'm4v', quality: 'smaller' });
    const preparedVideo = await verifyNativeArtifact(origin, token, videoRun.job, 'video/x-m4v',
      bytes => bytes.subarray(4, 8).toString('ascii') === 'ftyp', 'video');
    verifyDecodedOutput('video', preparedVideo, path.join(tempRoot, 'prepared.m4v'));

    const av1Available = capabilities.media.find(media => media.id === 'video')
      ?.operations.find(operation => operation.id === 'video-optimize')?.formats.includes('av1') === true;
    if (av1Available) {
      const av1Run = await submitSelectionJob(origin, auth, videoSource, 'video-optimize', { targetFormat: 'av1', quality: 'smaller' });
      const av1 = await verifyNativeArtifact(origin, token, av1Run.job, 'video/mp4',
        bytes => bytes.subarray(4, 8).toString('ascii') === 'ftyp', 'AV1 video');
      requireCondition(av1Run.job.items[0].attributes.codec === 'av1', 'The packaged AV1 result did not report its codec.');
      verifyAv1DecodedOutput(av1, path.join(tempRoot, 'prepared-av1.mp4'));
      requireCondition(createHash('sha256').update(fs.readFileSync(videoSource)).digest('hex') === videoHash,
        'The packaged AV1 conversion changed its selected original.');
      av1Verified = true;
    }
    requireCondition(createHash('sha256').update(fs.readFileSync(videoSource)).digest('hex') === videoHash,
      'The packaged video operation changed its selected original.');

    if (operations.find(operation => operation.id === 'video-hevc-convert')?.available) {
      const hevcRun = await submitSelectionJob(origin, auth, videoSource, 'video-hevc-convert', {});
      const hevc = await verifyNativeArtifact(origin, token, hevcRun.job, 'video/quicktime',
        bytes => bytes.subarray(4, 8).toString('ascii') === 'ftyp', 'HEVC video');
      verifyDecodedOutput('video-hevc', hevc, path.join(tempRoot, 'hevc.mov'));
      requireCondition(hevcRun.job.items[0].attributes?.codec === 'hevc', 'The HEVC operation did not report its selected codec.');
      requireCondition(createHash('sha256').update(fs.readFileSync(videoSource)).digest('hex') === videoHash,
        'The packaged HEVC operation changed its selected original.');
    }

    const audioVideoSource = path.join(tempRoot, 'sample-with-audio.mov');
    const mux = spawnSync('swift', [path.join(root, 'scripts/media-smoke-mux.swift'), videoSource, audioSource, audioVideoSource], {
      cwd: root, encoding: 'utf8', timeout: 90_000,
    });
    requireCondition(!mux.error && mux.status === 0, `Could not create an audio/video fixture: ${mux.stderr || mux.error?.message || mux.stdout}`);
    const audioVideoHash = createHash('sha256').update(fs.readFileSync(audioVideoSource)).digest('hex');
    const mutedRun = await submitSelectionJob(origin, auth, audioVideoSource, 'video-mute', {});
    const muted = await verifyNativeArtifact(origin, token, mutedRun.job, 'video/quicktime',
      bytes => bytes.subarray(4, 8).toString('ascii') === 'ftyp', 'muted video');
    verifyDecodedOutput('video-muted', muted, path.join(tempRoot, 'muted.mov'));
    requireCondition(createHash('sha256').update(fs.readFileSync(audioVideoSource)).digest('hex') === audioVideoHash,
      'The packaged video mute operation changed its selected original.');

    const speedRun = await submitSelectionJob(origin, auth, videoSource, 'video-speed', { factorPercent: 200 });
    const sped = await verifyNativeArtifact(origin, token, speedRun.job, 'video/quicktime',
      bytes => bytes.subarray(4, 8).toString('ascii') === 'ftyp', 'speed-adjusted video');
    verifyDecodedOutput('video-speed', sped, path.join(tempRoot, 'sped.mov'), [videoSource, path.join(tempRoot, 'sped.mov'), '200']);
    requireCondition(createHash('sha256').update(fs.readFileSync(videoSource)).digest('hex') === videoHash,
      'The packaged video speed operation changed its selected original.');

    const cropRun = await submitSelectionJob(origin, auth, videoSource, 'video-crop', {
      x: 10, y: 10, width: 100, height: 80,
    });
    const cropped = await verifyNativeArtifact(origin, token, cropRun.job, 'video/quicktime',
      bytes => bytes.subarray(4, 8).toString('ascii') === 'ftyp', 'cropped video');
    verifyDecodedOutput('video-crop', cropped, path.join(tempRoot, 'cropped.mov'), [path.join(tempRoot, 'cropped.mov'), '100', '80']);
    requireCondition(createHash('sha256').update(fs.readFileSync(videoSource)).digest('hex') === videoHash,
      'The packaged video crop operation changed its selected original.');

    const resizeRun = await submitSelectionJob(origin, auth, audioVideoSource, 'video-resize', {
      maxWidth: 100, maxHeight: 80,
    });
    const resized = await verifyNativeArtifact(origin, token, resizeRun.job, 'video/quicktime',
      bytes => bytes.subarray(4, 8).toString('ascii') === 'ftyp', 'resized video');
    verifyDecodedOutput('video-resize', resized, path.join(tempRoot, 'resized.mov'), [path.join(tempRoot, 'resized.mov'), '100', '80']);
    requireCondition(resizeRun.job.items[0].attributes.max_width === 100 &&
      resizeRun.job.items[0].attributes.max_height === 80,
    'The packaged video resize did not report its requested bounds.');
    requireCondition(createHash('sha256').update(fs.readFileSync(audioVideoSource)).digest('hex') === audioVideoHash,
      'The packaged video resize operation changed its selected original.');

    const gifRun = await submitSelectionJob(origin, auth, videoSource, 'video-to-gif', {
      fps: 5, maxWidth: 80, maxDurationSeconds: 2,
    });
    const gif = await verifyNativeArtifact(origin, token, gifRun.job, 'image/gif',
      bytes => bytes.subarray(0, 4).toString('ascii') === 'GIF8', 'video GIF');
    verifyDecodedOutput('gif', gif, path.join(tempRoot, 'prepared.gif'));
    requireCondition(createHash('sha256').update(fs.readFileSync(videoSource)).digest('hex') === videoHash,
      'The packaged video-to-GIF operation changed its selected original.');

    const cancelDirectory = path.join(tempRoot, 'cancel-video-batch');
    fs.mkdirSync(cancelDirectory);
    for (let index = 0; index < 30; index += 1) {
      fs.copyFileSync(videoSource, path.join(cancelDirectory, `clip-${index}.mov`));
    }
    const cancelInputHashes = fs.readdirSync(cancelDirectory).sort().map(name => {
      const inputPath = path.join(cancelDirectory, name);
      return createHash('sha256').update(fs.readFileSync(inputPath)).digest('hex');
    });
    const { payload: cancelSelection } = await request(origin, '/api/file-selections', {
      ...auth, method: 'POST', expectedStatus: 201, body: { paths: [cancelDirectory], access: 'read' },
    });
    const { payload: cancelManifest } = await request(origin, `/api/file-selections/${cancelSelection.id}`, auth);
    requireCondition(cancelManifest.files.length === 30, 'The cancellation stress batch was incomplete.');
    const cancelJob = await request(origin, '/api/media-jobs', {
      ...auth, method: 'POST', expectedStatus: 202,
      body: { items: cancelManifest.files.map(file => ({
        source: { kind: 'selection', selectionId: cancelSelection.id, fileId: file.id },
        operations: [{ operationId: 'video-optimize', options: { targetFormat: 'm4v', quality: 'smaller' } }],
      })) },
    });
    await request(origin, `/api/media-jobs/${cancelJob.payload.id}/cancellations`, {
      ...auth, method: 'POST', expectedStatus: 202, body: {},
    });
    const cancelled = await waitForJob(origin, cancelJob.payload.id, auth);
    requireCondition(cancelled.state === 'cancelled', 'The packaged media queue did not stop the batch when cancelled.');
    const expectedCancellationNames = Array.from({ length: 30 }, (_, index) => `clip-${index}.mov`).sort();
    const actualCancellationNames = fs.readdirSync(cancelDirectory).sort();
    requireCondition(JSON.stringify(actualCancellationNames) === JSON.stringify(expectedCancellationNames),
      'The cancelled media batch changed the selected input file set.');
    const unchangedCancellationInputs = actualCancellationNames.every((name, index) => {
      const inputPath = path.join(cancelDirectory, name);
      return createHash('sha256').update(fs.readFileSync(inputPath)).digest('hex') === cancelInputHashes[index];
    });
    requireCondition(unchangedCancellationInputs, 'The cancelled media batch changed one or more selected originals.');
    for (const selection of [imageRun.selection, audioRun.selection, normalizeRun.selection, videoRun.selection, mutedRun.selection, speedRun.selection, cropRun.selection, resizeRun.selection, gifRun.selection, cancelSelection]) {
      await request(origin, `/api/file-selections/${selection.id}`, { ...auth, method: 'DELETE', expectedStatus: 204 });
    }

    process.stdout.write(`Packaged media acceptance passed: all ${expectedOperations.length} operations are catalogued${avifVerified ? ' and AVIF conversion passed' : ' (AVIF encoder unavailable)'}${jxlVerified ? '; JPEG XL conversion passed' : '; JPEG XL encoder unavailable'}${audioFlacVerified ? '; FLAC conversion passed' : '; FLAC encoder unavailable'}${av1Verified ? '; AV1 video conversion passed' : '; AV1 encoder unavailable'}, saved pipelines start paused and survive corruption without replacement, native image (${prepared.length} bytes), audio (${preparedAudio.length} bytes), video (${preparedVideo.length} bytes), and GIF (${gif.length} bytes) jobs produce decoded artifacts, HEVC is checked when its native preset is available, crop returns requested dimensions, resize stays within requested bounds and preserves audio, mute removes the audio track, 2x speed output has the expected duration, oversized input is rejected, a 30-item native video batch cancels cleanly, native grants are enforced, and all converted and cancelled source files remain unchanged.\n`);
  } finally {
    child.kill('SIGTERM');
    await new Promise(resolve => {
      if (child.exitCode !== null || child.signalCode !== null) return resolve();
      child.once('exit', resolve);
      setTimeout(() => {
        if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
        resolve();
      }, 5_000).unref();
    });
    fs.rmSync(tempRoot, { recursive: true, force: true });
    activeSidecar = null;
  }
}

const binary = process.argv[2];
if (!binary) {
  process.stderr.write('Usage: node scripts/smoke-media-sidecar.mjs <packaged-sidecar-path>\n');
  process.exitCode = 2;
} else {
  smoke(path.resolve(binary)).catch(error => {
    process.stderr.write(`Packaged media acceptance failed: ${error.message}\n`);
    process.exitCode = 1;
  });
}
