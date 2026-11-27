import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { isOfficeKitPackagedMacIcon } from './macos-app-icon.mjs';
import { ejectSmokeImage } from './dmg-eject-retry.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const bundleDir = path.join(root, 'src-tauri', 'target', 'release', 'bundle', 'dmg');

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { cwd: root, encoding: 'utf8', ...options });
  if (result.error || result.status !== 0) {
    const diagnostic = [result.stderr, result.stdout, result.error?.message].filter(Boolean).join('\n') || 'No diagnostic output';
    throw new Error(`${command} ${args.join(' ')} failed: ${diagnostic.slice(-4_000)}`);
  }
  return result.stdout;
}

function imageDimensions(filePath) {
  const output = run('/usr/bin/sips', ['-g', 'pixelWidth', '-g', 'pixelHeight', filePath]);
  const width = output.match(/pixelWidth:\s*(\d+)/)?.[1];
  const height = output.match(/pixelHeight:\s*(\d+)/)?.[1];
  if (!width || !height) throw new Error(`Could not read image dimensions for ${path.basename(filePath)}.`);
  return { width: Number(width), height: Number(height) };
}

function writeToneWav(filePath, durationSeconds = 4, sampleRate = 16_000, { channels = 1, transient = false, amplitude = 6_000 } = {}) {
  const frameCount = durationSeconds * sampleRate;
  const pcmBytes = Buffer.alloc(frameCount * channels * 2);
  for (let frame = 0; frame < frameCount; frame += 1) {
    const time = frame / sampleRate;
    const level = transient ? (time % 0.25 < 0.002 ? 0.95 : 0.02) * 32767 : amplitude;
    const sample = Math.round(Math.sin(2 * Math.PI * (transient ? 10_000 : 440) * time) * level);
    for (let channel = 0; channel < channels; channel += 1) pcmBytes.writeInt16LE(sample, (frame * channels + channel) * 2);
  }
  const wav = Buffer.alloc(44 + pcmBytes.length);
  wav.write('RIFF', 0); wav.writeUInt32LE(36 + pcmBytes.length, 4); wav.write('WAVE', 8);
  wav.write('fmt ', 12); wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(channels, 22);
  wav.writeUInt32LE(sampleRate, 24); wav.writeUInt32LE(sampleRate * channels * 2, 28); wav.writeUInt16LE(channels * 2, 32); wav.writeUInt16LE(16, 34);
  wav.write('data', 36); wav.writeUInt32LE(pcmBytes.length, 40); pcmBytes.copy(wav, 44);
  fs.writeFileSync(filePath, wav, { flag: 'wx', mode: 0o600 });
}

function latestDmg(directory) {
  const matches = fs.readdirSync(directory)
    .filter(name => /^OfficeKit_.*\.dmg$/i.test(name))
    .map(name => path.join(directory, name))
    .sort((left, right) => fs.statSync(right).mtimeMs - fs.statSync(left).mtimeMs);
  if (!matches.length) throw new Error(`No OfficeKit DMG found in ${directory}`);
  return matches[0];
}

function hostFfmpeg() {
  return ['/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg', '/usr/bin/ffmpeg']
    .find(candidate => {
      try { return fs.statSync(candidate).isFile() && (fs.statSync(candidate).mode & 0o111) !== 0; }
      catch { return false; }
    }) || null;
}

function reserveSmokePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      if (!address || typeof address === 'string') {
        server.close(() => reject(new Error('Could not reserve an isolated OfficeKit API port.')));
        return;
      }
      server.close(error => error ? reject(error) : resolve(address.port));
    });
  });
}

async function listMediaMcpTools(executable, options = {}) {
  const child = spawn(executable, ['--mcp-server'], {
    cwd: root,
    stdio: ['pipe', 'pipe', 'pipe'],
    env: options.home ? { ...process.env, HOME: options.home } : process.env,
  });
  let output = '';
  let errorOutput = '';
  const pending = new Map();
  child.stdout.setEncoding('utf8');
  child.stderr.setEncoding('utf8');
  child.stdout.on('data', chunk => {
    output += chunk;
    const lines = output.split(/\r?\n/);
    output = lines.pop() || '';
    for (const line of lines) {
      if (!line) continue;
      try {
        const message = JSON.parse(line);
        if (pending.has(message.id)) {
          pending.get(message.id).resolve(message);
          pending.delete(message.id);
        }
      } catch (error) {
        for (const waiter of pending.values()) waiter.reject(error);
        pending.clear();
      }
    }
  });
  child.stderr.on('data', chunk => { errorOutput += chunk; });
  const request = (id, method, params) => new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`Timed out waiting for MCP ${method}; stderr: ${errorOutput}`));
    }, 30000);
    pending.set(id, {
      resolve: message => { clearTimeout(timeout); resolve(message); },
      reject: error => { clearTimeout(timeout); reject(error); },
    });
    child.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', id, method, params })}\n`);
  });
  const mcpStamp = {
    'io.modelcontextprotocol/protocolVersion': '2026-07-28',
    'io.modelcontextprotocol/clientInfo': { name: 'officekit-dmg-smoke', version: '1.0.0' },
    'io.modelcontextprotocol/clientCapabilities': {},
  };
  try {
    const discovery = await request(1, 'server/discover', { _meta: mcpStamp });
    if (discovery.error) throw new Error(`MCP discovery failed: ${JSON.stringify(discovery.error)}`);
    const listing = await request(2, 'tools/list', { _meta: mcpStamp });
    if (listing.error) throw new Error(`MCP tools/list failed: ${JSON.stringify(listing.error)}`);
    const tools = listing.result?.tools || [];
    const presetTool = tools.find(tool => tool.name === 'officekit_media_run_preset');
    const presetChoices = presetTool?.inputSchema?.properties?.preset?.enum || [];
    const expectedPresets = ['optimize-image', 'optimize-media', 'to-webp', 'downscale-image', 'downscale-video', 'downscale-audio', 'crop-aspect', 'sort-screenshots', 'audio-to-mp3', 'video-to-gif', 'video-2x-silent', 'uncrop-pdf'];
    if (expectedPresets.some(preset => !presetChoices.includes(preset))) {
      throw new Error(`Packaged MCP preset schema is missing a built-in preset: ${JSON.stringify(presetChoices)}`);
    }
    if (options.exercise) {
      let requestId = 3;
      const call = async (name, arguments_) => {
        const response = await request(requestId++, 'tools/call', {
          name,
          arguments: arguments_,
          _meta: mcpStamp,
        });
        if (response.error) throw new Error(`Packaged MCP ${name} failed: ${JSON.stringify(response.error)}`);
        const result = response.result;
        const text = result?.content?.find(item => item.type === 'text')?.text;
        if (result?.isError) return { isError: true, error: text || 'unknown MCP error' };
        if (!text) throw new Error(`Packaged MCP ${name} returned no typed result.`);
        return JSON.parse(text);
      };
      const savedDefault = await call('officekit_media_set_operation_default', {
        operation_id: 'image-optimize', options: { quality: 73, preserveMetadata: false },
      });
      const listedDefaults = await call('officekit_media_list_operation_defaults', {});
      if (savedDefault.state !== 'saved' || listedDefaults['image-optimize']?.quality !== 73) {
        throw new Error('Packaged MCP did not persist a validated operation default.');
      }
      const clearedDefaults = await call('officekit_media_clear_operation_defaults', {});
      if (clearedDefaults.state !== 'cleared') throw new Error('Packaged MCP did not clear operation defaults.');
      const triggerPipeline = await call('officekit_media_create_pipeline', {
        definition: {
          name: 'DMG trigger smoke',
          media: 'image',
          operations: [{ operationId: 'image-strip-metadata', options: {} }],
        },
      });
      const pinnedTrigger = await call('officekit_media_set_pipeline_trigger', {
        trigger: 'clipboard', pipeline_id: triggerPipeline.id,
      });
      const listedTriggers = await call('officekit_media_list_pipeline_triggers', {});
      const blockedTriggerPipelineDelete = await call('officekit_media_delete_pipeline', { pipeline_id: triggerPipeline.id });
      if (pinnedTrigger.pipelineId !== triggerPipeline.id || listedTriggers.clipboard !== triggerPipeline.id
        || !blockedTriggerPipelineDelete.isError) {
        throw new Error('Packaged MCP pipeline trigger binding or dependency guard failed.');
      }
      const clearedTrigger = await call('officekit_media_clear_pipeline_trigger', { trigger: 'clipboard' });
      if (clearedTrigger.state !== 'cleared') throw new Error('Packaged MCP did not clear the pipeline trigger binding.');
      const removedTriggerPipeline = await call('officekit_media_delete_pipeline', { pipeline_id: triggerPipeline.id });
      if (removedTriggerPipeline.state !== 'deleted') throw new Error('Packaged MCP did not delete the unpinned trigger pipeline.');
      const created = await call('officekit_media_create_pipeline', {
        definition: {
          name: 'DMG MCP smoke',
          media: 'image',
          operations: [{ operationId: 'image-strip-metadata', options: {} }],
        },
      });
      if (!created.id || created.state !== 'paused') throw new Error('Packaged MCP pipeline creation was not safely paused.');
      const zone = await call('officekit_media_create_preset_zone', {
        name: 'DMG smoke zone',
        pipeline_id: created.id,
      });
      if (!zone.id || zone.enabled !== false || zone.pipelineId !== created.id) {
        throw new Error('Packaged MCP preset zone was not created disabled against its pipeline.');
      }
      const renamedZone = await call('officekit_media_rename_preset_zone', {
        zone_id: zone.id,
        name: 'DMG smoke zone renamed',
      });
      if (renamedZone.isError) throw new Error(`Packaged MCP preset-zone rename failed: ${renamedZone.error}`);
      if (renamedZone.id !== zone.id || renamedZone.pipelineId !== created.id || renamedZone.state !== 'renamed' || 'enabled' in renamedZone) {
        throw new Error(`Packaged MCP preset-zone rename changed its identity or exposed session state: ${JSON.stringify({ zone, renamedZone })}`);
      }
      const replacement = await call('officekit_media_create_pipeline', {
        definition: {
          name: 'DMG MCP replacement',
          media: 'image',
          operations: [{ operationId: 'image-strip-metadata', options: {} }],
        },
      });
      if (!replacement.id || replacement.state !== 'paused') throw new Error('Packaged MCP replacement pipeline did not start paused.');
      const reboundZone = await call('officekit_media_rebind_preset_zone', {
        zone_id: zone.id,
        pipeline_id: replacement.id,
      });
      if (reboundZone.isError) throw new Error(`Packaged MCP preset-zone rebind failed: ${reboundZone.error}`);
      if (reboundZone.id !== zone.id || reboundZone.name !== renamedZone.name || reboundZone.pipelineId !== replacement.id || reboundZone.state !== 'rebound' || 'enabled' in reboundZone) {
        throw new Error(`Packaged MCP preset-zone rebind changed its identity or exposed session state: ${JSON.stringify({ zone, reboundZone })}`);
      }
      const blocked = await call('officekit_media_delete_pipeline', { pipeline_id: replacement.id });
      if (!blocked.isError) throw new Error('Packaged MCP deleted a pipeline still referenced by a preset zone.');
      const removedZone = await call('officekit_media_delete_preset_zone', { zone_id: zone.id });
      if (removedZone.state !== 'deleted') throw new Error('Packaged MCP did not remove the preset-zone binding.');
      const removedPipeline = await call('officekit_media_delete_pipeline', { pipeline_id: replacement.id });
      if (removedPipeline.state !== 'deleted') throw new Error('Packaged MCP did not remove the unreferenced pipeline.');
      const removedOriginalPipeline = await call('officekit_media_delete_pipeline', { pipeline_id: created.id });
      if (removedOriginalPipeline.state !== 'deleted') throw new Error('Packaged MCP did not remove the original pipeline.');
      const presetInput = path.join(root, 'tests', 'fixtures', 'similar-images', 'cc0', 'dog-on-road.jpg');
      const presetSourceHash = createHash('sha256').update(fs.readFileSync(presetInput)).digest('hex');
      const presetOutputDirectory = path.join(options.home, 'mcp-preset-output');
      const presetRun = await call('officekit_media_run_preset', {
        files: [presetInput], preset: 'to-webp', output_directory: presetOutputDirectory,
      });
      const presetArtifact = presetRun.results?.[0]?.output;
      const presetBytes = presetArtifact ? fs.readFileSync(path.join(presetOutputDirectory, presetArtifact)) : Buffer.alloc(0);
      if (presetRun.state !== 'complete' || presetArtifact !== 'dog-on-road-optimized.webp'
        || presetBytes.subarray(0, 4).toString('ascii') !== 'RIFF' || presetBytes.subarray(8, 12).toString('ascii') !== 'WEBP'
        || createHash('sha256').update(fs.readFileSync(presetInput)).digest('hex') !== presetSourceHash) {
        throw new Error('Packaged MCP preset runner did not create a safe WebP output copy.');
      }
      const downscaleSourceDimensions = imageDimensions(presetInput);
      const downscaleOutputDirectory = path.join(options.home, 'mcp-downscale-output');
      const downscaleRun = await call('officekit_media_run_preset', {
        files: [presetInput], preset: 'downscale-image', factor: 0.5,
        output_directory: downscaleOutputDirectory,
      });
      const downscaleArtifact = downscaleRun.results?.[0]?.output;
      const downscalePath = downscaleArtifact ? path.join(downscaleOutputDirectory, downscaleArtifact) : '';
      const downscaleDimensions = downscaleArtifact ? imageDimensions(downscalePath) : null;
      if (downscaleRun.state !== 'complete' || !downscaleDimensions
        || downscaleDimensions.width >= downscaleSourceDimensions.width
        || downscaleDimensions.height >= downscaleSourceDimensions.height
        || downscaleRun.results?.[0]?.attributes?.width !== downscaleDimensions.width
        || downscaleRun.results?.[0]?.attributes?.height !== downscaleDimensions.height
        || createHash('sha256').update(fs.readFileSync(presetInput)).digest('hex') !== presetSourceHash) {
        throw new Error('Packaged MCP image downscale did not create a smaller typed copy while preserving its source.');
      }
      const audioDownscaleInput = path.join(root, 'tests', 'fixtures', 'media', 'audio-tone.mp3');
      const audioDownscaleHash = createHash('sha256').update(fs.readFileSync(audioDownscaleInput)).digest('hex');
      const audioDownscaleOutputDirectory = path.join(options.home, 'mcp-audio-downscale-output');
      const audioDownscaleRun = await call('officekit_media_run_preset', {
        files: [audioDownscaleInput], preset: 'downscale-audio', factor: 0.5,
        output_directory: audioDownscaleOutputDirectory,
      });
      const audioDownscaleArtifact = audioDownscaleRun.results?.[0]?.output;
      const audioDownscalePath = audioDownscaleArtifact ? path.join(audioDownscaleOutputDirectory, audioDownscaleArtifact) : '';
      if (audioDownscaleRun.state !== 'complete' || !audioDownscaleArtifact?.endsWith('.m4a')
        || createHash('sha256').update(fs.readFileSync(audioDownscaleInput)).digest('hex') !== audioDownscaleHash) {
        throw new Error('Packaged MCP audio downscale did not create a separate M4A copy while preserving its source.');
      }
      run('swift', [path.join(root, 'scripts/media-smoke-verify.swift'), 'audio', audioDownscalePath]);
      const cropSourceDimensions = imageDimensions(presetInput);
      const cropOutputDirectory = path.join(options.home, 'mcp-aspect-crop-output');
      const cropRun = await call('officekit_media_run_preset', {
        files: [presetInput], preset: 'crop-aspect', aspect_ratio: '16:9',
        output_directory: cropOutputDirectory,
      });
      const cropArtifact = cropRun.results?.[0]?.output;
      const cropDimensions = cropArtifact ? imageDimensions(path.join(cropOutputDirectory, cropArtifact)) : null;
      if (cropRun.state !== 'complete' || !cropDimensions || cropDimensions.width > cropSourceDimensions.width
        || cropDimensions.height > cropSourceDimensions.height
        || Math.abs(cropDimensions.width / cropDimensions.height - 16 / 9) > 0.01
        || createHash('sha256').update(fs.readFileSync(presetInput)).digest('hex') !== presetSourceHash) {
        throw new Error('Packaged MCP aspect-ratio crop did not create a centered-ratio copy while preserving its source.');
      }
      const videoFixtureDirectory = path.join(options.home, 'video-downscale-fixture');
      fs.mkdirSync(videoFixtureDirectory, { recursive: true });
      const videoOnlyInput = path.join(videoFixtureDirectory, 'video-only.mov');
      const videoGenerate = spawnSync('swift', [path.join(root, 'scripts/media-smoke-video.swift'), videoOnlyInput], {
        cwd: root, encoding: 'utf8', timeout: 90_000,
      });
      if (videoGenerate.error || videoGenerate.status !== 0) {
        throw new Error(`Could not generate the local MCP video downscale fixture: ${videoGenerate.stderr || videoGenerate.error?.message || videoGenerate.stdout}`);
      }
      const videoInput = path.join(videoFixtureDirectory, 'video-input.mov');
      const videoMux = spawnSync('swift', [path.join(root, 'scripts/media-smoke-mux.swift'), videoOnlyInput,
        path.join(root, 'tests/fixtures/media/audio-tone.mp3'), videoInput], {
        cwd: root, encoding: 'utf8', timeout: 90_000,
      });
      if (videoMux.error || videoMux.status !== 0) {
        throw new Error(`Could not create the audio/video MCP fixture: ${videoMux.stderr || videoMux.error?.message || videoMux.stdout}`);
      }
      const videoInputHash = createHash('sha256').update(fs.readFileSync(videoInput)).digest('hex');
      const videoOutputDirectory = path.join(options.home, 'mcp-video-downscale-output');
      const videoDownscaleRun = await call('officekit_media_run_preset', {
        files: [videoInput], preset: 'downscale-video', factor: 0.5,
        output_directory: videoOutputDirectory,
      });
      const videoDownscaleArtifact = videoDownscaleRun.results?.[0]?.output;
      const videoDownscalePath = videoDownscaleArtifact ? path.join(videoOutputDirectory, videoDownscaleArtifact) : '';
      if (videoDownscaleRun.state !== 'complete' || videoDownscaleArtifact !== 'video-input-optimized.mov'
        || createHash('sha256').update(fs.readFileSync(videoInput)).digest('hex') !== videoInputHash) {
        throw new Error('Packaged MCP video downscale did not create a separate copy while preserving its source.');
      }
      run('swift', [path.join(root, 'scripts/media-smoke-verify.swift'), 'video-resize', videoDownscalePath, '80', '60']);
      const namedPipeline = await call('officekit_media_create_pipeline', {
        definition: {
          name: 'DMG named output smoke',
          media: 'image',
          operations: [{ operationId: 'image-strip-metadata', options: {} }],
          outputNameTemplate: '{name}-mcp.{ext}',
        },
      });
      const namedOutputDirectory = path.join(options.home, 'mcp-named-pipeline-output');
      const namedPipelineRun = await call('officekit_media_run_pipeline', {
        pipeline_id: namedPipeline.id,
        files: [presetInput],
        output_directory: namedOutputDirectory,
      });
      const namedArtifact = namedPipelineRun.results?.[0]?.output;
      const namedBytes = namedArtifact ? fs.readFileSync(path.join(namedOutputDirectory, namedArtifact)) : Buffer.alloc(0);
      if (namedPipeline.outputNameTemplate !== '{name}-mcp.{ext}' || namedArtifact !== 'dog-on-road-mcp.jpg'
        || namedBytes.subarray(0, 2).toString('hex') !== 'ffd8'
        || createHash('sha256').update(fs.readFileSync(presetInput)).digest('hex') !== presetSourceHash) {
        throw new Error('Packaged MCP pipeline output-name template did not create a safe JPEG copy.');
      }
      const removedNamedPipeline = await call('officekit_media_delete_pipeline', { pipeline_id: namedPipeline.id });
      if (removedNamedPipeline.state !== 'deleted') throw new Error('Packaged MCP did not remove its named output pipeline.');
    }
    return tools;
  } finally {
    child.stdin.end();
    if (child.exitCode === null) child.kill();
  }
}

async function smoke(dmgPath) {
  const smokePort = await reserveSmokePort();
  const absoluteDmgPath = path.resolve(dmgPath);
  run('hdiutil', ['verify', absoluteDmgPath]);

  const mountPoint = fs.mkdtempSync(path.join(os.tmpdir(), 'officekit-dmg-smoke-'));
  let mounted = false;
  try {
    run('hdiutil', ['attach', '-readonly', '-noautoopen', '-nobrowse', '-mountpoint', mountPoint, absoluteDmgPath]);
    mounted = true;

    const appPath = path.join(mountPoint, 'OfficeKit.app');
    const sidecarPath = path.join(appPath, 'Contents', 'MacOS', 'officekit-backend');
    const mediaCliPath = path.join(appPath, 'Contents', 'Resources', 'binaries', 'officekit-media');
    const finderWorkflowPath = path.join(appPath, 'Contents', 'Resources', 'resources', 'OfficeKit Optimize Image.workflow');
    const visionHelperPath = path.join(appPath, 'Contents', 'Resources', 'resources', 'officekit-backend', 'officekit-vision-ocr');
    const infoPlistPath = path.join(appPath, 'Contents', 'Info.plist');
    const applicationsPath = path.join(mountPoint, 'Applications');
    if (!fs.statSync(appPath).isDirectory()) throw new Error('DMG does not contain OfficeKit.app');
    run('codesign', ['--verify', '--deep', '--strict', appPath]);
    const entitlementPath = path.join(mountPoint, '..', `${path.basename(mountPoint)}-entitlements.plist`);
    try {
      run('codesign', ['-d', '--entitlements', entitlementPath, '--xml', appPath]);
      if (!fs.existsSync(entitlementPath)) throw new Error('DMG app has no signed entitlements; microphone access is blocked under Hardened Runtime.');
      const entitlements = JSON.parse(run('plutil', ['-convert', 'json', '-o', '-', entitlementPath]));
      if (entitlements['com.apple.security.device.audio-input'] !== true) throw new Error('DMG app lacks the Hardened Runtime audio-input entitlement required for the microphone prompt.');
    } finally {
      fs.rmSync(entitlementPath, { force: true });
    }
    const minimumSystemVersion = run('plutil', ['-extract', 'LSMinimumSystemVersion', 'raw', infoPlistPath]).trim();
    if (minimumSystemVersion !== '14.0') throw new Error('DMG does not declare the macOS 14 minimum required by FluidAudio.');
    const visionHelperBuild = run('otool', ['-l', visionHelperPath]);
    const visionHelperMinimum = visionHelperBuild.match(/cmd LC_BUILD_VERSION[\s\S]*?minos ([0-9]+(?:\.[0-9]+){0,2})/)?.[1];
    if (visionHelperMinimum !== '14.0') {
      throw new Error(`DMG Vision OCR helper must target macOS 14.0; found ${visionHelperMinimum || 'no deployment target'}.`);
    }
    const executableName = run('plutil', ['-extract', 'CFBundleExecutable', 'raw', infoPlistPath]).trim();
    const appExecutablePath = path.join(appPath, 'Contents', 'MacOS', executableName);
    const loadCommands = run('otool', ['-l', appExecutablePath]);
    if (!/cmd LC_RPATH[\s\S]{0,160}path \/usr\/lib\/swift\b/.test(loadCommands)) {
      throw new Error('DMG app does not include the macOS Swift runtime search path required by FluidAudio.');
    }
    const linkedLibraries = run('otool', ['-L', appExecutablePath]);
    if (!linkedLibraries.includes('/usr/lib/swift/libswift_Concurrency.dylib')) {
      throw new Error('DMG app is not linked to the expected FluidAudio Swift runtime.');
    }
    const microphoneDescription = run('plutil', ['-extract', 'NSMicrophoneUsageDescription', 'raw', infoPlistPath]).trim();
    if (microphoneDescription !== 'OfficeKit uses the microphone for on-device dictation. Audio is processed locally and is not sent to OfficeKit servers.') {
      throw new Error('DMG app is missing the approved microphone permission explanation.');
    }
    const iconFile = run('plutil', ['-extract', 'CFBundleIconFile', 'raw', infoPlistPath]).trim();
    if (iconFile !== 'icon.icns') throw new Error('DMG app does not reference the approved OfficeKit icon filename.');
    const iconPath = path.join(appPath, 'Contents', 'Resources', iconFile);
    const iconTempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'officekit-dmg-icon-'));
    try {
      const decodeIcon = (source, name) => {
        const outputDir = path.join(iconTempDir, `${name}.iconset`);
        run('iconutil', ['-c', 'iconset', source, '--output', outputDir]);
        return fs.readdirSync(outputDir).filter(file => file.endsWith('.png')).sort()
          .map(file => [file, fs.readFileSync(path.join(outputDir, file))]);
      };
      const bundledImages = decodeIcon(iconPath, 'bundled');
      const expectedImages = decodeIcon(path.join(root, 'src-tauri', 'icons', 'icon.icns'), 'expected');
      if (!isOfficeKitPackagedMacIcon(iconFile, bundledImages, expectedImages)) {
        throw new Error('DMG app does not render the approved OfficeKit monogram at every ICNS size.');
      }
    } finally {
      fs.rmSync(iconTempDir, { recursive: true, force: true });
    }
    if (!fs.statSync(sidecarPath).isFile() || !(fs.statSync(sidecarPath).mode & 0o111)) {
      throw new Error('DMG app does not contain an executable backend sidecar');
    }
    if (!fs.statSync(mediaCliPath).isFile() || !(fs.statSync(mediaCliPath).mode & 0o111)) {
      throw new Error('DMG app does not contain the packaged Media Toolkit CLI');
    }
    const finderInfoPath = path.join(finderWorkflowPath, 'Contents', 'Info.plist');
    const finderDocumentPath = path.join(finderWorkflowPath, 'Contents', 'document.wflow');
    if (!fs.statSync(finderWorkflowPath).isDirectory()
      || !fs.readFileSync(finderInfoPath, 'utf8').includes('app.officekit.media.optimize-image')
      || !fs.readFileSync(finderDocumentPath, 'utf8').includes('--preset optimize-image')) {
      throw new Error('DMG app does not contain the owned image-only Finder Quick Action.');
    }
    run('plutil', ['-lint', finderInfoPath, finderDocumentPath]);
    const openInWorkflowPath = path.join(appPath, 'Contents', 'Resources', 'resources', 'Open in OfficeKit.workflow');
    const openInInfoPath = path.join(openInWorkflowPath, 'Contents', 'Info.plist');
    const openInDocumentPath = path.join(openInWorkflowPath, 'Contents', 'document.wflow');
    if (!fs.statSync(openInWorkflowPath).isDirectory()
      || !fs.readFileSync(openInInfoPath, 'utf8').includes('app.officekit.finder.open-in-officekit')
      || !fs.readFileSync(openInDocumentPath, 'utf8').includes('/usr/bin/open -a')) {
      throw new Error('DMG app does not contain the owned Open in OfficeKit Finder Quick Action.');
    }
    run('plutil', ['-lint', openInInfoPath, openInDocumentPath]);
    const mcpHome = fs.mkdtempSync(path.join(os.tmpdir(), 'officekit-media-mcp-home-'));
    let toolList;
    try {
      toolList = await listMediaMcpTools(mediaCliPath, { home: mcpHome, exercise: true });
    } finally {
      fs.rmSync(mcpHome, { recursive: true, force: true });
    }
    const mcpToolNames = new Set(toolList.map(tool => tool.name));
    const requiredMediaTools = [
      'officekit_media_list_operations',
      'officekit_media_prepare_files',
      'officekit_media_run_preset',
      'officekit_media_list_pipelines',
      'officekit_media_create_pipeline',
      'officekit_media_rename_pipeline',
      'officekit_media_update_pipeline',
      'officekit_media_run_pipeline',
      'officekit_media_delete_pipeline',
      'officekit_media_list_preset_zones',
      'officekit_media_create_preset_zone',
      'officekit_media_rename_preset_zone',
      'officekit_media_rebind_preset_zone',
      'officekit_media_delete_preset_zone',
      'officekit_media_list_operation_defaults',
      'officekit_media_set_operation_default',
      'officekit_media_clear_operation_defaults',
      'officekit_media_list_pipeline_triggers',
      'officekit_media_set_pipeline_trigger',
      'officekit_media_clear_pipeline_trigger',
    ];
    if (requiredMediaTools.some(name => !mcpToolNames.has(name))) {
      throw new Error('Packaged Media Toolkit MCP server did not expose the operation and saved-pipeline tools.');
    }
    if (!fs.lstatSync(applicationsPath).isSymbolicLink() || fs.readlinkSync(applicationsPath) !== '/Applications') {
      throw new Error('DMG does not contain the Applications installation link');
    }
    run(process.execPath, [path.join(root, 'scripts', 'smoke-backend-sidecar.mjs'), sidecarPath], {
      env: { ...process.env, OFFICEKIT_API_PORT: String(smokePort) },
    });
    run(process.execPath, [path.join(root, 'scripts', 'smoke-media-sidecar.mjs'), sidecarPath]);
    const cliRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'officekit-media-cli-smoke-'));
    let mp3OutputStatus = 'FFmpeg unavailable';
    const videoFfmpegOutputStatuses = [];
    const ffmpeg = hostFfmpeg();
    try {
      const settingsEnvironment = { ...process.env, HOME: path.join(cliRoot, 'settings-home') };
      const settingsSchema = JSON.parse(run(mediaCliPath, ['--settings', 'schema'], { env: settingsEnvironment }));
      if (!settingsSchema['image-optimize']?.properties?.quality || !settingsSchema['pdf-uncrop']) {
        throw new Error('Packaged CLI settings schema did not include typed media operations.');
      }
      const savedSettings = JSON.parse(run(mediaCliPath, [
        '--settings', 'set', '--operation-id', 'image-optimize',
        '--options-json', '{"quality":74,"preserveMetadata":false}',
      ], { env: settingsEnvironment }));
      const listedSettings = JSON.parse(run(mediaCliPath, ['--settings', 'get', '--operation-id', 'image-optimize'], {
        env: settingsEnvironment,
      }));
      if (savedSettings.quality !== 74 || listedSettings.quality !== 74) {
        throw new Error('Packaged CLI settings did not persist typed operation defaults.');
      }
      run(mediaCliPath, ['--settings', 'clear', '--operation-id', 'image-optimize'], { env: settingsEnvironment });
      const clearedSettings = JSON.parse(run(mediaCliPath, ['--settings', 'list'], { env: settingsEnvironment }));
      if (Object.keys(clearedSettings).length !== 0) {
        throw new Error('Packaged CLI settings did not clear the selected operation default.');
      }
      const clopStyleSchema = JSON.parse(run(mediaCliPath, ['settings', 'schema', 'image', '--json'], { env: settingsEnvironment }));
      if (!clopStyleSchema['image-optimize']?.properties?.quality || Object.keys(clopStyleSchema).some(id => !id.startsWith('image-'))) {
        throw new Error('Packaged Clop-style CLI settings schema did not filter typed image operations.');
      }
      const qualitySchema = JSON.parse(run(mediaCliPath, ['settings', 'schema', 'quality', '--json'], { env: settingsEnvironment }));
      if (!qualitySchema['image-optimize']?.properties?.quality) {
        throw new Error('Packaged Clop-style CLI settings schema did not match an option name.');
      }
      const clopStyleSettings = JSON.parse(run(mediaCliPath, [
        'settings', 'set', 'image-optimize', '{"quality":69,"preserveMetadata":false}', '--json',
      ], { env: settingsEnvironment }));
      const clopStyleGet = JSON.parse(run(mediaCliPath, ['settings', 'get', 'image-optimize', '--json'], { env: settingsEnvironment }));
      if (clopStyleSettings.quality !== 69 || clopStyleGet.quality !== 69) {
        throw new Error('Packaged Clop-style CLI settings did not share the private typed defaults store.');
      }
      const inlineInput = path.join(root, 'tests', 'fixtures', 'similar-images', 'cc0', 'dog-on-road.jpg');
      const inlineSourceHash = createHash('sha256').update(fs.readFileSync(inlineInput)).digest('hex');
      const inlineOutputDirectory = path.join(cliRoot, 'inline-output');
      const inlineResult = JSON.parse(run(mediaCliPath, [
        'pipeline', 'run', 'convert(to: webp)', inlineInput, '--output-dir', inlineOutputDirectory,
      ], { env: settingsEnvironment }));
      const inlineOutput = path.join(inlineOutputDirectory, inlineResult.results?.[0]?.output || 'missing.webp');
      if (inlineResult.state !== 'complete' || !fs.readFileSync(inlineOutput).subarray(0, 4).equals(Buffer.from('RIFF'))
        || createHash('sha256').update(fs.readFileSync(inlineInput)).digest('hex') !== inlineSourceHash) {
        throw new Error('Packaged inline pipeline did not produce a WebP copy while preserving its source.');
      }
      const losslessOutputDirectory = path.join(cliRoot, 'lossless-output');
      const losslessResult = JSON.parse(run(mediaCliPath, [
        'pipeline', 'run', 'convert(to: webp, lossless: true)', inlineInput,
        '--output-dir', losslessOutputDirectory,
      ], { env: settingsEnvironment }));
      const losslessOutput = path.join(losslessOutputDirectory, losslessResult.results?.[0]?.output || 'missing.webp');
      if (losslessResult.state !== 'complete' || losslessResult.results?.[0]?.attributes?.lossless !== true
        || !fs.readFileSync(losslessOutput).subarray(0, 4).equals(Buffer.from('RIFF'))
        || createHash('sha256').update(fs.readFileSync(inlineInput)).digest('hex') !== inlineSourceHash) {
        throw new Error('Packaged lossless WebP conversion did not create a marked copy while preserving its source.');
      }
      const watermarkOutputDirectory = path.join(cliRoot, 'watermark-output');
      const watermarkSteps = `watermark(image: "${inlineInput}", position: bottomRight, opacity: 0.8, scale: 0.15)`;
      const watermarkResult = JSON.parse(run(mediaCliPath, [
        'pipeline', 'run', watermarkSteps, inlineInput, '--output-dir', watermarkOutputDirectory,
      ], { env: settingsEnvironment }));
      const watermarkOutput = path.join(watermarkOutputDirectory, watermarkResult.results?.[0]?.output || 'missing.jpg');
      if (watermarkResult.state !== 'complete' || !fs.statSync(watermarkOutput).isFile()
        || createHash('sha256').update(fs.readFileSync(inlineInput)).digest('hex') !== inlineSourceHash) {
        throw new Error('Packaged inline watermark did not publish a separate copy while preserving its source.');
      }
      const filterInput = path.join(root, 'tests', 'fixtures', 'similar-images', 'cc0', 'dandelion.jpg');
      const filterInputHash = createHash('sha256').update(fs.readFileSync(filterInput)).digest('hex');
      const sequenceOutputDirectory = path.join(cliRoot, 'sequence-output');
      const sequenceResult = JSON.parse(run(mediaCliPath, [
        'pipeline', 'run', 'convert(to: webp)', inlineInput, filterInput,
        '--name-template', '%f-%i.{ext}', '--output-dir', sequenceOutputDirectory,
      ], { env: settingsEnvironment }));
      if (sequenceResult.state !== 'complete'
        || sequenceResult.results?.map(item => item.output).join(',') !== 'dog-on-road-1.webp,dandelion-2.webp'
        || sequenceResult.results.some(item => !fs.statSync(path.join(sequenceOutputDirectory, item.output)).isFile())
        || createHash('sha256').update(fs.readFileSync(inlineInput)).digest('hex') !== inlineSourceHash
        || createHash('sha256').update(fs.readFileSync(filterInput)).digest('hex') !== filterInputHash) {
        throw new Error('Packaged inline batch did not increment filename sequence tokens while preserving sources.');
      }
      const filteredSteps = 'if(regex: "^dog", minFileSize: 1B) -> convert(to: webp)';
      const captureOutputDirectory = path.join(cliRoot, 'capture-output');
      const captureResult = JSON.parse(run(mediaCliPath, [
        'pipeline', 'run', 'if(regex: "^(dog)-(on)-(road)") -> convert(to: webp) -> fork() -> stripExif',
        inlineInput, '--name-template', '$1-$3-%i.{ext}', '--output-dir', captureOutputDirectory,
      ], { env: settingsEnvironment }));
      if (captureResult.state !== 'complete' || captureResult.results?.length !== 2
        || captureResult.results[0].output !== 'dog-on-road-fork-1.webp'
        || captureResult.results[1].output !== 'dog-road-1.webp'
        || captureResult.results.some(item => !fs.readFileSync(path.join(captureOutputDirectory, item.output)).subarray(0, 4).equals(Buffer.from('RIFF')))
        || createHash('sha256').update(fs.readFileSync(inlineInput)).digest('hex') !== inlineSourceHash) {
        throw new Error('Packaged filename captures did not publish safe fork/final copies while preserving the source.');
      }
      const filteredResult = JSON.parse(run(mediaCliPath, [
        'pipeline', 'run', filteredSteps, inlineInput, filterInput, '--output-dir', path.join(cliRoot, 'filtered-output'),
      ], { env: settingsEnvironment }));
      if (filteredResult.state !== 'complete' || filteredResult.results?.length !== 1
        || filteredResult.results[0].input !== path.basename(inlineInput)
        || filteredResult.skipped?.[0]?.input !== path.basename(filterInput)
        || createHash('sha256').update(fs.readFileSync(inlineInput)).digest('hex') !== inlineSourceHash
        || createHash('sha256').update(fs.readFileSync(filterInput)).digest('hex') !== filterInputHash) {
        throw new Error('Packaged inline filename filter did not select and skip files safely.');
      }
      const missingDpiResult = JSON.parse(run(mediaCliPath, [
        'pipeline', 'run', 'if(dpiGreaterThan: 1) -> convert(to: webp)', inlineInput, filterInput,
        '--output-dir', path.join(cliRoot, 'missing-dpi-output'),
      ], { env: settingsEnvironment }));
      if (missingDpiResult.state !== 'complete' || missingDpiResult.results?.length !== 0
        || missingDpiResult.skipped?.length !== 2
        || createHash('sha256').update(fs.readFileSync(inlineInput)).digest('hex') !== inlineSourceHash
        || createHash('sha256').update(fs.readFileSync(filterInput)).digest('hex') !== filterInputHash) {
        throw new Error('Packaged image-DPI filter did not fail closed on files without explicit DPI metadata.');
      }
      const forkOutputDirectory = path.join(cliRoot, 'fork-output');
      const forkResult = JSON.parse(run(mediaCliPath, [
        'pipeline', 'run', 'convert(to: webp) -> fork() -> optimise(compression: 70)', inlineInput,
        '--output-dir', forkOutputDirectory,
      ], { env: settingsEnvironment }));
      const forkOutputs = (forkResult.results || []).map(item => path.join(forkOutputDirectory, item.output));
      if (forkResult.state !== 'complete' || forkResult.results?.length !== 2
        || forkResult.results[0]?.output !== 'dog-on-road-fork-1.webp'
        || forkResult.results[1]?.output !== 'dog-on-road-optimized.webp'
        || forkOutputs.some(output => !fs.statSync(output).isFile()
          || !fs.readFileSync(output).subarray(0, 4).equals(Buffer.from('RIFF')))
        || createHash('sha256').update(fs.readFileSync(inlineInput)).digest('hex') !== inlineSourceHash) {
        throw new Error('Packaged inline fork did not publish its intermediate and final copies while preserving the source.');
      }
      const inlinePipeline = JSON.parse(run(mediaCliPath, [
        'pipeline', 'add', 'Smoke inline pipeline', 'convert(to: webp)', '--file-type', 'image',
      ], { env: settingsEnvironment }));
      const inlineSavedResult = JSON.parse(run(mediaCliPath, [
        'pipeline', 'run', 'Smoke inline pipeline', inlineInput, '--output-dir', path.join(cliRoot, 'saved-inline-output'),
      ], { env: settingsEnvironment }));
      if (inlinePipeline.state !== 'paused' || inlinePipeline.operations?.[0]?.operationId !== 'image-convert'
        || inlineSavedResult.state !== 'complete' || typeof inlineSavedResult.results?.[0]?.output !== 'string'
        || !inlineSavedResult.results[0].output.endsWith('.webp')
        || createHash('sha256').update(fs.readFileSync(inlineInput)).digest('hex') !== inlineSourceHash) {
        throw new Error('Packaged Clop-style pipeline add did not save and run typed steps safely.');
      }
      const inlineCropResult = JSON.parse(run(mediaCliPath, [
        'pipeline', 'run', 'crop(aspectRatio: 1:1) -> convert(to: webp)', inlineInput,
        '--output-dir', path.join(cliRoot, 'inline-crop-output'),
      ], { env: settingsEnvironment }));
      const inlineCropPath = path.join(cliRoot, 'inline-crop-output', inlineCropResult.results?.[0]?.output || 'missing.webp');
      if (inlineCropResult.state !== 'complete' || !fs.readFileSync(inlineCropPath).subarray(0, 4).equals(Buffer.from('RIFF'))
        || createHash('sha256').update(fs.readFileSync(inlineInput)).digest('hex') !== inlineSourceHash) {
        throw new Error('Packaged inline aspect-ratio crop did not create a source-preserving WebP copy.');
      }
      const smartCropResult = JSON.parse(run(mediaCliPath, [
        'pipeline', 'run', 'crop(aspectRatio: 1:1, smartCrop: true)', inlineInput,
        '--output-dir', path.join(cliRoot, 'inline-smart-crop-output'),
      ], { env: settingsEnvironment }));
      const smartCropPath = path.join(cliRoot, 'inline-smart-crop-output', smartCropResult.results?.[0]?.output || 'missing.jpg');
      const smartCropInfo = run('sips', ['-g', 'pixelWidth', '-g', 'pixelHeight', smartCropPath]);
      if (smartCropResult.state !== 'complete' || !/pixelWidth: 384/.test(smartCropInfo) || !/pixelHeight: 384/.test(smartCropInfo)
        || createHash('sha256').update(fs.readFileSync(inlineInput)).digest('hex') !== inlineSourceHash) {
        throw new Error('Packaged Vision smart crop did not create a source-preserving image copy.');
      }
      const inlineDownscaleResult = JSON.parse(run(mediaCliPath, [
        'pipeline', 'run', 'downscale(factor: 0.5) -> convert(to: webp)', inlineInput,
        '--output-dir', path.join(cliRoot, 'inline-downscale-output'),
      ], { env: settingsEnvironment }));
      const typedCropRecipe = path.join(cliRoot, 'typed-smart-crop.json');
      fs.writeFileSync(typedCropRecipe, JSON.stringify([
        { operationId: 'image-resize', options: { maxWidth: 200, maxHeight: 200 } },
        { operationId: 'image-crop', options: { aspectRatio: '1:1', smartCrop: true } },
      ]));
      const typedCropPipeline = JSON.parse(run(mediaCliPath, [
        'pipeline', 'add', 'Smoke typed smart crop', '--media', 'image', '--recipe', typedCropRecipe,
      ], { env: settingsEnvironment }));
      const typedCropDirectory = path.join(cliRoot, 'typed-smart-crop-output');
      const typedCropResult = JSON.parse(run(mediaCliPath, [
        'pipeline', 'run', typedCropPipeline.id, inlineInput, '--output-dir', typedCropDirectory,
      ], { env: settingsEnvironment }));
      const typedCropOutput = path.join(typedCropDirectory, typedCropResult.results?.[0]?.output || 'missing.jpg');
      const typedCropInfo = imageDimensions(typedCropOutput);
      if (typedCropPipeline.state !== 'paused' || typedCropResult.state !== 'complete'
        || typedCropResult.results?.[0]?.attributes?.smart_crop !== true
        || typedCropInfo.width !== 150 || typedCropInfo.height !== 150
        || createHash('sha256').update(fs.readFileSync(inlineInput)).digest('hex') !== inlineSourceHash) {
        throw new Error('Packaged saved typed smart crop did not use its resized image or preserve the source.');
      }
      const inlineDownscalePath = path.join(cliRoot, 'inline-downscale-output', inlineDownscaleResult.results?.[0]?.output || 'missing.webp');
      if (inlineDownscaleResult.state !== 'complete' || !fs.readFileSync(inlineDownscalePath).subarray(0, 4).equals(Buffer.from('RIFF'))
        || createHash('sha256').update(fs.readFileSync(inlineInput)).digest('hex') !== inlineSourceHash) {
        throw new Error('Packaged inline factor downscale did not create a source-preserving WebP copy.');
      }
      const targetSizeResult = JSON.parse(run(mediaCliPath, [
        'pipeline', 'run', 'targetSize(size: 10MB)', inlineInput, '--output-dir', path.join(cliRoot, 'target-size-output'),
      ], { env: settingsEnvironment }));
      const targetSizePath = path.join(cliRoot, 'target-size-output', targetSizeResult.results?.[0]?.output || 'missing.webp');
      if (targetSizeResult.state !== 'complete' || fs.statSync(targetSizePath).size > 10_000_000
        || createHash('sha256').update(fs.readFileSync(inlineInput)).digest('hex') !== inlineSourceHash) {
        throw new Error('Packaged inline targetSize did not publish a size-bounded copy while preserving its source.');
      }
      const recipePath = path.join(cliRoot, 'recipe.json');
      const outputDirectory = path.join(cliRoot, 'outputs');
      fs.writeFileSync(recipePath, JSON.stringify([{ operationId: 'image-optimize', options: { quality: 82, preserveMetadata: false } }]));
      const cliPipeline = JSON.parse(run(mediaCliPath, [
        'pipeline', 'add', 'Smoke pipeline', '--media', 'image', '--recipe', recipePath,
      ], { env: settingsEnvironment }));
      const cliReplacementPipeline = JSON.parse(run(mediaCliPath, [
        'pipeline', 'add', 'Smoke pipeline replacement', '--media', 'image', '--recipe', recipePath,
      ], { env: settingsEnvironment }));
      const cliPresetZone = JSON.parse(run(mediaCliPath, [
        'pipeline', 'preset', 'add', 'Smoke preset', 'Smoke pipeline',
      ], { env: settingsEnvironment }));
      const cliPresetBindings = JSON.parse(run(mediaCliPath, ['pipeline', 'preset', 'list'], { env: settingsEnvironment }));
      if (cliPresetZone.enabled !== false || cliPresetBindings.length !== 1
        || cliPresetBindings[0].id !== cliPresetZone.id || 'enabled' in cliPresetBindings[0]) {
        throw new Error('Packaged CLI preset-zone creation did not remain disabled and omit unobservable session state.');
      }
      const cliPresetRebound = JSON.parse(run(mediaCliPath, [
        'pipeline', 'preset', 'rebind', cliPresetZone.id, 'Smoke pipeline replacement',
      ], { env: settingsEnvironment }));
      const cliPresetRenamed = JSON.parse(run(mediaCliPath, [
        'pipeline', 'preset', 'rename', cliPresetZone.id, 'Smoke preset renamed',
      ], { env: settingsEnvironment }));
      const cliPresetRemoved = JSON.parse(run(mediaCliPath, [
        'pipeline', 'preset', 'remove', 'Smoke preset renamed',
      ], { env: settingsEnvironment }));
      if (cliPresetRebound.pipelineId !== cliReplacementPipeline.id || cliPresetRenamed.id !== cliPresetZone.id
        || cliPresetRemoved.state !== 'deleted'
        || JSON.parse(run(mediaCliPath, ['pipeline', 'preset', 'list'], { env: settingsEnvironment })).length !== 0) {
        throw new Error('Packaged CLI preset-zone rename, rebind, or removal failed.');
      }
      if (cliPipeline.state !== 'paused') throw new Error('Packaged CLI preset source pipeline did not remain paused.');
      const cli = run(mediaCliPath, ['--recipe', recipePath, '--output-dir', outputDirectory, path.join(root, 'tests', 'fixtures', 'similar-images', 'cc0', 'dog-on-road.jpg')]);
      const result = JSON.parse(cli);
      if (result.state !== 'complete' || result.results?.length !== 1) throw new Error('Packaged Media Toolkit CLI did not return one successful result.');
      if (!fs.statSync(path.join(outputDirectory, result.results[0].output)).isFile()) throw new Error('Packaged Media Toolkit CLI did not publish its prepared copy.');
      const collision = spawnSync(mediaCliPath, ['--recipe', recipePath, '--output-dir', outputDirectory, path.join(root, 'tests', 'fixtures', 'similar-images', 'cc0', 'dog-on-road.jpg')], { cwd: root, encoding: 'utf8' });
      if (collision.status !== 2 || !collision.stderr.includes('File exists')) throw new Error('Packaged Media Toolkit CLI did not refuse to overwrite an existing output.');
      const presetOutputDirectory = path.join(cliRoot, 'preset-outputs');
      for (const expectedName of ['dog-on-road-optimized.jpg', 'dog-on-road-optimized (2).jpg']) {
        const preset = run(mediaCliPath, ['--preset', 'optimize-image', '--collision-policy', 'suffix', '--output-dir', presetOutputDirectory, path.join(root, 'tests', 'fixtures', 'similar-images', 'cc0', 'dog-on-road.jpg')]);
        const presetResult = JSON.parse(preset);
        if (presetResult.state !== 'complete' || presetResult.results?.[0]?.output !== expectedName) {
          throw new Error(`Packaged image preset did not publish ${expectedName}.`);
        }
      }
      const webpInput = path.join(root, 'tests', 'fixtures', 'similar-images', 'cc0', 'dog-on-road.jpg');
      const webpSourceHash = createHash('sha256').update(fs.readFileSync(webpInput)).digest('hex');
      const webpOutputDirectory = path.join(cliRoot, 'webp-preset-outputs');
      const webpPreset = JSON.parse(run(mediaCliPath, ['--preset', 'to-webp', '--output-dir', webpOutputDirectory, webpInput]));
      const webpArtifact = webpPreset.results?.[0]?.output;
      const webpBytes = webpArtifact ? fs.readFileSync(path.join(webpOutputDirectory, webpArtifact)) : Buffer.alloc(0);
      if (webpPreset.state !== 'complete' || webpArtifact !== 'dog-on-road-optimized.webp'
        || webpBytes.subarray(0, 4).toString('ascii') !== 'RIFF' || webpBytes.subarray(8, 12).toString('ascii') !== 'WEBP'
        || createHash('sha256').update(fs.readFileSync(webpInput)).digest('hex') !== webpSourceHash) {
        throw new Error('Packaged to-webp preset did not create a valid WebP copy while preserving its source.');
      }
      const imageCompressionSourceHash = createHash('sha256').update(fs.readFileSync(webpInput)).digest('hex');
      const adaptiveOutputDirectory = path.join(cliRoot, 'adaptive-image-output');
      const adaptiveQualityResult = JSON.parse(run(mediaCliPath, [
        'optimise', '--compression', 'adaptive', '--output-dir', adaptiveOutputDirectory, webpInput,
      ]));
      const adaptiveFormatDirectory = path.join(cliRoot, 'adaptive-image-format-output');
      const adaptiveFormatResult = JSON.parse(run(mediaCliPath, [
        'optimise', '--adaptive-optimisation', '--output-dir', adaptiveFormatDirectory, webpInput,
      ]));
      const adaptiveArtifact = adaptiveFormatResult.results?.[0]?.output;
      const adaptiveBytes = adaptiveArtifact ? fs.readFileSync(path.join(adaptiveFormatDirectory, adaptiveArtifact)) : Buffer.alloc(0);
      const adaptiveFormat = adaptiveFormatResult.results?.[0]?.attributes?.selected_format;
      const adaptiveSignatureValid = adaptiveFormat === 'jpeg'
        ? adaptiveBytes.subarray(0, 3).equals(Buffer.from([0xff, 0xd8, 0xff]))
        : adaptiveFormat === 'png' && adaptiveBytes.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]));
      const numericImageCompressionDirectory = path.join(cliRoot, 'image-compression-output');
      const numericImageCompression = JSON.parse(run(mediaCliPath, [
        'optimise', '--compression', '55', '--output-dir', numericImageCompressionDirectory, webpInput,
      ]));
      if (adaptiveQualityResult.state !== 'complete' || adaptiveQualityResult.results?.[0]?.attributes?.compression !== 'adaptive'
        || adaptiveFormatResult.state !== 'complete' || !['jpg', 'png'].includes(path.extname(adaptiveArtifact ?? '').slice(1))
        || !adaptiveSignatureValid || adaptiveFormatResult.results?.[0]?.attributes?.adaptive !== true
        || numericImageCompression.state !== 'complete'
        || numericImageCompression.results?.[0]?.attributes?.compression !== 55
        || createHash('sha256').update(fs.readFileSync(webpInput)).digest('hex') !== imageCompressionSourceHash) {
        throw new Error('Packaged image compression controls did not create valid separate copies while preserving their source.');
      }
      const verbOutputDirectory = path.join(cliRoot, 'convert-verb-outputs');
      const verbConversion = JSON.parse(run(mediaCliPath, [
        'convert', '--operation-id', 'image-convert', '--options-json', '{"targetFormat":"webp","quality":75}',
        '--output-dir', verbOutputDirectory, webpInput,
      ]));
      const verbArtifact = verbConversion.results?.[0]?.output;
      const verbBytes = verbArtifact ? fs.readFileSync(path.join(verbOutputDirectory, verbArtifact)) : Buffer.alloc(0);
      if (verbConversion.state !== 'complete' || verbArtifact !== 'dog-on-road-optimized.webp'
        || verbBytes.subarray(0, 4).toString('ascii') !== 'RIFF' || verbBytes.subarray(8, 12).toString('ascii') !== 'WEBP'
        || createHash('sha256').update(fs.readFileSync(webpInput)).digest('hex') !== webpSourceHash) {
        throw new Error('Packaged typed convert verb did not create a valid WebP copy while preserving its source.');
      }
      const downscaleInput = path.join(root, 'tests', 'fixtures', 'similar-images', 'cc0', 'dog-on-road.jpg');
      const downscaleSourceHash = createHash('sha256').update(fs.readFileSync(downscaleInput)).digest('hex');
      const downscaleInputDimensions = imageDimensions(downscaleInput);
      const downscaleOutputDirectory = path.join(cliRoot, 'downscale-outputs');
      const downscalePreset = JSON.parse(run(mediaCliPath, [
        '--preset', 'downscale-image', '--factor', '0.5', '--output-dir', downscaleOutputDirectory, downscaleInput,
      ]));
      const downscaleArtifact = downscalePreset.results?.[0]?.output;
      const downscaleArtifactPath = downscaleArtifact ? path.join(downscaleOutputDirectory, downscaleArtifact) : '';
      const downscaleOutputDimensions = downscaleArtifact ? imageDimensions(downscaleArtifactPath) : null;
      if (downscalePreset.state !== 'complete' || !downscaleOutputDimensions
        || downscaleOutputDimensions.width >= downscaleInputDimensions.width
        || downscaleOutputDimensions.height >= downscaleInputDimensions.height
        || createHash('sha256').update(fs.readFileSync(downscaleInput)).digest('hex') !== downscaleSourceHash) {
        throw new Error('Packaged downscale-image preset did not create a smaller output copy while preserving its source.');
      }
      const identityOutputDirectory = path.join(cliRoot, 'downscale-identity-outputs');
      const identityPreset = JSON.parse(run(mediaCliPath, [
        '--preset', 'downscale-image', '--factor', '1', '--output-dir', identityOutputDirectory, downscaleInput,
      ]));
      const identityArtifact = identityPreset.results?.[0]?.output;
      if (identityPreset.state !== 'complete' || !identityArtifact
        || !fs.readFileSync(path.join(identityOutputDirectory, identityArtifact)).equals(fs.readFileSync(downscaleInput))
        || createHash('sha256').update(fs.readFileSync(downscaleInput)).digest('hex') !== downscaleSourceHash) {
        throw new Error('Packaged downscale-image factor 1 did not create a byte-identical copy while preserving its source.');
      }
      const audioDownscaleInput = path.join(root, 'tests', 'fixtures', 'media', 'audio-tone.mp3');
      const audioDownscaleHash = createHash('sha256').update(fs.readFileSync(audioDownscaleInput)).digest('hex');
      const audioDownscaleOutputDirectory = path.join(cliRoot, 'audio-downscale-outputs');
      const audioDownscale = JSON.parse(run(mediaCliPath, [
        'downscale', '--factor', '0.5', '--output-dir', audioDownscaleOutputDirectory, audioDownscaleInput,
      ]));
      const audioDownscaleArtifact = audioDownscale.results?.[0]?.output;
      const audioDownscalePath = audioDownscaleArtifact ? path.join(audioDownscaleOutputDirectory, audioDownscaleArtifact) : '';
      if (audioDownscale.state !== 'complete' || !audioDownscaleArtifact?.endsWith('.m4a')
        || createHash('sha256').update(fs.readFileSync(audioDownscaleInput)).digest('hex') !== audioDownscaleHash) {
        throw new Error('Packaged audio downscale did not create a separate M4A while preserving its source.');
      }
      run('swift', [path.join(root, 'scripts/media-smoke-verify.swift'), 'audio', audioDownscalePath]);
      const audioDownscaleIdentityDirectory = path.join(cliRoot, 'audio-downscale-identity-outputs');
      const audioDownscaleIdentity = JSON.parse(run(mediaCliPath, [
        'downscale', '--factor', '1', '--output-dir', audioDownscaleIdentityDirectory, audioDownscaleInput,
      ]));
      const audioDownscaleIdentityArtifact = audioDownscaleIdentity.results?.[0]?.output;
      if (audioDownscaleIdentity.state !== 'complete' || !audioDownscaleIdentityArtifact
        || !fs.readFileSync(path.join(audioDownscaleIdentityDirectory, audioDownscaleIdentityArtifact)).equals(fs.readFileSync(audioDownscaleInput))
        || createHash('sha256').update(fs.readFileSync(audioDownscaleInput)).digest('hex') !== audioDownscaleHash) {
        throw new Error('Packaged audio downscale factor 1 did not create a byte-identical copy while preserving its source.');
      }
      const videoOnlyInput = path.join(cliRoot, 'video-downscale-only.mov');
      const videoGenerate = spawnSync('swift', [path.join(root, 'scripts/media-smoke-video.swift'), videoOnlyInput], {
        cwd: root, encoding: 'utf8', timeout: 90_000,
      });
      if (videoGenerate.error || videoGenerate.status !== 0) {
        throw new Error(`Could not generate the local video downscale fixture: ${videoGenerate.stderr || videoGenerate.error?.message || videoGenerate.stdout}`);
      }
      const videoCropOutputDirectory = path.join(cliRoot, 'video-aspect-crop-outputs');
      const videoCropHash = createHash('sha256').update(fs.readFileSync(videoOnlyInput)).digest('hex');
      const videoCropRun = JSON.parse(run(mediaCliPath, [
        'crop', '--aspect-ratio', '1:1', '--output-dir', videoCropOutputDirectory, videoOnlyInput,
      ]));
      const videoCropArtifact = videoCropRun.results?.[0]?.output;
      const videoCropPath = videoCropArtifact ? path.join(videoCropOutputDirectory, videoCropArtifact) : '';
      if (videoCropRun.state !== 'complete' || !videoCropArtifact
        || createHash('sha256').update(fs.readFileSync(videoOnlyInput)).digest('hex') !== videoCropHash) {
        throw new Error('Packaged CLI aspect-ratio video crop did not publish a new copy while preserving its source.');
      }
      run('swift', [path.join(root, 'scripts/media-smoke-verify.swift'), 'video-crop', videoCropPath, '120', '120']);
      const videoDownscaleInput = path.join(cliRoot, 'video-downscale-input.mov');
      const videoMux = spawnSync('swift', [path.join(root, 'scripts/media-smoke-mux.swift'), videoOnlyInput,
        path.join(root, 'tests/fixtures/media/audio-tone.mp3'), videoDownscaleInput], {
        cwd: root, encoding: 'utf8', timeout: 90_000,
      });
      if (videoMux.error || videoMux.status !== 0) {
        throw new Error(`Could not create the audio/video downscale fixture: ${videoMux.stderr || videoMux.error?.message || videoMux.stdout}`);
      }
      const videoDownscaleHash = createHash('sha256').update(fs.readFileSync(videoDownscaleInput)).digest('hex');
      const videoSmartRecipe = path.join(cliRoot, 'typed-video-smart-crop.json');
      fs.writeFileSync(videoSmartRecipe, JSON.stringify([
        { operationId: 'video-crop', options: { aspectRatio: '1:1', smartCrop: true } },
      ]));
      const videoSmartDirectory = path.join(cliRoot, 'typed-video-smart-crop-output');
      const videoSmartResult = JSON.parse(run(mediaCliPath, [
        '--recipe', videoSmartRecipe, '--output-dir', videoSmartDirectory, videoDownscaleInput,
      ]));
      const videoSmartOutput = path.join(videoSmartDirectory, videoSmartResult.results?.[0]?.output || 'missing.mov');
      if (videoSmartResult.state !== 'complete' || videoSmartResult.results?.[0]?.attributes?.smart_crop !== true
        || createHash('sha256').update(fs.readFileSync(videoDownscaleInput)).digest('hex') !== videoDownscaleHash) {
        throw new Error('Packaged typed video smart crop did not preserve the source.');
      }
      run('swift', [path.join(root, 'scripts/media-smoke-verify.swift'), 'video-crop', videoSmartOutput, '120', '120']);
      run('swift', [path.join(root, 'scripts/media-smoke-verify.swift'), 'video-resize', videoSmartOutput, '120', '120']);
      const videoCapFpsOutputDirectory = path.join(cliRoot, 'video-cap-fps-outputs');
      const videoCapFpsResult = JSON.parse(run(mediaCliPath, [
        'pipeline', 'run', 'capFps(fps: 15)', videoDownscaleInput, '--output-dir', videoCapFpsOutputDirectory,
      ]));
      const videoCapFpsArtifact = videoCapFpsResult.results?.[0]?.output;
      const videoCapFpsPath = videoCapFpsArtifact ? path.join(videoCapFpsOutputDirectory, videoCapFpsArtifact) : '';
      if (videoCapFpsResult.state !== 'complete' || !videoCapFpsArtifact
        || createHash('sha256').update(fs.readFileSync(videoDownscaleInput)).digest('hex') !== videoDownscaleHash) {
        throw new Error('Packaged capFps pipeline did not create a separate copy while preserving its source.');
      }
      run('swift', [path.join(root, 'scripts/media-smoke-verify.swift'), 'video-fps', videoDownscaleInput, videoCapFpsPath, '15']);
      const videoMetadataOutputDirectory = path.join(cliRoot, 'video-metadata-outputs');
      const videoMetadataResult = JSON.parse(run(mediaCliPath, [
        'strip-exif', '--output-dir', videoMetadataOutputDirectory, videoDownscaleInput,
      ]));
      const videoMetadataArtifact = videoMetadataResult.results?.[0]?.output;
      if (videoMetadataResult.state !== 'complete' || !videoMetadataArtifact
        || createHash('sha256').update(fs.readFileSync(videoDownscaleInput)).digest('hex') !== videoDownscaleHash) {
        throw new Error('Packaged video strip-exif did not create a separate copy while preserving its source.');
      }
      run('swift', [path.join(root, 'scripts/media-smoke-verify.swift'), 'video-strip-metadata', videoDownscaleInput,
        path.join(videoMetadataOutputDirectory, videoMetadataArtifact)]);
      const videoDownscaleOutputDirectory = path.join(cliRoot, 'video-downscale-outputs');
      const videoDownscale = JSON.parse(run(mediaCliPath, [
        'downscale', '--factor', '0.5', '--output-dir', videoDownscaleOutputDirectory, videoDownscaleInput,
      ]));
      const videoDownscaleArtifact = videoDownscale.results?.[0]?.output;
      const videoDownscalePath = videoDownscaleArtifact ? path.join(videoDownscaleOutputDirectory, videoDownscaleArtifact) : '';
      if (videoDownscale.state !== 'complete' || videoDownscaleArtifact !== 'video-downscale-input-optimized.mov'
        || createHash('sha256').update(fs.readFileSync(videoDownscaleInput)).digest('hex') !== videoDownscaleHash) {
        throw new Error('Packaged video downscale did not create a separate output while preserving its source.');
      }
      run('swift', [path.join(root, 'scripts/media-smoke-verify.swift'), 'video-resize', videoDownscalePath, '80', '60']);
      const videoDownscaleIdentityDirectory = path.join(cliRoot, 'video-downscale-identity-outputs');
      const videoDownscaleIdentity = JSON.parse(run(mediaCliPath, [
        'downscale', '--factor', '1', '--output-dir', videoDownscaleIdentityDirectory, videoDownscaleInput,
      ]));
      const videoDownscaleIdentityArtifact = videoDownscaleIdentity.results?.[0]?.output;
      if (videoDownscaleIdentity.state !== 'complete' || !videoDownscaleIdentityArtifact
        || !fs.readFileSync(path.join(videoDownscaleIdentityDirectory, videoDownscaleIdentityArtifact)).equals(fs.readFileSync(videoDownscaleInput))
        || createHash('sha256').update(fs.readFileSync(videoDownscaleInput)).digest('hex') !== videoDownscaleHash) {
        throw new Error('Packaged video downscale factor 1 did not create a byte-identical copy while preserving its source.');
      }
      if (process.platform === 'darwin') {
        const heicInput = path.join(cliRoot, 'still-medium.heic');
        const heicFixture = path.join(root, 'tests', 'fixtures', 'similar-images', 'cc0', 'heic', 'still-medium.heic');
        fs.copyFileSync(heicFixture, heicInput);
        const heicSourceHash = createHash('sha256').update(fs.readFileSync(heicInput)).digest('hex');
        const heicOutputDirectory = path.join(cliRoot, 'heic-webp');
        const heicPreset = JSON.parse(run(mediaCliPath, [
          '--preset', 'to-webp', '--output-dir', heicOutputDirectory, heicInput,
        ]));
        const heicArtifact = heicPreset.results?.[0]?.output;
        const heicBytes = heicArtifact ? fs.readFileSync(path.join(heicOutputDirectory, heicArtifact)) : Buffer.alloc(0);
        if (heicPreset.state !== 'complete' || !heicArtifact?.endsWith('.webp')
          || heicBytes.subarray(0, 4).toString('ascii') !== 'RIFF'
          || heicBytes.subarray(8, 12).toString('ascii') !== 'WEBP'
          || createHash('sha256').update(fs.readFileSync(heicInput)).digest('hex') !== heicSourceHash) {
          throw new Error('Packaged HEIC conversion did not create a WebP copy while preserving the source.');
        }
      }
      const screenshotInput = path.join(cliRoot, 'Screenshot 2025-06-15 at 10.00.00.jpg');
      fs.copyFileSync(path.join(root, 'tests', 'fixtures', 'similar-images', 'cc0', 'dog-on-road.jpg'), screenshotInput);
      const screenshotTime = new Date(2025, 5, 15, 10, 0, 0);
      fs.utimesSync(screenshotInput, screenshotTime, screenshotTime);
      const screenshotHash = createHash('sha256').update(fs.readFileSync(screenshotInput)).digest('hex');
      const screenshotOutputDirectory = path.join(cliRoot, 'sorted-screenshots');
      const screenshotPreset = JSON.parse(run(mediaCliPath, [
        '--preset', 'sort-screenshots', '--output-dir', screenshotOutputDirectory, screenshotInput,
      ]));
      const sortedScreenshot = screenshotPreset.results?.[0]?.output;
      if (screenshotPreset.state !== 'complete' || sortedScreenshot !== '25/06/Screenshot 2025-06-15 at 10.00.00.jpg'
        || !fs.statSync(path.join(screenshotOutputDirectory, sortedScreenshot)).isFile()
        || createHash('sha256').update(fs.readFileSync(screenshotInput)).digest('hex') !== screenshotHash) {
        throw new Error('Packaged screenshot sorter did not create a dated copy while preserving its source.');
      }
      const deviceListing = JSON.parse(run(mediaCliPath, ['--preset', 'crop-pdf', '--list-devices']));
      const paperListing = JSON.parse(run(mediaCliPath, ['--preset', 'crop-pdf', '--list-paper-sizes']));
      if (deviceListing.devices?.length !== 101 || !deviceListing.devices.includes('iPad Air')
        || paperListing.paperSizes?.length !== 104 || !paperListing.paperSizes.includes('Letter')) {
        throw new Error('Packaged PDF crop CLI did not load its device and paper-size catalogs.');
      }
      const pdfInputRoot = path.join(cliRoot, 'pdf-incoming');
      const pdfNestedRoot = path.join(pdfInputRoot, 'nested');
      const pdfOutputDirectory = path.join(pdfInputRoot, 'prepared');
      fs.mkdirSync(pdfNestedRoot, { recursive: true });
      fs.mkdirSync(pdfOutputDirectory, { recursive: true });
      const pdfFixture = path.join(root, 'tests', 'fixtures', 'pdf-page-management-source.pdf');
      const pdfFixtureHash = createHash('sha256').update(fs.readFileSync(pdfFixture)).digest('hex');
      const scannedPdfDirectory = path.join(cliRoot, 'dpi-scan-fixture');
      const scannedPdf = JSON.parse(run(mediaCliPath, [
        'pipeline', 'run', 'optimise(dpi: 72)', pdfFixture, '--output-dir', scannedPdfDirectory,
      ]));
      if (scannedPdf.state !== 'complete' || scannedPdf.results?.length !== 1) {
        throw new Error('Packaged visual PDF operation did not create a DPI-filter fixture.');
      }
      const scannedPdfInput = path.join(scannedPdfDirectory, scannedPdf.results[0].output);
      const scannedPdfHash = createHash('sha256').update(fs.readFileSync(scannedPdfInput)).digest('hex');
      const pdfDpiDirectory = path.join(cliRoot, 'dpi-filter-output');
      const pdfDpiResult = JSON.parse(run(mediaCliPath, [
        'pipeline', 'run', 'if(dpiGreaterThan: 60, dpiLowerThan: 100) -> optimise',
        scannedPdfInput, pdfFixture, '--output-dir', pdfDpiDirectory,
      ]));
      if (pdfDpiResult.state !== 'complete' || pdfDpiResult.results?.length !== 1
        || pdfDpiResult.results[0].input !== path.basename(scannedPdfInput)
        || pdfDpiResult.skipped?.length !== 1 || pdfDpiResult.skipped[0].input !== path.basename(pdfFixture)
        || !fs.statSync(path.join(pdfDpiDirectory, pdfDpiResult.results[0].output)).isFile()
        || createHash('sha256').update(fs.readFileSync(scannedPdfInput)).digest('hex') !== scannedPdfHash
        || createHash('sha256').update(fs.readFileSync(pdfFixture)).digest('hex') !== pdfFixtureHash) {
        throw new Error('Packaged PDF DPI filter did not select scanned images and skip vector-only content safely.');
      }
      const firstPdfInput = path.join(pdfInputRoot, 'first.pdf');
      const nestedPdfInput = path.join(pdfNestedRoot, 'second.pdf');
      const previousPdf = path.join(pdfOutputDirectory, 'previous.pdf');
      for (const target of [firstPdfInput, nestedPdfInput, previousPdf]) fs.copyFileSync(pdfFixture, target);
      const pdfInputHashes = [firstPdfInput, nestedPdfInput].map(file => createHash('sha256').update(fs.readFileSync(file)).digest('hex'));
      const previousPdfHash = createHash('sha256').update(fs.readFileSync(previousPdf)).digest('hex');
      const pdfCrop = JSON.parse(run(mediaCliPath, [
        '--preset', 'crop-pdf', '--for-device', 'iPad Air', '--extend', '--recursive',
        '--output-dir', pdfOutputDirectory, pdfInputRoot,
      ]));
      if (pdfCrop.state !== 'complete' || pdfCrop.results?.length !== 2
        || pdfCrop.results.map(item => item.input).join(',') !== 'first.pdf,second.pdf'
        || pdfCrop.results.some(item => !fs.statSync(path.join(pdfOutputDirectory, item.output)).isFile())
        || [firstPdfInput, nestedPdfInput].some((file, index) => createHash('sha256').update(fs.readFileSync(file)).digest('hex') !== pdfInputHashes[index])
        || createHash('sha256').update(fs.readFileSync(previousPdf)).digest('hex') !== previousPdfHash) {
        throw new Error('Packaged recursive PDF crop did not preserve inputs and exclude its output tree.');
      }
      const uncropInput = path.join(root, 'tests', 'fixtures', 'pdf-page-management-source.pdf');
      const uncropSourceHash = createHash('sha256').update(fs.readFileSync(uncropInput)).digest('hex');
      const uncropOutputDirectory = path.join(cliRoot, 'uncropped-pdfs');
      const uncropResult = JSON.parse(run(mediaCliPath, [
        '--preset', 'uncrop-pdf', '--output-dir', uncropOutputDirectory, uncropInput,
      ]));
      const uncropArtifact = uncropResult.results?.[0]?.output;
      if (uncropResult.state !== 'complete' || uncropArtifact !== 'pdf-page-management-source-uncropped.pdf'
        || fs.readFileSync(path.join(uncropOutputDirectory, uncropArtifact)).subarray(0, 5).toString('ascii') !== '%PDF-'
        || createHash('sha256').update(fs.readFileSync(uncropInput)).digest('hex') !== uncropSourceHash) {
        throw new Error('Packaged uncrop-pdf preset did not publish a valid new PDF while preserving its source.');
      }
      const pageExportInput = path.join(root, 'tests', 'fixtures', 'pdf-page-management-source.pdf');
      const pageExportHash = createHash('sha256').update(fs.readFileSync(pageExportInput)).digest('hex');
      const pageExportDirectory = path.join(cliRoot, 'pdf-page-images');
      const pageExport = JSON.parse(run(mediaCliPath, [
        'pipeline', 'run', 'extractPagesAsImages(format: png, quality: high, dpi: 120)',
        pageExportInput, '--output-dir', pageExportDirectory,
      ]));
      const pageExportArtifact = pageExport.results?.[0]?.output;
      const pageExportPath = pageExportArtifact ? path.join(pageExportDirectory, pageExportArtifact) : '';
      const pageNames = pageExportPath && fs.existsSync(pageExportPath)
        ? run('/usr/bin/unzip', ['-Z1', pageExportPath]).trim().split('\n') : [];
      if (pageExport.state !== 'complete' || !pageExportArtifact?.endsWith('.zip')
        || pageNames.length < 2 || pageNames.some((name, index) => name !== `page-${String(index + 1).padStart(3, '0')}.png`)
        || createHash('sha256').update(fs.readFileSync(pageExportInput)).digest('hex') !== pageExportHash) {
        throw new Error('Packaged extractPagesAsImages did not publish an ordered image archive while preserving its source.');
      }
      const videoWatermarkLogo = path.join(root, 'tests', 'fixtures', 'similar-images', 'cc0', 'dog-portrait.jpg');
      const videoWatermarkHash = createHash('sha256').update(fs.readFileSync(videoDownscaleInput)).digest('hex');
      const videoWatermarkDirectory = path.join(cliRoot, 'video-watermark-output');
      const videoWatermarkResult = JSON.parse(run(mediaCliPath, [
        'pipeline', 'run', `watermark(image: "${videoWatermarkLogo}", position: topLeft, opacity: 1.0, scale: 0.2)`,
        videoDownscaleInput, '--output-dir', videoWatermarkDirectory,
      ]));
      const videoWatermarkArtifact = videoWatermarkResult.results?.[0]?.output;
      const videoWatermarkPath = videoWatermarkArtifact
        ? path.join(videoWatermarkDirectory, videoWatermarkArtifact) : '';
      if (videoWatermarkResult.state !== 'complete' || !videoWatermarkArtifact?.endsWith('.mov')
        || videoWatermarkResult.results?.[0]?.attributes?.watermarked !== true
        || createHash('sha256').update(fs.readFileSync(videoDownscaleInput)).digest('hex') !== videoWatermarkHash) {
        throw new Error('Packaged video watermark pipeline did not publish a new MOV while preserving its source.');
      }
      run('swift', [path.join(root, 'scripts/media-smoke-verify.swift'), 'video-watermark', videoDownscaleInput, videoWatermarkPath]);
      if (ffmpeg) {
        const ffprobeCandidate = path.join(path.dirname(ffmpeg), 'ffprobe');
        const ffprobe = fs.existsSync(ffprobeCandidate) ? ffprobeCandidate : null;
        const highResolutionVideo = path.join(cliRoot, 'smart-crop-4k.mov');
        run(ffmpeg, [
          '-nostdin', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=3840x2160:r=1:d=1',
          '-frames:v', '1', '-an', '-threads', '1', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '40',
          '-pix_fmt', 'yuv420p', '-f', 'mov', '-y', highResolutionVideo,
        ], { timeout: 20_000 });
        const highResolutionHash = createHash('sha256').update(fs.readFileSync(highResolutionVideo)).digest('hex');
        const smartBoundsHelper = path.join(appPath, 'Contents', 'Resources', 'resources', 'officekit-backend', 'officekit-media-transform');
        const highResolutionBounds = JSON.parse(run(smartBoundsHelper, [
          'smart-crop-bounds', highResolutionVideo, 'video',
        ], { timeout: 25_000 }));
        if (highResolutionBounds.width !== 3840 || highResolutionBounds.height !== 2160
          || typeof highResolutionBounds.detected !== 'boolean'
          || createHash('sha256').update(fs.readFileSync(highResolutionVideo)).digest('hex') !== highResolutionHash) {
          throw new Error('Packaged video saliency did not retain source geometry while analyzing its bounded frame.');
        }
        const videoCodecTargets = [
          { target: 'mp4', extension: 'mp4', codec: 'h264' },
          { target: 'webm', extension: 'webm', codec: 'vp9' },
          { target: 'x265', extension: 'mp4', codec: 'hevc' },
        ];
        const sourceHash = createHash('sha256').update(fs.readFileSync(videoDownscaleInput)).digest('hex');
        for (const { target, extension, codec } of videoCodecTargets) {
          const outputDirectory = path.join(cliRoot, `video-${target}-outputs`);
          const outputRun = spawnSync(mediaCliPath, [
            'pipeline', 'run', `convert(to: ${target})`, videoDownscaleInput,
            '--output-dir', outputDirectory,
          ], { cwd: root, encoding: 'utf8', timeout: 130_000 });
          if (outputRun.status === 2 && outputRun.stderr.includes('not available in this build')) {
            videoFfmpegOutputStatuses.push(`${target} encoder unavailable`);
            continue;
          }
          if (outputRun.error || outputRun.status !== 0) {
            throw new Error(`Packaged ${target} video conversion failed: ${outputRun.stderr || outputRun.error?.message || outputRun.stdout}`);
          }
          const outputResult = JSON.parse(outputRun.stdout);
          const outputArtifact = outputResult.results?.[0]?.output;
          const outputPath = outputArtifact ? path.join(outputDirectory, outputArtifact) : '';
          if (outputResult.state !== 'complete' || !outputArtifact?.endsWith(`.${extension}`)
            || outputResult.results?.[0]?.attributes?.codec !== codec) {
            throw new Error(`Packaged ${target} video conversion returned an invalid artifact or codec result.`);
          }
          if (ffprobe) {
            const probe = JSON.parse(run(ffprobe, [
              '-v', 'error', '-show_entries', 'stream=codec_type,codec_name', '-of', 'json', outputPath,
            ]));
            const videoStream = probe.streams?.find(stream => stream.codec_type === 'video');
            const audioStream = probe.streams?.find(stream => stream.codec_type === 'audio');
            if (videoStream?.codec_name !== codec || !audioStream) {
              throw new Error(`Packaged ${target} conversion did not produce the requested video codec and retain audio.`);
            }
          }
          run(ffmpeg, [
            '-nostdin', '-hide_banner', '-loglevel', 'error', '-protocol_whitelist', 'file,pipe',
            '-i', outputPath, '-f', 'null', '-',
          ], { timeout: 130_000 });
          videoFfmpegOutputStatuses.push(`${target}/${codec} conversion passed`);
        }
        const compressionDirectory = path.join(cliRoot, 'video-compression-output');
        const compressionRun = spawnSync(mediaCliPath, [
          'pipeline', 'run', 'optimise(compression: 55)', videoDownscaleInput,
          '--output-dir', compressionDirectory,
        ], { cwd: root, encoding: 'utf8', timeout: 130_000 });
        if (compressionRun.error || compressionRun.status !== 0) {
          throw new Error(`Packaged video compression-factor pipeline failed: ${compressionRun.stderr || compressionRun.error?.message || compressionRun.stdout}`);
        }
        const compressionResult = JSON.parse(compressionRun.stdout);
        const compressionArtifact = compressionResult.results?.[0]?.output;
        const compressionPath = compressionArtifact ? path.join(compressionDirectory, compressionArtifact) : '';
        if (compressionResult.state !== 'complete' || !compressionArtifact?.endsWith('.mp4')
          || compressionResult.results?.[0]?.attributes?.compression !== 55
          || compressionResult.results?.[0]?.attributes?.codec !== 'h264') {
          throw new Error('Packaged compression-factor pipeline did not return its H.264 MP4 result.');
        }
        run(ffmpeg, [
          '-nostdin', '-hide_banner', '-loglevel', 'error', '-protocol_whitelist', 'file,pipe',
          '-i', compressionPath, '-f', 'null', '-',
        ], { timeout: 130_000 });
        videoFfmpegOutputStatuses.push('H.264 compression factor 55 passed');
        const directCompressionDirectory = path.join(cliRoot, 'video-direct-compression-output');
        const directCompression = JSON.parse(run(mediaCliPath, [
          'optimise', '--compression', '55', '--output-dir', directCompressionDirectory, videoDownscaleInput,
        ]));
        const directCompressionArtifact = directCompression.results?.[0]?.output;
        const directCompressionPath = directCompressionArtifact
          ? path.join(directCompressionDirectory, directCompressionArtifact) : '';
        if (directCompression.state !== 'complete' || !directCompressionArtifact?.endsWith('.mp4')
          || directCompression.results?.[0]?.attributes?.compression !== 55
          || directCompression.results?.[0]?.attributes?.codec !== 'h264') {
          throw new Error('Packaged optimise --compression did not return its H.264 MP4 result.');
        }
        run(ffmpeg, [
          '-nostdin', '-hide_banner', '-loglevel', 'error', '-protocol_whitelist', 'file,pipe',
          '-i', directCompressionPath, '-f', 'null', '-',
        ], { timeout: 130_000 });
        videoFfmpegOutputStatuses.push('Clop-style --compression 55 flag passed');
        if (createHash('sha256').update(fs.readFileSync(videoDownscaleInput)).digest('hex') !== sourceHash) {
          throw new Error('Optional FFmpeg video conversion or compression changed its selected original.');
        }
      }
      const audioSpeedHelper = path.join(appPath, 'Contents', 'Resources', 'resources', 'officekit-backend', 'officekit-media-transform');
      const audioSpeedInput = path.join(root, 'tests', 'fixtures', 'media', 'audio-tone.mp3');
      const audioSpeedSourceHash = createHash('sha256').update(fs.readFileSync(audioSpeedInput)).digest('hex');
      const audioSpeedSourceDuration = JSON.parse(run(audioSpeedHelper, ['audio-info', audioSpeedInput])).duration;
      const audioSpeedDirectory = path.join(cliRoot, 'audio-speed-output');
      const audioSpeedResult = JSON.parse(run(mediaCliPath, [
        'pipeline', 'run', 'changeSpeed(factor: 2.0)', audioSpeedInput, '--output-dir', audioSpeedDirectory,
      ]));
      const audioSpeedArtifact = audioSpeedResult.results?.[0]?.output;
      const audioSpeedPath = audioSpeedArtifact ? path.join(audioSpeedDirectory, audioSpeedArtifact) : '';
      const audioSpeedDuration = audioSpeedPath
        ? JSON.parse(run(audioSpeedHelper, ['audio-info', audioSpeedPath])).duration : 0;
      if (audioSpeedResult.state !== 'complete' || !audioSpeedArtifact?.endsWith('.m4a')
        || Math.abs(audioSpeedDuration - audioSpeedSourceDuration / 2) > 0.2
        || createHash('sha256').update(fs.readFileSync(audioSpeedInput)).digest('hex') !== audioSpeedSourceHash) {
        throw new Error('Packaged audio changeSpeed did not halve the duration in a separate M4A copy while preserving its source.');
      }
      const lowerBitrateInput = path.join(cliRoot, 'lower-bitrate-tone.wav');
      writeToneWav(lowerBitrateInput);
      const lowerBitrateSourceHash = createHash('sha256').update(fs.readFileSync(lowerBitrateInput)).digest('hex');
      const lowerBitrateDirectory = path.join(cliRoot, 'lower-bitrate-output');
      const lowerBitrateResult = JSON.parse(run(mediaCliPath, [
        'pipeline', 'run', 'lowerBitrate(kbps: 96)', lowerBitrateInput, '--output-dir', lowerBitrateDirectory,
      ]));
      const lowerBitrateArtifact = lowerBitrateResult.results?.[0]?.output;
      const lowerBitratePath = lowerBitrateArtifact ? path.join(lowerBitrateDirectory, lowerBitrateArtifact) : '';
      const lowerBitrateDuration = lowerBitratePath
        ? JSON.parse(run(audioSpeedHelper, ['audio-info', lowerBitratePath])).duration : 0;
      if (lowerBitrateResult.state !== 'complete' || !lowerBitrateArtifact?.endsWith('.m4a')
        || lowerBitrateResult.results?.[0]?.attributes?.bitrate_kbps !== 96
        || lowerBitrateResult.results?.[0]?.attributes?.no_upscale !== true
        || Math.abs(lowerBitrateDuration - 4) > 0.2
        || createHash('sha256').update(fs.readFileSync(lowerBitrateInput)).digest('hex') !== lowerBitrateSourceHash) {
        throw new Error('Packaged lowerBitrate did not create a rate-capped M4A copy with its source unchanged.');
      }
      const mixedImage = path.join(root, 'tests', 'fixtures', 'similar-images', 'cc0', 'dog-on-road.jpg');
      const mixedAudio = path.join(root, 'tests', 'fixtures', 'media', 'audio-tone.mp3');
      const mixedHashes = [mixedImage, mixedAudio].map(file => createHash('sha256').update(fs.readFileSync(file)).digest('hex'));
      const mixedOutputDirectory = path.join(cliRoot, 'mixed-preset-outputs');
      const mixedPreset = run(mediaCliPath, ['--preset', 'optimize-media', '--output-dir', mixedOutputDirectory, mixedImage, mixedAudio]);
      const mixedResult = JSON.parse(mixedPreset);
      const mixedAudioOutput = mixedResult.results?.[1]?.output;
      const mixedAudioBytes = mixedAudioOutput ? fs.readFileSync(path.join(mixedOutputDirectory, mixedAudioOutput)) : Buffer.alloc(0);
      if (mixedResult.state !== 'complete' || mixedResult.results?.length !== 2
        || mixedResult.results[0]?.output !== 'dog-on-road-optimized.jpg'
        || mixedAudioOutput !== 'audio-tone-optimized.m4a'
        || mixedResult.results[1]?.attributes?.bitrate_kbps !== 192
        || mixedAudioBytes.subarray(4, 8).toString('ascii') !== 'ftyp') {
        throw new Error(`Packaged mixed-media preset did not route image and audio files through their typed conversions: ${JSON.stringify(mixedResult)}`);
      }
      for (const item of mixedResult.results) {
        if (!fs.statSync(path.join(mixedOutputDirectory, item.output)).isFile()) {
          throw new Error(`Packaged mixed-media preset did not publish ${item.output}.`);
        }
      }
      if ([mixedImage, mixedAudio].some((file, index) => createHash('sha256').update(fs.readFileSync(file)).digest('hex') !== mixedHashes[index])) {
        throw new Error('Packaged mixed-media preset changed one or more selected originals.');
      }
      if (ffmpeg) {
        // Meter the encoded artifact, because AAC can change both loudness and peaks.
        for (const fixture of [
          { name: 'quiet-mono', channels: 1 },
          { name: 'transient-stereo', channels: 2, transient: true },
          { name: 'quiet-surround', channels: 6 },
        ]) {
          const input = path.join(cliRoot, `${fixture.name}.wav`);
          writeToneWav(input, 4, 48_000, { ...fixture, amplitude: 327 });
          const originalHash = createHash('sha256').update(fs.readFileSync(input)).digest('hex');
          const directory = path.join(cliRoot, `${fixture.name}-normalized`);
          const result = JSON.parse(run(mediaCliPath, [
            'pipeline', 'run', 'normalize(lufs: -14)', input, '--output-dir', directory,
          ], { timeout: 130_000 }));
          const item = result.results?.[0];
          const attributes = item?.attributes;
          if (result.state !== 'complete' || !item?.output?.endsWith('.m4a')) {
            throw new Error('Packaged normalization did not publish a separate M4A.');
          }
          // A host FFmpeg may lack loudnorm; the native fallback has a separate sample-peak contract.
          if (attributes?.true_peak_dbfs === undefined) {
            if (fixture.name !== 'quiet-mono' || !Number.isFinite(attributes?.sample_peak_dbfs)
              || attributes.sample_peak_dbfs > -2) throw new Error('Invalid native normalization fallback.');
            process.stdout.write('Host loudnorm unavailable; multichannel true-peak conformance skipped.\n');
            break;
          }
          const output = path.join(directory, item.output);
          const meter = spawnSync(ffmpeg, [
            '-nostdin', '-hide_banner', '-nostats', '-protocol_whitelist', 'file,pipe', '-i', output,
            '-map', '0:a:0', '-af', 'loudnorm=I=-14:LRA=11:TP=-2:print_format=json', '-f', 'null', '-',
          ], { encoding: 'utf8', timeout: 30_000 });
          if (meter.error || meter.status !== 0) throw new Error('Could not independently meter normalized audio.');
          const start = meter.stderr.lastIndexOf('{');
          const measured = JSON.parse(meter.stderr.slice(start, meter.stderr.indexOf('}', start) + 1));
          const loudness = Number(measured.input_i), peak = Number(measured.input_tp);
          if (![loudness, peak, attributes.output_lufs, attributes.true_peak_dbfs].every(Number.isFinite)
            || Math.abs(loudness - attributes.output_lufs) > 0.02
            || Math.abs(peak - attributes.true_peak_dbfs) > 0.02 || peak > -2
            || attributes.target_met !== (Math.abs(loudness + 14) <= 0.5)
            || (!fixture.transient && attributes.target_met !== true)) {
            throw new Error(`Packaged normalization misreported decoded loudness or exceeded its peak ceiling: ${fixture.name}.`);
          }
          const ffprobe = path.join(path.dirname(ffmpeg), 'ffprobe');
          if (fs.existsSync(ffprobe)) {
            const stream = JSON.parse(run(ffprobe, [
              '-v', 'error', '-select_streams', 'a:0', '-show_entries',
              'stream=channels,sample_rate,duration', '-of', 'json', output,
            ], { timeout: 10_000 })).streams?.[0];
            if (stream?.channels !== fixture.channels || stream.sample_rate !== '48000'
              || Math.abs(Number(stream.duration) - 4) > 0.1) throw new Error('Normalization changed channel count or duration.');
          }
          if (createHash('sha256').update(fs.readFileSync(input)).digest('hex') !== originalHash) {
            throw new Error('Normalization changed its selected original.');
          }
          process.stdout.write(`Verified packaged decoded loudness and true peak: ${fixture.name}.\n`);
        }
        const nativeInput = path.join(cliRoot, 'native-transient.wav');
        writeToneWav(nativeInput, 4, 48_000, { channels: 2, transient: true });
        const nativeSourceHash = createHash('sha256').update(fs.readFileSync(nativeInput)).digest('hex');
        const nativeOutput = path.join(cliRoot, 'native-transient.m4a');
        const nativeMetrics = path.join(cliRoot, 'native-transient.metrics.json');
        run(audioSpeedHelper, ['audio-normalize', nativeInput, nativeOutput, '-14', nativeMetrics], { timeout: 130_000 });
        const nativeMeasured = JSON.parse(fs.readFileSync(nativeMetrics, 'utf8'));
        const decoded = run(ffmpeg, [
          '-nostdin', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-i', nativeOutput,
          '-map', '0:a:0', '-ar', '48000', '-c:a', 'pcm_f32le', '-f', 'f32le', '-',
        ], { encoding: null, timeout: 30_000, maxBuffer: 4 * 1024 * 1024 });
        let samplePeak = 0;
        for (let offset = 0; offset < decoded.length; offset += 4) samplePeak = Math.max(samplePeak, Math.abs(decoded.readFloatLE(offset)));
        const samplePeakDbfs = 20 * Math.log10(samplePeak);
        if (!Number.isFinite(samplePeakDbfs) || !Number.isFinite(nativeMeasured.sample_peak_dbfs)
          || samplePeakDbfs > -2 || nativeMeasured.sample_peak_dbfs > -2
          || Math.abs(samplePeakDbfs - nativeMeasured.sample_peak_dbfs) > 0.02
          || nativeMeasured.true_peak_dbfs !== undefined
          || createHash('sha256').update(fs.readFileSync(nativeInput)).digest('hex') !== nativeSourceHash) {
          throw new Error('Native normalization exceeded its decoded sample-peak contract or changed its source.');
        }
        process.stdout.write('Verified packaged native decoded sample-peak ceiling.\n');
        const silentInput = path.join(cliRoot, 'silent.wav');
        writeToneWav(silentInput, 4, 48_000, { amplitude: 0 });
        const silentHash = createHash('sha256').update(fs.readFileSync(silentInput)).digest('hex');
        const silentDirectory = path.join(cliRoot, 'silent-output');
        const silentResult = spawnSync(mediaCliPath, [
          'pipeline', 'run', 'normalize(lufs: -14)', silentInput, '--output-dir', silentDirectory,
        ], { encoding: 'utf8', timeout: 130_000 });
        if (silentResult.error || silentResult.status !== 2
          || (fs.existsSync(silentDirectory) && fs.readdirSync(silentDirectory).length)
          || createHash('sha256').update(fs.readFileSync(silentInput)).digest('hex') !== silentHash) {
          throw new Error('Silent normalization did not fail without publishing or changing the source.');
        }
        const mp3Input = path.join(root, 'tests', 'fixtures', 'media', 'audio-tone.mp3');
        const mp3Hash = createHash('sha256').update(fs.readFileSync(mp3Input)).digest('hex');
        const mp3RecipePath = path.join(cliRoot, 'mp3-recipe.json');
        const mp3OutputDirectory = path.join(cliRoot, 'mp3-outputs');
        fs.writeFileSync(mp3RecipePath, JSON.stringify([{ operationId: 'audio-convert', options: { targetFormat: 'mp3', bitrateKbps: 128 } }]));
        const mp3Run = spawnSync(mediaCliPath, ['--recipe', mp3RecipePath, '--output-dir', mp3OutputDirectory, mp3Input], { cwd: root, encoding: 'utf8', timeout: 130_000 });
        if (mp3Run.status === 0) {
          const mp3Result = JSON.parse(mp3Run.stdout);
          const mp3ArtifactPath = path.join(mp3OutputDirectory, mp3Result.results?.[0]?.output || '');
          const mp3Bytes = fs.readFileSync(mp3ArtifactPath);
          if (mp3Result.state !== 'complete' || mp3Result.results?.[0]?.attributes?.codec !== 'mp3'
            || mp3Result.results[0].attributes.lossy !== true || mp3Result.results[0].attributes.bitrate_kbps !== 128
            || !(mp3Bytes.subarray(0, 3).toString('ascii') === 'ID3' || (mp3Bytes[0] === 0xFF && (mp3Bytes[1] & 0xE0) === 0xE0))) {
            throw new Error('Packaged MP3 output did not return the expected signature and codec attributes.');
          }
          run(ffmpeg, ['-nostdin', '-hide_banner', '-loglevel', 'error', '-protocol_whitelist', 'file,pipe', '-i', mp3ArtifactPath, '-f', 'null', '-']);
          if (createHash('sha256').update(fs.readFileSync(mp3Input)).digest('hex') !== mp3Hash) {
            throw new Error('Packaged MP3 encoding changed its selected original.');
          }
          mp3OutputStatus = 'host-FFmpeg MP3 conversion passed';
        } else if (mp3Run.status === 2 && mp3Run.stderr.includes('not available in this build')) {
          mp3OutputStatus = 'MP3 encoder unavailable';
        } else {
          throw new Error(`Packaged MP3 output failed: ${mp3Run.stderr || mp3Run.stdout || mp3Run.error?.message}`);
        }
      }
    } finally {
      fs.rmSync(cliRoot, { recursive: true, force: true });
    }
    process.stdout.write(`Verified Media Toolkit CLI/MCP: image, video and audio downscaling; image/video crop; lower-bitrate audio; adaptive/numeric and lossless image conversion; byte-identical factor-1 copies; ${videoFfmpegOutputStatuses.join(', ') || 'optional video encoders unavailable'}; ${mp3OutputStatus}\n`);
    process.stdout.write(`Verified macOS installer: ${absoluteDmgPath}\n`);
  } finally {
    try {
      if (mounted) await ejectSmokeImage(mountPoint, run);
      mounted = false;
    } finally {
      if (!mounted) fs.rmSync(mountPoint, { recursive: true, force: true });
    }
  }
}

try {
  await smoke(process.argv[2] || latestDmg(bundleDir));
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
}
