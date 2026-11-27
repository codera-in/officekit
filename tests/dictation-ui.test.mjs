import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from './helpers/vm.mjs';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const bundled = fs.readFileSync(path.join(root, 'dist-ui/index.html'), 'utf8');

function dictionaryFactory() {
  const functionSource = source.match(/function createOfficeKitDictationDictionary\([\s\S]*?\n        }/)?.[0];
  assert.ok(functionSource, 'dictionary persistence helper exists');
  return vm.runInNewContext(`(${functionSource})`, {});
}

function transcriptHistoryFactory(storage, id = 0, now = () => '2026-10-12T09:13:00.000Z') {
  const functionSource = source.match(/function createOfficeKitDictationHistory\([\s\S]*?\n        }/)?.[0];
  assert.ok(functionSource, 'transcript history persistence helper exists');
  return vm.runInNewContext(`(${functionSource})`, { crypto: { randomUUID: () => `history-${++id}` } })(
    storage,
    () => `history-${++id}`,
    now,
  );
}

function dictationHotkeyPreferenceFactory(storage) {
  const functionSource = source.match(/function createDictationHotkeyPreference\([\s\S]*?\n        }/)?.[0];
  assert.ok(functionSource, 'dictation shortcut preference store exists');
  return vm.runInNewContext(`(${functionSource})`, {})(storage);
}

function dictationEventListenerManagerFactory() {
  const functionSource = source.match(/function createDictationEventListenerManager\(\) \{[\s\S]*?\n        }/)?.[0];
  assert.ok(functionSource, 'dictation event listener manager exists');
  return vm.runInNewContext(`(${functionSource})`, {});
}

function memoryStorage(initial = undefined) {
  const values = new Map();
  let firstRead = initial;
  let lastValue = initial;
  return {
    getItem(key) {
      if (values.has(key)) return values.get(key);
      if (firstRead !== undefined) { const value = firstRead; firstRead = undefined; return value; }
      return null;
    },
    setItem(key, next) { values.set(key, next); lastValue = next; },
    get raw() { return lastValue; },
  };
}

test('dictation uses native local ASR, Fn, cleanup and paste-back commands', () => {
  assert.match(source, /dictation_model_status/);
  assert.match(source, /dictation_prepare_model/);
  assert.match(source, /dictation_request_microphone_permission/);
  assert.match(source, /dictation_request_accessibility_permission/);
  assert.match(source, /dictation_hotkey_enable/);
  assert.match(source, /dictation_hotkey_disable/);
  assert.match(source, /dictation_cleanup_and_paste/);
  assert.match(source, /window\.__TAURI__\.event\?\.listen/);
  assert.match(source, /dictation-transcript/);
  assert.match(source, /dictation-error/);
  assert.doesNotMatch(source, /\b(?:SpeechRecognition|webkitSpeechRecognition|getUserMedia|MediaRecorder)\b/);
  assert.equal(source, bundled, 'Tauri bundle matches the tested UI');
});

test('voice transcription and meeting notes are separate routes with a shared local audio importer', () => {
  const registry = fs.readFileSync(path.join(root, 'officekit/engines/engine_comms.py'), 'utf8');
  assert.match(registry, /"id": "voice_transcription", "name": "Voice Transcription"/);
  assert.match(registry, /"id": "meeting_notes", "name": "Meeting Notes"/);
  assert.match(source, /voice_transcription: \{ tab: 'dictate', audioView: 'voice'/);
  assert.match(source, /meeting_notes: \{ tab: 'dictate', audioView: 'meeting'/);
  assert.match(source, /data-audio-view="voice"/);
  assert.match(source, /data-audio-view="meeting"/);
  assert.match(source, /dictation_transcribe_audio_file/);
  assert.match(source, /aria-label="Audio tools"/);
  assert.match(source, /shared on-device model/);
  const rust = fs.readFileSync(path.join(root, 'src-tauri/src/lib.rs'), 'utf8');
  assert.match(rust, /fn dictation_transcribe_audio_file/);
  assert.match(rust, /blocking_pick_file()/);
  assert.match(rust, /"wav", "mp3", "m4a"/);
  assert.match(rust, /MAX_INPUT_BYTES: u64 = 64 \* 1024 \* 1024/);
  assert.match(rust, /parse_mono_f32_wav/);
  assert.match(rust, /samples\.fill\(0\.0\)/);
  assert.equal(source, bundled, 'Tauri bundle matches the tested UI');
});

test('meeting notes has one generate action and gives focused guidance when the transcript is empty', async () => {
  const screen = source.slice(source.indexOf('<section id="tab-dictate"'), source.indexOf('<section id="tab-unlocker"'));
  assert.doesNotMatch(screen, /id="dictation-mode-insights"|Insights &amp; notes/);
  assert.equal((screen.match(/data-officekit-click="processMeetingNotes\(\)"/g) || []).length, 1);
  assert.match(screen, /id="meeting-notes-generate"[^>]*>Generate meeting notes/);

  const functionSource = source.match(/async function processMeetingNotes\(\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(functionSource, 'meeting notes generation handler exists');
  const elements = new Map([
    ['dictate-transcript', { value: '', focused: false, focus() { this.focused = true; } }],
    ['dictation-transcript-status', { textContent: '' }],
  ]);
  const context = {
    meetingNotesRequestSequence: 0,
    meetingNotesInFlight: false,
    document: { getElementById: id => elements.get(id) },
  };
  const processMeetingNotes = vm.runInNewContext(`(${functionSource})`, context);
  await processMeetingNotes();
  assert.equal(elements.get('dictation-transcript-status').textContent, 'Add or record a transcript before generating meeting notes.');
  assert.equal(elements.get('dictate-transcript').focused, true);
  assert.equal(context.meetingNotesRequestSequence, 0, 'empty input does not send or start a request');
});

test('meeting notes use standard shared-dock buttons with one primary download action', () => {
  const actions = source.match(/<div id="meeting-notes-actions"([\s\S]*?)<\/div>/)?.[0];
  assert.ok(actions, 'meeting notes result actions exist');
  assert.match(actions, /role="group" aria-label="Meeting note actions"/);
  assert.match(actions, /id="meeting-notes-copy"[^>]*class="btn btn-outline/);
  assert.match(actions, /id="meeting-notes-save"[^>]*class="btn btn-outline/);
  assert.match(actions, /id="meeting-notes-download"[^>]*class="btn btn-primary/);
  assert.ok(actions.indexOf('id="meeting-notes-copy"') < actions.indexOf('id="meeting-notes-download"'));
  assert.ok(actions.indexOf('id="meeting-notes-download"') < actions.indexOf('id="meeting-notes-save"'));
  assert.doesNotMatch(actions, /ok-text-link/);
  assert.equal((actions.match(/class="btn btn-primary/g) || []).length, 1);
  assert.equal((actions.match(/<button\b/g) || []).length, 3);
  assert.equal(source, bundled, 'Tauri bundle matches the tested UI');
});

test('dictation reports a missing microphone, model setup progress, and local model cleanup', () => {
  assert.match(source, /status\.input_available === false/);
  assert.match(source, /No microphone detected\. Connect one/);
  assert.match(source, /Check microphone again/);
  assert.match(source, /dictation_model_inventory/);
  assert.match(source, /dictation_model_delete/);
  assert.match(source, /dictation-model-delete-dialog/);
  assert.match(source, /dictation-model-progress-bar/);
  assert.match(source, /bytes_downloaded/);
  assert.match(source, /completed_files/);
  assert.match(source, /Saved transcripts will stay here/);
  const native = fs.readFileSync(path.join(root, 'src-tauri/macos-dictation.swift'), 'utf8');
  const rust = fs.readFileSync(path.join(root, 'src-tauri/src/lib.rs'), 'utf8');
  assert.match(native, /officekit_dictation_has_audio_input/);
  assert.match(rust, /"No microphone detected\. Connect one or choose an input in macOS Sound settings\."/);
  assert.match(rust, /if !model_delete_allowed\([\s\S]*?current\.model == model/);
  assert.match(rust, /phase: "verifying"/);
  assert.match(rust, /fluid_model_progress_callback/);
  assert.equal(source, bundled, 'Tauri bundle matches the tested UI');
});

test('downloaded model inventory failures stay visible and can be retried', async () => {
  const helpers = source.match(/function formatLocalModelSize\([\s\S]*?(?=\n        function deleteDictationModel\()/)?.[0];
  assert.ok(helpers, 'model inventory rendering and refresh helpers exist');
  const elements = new Map();
  const makeElement = () => ({
    textContent: '', disabled: false, children: [],
    classList: { hidden: true, toggle(_name, value) { this.hidden = value; } },
    replaceChildren() { this.children = []; }, append(child) { this.children.push(child); },
  });
  for (const id of ['dictation-model-library', 'dictation-model-library-list', 'dictation-model-library-total', 'dictation-model-library-error', 'dictation-model-library-retry']) {
    elements.set(id, makeElement());
  }
  const context = {
    dictationModelInventory: [], dictationModelInventoryLoaded: false, dictationModelInventoryError: '',
    document: { getElementById: id => elements.get(id) || null, createElement: makeElement },
    tauriInvoke: () => async () => { throw new Error('Model storage is unavailable.'); },
  };
  vm.runInNewContext(helpers, context);
  assert.equal(await context.refreshDictationModelInventory(), null);
  assert.equal(elements.get('dictation-model-library').classList.hidden, false);
  assert.equal(elements.get('dictation-model-library-error').textContent, 'Model storage is unavailable.');
  assert.equal(elements.get('dictation-model-library-error').classList.hidden, false);
  assert.equal(elements.get('dictation-model-library-retry').classList.hidden, false);
  assert.equal(elements.get('dictation-model-library-retry').textContent, 'Retry model list');
  assert.equal(context.dictationModelInventoryLoaded, false);
});

test('global appearance preference supports System, Light, and Dark before first paint', () => {
  assert.match(source, /root\.dataset\.themePreference = preference/);
  assert.match(source, /prefers-color-scheme: dark/);
  assert.match(source, /officekit\.theme/);
  assert.match(source, /id="officekit-theme-toggle"[^>]*aria-label="Switch to dark mode"/);
  assert.match(source, /id="officekit-theme-system"[^>]*>Follow macOS appearance</);
  assert.match(source, /officekit-download-dialog/);
  const css = fs.readFileSync(path.join(root, 'assets/officekit.input.css'), 'utf8');
  assert.match(css, /:root\[data-theme="dark"\] \.ok-app/);
  assert.match(css, /officekit-export-paper/);
  assert.match(css, /prefers-reduced-motion:reduce/);
  assert.match(css, /#screenshot-canvas \{ color-scheme: light;/);
  assert.equal(source, bundled, 'Tauri bundle matches the tested UI');
});

test('dictation transcript history persists bounded, local transcripts with reopen and deletion support', () => {
  const storage = memoryStorage();
  const history = transcriptHistoryFactory(storage);
  history.add('Actual recognized words.', 'push-to-talk');
  history.add('Meeting segment words.', 'meeting');
  history.add('Imported audio words.', 'audio-file');
  assert.deepEqual(JSON.parse(JSON.stringify(history.list().map(({ text, source }) => ({ text, source })))), [
    { text: 'Imported audio words.', source: 'audio-file' },
    { text: 'Meeting segment words.', source: 'meeting' },
    { text: 'Actual recognized words.', source: 'push-to-talk' },
  ]);
  assert.equal(JSON.stringify(transcriptHistoryFactory(storage).list().map(entry => entry.id)), JSON.stringify(['history-3', 'history-2', 'history-1']));
  history.remove('history-2');
  assert.equal(JSON.stringify(history.list().map(entry => entry.text)), JSON.stringify(['Imported audio words.', 'Actual recognized words.']));
  history.clear();
  assert.equal(JSON.stringify(history.list()), '[]');
  assert.throws(() => history.add('x'.repeat(262145), 'meeting'), /cannot be saved/);
  assert.equal(history.add('x'.repeat(32769), 'meeting')[0].text.length,32769);
  assert.throws(() => history.add('Text', 'unknown'), /cannot be saved/);
  assert.equal(source.includes('officekit.dictation.history.v1'), true);
});

test('transcript retention is opt-in, persists supported periods, and removes expired entries', () => {
  const storage = memoryStorage();
  let currentTime = Date.parse('2026-10-01T12:00:00.000Z');
  const now = () => new Date(currentTime).toISOString();
  const history = transcriptHistoryFactory(storage, 0, now);
  assert.deepEqual(JSON.parse(JSON.stringify(history.retention())), { enabled: false, days: 30 });
  history.add('Older transcript.', 'meeting');
  currentTime = Date.parse('2026-10-25T12:00:00.000Z');
  history.add('Recent transcript.', 'push-to-talk');
  currentTime = Date.parse('2026-10-31T12:00:00.000Z');
  assert.equal(history.list().length, 2, 'disabled cleanup preserves old transcripts');
  assert.deepEqual(JSON.parse(JSON.stringify(history.configureRetention(true, 7))), { enabled: true, days: 7, removed: 1 });
  assert.deepEqual(JSON.parse(JSON.stringify(history.list().map(entry => entry.text))), ['Recent transcript.']);
  assert.deepEqual(JSON.parse(JSON.stringify(transcriptHistoryFactory(storage, 2, now).retention())), { enabled: true, days: 7 });
  assert.throws(() => history.configureRetention(true, 14), /supported transcript retention/i);
  history.configureRetention(false, 90);
  assert.deepEqual(JSON.parse(JSON.stringify(history.retention())), { enabled: false, days: 90 });
  currentTime = Date.parse('2026-11-01T12:00:00.000Z');
  history.add('Exactly ninety days old.', 'meeting');
  currentTime = Date.parse('2027-01-30T12:00:00.000Z');
  history.add('Ninety day boundary.', 'meeting');
  assert.equal(history.list().length, 3, 'disabled cleanup preserves transcripts regardless of age');
  assert.deepEqual(JSON.parse(JSON.stringify(history.configureRetention(true, 90))), { enabled: true, days: 90, removed: 2 });
  assert.deepEqual(JSON.parse(JSON.stringify(history.list().map(entry => entry.text))), ['Ninety day boundary.']);
  assert.equal(source.includes('officekit.dictation.history.retention.v1'), true);
});

test('transcript history screen exposes opt-in retention controls and labeled per-entry actions', () => {
  const screen = source.slice(source.indexOf('<section id="tab-dictate"'), source.indexOf('<section id="tab-unlocker"'));
  assert.match(screen, /id="dictation-history-auto-clear"/);
  assert.match(screen, /id="dictation-history-retention-days"/);
  assert.match(screen, /option value="7"/);
  assert.match(screen, /option value="30"/);
  assert.match(screen, /option value="90"/);
  assert.match(screen, /Clear all history/);
  assert.match(source, /Auto-clears in/);
  assert.match(source, /setInterval\(\(\) => renderDictationHistory\(\), 60 \* 60 \* 1000\)/);
  assert.equal(source, bundled, 'Tauri bundle matches the tested UI');
});

test('dictation shortcut enable choice persists across app restarts and explicit disable clears it', () => {
  const storage = {
    values: new Map(),
    getItem(key) { return this.values.get(key) ?? null; },
    setItem(key, value) { this.values.set(key, String(value)); },
    removeItem(key) { this.values.delete(key); },
  };
  const firstLaunch = dictationHotkeyPreferenceFactory(storage);
  assert.equal(firstLaunch.shouldEnable(), false);
  firstLaunch.setEnabled(true);
  assert.equal(dictationHotkeyPreferenceFactory(storage).shouldEnable(), true);
  dictationHotkeyPreferenceFactory(storage).setEnabled(false);
  assert.equal(dictationHotkeyPreferenceFactory(storage).shouldEnable(), false);
});

test('saved shortcut restores only after the model and both permissions are ready', async () => {
  const functionSource = source.match(/async function restoreDictationHotkeyIfRequested\(\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(functionSource, 'startup shortcut restore handler exists');
  const storage = {
    getItem: () => 'true',
    setItem: () => {},
    removeItem: () => {},
  };
  const calls = [];
  let modelState = 'installed';
  const context = {
    dictationStartupReady: true,
    dictationHotkeyRestoreInProgress: false,
    window: { localStorage: storage },
    createDictationHotkeyPreference: () => ({ shouldEnable: () => true }),
    tauriInvoke: () => async command => {
      calls.push(command);
      if (command === 'dictation_model_status') return { state: modelState };
      if (command === 'dictation_microphone_permission') return { permission: 'granted' };
      if (command === 'dictation_accessibility_permission') return { permission: 'granted' };
      if (command === 'dictation_hotkey_status') return { state: 'disabled' };
      if (command === 'dictation_hotkey_enable') return { state: 'ready' };
      throw new Error(`Unexpected command ${command}`);
    },
    refreshDictationHotkeyStatus: async () => calls.push('refresh'),
    setDictationStatus: () => {},
  };
  await vm.runInNewContext(`(${functionSource})`, context)();
  assert.deepEqual(calls, [
    'dictation_model_status', 'dictation_microphone_permission',
    'dictation_accessibility_permission', 'dictation_hotkey_status',
    'dictation_hotkey_enable', 'refresh',
  ]);
  calls.length = 0;
  modelState = 'ready';
  await vm.runInNewContext(`(${functionSource})`, context)();
  assert.ok(calls.includes('dictation_hotkey_enable'));
  assert.ok(!calls.includes('dictation_prepare_model'), 'saved enabled shortcuts never load model weights');
  assert.match(source, /await restoreDictationHotkeyIfRequested\(\);/);
});

test('native push-to-talk preview updates the live transcript before final transcription', () => {
  const functionSource = source.match(/function handleNativeDictationPreview\(event\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(functionSource, 'native partial transcript handler exists');
  const live = { textContent: '' };
  const status = { textContent: '' };
  const context = {
    document: { getElementById: id => id === 'dictation-live-transcript' ? live : status },
    setDictationLiveTranscript: (text, fallback) => { live.textContent = text || fallback; },
  };
  vm.runInNewContext(`(${functionSource})`, context)({ payload: { text: 'Words appear while speaking.' } });
  assert.equal(live.textContent, 'Words appear while speaking.');
  assert.match(status.textContent, /live preview/i);
  assert.match(source, /\['dictation-preview', handleNativeDictationPreview\]/);
  const native = fs.readFileSync(path.join(root, 'src-tauri/macos-dictation.swift'), 'utf8');
  const rust = fs.readFileSync(path.join(root, 'src-tauri/src/lib.rs'), 'utf8');
  assert.match(native, /officekit_dictation_copy_samples_range/);
  assert.match(rust, /fn run_dictation_preview[\s\S]*?app\.emit\("dictation-preview"/);
  assert.match(rust, /run_dictation_preview\(preview_app, generation\)/);
  assert.match(native, /func finish\(_ value: UInt64\)[\s\S]*?DispatchQueue\.main\.async \{/);
  assert.doesNotMatch(native, /func finish\(_ value: UInt64\)[\s\S]*?asyncAfter\(deadline: \.now\(\) \+ 1\.2\)/);
});

test('native dictation delivery status preserves complete recovery and never claims confirmed insertion', async () => {
  const functionSource = source.match(/async function handleNativeDictationTranscript\(event\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(functionSource);
  for (const [delivery, expected] of [
    ['paste-requested-clipboard-retained', /paste requested/i],
    ['target-changed-clipboard-retained', /target|app.*changed|switched/i],
    ['permission-required-transcript-retained', /accessibility|permission/i],
    ['paste-failed-transcript-retained', /failed|could not|not.*pasted/i],
  ]) {
    const elements = new Map();
    const saved = [];
    const remembered = [];
    const text = 'Complete cleaned Unicode transcript é with\nmultiple lines.';
    const context = {
      document: {getElementById:id=>{if(!elements.has(id)) elements.set(id,{value:'',textContent:'',classList:{add(){},remove(){}}});return elements.get(id);}},
      dictationFinalizationSequence:0, setDictationLiveTranscript:()=>{}, updateDictationWordCount:()=>{},
      setDictationStatus:()=>{}, dictationDictionaryEntries:()=>[{source:'',replacement:'easydp'},{source:'ecdp',replacement:'EasyDP'}],
      dictationWordList:entries=>entries.filter(entry=>!entry.source).map(entry=>entry.replacement),
      dictationStepsRecord:()=>undefined,
      dictationSmartCleanupMode:()=>'smart', dictationLanguageHint:()=>'en', dictationFixGrammar:()=>false,
      dictationNativeAppModes:()=>({'com.apple.mail':{smart:true}}), rememberDictationApp:app=>remembered.push(app),
      dictationHistoryStore: {add:(value,origin)=>saved.push([value,origin])},
      saveDictationHistory:(value,origin)=>saved.push([value,origin]),
      tauriInvoke:()=>async(command,args)=>{
        assert.equal(command,'dictation_cleanup_and_paste');
        assert.equal(args.text,'Raw recognized words.');
        assert.equal(args.mode,'smart');
        assert.equal(args.language,'en');
        assert.equal(args.fixGrammar,false,'grammar fixes are only requested when the person turned them on');
        assert.equal(JSON.stringify(args.appModes),'{"com.apple.mail":{"smart":true}}','per-app choices travel with the cleanup');
        assert.equal(JSON.stringify(args.dictionary),'{"ecdp":"EasyDP"}','only entries with a source are fixed replacements');
        assert.equal(JSON.stringify(args.words),'["easydp"]','plain words travel separately');
        return {text,delivery_status:delivery,app:{name:'Mail',bundle_id:'com.apple.mail'}};
      },
    };
    await vm.runInNewContext(`var dictationHistoryStore = {add: (value, origin) => globalThis.__saved.push([value, origin])}; (${functionSource})`, {...context,__saved:saved})({payload:{text:'Raw recognized words.',audio_duration_seconds:12,capture_generation:9}});
    assert.equal(elements.get('dictate-transcript').value,text);
    assert.deepEqual(saved,[[text,'push-to-talk']]);
    assert.equal(JSON.stringify(remembered),'[{"name":"Mail","bundle_id":"com.apple.mail"}]','the focused app is passed on to be remembered');
    const feedback=elements.get('dictation-transcript-status').textContent;
    assert.match(feedback,expected,delivery);
    assert.doesNotMatch(feedback,/transcript pasted into the focused app/i);
  }
});

test('dictation screen exposes actual live words and local recent transcript history', () => {
  const screen = source.slice(source.indexOf('<section id="tab-dictate"'), source.indexOf('<section id="tab-unlocker"'));
  assert.match(screen, /id="dictation-live-transcript"[^>]*aria-live="polite"/);
  assert.match(screen, /id="dictation-history-list"/);
  assert.match(screen, /Saved only on this Mac/);
  assert.match(source, /setDictationLiveTranscript\(payload\.text\)/);
  assert.match(source, /setDictationLiveTranscript\(meetingTranscriptDraft\)/);
  assert.match(source, /saveDictationHistory\(completedTranscript, 'meeting'\)/);
  assert.match(source, /saveDictationHistory\(result\.text, 'push-to-talk', dictationStepsRecord\(payload, result\)\)/);
  const native = fs.readFileSync(path.join(root, 'src-tauri/macos-dictation.swift'), 'utf8');
  const rust = fs.readFileSync(path.join(root, 'src-tauri/src/lib.rs'), 'utf8');
  assert.match(native, /officekit_dictation_overlay_transcript/);
  assert.match(native, /showTranscript\(_ text: String/);
  assert.match(native, /func finish\(_ value: UInt64\)[\s\S]*?DispatchQueue\.main\.async \{/);
  assert.doesNotMatch(native, /func finish\(_ value: UInt64\)[\s\S]*?asyncAfter\(deadline: \.now\(\) \+ 1\.2\)/);
  assert.match(rust, /officekit_dictation_overlay_transcript\([\s\S]*transcript\.text\.as_ptr\(\)/);
  assert.equal(source, bundled, 'Tauri bundle matches the tested UI');
});

test('dictation offers a persisted modifier-key choice and sends it to the native monitor', () => {
  const screen = source.slice(source.indexOf('<section id="tab-dictate"'), source.indexOf('<section id="tab-unlocker"'));
  assert.match(screen, /id="dictation-hotkey-choice"/);
  for (const key of ['fn', 'left_option', 'right_option', 'left_control', 'right_control', 'left_command', 'right_command', 'left_shift', 'right_shift']) {
    assert.match(screen, new RegExp(`value="${key}"`));
  }
  assert.match(source, /officekit\.dictation\.hotkey/);
  assert.match(source, /dictation_hotkey_configure/);
  assert.match(source, /async function configureDictationHotkey\(/);
  assert.match(source, /storedHotkey\) \? storedHotkey : 'left_option'/);
  assert.match(source, /Enable Left Option shortcut/);
  assert.match(screen, /value="left_option" selected/);
  const native = fs.readFileSync(path.join(root, 'src-tauri/macos-dictation.swift'), 'utf8');
  assert.match(native, /officekitDictationStartHotkeyMonitor\([\s\S]*_ keyID: Int32,[\s\S]*_ keyCode: Int32,[\s\S]*_ modifierMask: Int32/);
  assert.match(native, /event\.keyCode == configuredKeyCode/);
  for (const [id, keyCode] of [[0, 63], [1, 58], [2, 61], [3, 59], [4, 62], [5, 55], [6, 54], [7, 56], [8, 60]]) {
    assert.match(native, new RegExp(`case ${id}: ${keyCode}(?:\\n|$)`));
  }
  assert.match(native, /dictationModifierKeyIsDown\([\s\S]*flags: event\.modifierFlags\.rawValue/);
  assert.doesNotMatch(native, /CGEventSource\.keyState/);
  assert.doesNotMatch(native, /event\.modifierFlags\.contains\(configuredKey\.flag\)/);
  assert.match(source, /choice\.disabled = status\.state !== 'disabled'/);
  assert.match(source, /Hold \$\{label\} to dictate/);
  assert.equal(source, bundled, 'Tauri bundle matches the tested UI');
});

test('native push-to-talk does not report ready when either event monitor is missing', () => {
  const native = fs.readFileSync(path.join(root, 'src-tauri/macos-dictation.swift'), 'utf8');
  assert.match(native, /guard monitors\.0 != nil && monitors\.1 != nil else \{/);
  assert.match(native, /if let global \{ NSEvent\.removeMonitor\(global\) \}/);
  assert.match(native, /if let local \{ NSEvent\.removeMonitor\(local\) \}/);
  assert.match(native, /return 3/);
});

test('macOS microphone permission requests TCC without requiring a discovered audio device', () => {
  const native = fs.readFileSync(path.join(root, 'src-tauri/macos-dictation.swift'), 'utf8');
  assert.match(native, /import AVFoundation/);
  assert.match(native, /AVCaptureDevice\.authorizationStatus\(for: \.audio\)/);
  assert.match(native, /AVCaptureDevice\.requestAccess\(for: \.audio\)/);
  assert.match(native, /OfficeKitMicrophonePermissionProbe\.shared\.request\(\)/);
  assert.match(native, /dictationShouldRequestMicrophoneAccess\(for: permission\)/);
  assert.doesNotMatch(native, /AVCaptureDevice\.default\(for: \.audio\)/);
  assert.doesNotMatch(native, /AVCaptureDeviceInput\(device: device\)/);
  assert.doesNotMatch(native, /AVAudioApplication\.(?:shared\.recordPermission|requestRecordPermission)/);
  assert.match(native, /currentDictationMicrophonePermissionCode\(\) == 0/);
  assert.match(fs.readFileSync(path.join(root, 'src-tauri/build.rs'), 'utf8'), /rustc-link-lib=framework=AVFoundation/);
});

test('dictation records a custom hold-to-talk key chord and validates it natively', () => {
  const start = source.indexOf('<section id="tab-dictate"');
  const end = source.indexOf('<section id="tab-unlocker"', start);
  const screen = source.slice(start, end);
  const mock = fs.readFileSync(path.join(root, 'design/mocks/dictation-custom-ptt-key.html'), 'utf8');
  assert.match(screen, /option value="custom">Custom key combination/);
  assert.match(screen, /id="dictation-hotkey-record"/);
  assert.match(screen, /id="dictation-hotkey-capture-status"/);
  assert.match(screen, /macOS passes the keys through/);
  assert.match(source, /dictation_hotkey_configure_custom/);
  assert.match(source, /beginDictationHotkeyCapture\(/);
  assert.match(source, /'beginDictationHotkeyCapture'/);
  assert.match(source, /event\.code/);
  assert.match(source, /modifierMask/);
  assert.match(screen, /F13–F20/);
  assert.match(mock, /Custom key combination/);
  assert.match(mock, /Record shortcut/);
  const rust = fs.readFileSync(path.join(root, 'src-tauri/src/dictation.rs'), 'utf8');
  const native = fs.readFileSync(path.join(root, 'src-tauri/macos-dictation.swift'), 'utf8');
  assert.match(rust, /fn validate_custom_hotkey\(/);
  assert.match(rust, /SAFE_STANDALONE_FUNCTION_KEYS/);
  assert.match(rust, /choose F13 through F20 by itself/);
  assert.match(native, /event\.type == \.keyDown && event\.keyCode == custom\.keyCode/);
  assert.match(native, /event\.type == \.keyUp && event\.keyCode == custom\.keyCode/);
  assert.match(native, /matching: eventTypes/);
  const bridge = fs.readFileSync(path.join(root, 'src-tauri/src/lib.rs'), 'utf8');
  assert.match(bridge, /dictation_hotkey_configure_custom,/);
  assert.equal(source, bundled, 'Tauri bundle matches the tested UI');
});

test('dictation capture UI and native command accept the same physical key codes', () => {
  const uiMapping = source.match(/const macDictationKeyCodes = Object\.freeze\((\{[\s\S]*?\})\);/);
  assert.ok(uiMapping, 'capture UI exposes its Mac key-code map');
  const uiCodes = [...new Set(Object.values(vm.runInNewContext(`(${uiMapping[1]})`)))].sort((a, b) => a - b);
  const rust = fs.readFileSync(path.join(root, 'src-tauri/src/dictation.rs'), 'utf8');
  const nativeAllowlist = rust.match(/const SUPPORTED_CUSTOM_HOTKEY_KEY_CODES: &\[u16\] = &\[([\s\S]*?)\];/);
  assert.ok(nativeAllowlist, 'native command has a bounded key-code allowlist');
  const nativeCodes = [...nativeAllowlist[1].matchAll(/\d+/g)].map(([value]) => Number(value)).sort((a, b) => a - b);
  assert.deepEqual(nativeCodes, uiCodes);
  assert.equal(new Set(nativeCodes).size, nativeCodes.length, 'native allowlist contains no duplicate keys');
});

test('dictation screen exposes model, permissions, shortcut, personal dictionary and notes review', () => {
  const start = source.indexOf('<section id="tab-dictate"');
  const end = source.indexOf('<section id="tab-unlocker"', start);
  const screen = start >= 0 && end > start ? source.slice(start, end) : '';
  assert.ok(screen, 'dictation screen exists');
  assert.match(source, /id="app-feedback-toast"[^>]*role="status"/);
  assert.match(source, /id="app-feedback-icon"/);
  assert.match(source, /function showAppFeedbackToast\(message, state = 'working'\)/);
  assert.match(source, /success: \{ icon: 'fa-solid fa-circle-check text-emerald-400'/);
  assert.match(source, /error: \{ icon: 'fa-solid fa-circle-exclamation text-rose-400'/);
  for (const id of [
    'dictation-model-status',
    'dictation-model-download',
    'dictation-microphone-status',
    'dictation-microphone-request',
    'dictation-accessibility-status',
    'dictation-accessibility-request',
    'dictation-hotkey-status',
    'dictation-hotkey-choice',
    'dictation-hotkey-toggle',
    'dictation-events-recovery',
    'dictation-events-retry',
    'dictation-dictionary-source',
    'dictation-dictionary-replacement',
    'dictate-transcript',
    'dictation-clear',
    'notes-result',
  ]) assert.match(screen, new RegExp(`id="${id}"`));
  assert.match(screen, /aria-live="polite"/);
  assert.match(screen, /open speech model for on-device dictation/i);
  assert.match(screen, /audio is never uploaded/i);
  assert.match(screen, /25 European languages/);
  assert.match(screen, /CC BY 4\.0/);
  assert.match(source, /Apache 2\.0/);
  assert.match(screen, /paste/i);
  assert.match(source, /connectNativeDictationEvents\(/);
  assert.match(source, /retryNativeDictationEvents\(/);
  assert.doesNotMatch(source, /Could not listen for Fn shortcut events\. Restart OfficeKit/);
});

test('dictation explains model language coverage, storage, tradeoffs and licensing', () => {
  const mock = fs.readFileSync(path.join(root, 'design/mocks/dictation-model-catalog.html'), 'utf8');
  for (const detail of [
    'Parakeet V3', '25', 'European languages', '~460 MB', 'CC BY 4.0',
    'Parakeet V2', 'English', '~440 MB', 'Qwen3 ASR 0.6B', '30', '22',
    'Chinese dialects', '~4 GB', 'Hindi', 'Apache 2.0', 'macOS 15+',
    'Audio and transcripts stay on this Mac',
  ]) assert.ok(mock.includes(detail), `model catalog includes ${detail}`);
  assert.match(mock, /does not cover Tamil or Hindi/);
  assert.match(mock, /does not cover Tamil/);
  assert.match(source, /dictation-model-fit/);
  assert.match(source, /dictation-model-footprint/);
  assert.match(source, /30 languages \+ 22 Chinese dialects/);
  assert.doesNotMatch(source, /52 languages/);
  assert.equal(source, bundled, 'Tauri bundle matches the tested UI');
});

test('first speech-model failures reach the existing Coach and meeting error fields', () => {
  const functionSource = source.match(/function handleNativeDictationError\(event\) \{[\s\S]*?\n        \}/)?.[0];
  const fields = new Map();
  const errors = [];
  const handle = vm.runInNewContext(`(${functionSource})`, {
    document: { getElementById: id => {
      if (!fields.has(id)) fields.set(id, { textContent: '' });
      return fields.get(id);
    } },
    setDictationStatus: (message, error) => errors.push({ message, error }),
  });
  handle({ payload: { speech_model: true, meeting: true, message: 'The cached speech model is incomplete.' } });
  assert.equal(fields.get('speech-coach-status').textContent, 'The cached speech model is incomplete.');
  assert.equal(fields.get('meeting-record-error').textContent, 'The cached speech model is incomplete.');
  assert.deepEqual(errors, [{ message: 'The cached speech model is incomplete.', error: true }]);
});

test('selecting an installed model keeps its prepare action idle without loading weights', async () => {
  const functionSource = source.match(/async function selectDictationModel\(modelId\) \{[\s\S]*?\n        \}/)?.[0];
  const choice = { disabled: false, value: '' };
  const button = { disabled: false, textContent: '', classList: { toggle() {} } };
  const status = { state: 'installed', model_id: 'whisper_medium', message: 'Stored locally' };
  const calls = [];
  const select = vm.runInNewContext(`(${functionSource})`, {
    document: { getElementById: id => id === 'dictation-model-choice' ? choice : button },
    window: { localStorage: { setItem() {} } },
    officekitSyncDictationModelPicker() {}, updateDictationModelDetails() {},
    dictationModelOutcomeState: () => 'info',
    currentDictationMode: 'transcribe', currentDictationSpokenLanguage: 'auto',
    setDictationStatus: error => assert.fail(error), refreshDictationModelStatus: () => assert.fail('Unexpected refresh'),
    tauriInvoke: () => async command => {
      calls.push(command);
      if (command === 'dictation_model_select') return status;
      assert.ok(['dictation_set_translation_mode', 'dictation_set_spoken_language'].includes(command));
    },
  });
  assert.equal(await select('whisper_medium'), status);
  assert.equal(button.textContent, 'Prepare model');
  assert.equal(button.disabled, false);
  assert.equal(choice.disabled, false);
  assert.ok(!calls.includes('dictation_prepare_model'));
});

test('startup and downloaded model selection never prepare speech weights', async () => {
  const startup = source.match(/async function initNativeDictation\(\) \{[\s\S]*?\n        \}/)?.[0];
  const selection = source.match(/async function selectDictationModel\(modelId\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(startup);
  assert.ok(selection);
  assert.doesNotMatch(startup, /prepareDictationModel|dictation_prepare_model|autoPrepare/);
  assert.doesNotMatch(selection, /prepareDictationModel|dictation_prepare_model|autoPrepare/);
  assert.doesNotMatch(source, /autoPrepareInstalledDictationModel/);
  assert.equal(source, bundled, 'Tauri bundle matches the tested UI');
});

test('dictation permission status refreshes when OfficeKit returns from System Settings', async () => {
  const start = source.indexOf('let dictationPermissionRefreshInProgress');
  const end = source.indexOf('async function requestDictationPermission', start);
  const permissionRefreshSource = source.slice(start, end);
  assert.ok(start >= 0 && end > start, 'permission refresh listens for app focus and visibility');
  let delayedCallback;
  let delayMs;
  const listeners = {};
  const calls = [];
  const screen = { hidden: true, classList: { contains: () => screen.hidden } };
  const context = {
    window: {
      __TAURI__: { core: { invoke: () => {} } },
      addEventListener: (name, listener) => { listeners[`window:${name}`] = listener; },
      setTimeout: (callback, delay) => { delayedCallback = callback; delayMs = delay; },
    },
    document: {
      visibilityState: 'visible',
      addEventListener: (name, listener) => { listeners[`document:${name}`] = listener; },
      getElementById: () => screen,
    },
    refreshDictationPermission: async kind => calls.push(kind),
    refreshDictationHotkeyStatus: async () => calls.push('shortcut'),
    restoreDictationHotkeyIfRequested: async () => calls.push('restore'),
  };
  vm.runInNewContext(permissionRefreshSource, context);
  assert.equal(typeof listeners['window:focus'], 'function');
  assert.equal(typeof listeners['document:visibilitychange'], 'function');
  listeners['window:focus']();
  assert.equal(delayedCallback, undefined, 'does not refresh while another screen is open');

  screen.hidden = false;
  listeners['window:focus']();
  assert.equal(delayMs, 150, 'waits briefly for System Settings to hand focus back');
  await delayedCallback();
  assert.deepEqual(calls, ['microphone', 'accessibility', 'shortcut', 'restore']);
  assert.equal(source, bundled, 'Tauri bundle matches the tested UI');
});

test('denied microphone permission opens macOS Microphone Settings from the card action', async () => {
  const functionSource = source.match(/async function refreshDictationPermission\(kind\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(functionSource, 'permission refresh handler exists');
  const button = {
    disabled: false,
    textContent: '',
    dataset: {},
    classList: { toggle: () => {} },
    setAttribute(name, value) { if (name === 'data-officekit-click') this.dataset.officekitClick = value; },
  };
  const statusElement = { textContent: '' };
  const context = {
    document: { getElementById: id => id === 'dictation-microphone-status' ? statusElement : button },
    tauriInvoke: () => async command => {
      assert.equal(command, 'dictation_microphone_permission');
      return { permission: 'denied', message: 'Allow microphone access in System Settings.' };
    },
  };
  const refresh = vm.runInNewContext(`(${functionSource})`, context);
  await refresh('microphone');
  assert.equal(button.textContent, 'Open Microphone Settings');
  assert.equal(button.dataset.officekitClick, "openDictationPermissionSettings('microphone')");
  assert.equal(button.disabled, false);
  assert.match(source, /dictation_open_permission_settings/);
});

test('microphone authorization shows progress while the native request is pending', async () => {
  const functionSource = source.match(/async function requestDictationPermission\(kind, command\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(functionSource, 'permission request handler exists');
  const button = { disabled: false, textContent: 'Allow microphone' };
  const statusElement = { textContent: '' };
  let finishNativeRequest;
  const context = {
    Date,
    Promise,
    window: { setTimeout: callback => callback() },
    document: { getElementById: id => id === 'dictation-microphone-status' ? statusElement : button },
    tauriInvoke: () => async command => {
      if (command === 'dictation_request_microphone_permission') {
        return new Promise(resolve => { finishNativeRequest = resolve; });
      }
      if (command === 'dictation_microphone_permission') return { permission: 'granted', message: 'Microphone access is enabled.' };
      assert.fail(`unexpected command ${command}`);
    },
    refreshDictationPermission: async () => ({ permission: 'granted' }),
    refreshDictationHotkeyStatus: async () => {},
    restoreDictationHotkeyIfRequested: async () => {},
    setDictationStatus: () => {},
    persistDictationHotkeyEnabled: () => {},
  };
  const request = vm.runInNewContext(`(${functionSource})`, context);
  const pending = request('microphone', 'dictation_request_microphone_permission');
  assert.equal(button.disabled, true);
  assert.equal(button.textContent, 'Requesting…');
  assert.match(statusElement.textContent, /macOS microphone permission/);
  finishNativeRequest({ permission: 'granted' });
  await pending;
});

test('enabling a shortcut registers it without preparing speech weights and remembers the request', async () => {
  const functionSource = source.match(/async function enablePreparedDictationHotkey\(\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(functionSource);
  for (const allowed of [true, false]) {
    const calls = [];
    const enable = vm.runInNewContext(`(${functionSource})`, {
      tauriInvoke: () => async command => {
        calls.push(command);
        assert.equal(command, 'dictation_hotkey_enable', 'native registration decides availability without eager preparation');
        if (!allowed) throw new Error('Prepare the local model');
        return { state: 'ready' };
      },
      persistDictationHotkeyEnabled: value => calls.push(`persist:${value}`),
    });
    if (allowed) {
      const result = await enable();
      assert.equal(result.state, 'ready');
      assert.deepEqual(calls, ['dictation_hotkey_enable', 'persist:true']);
    } else {
      await assert.rejects(enable, /Prepare the local model/);
      assert.deepEqual(calls, ['dictation_hotkey_enable']);
    }
  }
  const setup = fs.readFileSync(path.join(root, 'assets/officekit-setup.js'), 'utf8');
  const settingsWindow = {
    document: { readyState: 'loading', addEventListener() {} },
    __TAURI__: { core: { invoke: async () => ({ state: 'disabled' }) } },
    enablePreparedDictationHotkey: async () => { throw new Error('Model not downloaded'); },
  };
  vm.runInNewContext(setup, { window: settingsWindow });
  assert.equal(await settingsWindow.officekitSetup.setDictationShortcut(true), 'pending');
  settingsWindow.enablePreparedDictationHotkey = async () => ({ state: 'ready' });
  assert.equal(await settingsWindow.officekitSetup.setDictationShortcut(true), true);
});

test('shortcut toggle shows immediate progress feedback while native command is pending', async () => {
  const functionSource = source.match(/async function toggleDictationHotkey\(\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(functionSource, 'shortcut toggle handler exists');
  let finishStatus;
  const button = { disabled: false, textContent: 'Enable Left Option shortcut' };
  const statusElement = { textContent: 'Shortcut is off' };
  const calls = [];
  const notices = [];
  const context = {
    document: { getElementById: id => id === 'dictation-hotkey-toggle' ? button : statusElement },
    tauriInvoke: () => command => {
      calls.push(command);
      if (command === 'dictation_hotkey_status') return Promise.resolve({ state: 'disabled', key: 'left_option' });
      if (command === 'dictation_hotkey_enable') return new Promise(resolve => { finishStatus = resolve; });
      throw new Error(`Unexpected command: ${command}`);
    },
    dictationHotkeyLabel: () => 'Left Option',
    setDictationStatus: () => {},
    persistDictationHotkeyEnabled: () => {},
    enablePreparedDictationHotkey: () => context.tauriInvoke()('dictation_hotkey_enable'),
    showAppFeedbackToast: (message, state) => notices.push({ message, state }),
    refreshDictationHotkeyStatus: async () => {},
  };
  const toggle = vm.runInNewContext(`(${functionSource})`, context);
  const pending = toggle();
  assert.equal(button.disabled, true, 'button disables immediately to prevent duplicate requests');
  assert.equal(button.textContent, 'Checking shortcut…', 'button shows immediate progress');
  assert.equal(statusElement.textContent, 'Checking shortcut status…', 'live status announces the action');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(button.textContent, 'Enabling…', 'button describes the native operation while it is pending');
  assert.deepEqual(notices.map(notice => notice.state), ['working', 'working']);
  finishStatus({ state: 'ready', key: 'left_option' });
  await pending;
  assert.equal(button.disabled, false);
  assert.deepEqual(calls, ['dictation_hotkey_status', 'dictation_hotkey_enable']);
  assert.deepEqual(notices.at(-1), { message: 'Shortcut ready. Hold Left Option to dictate into the focused app.', state: 'success' });
});

test('shortcut toggle shows a visible error notice when the native command fails', async () => {
  const functionSource = source.match(/async function toggleDictationHotkey\(\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(functionSource, 'shortcut toggle handler exists');
  const button = { disabled: false, textContent: 'Enable shortcut' };
  const statusElement = { textContent: 'Shortcut is off' };
  const notices = [];
  const context = {
    document: { getElementById: id => id === 'dictation-hotkey-toggle' ? button : statusElement },
    tauriInvoke: () => command => {
      if (command === 'dictation_hotkey_status') return Promise.resolve({ state: 'disabled', key: 'left_option' });
      if (command === 'dictation_hotkey_enable') return Promise.reject(new Error('Accessibility access is required'));
      throw new Error(`Unexpected command: ${command}`);
    },
    dictationHotkeyLabel: () => 'Left Option',
    setDictationStatus: () => {},
    enablePreparedDictationHotkey: () => context.tauriInvoke()('dictation_hotkey_enable'),
    showAppFeedbackToast: (message, state) => notices.push({ message, state }),
    refreshDictationHotkeyStatus: async () => {},
  };
  await vm.runInNewContext(`(${functionSource})`, context)();
  assert.equal(button.disabled, false);
  assert.equal(notices.at(-1).state, 'error');
  assert.match(notices.at(-1).message, /Accessibility access is required/);
});

test('the Parakeet credit line names the creator, the conversion, the licence and its link (CC BY 4.0)', () => {
  const credit = /Model: NVIDIA Parakeet TDT 0\.6B[^']*converted to Core ML by FluidInference\. License: CC BY 4\.0 \(creativecommons\.org\/licenses\/by\/4\.0\)\./;
  const shown = source.match(/id="dictation-model-license"[^>]*>([^<]*)</)[1];
  assert.match(shown, credit);
  for (const id of ['parakeet_v3', 'parakeet_v2']) {
    const line = source.match(new RegExp(`${id}: \\{[^}]*?license: '([^']*)'`))?.[1] ?? '';
    assert.match(line, credit, `${id} credit line`);
  }
  // Models under other licences keep their own line and are not credited to NVIDIA.
  const qwen = source.match(/qwen3_asr: \{[^}]*?license: '([^']*)'/)?.[1] ?? '';
  assert.ok(qwen.length > 0 && !/NVIDIA/.test(qwen), 'qwen3 keeps its own licence line');
});

test('dictation lets users choose supported open local speech models and routes selection natively', () => {
  const screen = source.slice(source.indexOf('<section id="tab-dictate"'), source.indexOf('<section id="tab-unlocker"'));
  assert.match(screen, /id="dictation-model-choice"/);
  assert.match(screen, /value="parakeet_v3"[^>]*>Parakeet v3 · Multilingual/);
  assert.match(screen, /value="parakeet_v2"[^>]*>Parakeet v2 · English/);
  assert.match(screen, /value="qwen3_asr"[^>]*>Qwen3 ASR 0\.6B · wider language coverage/);
  assert.match(screen, /value="whisper_medium"[^>]*>Whisper Medium · multilingual · 1\.54 GB/);
  assert.match(screen, /value="whisper_large_v3_turbo"[^>]*>Whisper Large v3 Turbo · fast · 1\.63 GB/);
  assert.match(source, /dictation_model_select/);
  assert.match(source, /officekit\.dictation\.model/);
  assert.match(source, /async function selectDictationModel\(/);
  assert.match(fs.readFileSync(path.join(root, 'src-tauri/src/lib.rs'), 'utf8'), /fn dictation_model_select\(/);
  const backend = fs.readFileSync(path.join(root, 'src-tauri/src/lib.rs'), 'utf8');
  assert.match(backend, /init_qwen3_asr_with_progress\(/);
  assert.match(backend, /transcribe_qwen3_chunks\(samples, \|chunk\| \{[\s\S]*?qwen3_transcribe_samples\(chunk, None\)/);
  assert.match(backend, /qwen3_supported_on_current_os/);
  assert.match(backend, /fn load_whisper_context\(/);
  assert.match(backend, /WhisperContext::new_with_params/);
  assert.match(backend, /fn transcribe_samples_buffer\([\s\S]*?params\.set_translate\(translate_to_english\)/);
  assert.match(fs.readFileSync(path.join(root, 'src-tauri/Cargo.toml'), 'utf8'), /whisper-rs\s*=.*features\s*=\s*\["metal"\]/);
  assert.match(backend, /fn dictation_set_translation_mode\(/);
  assert.match(backend, /fn dictation_set_spoken_language\(/);
  assert.match(source, /meetingTranslationDraft/);
  assert.match(source, /dictation-translation-result/);
  assert.match(source, /whisper\.cpp runtime: MIT/);
  assert.match(fs.readFileSync(path.join(root, 'src-tauri/vendor/fluidaudio-rs/swift/FluidAudioBridge.swift'), 'utf8'), /Qwen3AsrModels\.download\(\)/);
  assert.equal(source, bundled, 'Tauri bundle matches the tested UI');
});

test('speech model list shows honest speed and accuracy fields and language/output choices', () => {
  const screen = source.slice(source.indexOf('<section id="tab-dictate"'), source.indexOf('<section id="tab-unlocker"'));
  const modelPicker = screen.slice(screen.indexOf('id="dictation-model-options"'), screen.indexOf('id="dictation-spoken-language"'));
  const referenceRatings = {
    parakeet_v3: [9.9, 9.4], parakeet_v2: [9.9, 9.4], whisper_base: [8.5, 7.2],
    whisper_large_v3: [3, 9.5], whisper_large_v3_turbo: [7.5, 9.4],
    whisper_tiny: [9.5, 6], whisper_large_v3_turbo_q5: [7.5, 9.4],
  };
  const modelIds = ['parakeet_v3', 'parakeet_v2', 'qwen3_asr', 'whisper_tiny', 'whisper_base', 'whisper_small', 'whisper_medium', 'whisper_large_v3', 'whisper_large_v3_turbo', 'whisper_large_v3_turbo_q5'];
  for (const modelId of modelIds) {
    const option = modelPicker.match(new RegExp(`data-dictation-model-option="${modelId}"[\\s\\S]*?<\\/button>`))?.[0];
    assert.ok(option, `${modelId} is available in the expanded picker`);
    if (referenceRatings[modelId]) {
      const [speed, accuracy] = referenceRatings[modelId];
      assert.match(option, new RegExp(`data-speed="${speed}" data-accuracy="${accuracy}"`));
      assert.match(option, new RegExp(`data-dictation-rating="speed"[\\s\\S]*?>${speed.toFixed(1)}</b>`));
      assert.match(option, new RegExp(`data-dictation-rating="accuracy"[\\s\\S]*?>${accuracy.toFixed(1)}</b>`));
    } else {
      assert.match(option, /Speed —/);
      assert.match(option, /Accuracy —/);
    }
  }
  assert.match(modelPicker, /Ratings are reference scores for comparison, not measured on this Mac/);
  assert.doesNotMatch(source, new RegExp(['voice', 'ink'].join(''), 'i'), 'no third-party product names in the open-source UI');
  const tagsOf = modelId => [...modelPicker
    .match(new RegExp(`data-dictation-model-option="${modelId}"[\\s\\S]*?<\\/button>`))[0]
    .matchAll(/data-dictation-tag>([^<]+)</g)].map(match => match[1]);
  assert.deepEqual(tagsOf('parakeet_v3'), ['Multilingual', '494 MB']);
  assert.deepEqual(tagsOf('parakeet_v2'), ['English', '474 MB']);
  assert.deepEqual(tagsOf('whisper_medium'), ['Multilingual', '1.54 GB', 'Translates to English']);
  assert.deepEqual(tagsOf('whisper_large_v3'), ['Multilingual', '3.10 GB', 'Translates to English']);
  assert.ok(!tagsOf('whisper_large_v3_turbo').includes('Translates to English'), 'Turbo does not translate');
  assert.deepEqual(tagsOf('whisper_tiny'), ['Multilingual', '78 MB']);
  assert.deepEqual(tagsOf('whisper_large_v3_turbo_q5'), ['Multilingual', 'Fast', '574 MB']);
  assert.ok(!tagsOf('whisper_large_v3_turbo_q5').includes('Translates to English'), 'quantized Turbo does not translate');
  assert.match(modelPicker, /data-dictation-model-option="whisper_large_v3_turbo_q5"[\s\S]*?<\/button>\s*<\/div>/, 'the quantized Turbo row is last and closes the list');
  assert.doesNotMatch(modelPicker, />Streaming</, 'no Streaming tag: live preview is identical for every model');
  assert.match(modelPicker, /role="option"/);
  assert.match(source, /officekitSyncDictationModelPicker[\s\S]*?item\.setAttribute\('aria-label'/);
  assert.match(screen, /aria-haspopup="listbox"/);
  assert.match(screen, /id="dictation-output-language"/);
  assert.match(screen, /value="source">Transcribe only/);
  assert.match(screen, /value="en">English/);
  assert.match(source, /async function selectDictationOutputLanguage\(/);
  assert.match(source, /English translation requires Whisper Medium or Large v3/);
  assert.match(source, /Speed rating unavailable\. Accuracy rating unavailable/);
  assert.equal(source, bundled, 'Tauri bundle matches the tested UI');
});

test('the main Tauri window is granted the event capability required by native dictation listeners', () => {
  const capability = JSON.parse(fs.readFileSync(path.join(root, 'src-tauri/capabilities/default.json'), 'utf8'));
  assert.equal(capability.identifier, 'officekit-main');
  assert.deepEqual(capability.windows, ['main']);
  assert.ok(capability.permissions.includes('core:event:default'));
});

test('personal dictionary persists locally and rejects invalid or ambiguous entries', () => {
  const createStore = dictionaryFactory();
  const storage = memoryStorage();
  const store = createStore(storage);
  assert.equal(JSON.stringify(store.list()), '[]');
  store.add('office kit', 'OfficeKit');
  store.add('pike pdf', 'PyPDF');
  assert.equal(store.list().length, 2);
  assert.throws(() => store.add('Office Kit', 'Office Kit'), /already exists/i);
  assert.throws(() => store.add('word', ''), /required/i);
  assert.throws(() => store.add('', '   '), /required/i);
  assert.throws(() => store.add('word', 'x'.repeat(65)), /64 characters/i);
  assert.throws(() => store.add('word', 'bad\nvalue'), /control/i);
  assert.equal(JSON.stringify(JSON.parse(storage.raw).map(entry => entry.source)), JSON.stringify(['office kit', 'pike pdf']));
  assert.equal(JSON.stringify(createStore(storage).list().map(entry => entry.replacement)), JSON.stringify(['OfficeKit', 'PyPDF']));
  const fullDictionary = Array.from({ length: 256 }, (_, index) => ({ source: `source${index}`, replacement: `target${index}` }));
  assert.throws(() => createStore(memoryStorage(JSON.stringify(fullDictionary))).add('extra', 'Extra'), /256 entries/i);
});

test('plain words need no source, stay unique without regard to case and count toward the limit', () => {
  const createStore = dictionaryFactory();
  const store = createStore(memoryStorage());
  store.add('', 'Kubernetes');
  store.add('  ', ' easydp ');
  assert.equal(JSON.stringify(store.list()), JSON.stringify([
    { source: '', replacement: 'Kubernetes' },
    { source: '', replacement: 'easydp' },
  ]));
  assert.throws(() => store.add('', 'KUBERNETES'), /already in your dictionary/i);
  store.add('ecdp', 'Kubernetes');
  assert.equal(store.list().length, 3, 'a replace entry may share its target with a plain word');
  assert.throws(() => store.add('', 'x'.repeat(65)), /64 characters/i);
  assert.throws(() => store.add('', 'bad\nvalue'), /control/i);
  const full = Array.from({ length: 256 }, (_, index) => ({ source: '', replacement: `word${index}` }));
  assert.throws(() => createStore(memoryStorage(JSON.stringify(full))).add('', 'Extra'), /256 entries/i);
});

test('comma-separated variants become one entry each and skip terms already saved', () => {
  const createStore = dictionaryFactory();
  const store = createStore(memoryStorage());
  assert.equal(JSON.stringify(store.parseVariants(' open a i, Open Eye ,, open a i , open ai')), JSON.stringify(['open a i', 'Open Eye', 'open ai']));
  assert.equal(JSON.stringify(store.parseVariants('')), '[]');
  assert.equal(JSON.stringify(store.parseVariants(null)), '[]');
  const first = store.addVariants(['open a i', 'open eye'], 'OpenAI');
  assert.equal(JSON.stringify(first), JSON.stringify({ added: 2, duplicates: 0, invalid: 0, overLimit: 0 }));
  const again = store.addVariants(['OPEN EYE', 'open ai'], 'OpenAI');
  assert.equal(JSON.stringify(again), JSON.stringify({ added: 1, duplicates: 1, invalid: 0, overLimit: 0 }));
  assert.equal(JSON.stringify(store.list().map(entry => entry.source)), JSON.stringify(['open a i', 'open eye', 'open ai']));
  const bad = store.addVariants(['fine', 'x'.repeat(65), 'bad\nterm'], 'Word');
  assert.equal(JSON.stringify(bad), JSON.stringify({ added: 1, duplicates: 0, invalid: 2, overLimit: 0 }));
  assert.equal(JSON.stringify(store.addVariants([], 'Plain')), JSON.stringify({ added: 1, duplicates: 0, invalid: 0, overLimit: 0 }));
  assert.equal(store.addVariants([], 'plain').duplicates, 1, 'plain words stay unique without regard to case');
  assert.equal(store.addVariants(['x'], '').invalid, 1, 'a word is required');
});

test('export writes versioned JSON and import round-trips it, JSON arrays and CSV', () => {
  const createStore = dictionaryFactory();
  const store = createStore(memoryStorage());
  store.add('', 'Kubernetes');
  store.add('cube cuttle', 'kubectl');
  const exported = JSON.parse(store.exportJson());
  assert.equal(exported.format, 'officekit-dictation-dictionary');
  assert.equal(exported.version, 1);
  assert.equal(JSON.stringify(exported.entries), JSON.stringify(store.list()));

  const fresh = createStore(memoryStorage());
  assert.equal(JSON.stringify(fresh.importText(store.exportJson())), JSON.stringify({ added: 2, duplicates: 0, invalid: 0, overLimit: 0 }));
  assert.equal(JSON.stringify(fresh.list()), JSON.stringify(store.list()));
  assert.equal(fresh.importText(store.exportJson()).duplicates, 2, 'importing the same file again changes nothing');

  const other = createStore(memoryStorage());
  assert.equal(other.importText('["Alpha", {"source": "bee", "replacement": "B"}, 5, null]').added, 2);
  assert.equal(other.importText('["Alpha"]').duplicates, 1);

  const csv = createStore(memoryStorage());
  const result = csv.importText('﻿Misheard,Word\r\nopen a i,OpenAI\r\n"quote, comma",Quoted\r\nSolo\r\n\r\na,b,c\r\n');
  assert.equal(JSON.stringify(result), JSON.stringify({ added: 3, duplicates: 0, invalid: 1, overLimit: 0 }));
  assert.equal(JSON.stringify(csv.list()), JSON.stringify([
    { source: 'open a i', replacement: 'OpenAI' },
    { source: 'quote, comma', replacement: 'Quoted' },
    { source: '', replacement: 'Solo' },
  ]));
  assert.equal(createStore(memoryStorage()).importText('a\tb').added, 1, 'tab-separated rows are read too');
  const quoted = createStore(memoryStorage());
  quoted.importText('"say ""hi""",Greeting');
  assert.equal(quoted.list()[0].source, 'say "hi"', 'a doubled quote inside a quoted field is one quote');
});

test('import rejects unreadable files and stays within the 256-entry and size limits', () => {
  const createStore = dictionaryFactory();
  const store = createStore(memoryStorage());
  assert.throws(() => store.importText(''), /empty/i);
  assert.throws(() => store.importText('   \n '), /empty/i);
  assert.throws(() => store.importText(null), /empty/i);
  assert.throws(() => store.importText('{broken'), /not valid JSON/i);
  assert.throws(() => store.importText('{"entries": 5}'), /no dictionary entries/i);
  assert.throws(() => store.importText('x'.repeat(1024 * 1024 + 1)), /larger than 1 MB/i);
  assert.equal(store.list().length, 0, 'a rejected file changes nothing');

  const rows = Array.from({ length: 300 }, (_, index) => `word${index}`).join('\n');
  const result = store.importText(rows);
  assert.equal(JSON.stringify(result), JSON.stringify({ added: 256, duplicates: 0, invalid: 0, overLimit: 44 }));
  assert.equal(store.list().length, 256);

  const huge = createStore(memoryStorage()).importText(Array.from({ length: 2100 }, (_, index) => `w${index}`).join('\n'));
  assert.equal(huge.added, 256);
  assert.equal(huge.overLimit, 2100 - 256, 'rows past the import cap count as not fitting');
  const sameSource = createStore(memoryStorage()).importText('only,one\nonly,two');
  assert.equal(JSON.stringify(sameSource), JSON.stringify({ added: 1, duplicates: 1, invalid: 0, overLimit: 0 }), 'a misheard term maps to one word');
});

test('dictionary card offers variants, Import and Export as text links, not buttons', () => {
  const card = source.slice(source.indexOf('aria-labelledby="dictionary-heading"'), source.indexOf('id="dictation-dictionary-message"'));
  assert.match(card, /id="dictation-dictionary-import"[^>]*class="ok-text-link"/);
  assert.match(card, /id="dictation-dictionary-export"[^>]*class="ok-text-link"/);
  assert.doesNotMatch(card, /id="dictation-dictionary-(import|export)"[^>]*\bbtn\b/);
  assert.match(card, /id="dictation-dictionary-import-file" type="file"/);
  assert.match(card, /separate variants with commas/);
  for (const action of ['chooseDictationDictionaryImport', 'exportDictationDictionary', 'importDictationDictionaryFile']) {
    assert.match(source, new RegExp(`'${action}'`), `${action} is a registered delegated action`);
    assert.match(source, new RegExp(`function ${action}\\(`));
  }
  assert.equal(source, bundled, 'Tauri bundle matches the tested UI');
});

test('personal dictionary fails safely on corrupt storage and storage exceptions', () => {
  const createStore = dictionaryFactory();
  const corrupt = createStore(memoryStorage('{not-json'));
  assert.throws(() => corrupt.list(), /could not be read/i);
  const unavailable = {
    getItem() { return null; },
    setItem() { throw new Error('quota'); },
  };
  assert.throws(() => createStore(unavailable).add('word', 'Word'), /could not be saved/i);
});

test('dictation event setup rolls back partial listeners and can retry without restarting the app', async () => {
  const createManager = dictationEventListenerManagerFactory();
  const manager = createManager();
  const removed = [];
  let failOnce = true;
  const handlers = [
    ['dictation-transcript', () => {}],
    ['dictation-error', () => {}],
    ['dictation-hotkey-state', () => {}],
  ];
  const listen = async (eventName) => {
    if (eventName === 'dictation-error' && failOnce) {
      failOnce = false;
      throw new Error('native event registration denied');
    }
    return () => removed.push(eventName);
  };

  assert.equal(JSON.stringify(await manager.connect(listen, handlers)), JSON.stringify({ ok: false, event: 'dictation-error' }));
  assert.deepEqual(removed, ['dictation-transcript']);
  assert.equal(JSON.stringify(await manager.connect(listen, handlers)), JSON.stringify({ ok: true }));
  assert.deepEqual(removed, ['dictation-transcript']);
  await manager.disconnect();
  assert.deepEqual(removed, ['dictation-transcript', 'dictation-hotkey-state', 'dictation-error', 'dictation-transcript']);
});

test('dictation operation errors use the global toast instead of a setup-card alert', () => {
  const functionSource = source.match(/function setDictationStatus\(message, isError = false\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(functionSource, 'setDictationStatus helper exists');
  assert.match(source, /id="app-feedback-toast"[^>]*role="status"/);
  assert.doesNotMatch(source, /id="dictation-error" role="alert"/);
  const dom = {
    recordingStatus: { textContent: '' },
    toastMessages: [],
  };
  const context = {
    showAppFeedbackToast: (message, state) => dom.toastMessages.push({ message, state }),
    document: {
      getElementById(id) {
        if (id === 'recording-status') return dom.recordingStatus;
        return null;
      },
    },
  };
  const setStatus = vm.runInNewContext(`(${functionSource})`, context);

  // Normal info status
  setStatus('Ready to speak.');
  assert.equal(dom.recordingStatus.textContent, 'Ready to speak.');
  assert.deepEqual(dom.toastMessages, []);

  // Tauri command string error
  setStatus('Allow microphone access before enabling the Right Shift shortcut', true);
  assert.equal(dom.recordingStatus.textContent, 'Ready to speak.', 'operation errors must not appear in the unrelated setup card');
  assert.deepEqual(dom.toastMessages.at(-1), { message: 'Allow microphone access before enabling the Right Shift shortcut', state: 'error' });

  // Error object
  setStatus(new Error('Accessibility permission denied'), true);
  assert.deepEqual(dom.toastMessages.at(-1), { message: 'Accessibility permission denied', state: 'error' });

  // Empty or undefined message must not create an empty toast.
  const messageCount = dom.toastMessages.length;
  setStatus(undefined, true);
  assert.equal(dom.toastMessages.length, messageCount);
});

test('meeting-recording failures remain visible beside the recorder after the global toast closes', () => {
  const screen = source.slice(source.indexOf('<section id="tab-dictate"'), source.indexOf('<section id="tab-unlocker"'));
  assert.match(screen, /id="meeting-record-error"[^>]*role="alert"/);
  const functionSource = source.match(/async function toggleMeetingRecording\(\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(functionSource, 'meeting recorder action exists');
  const statusBadge = { className: '', textContent: 'Recorder idle' };
  const localError = {
    textContent: '',
    hidden: true,
    classList: {
      add: () => { localError.hidden = true; },
      remove: () => { localError.hidden = false; },
    },
  };
  const button = { disabled: false };
  const messages = [];
  const context = {
    meetingRecordingActive: false,
    syncMeetingNotesActionState() {},
    document: {
      getElementById(id) {
        return ({
          'meeting-record-toggle': button,
          'meeting-record-btn-text': null,
          'meeting-record-icon': null,
          'meeting-record-status': statusBadge,
          'meeting-record-error': localError,
          'meeting-audio-source': { value: 'microphone' },
        })[id] ?? null;
      },
    },
    tauriInvoke: () => async () => { throw new Error('Allow microphone access before recording a meeting'); },
    setDictationStatus: (message, isError) => messages.push({ message, isError }),
  };
  const toggle = vm.runInNewContext(`(${functionSource})`, context);
  return toggle().then(() => {
    assert.equal(statusBadge.textContent, 'Recording failed');
    assert.equal(localError.textContent, 'Allow microphone access before recording a meeting');
    assert.equal(localError.hidden, false);
    assert.deepEqual(messages, [{ message: localError.textContent, isError: true }]);
    assert.equal(button.disabled, false);
  });
});

test('whole meeting recording UI, audio source toggling, and event listeners exist', () => {
  assert.ok(source.includes('id="meeting-record-toggle"'), 'Meeting record toggle button exists');
  assert.ok(source.includes('id="meeting-audio-source"'), 'Meeting audio source select exists');
  assert.ok(source.includes('id="meeting-system-audio-note"'), 'Meeting system audio banner exists');
  assert.ok(source.includes('toggleMeetingRecording()'), 'toggleMeetingRecording handler registered');
  assert.ok(source.includes('requestMeetingSystemAudioPermission()'), 'requestMeetingSystemAudioPermission handler registered');
  assert.ok(source.includes('dictation-meeting-chunk'), 'Listens for dictation-meeting-chunk Tauri event');
  assert.ok(source.includes('dictation-meeting-progress'), 'Listens for dictation-meeting-progress Tauri event');
  assert.ok(source.includes('dictation-meeting-stopped'), 'Listens for dictation-meeting-stopped Tauri event');
  assert.ok(source.includes('dictation_meeting_record_start'), 'Calls dictation_meeting_record_start command');
  assert.ok(source.includes('dictation_meeting_record_stop'), 'Calls dictation_meeting_record_stop command');
});

test('meeting translation accumulates separately and survives untranslated segments', () => {
  const functionSource = source.match(/function handleNativeMeetingChunk\(event\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(functionSource);
  const elements = new Map();
  const context = {
    meetingTranscriptDraft: '', meetingTranslationDraft: '',
    document: {getElementById:id=>{if(!elements.has(id)) elements.set(id,{value:'',textContent:'',classList:{add(){},remove(){}}});return elements.get(id);}},
    setDictationLiveTranscript:()=>{}, updateDictationWordCount:()=>{},
  };
  const handleChunk = vm.runInNewContext(`(${functionSource})`, context);
  handleChunk({payload:{text:'வணக்கம்',translated_text:'Hello'}});
  handleChunk({payload:{text:'நன்றி'}});
  assert.equal(elements.get('dictate-transcript').value, 'வணக்கம் நன்றி');
  assert.equal(elements.get('dictation-translation-text').value, 'Hello');
  assert.equal(elements.get('dictation-translation-result').classList.add instanceof Function, true);
});

test('audio tool tabs can switch between voice transcription and meeting notes via delegation', () => {
  const actionsMatch = source.match(/const OFFICEKIT_DELEGATED_ACTIONS = new Set\(\[([\s\S]*?)\]\);/);
  assert.ok(actionsMatch, 'OFFICEKIT_DELEGATED_ACTIONS exists');
  const delegatedActions = new Set(Array.from(actionsMatch[1].matchAll(/'([^']+)'/g), m => m[1]));

  assert.ok(delegatedActions.has('setAudioToolView'), 'setAudioToolView is in delegated actions');
  assert.ok(delegatedActions.has('selectDictationLanguage'), 'selectDictationLanguage is in delegated actions');
  assert.ok(delegatedActions.has('transcribeDictationAudioFile'), 'transcribeDictationAudioFile is in delegated actions');
  assert.ok(delegatedActions.has('copyDictationTranslation'), 'copyDictationTranslation is in delegated actions');
  assert.ok(delegatedActions.has('downloadDictationTranslation'), 'downloadDictationTranslation is in delegated actions');
  assert.ok(delegatedActions.has('dismissAppFeedbackToast'), 'dismissAppFeedbackToast is in delegated actions');

  // Verify all data-officekit-* attributes in the HTML are covered by OFFICEKIT_DELEGATED_ACTIONS
  const callMatches = Array.from(source.matchAll(/data-officekit-[a-z]+="([A-Za-z0-9_$]+)\(/g), m => m[1]);
  for (const callName of callMatches) {
    assert.ok(delegatedActions.has(callName), `delegated action '${callName}' must be in OFFICEKIT_DELEGATED_ACTIONS`);
  }

  // Test setAudioToolView behavior
  const setAudioToolViewSource = source.match(/function setAudioToolView\(view\) \{[\s\S]*?\n        \}/)?.[0];
  assert.ok(setAudioToolViewSource, 'setAudioToolView function exists');

  const elements = new Map();
  function getEl(id) {
    if (!elements.has(id)) {
      elements.set(id, {
        id,
        textContent: '',
        placeholder: '',
        hidden: false,
        nextElementSibling: { textContent: '' },
        dataset: {},
        attributes: {},
        classList: {
          classes: new Set(),
          toggle(cls, state) {
            if (state) this.classes.add(cls);
            else this.classes.delete(cls);
          },
          has(cls) { return this.classes.has(cls); }
        },
        setAttribute(name, val) { this.attributes[name] = String(val); },
        getAttribute(name) { return this.attributes[name]; }
      });
    }
    return elements.get(id);
  }

  const voiceBtn = getEl('voice-btn');
  voiceBtn.dataset.audioToolTab = 'voice';
  const meetingBtn = getEl('meeting-btn');
  meetingBtn.dataset.audioToolTab = 'meeting';

  const voiceCard = getEl('voice-card');
  voiceCard.dataset.audioView = 'voice';
  const meetingCard = getEl('meeting-card');
  meetingCard.dataset.audioView = 'meeting';

  const context = {
    document: {
      getElementById: id => getEl(id),
      querySelectorAll: selector => {
        if (selector === '[data-audio-view]') return [voiceCard, meetingCard];
        if (selector === '[data-audio-tool-tab]') return [voiceBtn, meetingBtn];
        return [];
      }
    },
    window: { officekitAudioToolView: '', OfficeKitToolActions: { schedule() {} } },
    syncMeetingNotesActionState() {}
  };

  const setAudioToolView = vm.runInNewContext(`(${setAudioToolViewSource})`, context);

  // Switch to meeting view
  setAudioToolView('meeting');
  assert.equal(getEl('audio-tool-title').textContent, 'Meeting Notes');
  assert.equal(context.window.officekitAudioToolView, 'meeting');
  assert.equal(meetingBtn.attributes['aria-selected'], 'true');
  assert.equal(voiceBtn.attributes['aria-selected'], 'false');
  assert.equal(voiceCard.hidden, true);
  assert.equal(meetingCard.hidden, false);

  // Switch back to voice transcription view
  setAudioToolView('voice');
  assert.equal(getEl('audio-tool-title').textContent, 'Voice Transcription');
  assert.equal(context.window.officekitAudioToolView, 'voice');
  assert.equal(voiceBtn.attributes['aria-selected'], 'true');
  assert.equal(meetingBtn.attributes['aria-selected'], 'false');
  assert.equal(voiceCard.hidden, false);
  assert.equal(meetingCard.hidden, true);
});

function vocabularyHelpers(context) {
  const terms = source.match(/function dictationVocabularyTerms\([\s\S]*?\n        }/)?.[0];
  const sync = source.match(/function syncDictationVocabulary\([\s\S]*?\n        }/)?.[0];
  assert.ok(terms && sync, 'vocabulary helpers exist');
  return vm.runInNewContext(`(() => { ${terms}\n${sync}\nreturn { dictationVocabularyTerms, syncDictationVocabulary }; })()`, context);
}

test('dictionary replacement targets become a deduplicated, bounded Whisper vocabulary', () => {
  const { dictationVocabularyTerms } = vocabularyHelpers({});
  assert.equal(
    JSON.stringify(dictationVocabularyTerms([
      { source: 'office kit', replacement: 'OfficeKit' },
      { source: 'officekit', replacement: 'officekit' },
      { source: 'jason', replacement: 'JSON' },
    ])),
    JSON.stringify(['OfficeKit', 'JSON']),
  );
  const many = Array.from({ length: 300 }, (_, index) => ({ source: `s${index}`, replacement: `t${index}` }));
  assert.equal(dictationVocabularyTerms(many).length, 256);
});

test('vocabulary sync calls the native command only in the desktop app and never throws', async () => {
  const calls = [];
  const desktop = vocabularyHelpers({
    window: { __TAURI__: { core: { invoke() {} } } },
    tauriInvoke: () => (command, args) => { calls.push([command, args]); return Promise.reject(new Error('busy')); },
  });
  desktop.syncDictationVocabulary([{ source: 'office kit', replacement: 'OfficeKit' }]);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(JSON.stringify(calls), JSON.stringify([['dictation_set_vocabulary', { terms: ['OfficeKit'] }]]));

  const browser = vocabularyHelpers({ window: {}, tauriInvoke: () => { throw new Error('must not be called'); } });
  browser.syncDictationVocabulary([{ source: 'a', replacement: 'B' }]);
});

function suggestionsFactory() {
  const functionSource = source.match(/function createOfficeKitDictationSuggestions\([\s\S]*?\n        }/)?.[0];
  assert.ok(functionSource, 'dictionary suggestion store exists');
  return vm.runInNewContext(`(${functionSource})`, {});
}

const pairs = list => list.map(entry => `${entry.source}→${entry.replacement}`);

test('edits that fix a name or brand become dictionary suggestions immediately', () => {
  const store = suggestionsFactory()(memoryStorage());
  store.learn('please email sedu about the report', 'please email Sedhu about the report');
  store.learn('we use office kit every day', 'we use OfficeKit every day');
  assert.equal(JSON.stringify(pairs(store.list())), JSON.stringify(['office kit→OfficeKit', 'sedu→Sedhu']));
});

test('plain lowercase and case-only fixes need a second sighting before they are suggested', () => {
  const store = suggestionsFactory()(memoryStorage());
  store.learn('i will recieve the file', 'i will receive the file');
  assert.equal(store.list().length, 0);
  store.learn('did you recieve it', 'did you receive it');
  assert.equal(JSON.stringify(pairs(store.list())), JSON.stringify(['recieve→receive']));

  const casing = suggestionsFactory()(memoryStorage());
  casing.learn('the plan is ready', 'The plan is ready');
  assert.equal(casing.list().length, 0, 'sentence capitalization alone is not a vocabulary signal');
});

test('capital-only fixes never suggest short words and need three sightings for longer ones', () => {
  const store = suggestionsFactory()(memoryStorage());
  for (let round = 0; round < 6; round += 1) store.learn(`the plan ${round} is ready`, `The plan ${round} is ready`);
  assert.equal(store.list().length, 0, 'a repeated sentence-start capital is not a dictionary entry');

  const proper = suggestionsFactory()(memoryStorage());
  proper.learn('we run kubernetes here', 'we run Kubernetes here');
  proper.learn('deploy kubernetes today', 'deploy Kubernetes today');
  assert.equal(proper.list().length, 0, 'two capital-only sightings are not enough');
  proper.learn('is kubernetes ready', 'is Kubernetes ready');
  assert.equal(JSON.stringify(pairs(proper.list())), JSON.stringify(['kubernetes→Kubernetes']));
});

test('pending sightings and dismissals stay bounded in storage', () => {
  const storage = memoryStorage();
  const store = suggestionsFactory()(storage);
  const letters = index => index.toString(26).replace(/\d/g, digit => String.fromCharCode(113 + Number(digit)));
  for (let index = 0; index < 100; index += 1) store.learn(`say plain${letters(index)}x now`, `say plain${letters(index)}y now`);
  const pending = JSON.parse(storage.getItem('officekit.dictation.suggestions.pending.v1') || '{}');
  assert.ok(Object.keys(pending).length <= 64);
  assert.equal(store.list().length, 0, 'single lowercase sightings are only counted, never suggested');
});

test('rewrites, long edits and unrelated word swaps never produce suggestions', () => {
  const store = suggestionsFactory()(memoryStorage());
  store.learn('we ship on friday afternoon', 'we deliver on Monday morning');
  store.learn('send it to the team', 'send it to the entire engineering and design organization');
  store.learn('the plan is good', 'a Totally different sentence appears here now');
  store.learn('', 'anything');
  store.learn('same text', 'same text');
  assert.equal(store.list().length, 0);
  const long = Array.from({ length: 401 }, (_, index) => `word${index}`).join(' ');
  store.learn(long, long.replace('word5 ', 'Word5x '));
  assert.equal(store.list().length, 0, 'transcripts over 400 words are skipped');
});

test('suggestions skip known dictionary sources, dismissed pairs and duplicates, and stay bounded', () => {
  const createStore = suggestionsFactory();
  const storage = memoryStorage();
  const store = createStore(storage);
  store.learn('ask sedu now', 'ask Sedhu now', [{ source: 'Sedu', replacement: 'Sedhu' }]);
  assert.equal(store.list().length, 0, 'terms already in the dictionary are not suggested');

  store.learn('ask sedu now', 'ask Sedhu now');
  store.learn('ask sedu again', 'ask Sedhu again');
  assert.equal(store.list().length, 1, 'the same pair is not suggested twice');
  assert.equal(store.dismiss(0), true);
  store.learn('ask sedu later', 'ask Sedhu later');
  assert.equal(store.list().length, 0, 'a dismissed pair is not suggested again');
  assert.equal(createStore(storage).list().length, 0, 'dismissals persist');

  const many = createStore(memoryStorage());
  for (let index = 0; index < 30; index += 1) many.learn(`say bravo${index}x now`, `say Bravo${index}y now`);
  assert.ok(many.list().length <= 20);
});

test('accepting removes one suggestion, and removing an unknown index changes nothing', () => {
  const store = suggestionsFactory()(memoryStorage());
  store.learn('hi sedu', 'hi Sedhu');
  store.learn('use office kit', 'use OfficeKit');
  assert.equal(store.remove(5), null);
  assert.equal(store.remove(-1), null);
  assert.equal(store.remove(0).replacement, 'OfficeKit');
  assert.equal(JSON.stringify(pairs(store.list())), JSON.stringify(['sedu→Sedhu']));
});

test('suggestion storage fails open: corrupt data is ignored and write errors never throw', () => {
  const createStore = suggestionsFactory();
  const corrupt = createStore(memoryStorage('{not json'));
  assert.equal(corrupt.list().length, 0);
  const badShape = createStore(memoryStorage(JSON.stringify([{ source: 5, replacement: 'x' }, { source: 'a\u0000b', replacement: 'c' }, { source: 'ok', replacement: 'Fine' }])));
  assert.equal(JSON.stringify(pairs(badShape.list())), JSON.stringify(['ok→Fine']));
  const broken = createStore({ getItem() { throw new Error('blocked'); }, setItem() { throw new Error('full'); } });
  assert.equal(JSON.stringify(broken.learn('hi sedu', 'hi Sedhu')), '[]');
  assert.equal(broken.list().length, 0);
  assert.equal(broken.dismiss(0), false);
});

function smartPreferencesFactory() {
  const functionSource = source.match(/function createOfficeKitDictationSmartPreferences\([\s\S]*?\n        }/)?.[0];
  assert.ok(functionSource, 'smart dictation preference store exists');
  return vm.runInNewContext(`(${functionSource})`, {});
}

test('smart dictation preferences default to cleanup and app context on, field text off', () => {
  const store = smartPreferencesFactory()(memoryStorage());
  assert.equal(JSON.stringify(store.all()), JSON.stringify({ smartCleanup: true, appContext: true, fieldText: false, fasterResults: true, fixGrammar: false, rawAudio: false }));
});

test('smart dictation preferences persist, reject unknown names and survive broken storage', () => {
  const createStore = smartPreferencesFactory();
  const storage = memoryStorage();
  const store = createStore(storage);
  store.set('fieldText', true);
  store.set('smartCleanup', false);
  assert.equal(JSON.stringify(createStore(storage).all()), JSON.stringify({ smartCleanup: false, appContext: true, fieldText: true, fasterResults: true, fixGrammar: false, rawAudio: false }));
  store.set('rawAudio', true);
  assert.equal(createStore(storage).all().rawAudio, true, 'raw audio is saved for the next launch');
  store.set('rawAudio', false);
  assert.throws(() => store.set('unknown', true), /unknown smart dictation setting/i);
  assert.throws(() => store.set('fieldText', 'yes'), /unknown smart dictation setting/i);
  assert.equal(JSON.stringify(createStore(memoryStorage('garbage')).all()), JSON.stringify({ smartCleanup: true, appContext: true, fieldText: false, fasterResults: true, fixGrammar: false, rawAudio: false }));

  const broken = createStore({ getItem() { throw new Error('blocked'); }, setItem() { throw new Error('full'); } });
  assert.equal(JSON.stringify(broken.all()), JSON.stringify({ smartCleanup: true, appContext: true, fieldText: false, fasterResults: true, fixGrammar: false, rawAudio: false }));
  assert.throws(() => broken.set('appContext', false), /could not be saved/i);
});

function appModesFactory() {
  const functionSource = source.match(/function createOfficeKitDictationAppModes\([\s\S]*?\n        }/)?.[0];
  assert.ok(functionSource, 'per-app dictation store exists');
  return vm.runInNewContext(`(${functionSource})`, {});
}

test('per-app settings remember apps newest first, keep choices and reject bad bundle ids', () => {
  const createStore = appModesFactory();
  const storage = memoryStorage();
  const store = createStore(storage);
  assert.equal(store.list().length, 0);
  assert.equal(store.remember('com.apple.mail', 'Mail'), true);
  assert.equal(store.remember('com.apple.Terminal', 'Terminal'), true);
  store.setChoice('com.apple.mail', 'smart', 'on');
  assert.equal(store.remember('COM.APPLE.MAIL', 'Mail'), true, 'a repeat moves the app up and keeps its choices');
  assert.equal(JSON.stringify(store.list().map(app => [app.bundleId, app.smart])), JSON.stringify([['com.apple.mail', 'on'], ['com.apple.Terminal', 'default']]));
  for (const bad of ['', 'has space', 'a/b', 'x'.repeat(129), null, 7]) assert.equal(store.remember(bad, 'X'), false, String(bad));
  assert.equal(store.list().length, 2);
  assert.equal(JSON.stringify(createStore(storage).list().map(app => app.name)), JSON.stringify(['Mail', 'Terminal']), 'the list is saved on this Mac');
});

test('per-app choices are validated and become native modes only when explicit', () => {
  const store = appModesFactory()(memoryStorage());
  store.remember('com.apple.mail', 'Mail');
  store.remember('com.apple.Terminal', 'Terminal');
  store.remember('com.tinyspeck.slackmacgap', 'Slack');
  store.setChoice('com.apple.mail', 'smart', 'on');
  store.setChoice('com.apple.mail', 'fixGrammar', 'off');
  store.setChoice('com.apple.Terminal', 'smart', 'off');
  const sorted = modes => JSON.stringify(Object.entries(modes).sort(([left], [right]) => left.localeCompare(right)));
  assert.equal(sorted(store.nativeModes()), sorted({
    'com.apple.Terminal': { smart: false },
    'com.apple.mail': { smart: true, fixGrammar: false },
  }), 'Slack stays on Default and is not sent');
  store.setChoice('com.apple.Terminal', 'smart', 'default');
  assert.equal(JSON.stringify(Object.keys(store.nativeModes())), JSON.stringify(['com.apple.mail']));
  assert.throws(() => store.setChoice('com.apple.mail', 'smart', 'maybe'), /unknown per-app setting/i);
  assert.throws(() => store.setChoice('com.apple.mail', 'other', 'on'), /unknown per-app setting/i);
  assert.throws(() => store.setChoice('not.listed', 'smart', 'on'), /not in the list/i);
});

test('per-app settings are bounded to 64 apps, sanitize names and survive corrupt or blocked storage', () => {
  const createStore = appModesFactory();
  const store = createStore(memoryStorage());
  for (let index = 0; index < 70; index += 1) store.remember(`app.n${index}`, `App ${index}`);
  assert.equal(store.list().length, 64);
  assert.equal(store.list()[0].bundleId, 'app.n69', 'newest first; the oldest fall off');
  store.remember('control.name', 'Bad\u0000\nName'.padEnd(100, 'x'));
  const stored = store.list()[0];
  assert.ok(!/[\u0000-\u001f]/.test(stored.name) && stored.name.length <= 64);
  assert.equal(createStore(memoryStorage('{not json')).list().length, 0);
  assert.equal(createStore(memoryStorage('[{"bundleId":"bad id"},{"bundleId":"ok.id","smart":"zzz"}]')).list()[0].smart, 'default');
  const blocked = createStore({ getItem() { throw new Error('blocked'); }, setItem() { throw new Error('full'); } });
  assert.equal(blocked.list().length, 0);
  assert.throws(() => blocked.remember('a.b', 'A'), /could not be saved/i);
});

test('Smart dictation card has the Per app table with dropdowns only and sends the choices to the native cleanup', () => {
  const card = source.slice(source.indexOf('id="dictation-smart-card"'), source.indexOf('id="dictation-smart-message"'));
  assert.match(card, /id="dictation-app-modes-title"[^>]*>Per app</);
  assert.match(card, /Smart cleanup<\/th>[\s\S]*Fix grammar<\/th>/);
  assert.match(card, /id="dictation-app-modes-empty"[^>]*>No apps yet\. Dictate into an app/);
  assert.match(card, /Needs “Use the app you are typing in” to be on/);
  const section = card.slice(card.indexOf('id="dictation-app-modes"'));
  assert.doesNotMatch(section, /<button/, 'the Per app section adds no buttons');
  assert.match(source, /appModes: dictationNativeAppModes\(\)/);
  assert.match(source, /rememberDictationApp\(result\.app\)/);
  assert.match(source, /dictationSmartPreferencesStore\?\.all\(\)\.appContext/, 'apps are only remembered while app context is on');
  assert.match(source, /select\.setAttribute\('aria-label', `\$\{title\} for \$\{app\.name\}`\)/);
  assert.equal(source, bundled, 'Tauri bundle matches the tested UI');
});

test('cleanup mode and language hint follow the saved preference, the spoken language and the model', () => {
  const helpers = (context) => {
    const names = ['dictationSmartCleanupMode', 'dictationLanguageHint'];
    const body = names.map(name => source.match(new RegExp(`function ${name}\\([\\s\\S]*?\\n        }`))?.[0]);
    assert.ok(body.every(Boolean), 'helpers exist');
    return vm.runInNewContext(`(() => { let dictationSmartPreferencesStore = __store; ${body.join('\n')}\nreturn { ${names.join(', ')} }; })()`, context);
  };
  const store = (smartCleanup) => ({ all: () => ({ smartCleanup }) });
  assert.equal(helpers({ __store: store(true) }).dictationSmartCleanupMode(), 'smart');
  assert.equal(helpers({ __store: store(false) }).dictationSmartCleanupMode(), 'rules');
  assert.equal(helpers({ __store: null }).dictationSmartCleanupMode(), 'rules');

  const hint = (language, model) => helpers({
    __store: null,
    currentDictationSpokenLanguage: language,
    window: { localStorage: { getItem: () => model } },
  }).dictationLanguageHint();
  assert.equal(hint('de', 'whisper_small'), 'de');
  assert.equal(hint('auto', 'parakeet_v2'), 'en');
  assert.equal(hint('auto', 'parakeet_v3'), undefined);
  assert.equal(hint('auto', null), undefined);
});

test('smart dictation card exposes accessible switches and wires cleanup and context to the native commands', () => {
  for (const id of ['dictation-smart-card', 'dictation-smart-cleanup', 'dictation-app-context', 'dictation-field-text', 'dictation-faster-results', 'dictation-field-text-state', 'dictation-smart-message']) {
    assert.match(source, new RegExp(`id="${id}"`), id);
  }
  for (const id of ['dictation-smart-cleanup', 'dictation-app-context', 'dictation-field-text', 'dictation-faster-results']) {
    assert.match(source, new RegExp(`id="${id}"[^>]*aria-labelledby="${id}-title"|id="${id}"[^>]*aria-labelledby="[a-z-]+-title"`), `${id} has an accessible name`);
    assert.match(source, new RegExp(`id="${id}"[^>]*aria-describedby=`), `${id} has a description`);
  }
  assert.match(source, /mode: dictationSmartCleanupMode\(\),\s*language: dictationLanguageHint\(\),/);
  assert.match(source, /'dictation_set_context_options', \{ appContext, fieldText \}/);
  assert.match(source, /'dictation_set_streaming_commit', \{ enabled: fasterResults \}/);
  assert.match(source, /initDictationSmartPreferences\(\);/);
  assert.match(source, /aria-live="polite" class="mt-2 text-sm text-slate-600"><\/p>\s*<\/section>\s*<section data-audio-view="voice"[^>]*aria-labelledby="dictionary-heading"/);
  const rust = fs.readFileSync(path.join(root, 'src-tauri/src/lib.rs'), 'utf8');
  assert.match(rust, /dictation_set_context_options,\n/);
  assert.match(rust, /dictation_set_streaming_commit,\n/);
  assert.match(source, /Password fields are always skipped/);
});

test('rendering the dictionary keeps the native vocabulary in sync and the command is registered', () => {
  assert.match(source, /syncDictationVocabulary\(entries\);/);
  const rust = fs.readFileSync(path.join(root, 'src-tauri/src/lib.rs'), 'utf8');
  assert.match(rust, /fn dictation_set_vocabulary\(/);
  assert.match(rust, /dictation_set_vocabulary,\n/);
});

const stepsFixture = () => ({
  heard: 'so um I think we ship Friday no wait Thursday',
  afterSmart: 'so I think we ship Thursday',
  dictionaryChanges: [{ from: 'easy D P', to: 'easydp' }],
  rulesText: 'So I think we ship Thursday.',
  polished: false,
  delivery: 'paste-requested-clipboard-retained',
  capture: { recordedSeconds: 14.2, speechSeconds: 11.8, hadSpeech: true, levelDb: -31 },
  settings: { smartCleanup: true, fasterResults: true, appContext: false, fixGrammar: false },
});

test('history keeps the processing steps with the transcript and drops malformed ones', () => {
  const storage = memoryStorage();
  const history = transcriptHistoryFactory(storage);
  history.add('So I think we ship Thursday.', 'push-to-talk', stepsFixture());
  history.add('No steps here.', 'meeting');
  history.add('Bad steps.', 'push-to-talk', { heard: 5, rulesText: 'x' });
  const [bad, plain, withSteps] = JSON.parse(JSON.stringify(history.list()));
  assert.deepEqual(withSteps.steps, stepsFixture());
  assert.equal(plain.steps, undefined);
  assert.equal(bad.steps, undefined, 'malformed steps never block saving the transcript');
  assert.deepEqual(JSON.parse(JSON.stringify(transcriptHistoryFactory(storage).list()[2].steps)), stepsFixture(), 'steps survive a reload');
  history.remove(withSteps.id);
  assert.equal(JSON.parse(storage.raw).some(entry => entry.steps), false, 'removing the transcript removes its steps');
});

test('history steps are bounded and unknown fields are stripped on read', () => {
  const history = transcriptHistoryFactory(memoryStorage());
  const steps = { ...stepsFixture(), extra: 'x', capture: { recordedSeconds: Infinity, speechSeconds: 1, hadSpeech: true },
    dictionaryChanges: Array.from({ length: 60 }, (_, index) => ({ from: `a${index}`, to: 'b' })).concat([{ from: 1, to: 'x' }]),
    settings: 'on', afterSmart: 7 };
  history.add('Text.', 'push-to-talk', steps);
  const saved = JSON.parse(JSON.stringify(history.list()[0].steps));
  assert.equal(saved.extra, undefined);
  assert.equal(saved.capture, undefined, 'non-finite numbers are rejected');
  assert.equal(saved.dictionaryChanges.length, 50);
  assert.equal(saved.settings, undefined);
  assert.equal(saved.afterSmart, null);
});

test('the steps record maps the native result and settings, and is absent without steps', () => {
  const build = stepsRecordFunctions().dictationStepsRecord;
  const record = build(
    { text: 'raw words', capture: { recorded_seconds: 6, speech_seconds: 0, had_speech: false, level_db: null } },
    { delivery_status: 'paste-failed-transcript-retained', steps: { after_smart: null, dictionary_changes: [{ from: 'a', to: 'b' }], rules_text: 'Raw words.', polished: true } },
  );
  assert.deepEqual(JSON.parse(JSON.stringify(record)), {
    heard: 'raw words', afterSmart: null, dictionaryChanges: [{ from: 'a', to: 'b' }], rulesText: 'Raw words.', polished: true,
    delivery: 'paste-failed-transcript-retained',
    capture: { recordedSeconds: 6, speechSeconds: 0, hadSpeech: false, levelDb: null },
    settings: { smartCleanup: true, fasterResults: false, appContext: true, fixGrammar: false },
  });
  const grammar = build({ text: 'we was late' }, { delivery_status: 'x', steps: { after_smart: null, dictionary_changes: [], rules_text: 'We was late.', grammar_text: 'We were late.', grammar_fixes: [{ from: 'was', to: 'were', hint: 'Agreement' }], polished: false } });
  assert.equal(grammar.grammarText, 'We were late.');
  assert.deepEqual(JSON.parse(JSON.stringify(grammar.grammarFixes)), [{ from: 'was', to: 'were', hint: 'Agreement' }]);
  assert.equal(build({ text: 'raw' }, { text: 'Raw.' }), undefined);
});

function stepsRecordFunctions() {
  const names = ['dictationStepsRecord', 'dictationCaptureRecord', 'dictationFailureRecord'];
  const bodies = names.map(name => source.match(new RegExp(`function ${name}\\([^)]*\\) \\{[\\s\\S]*?\\n        }`))?.[0]);
  bodies.forEach((body, index) => assert.ok(body, names[index]));
  return vm.runInNewContext(`var dictationSmartPreferencesStore = { all: () => ({ smartCleanup: true, fasterResults: false, appContext: true }) };
    ${bodies.join('\n')}; ({ ${names.join(', ')} })`, {});
}

function levelFunctions() {
  const names = ['dictationWordCount', 'dictationLostWords', 'dictationLevels', 'dictationLossLevel', 'dictationFailureSummary'];
  const bodies = names.map(name => source.match(new RegExp(`function ${name}\\([^)]*\\) \\{[\\s\\S]*?\\n        }`))?.[0]);
  bodies.forEach((body, index) => assert.ok(body, names[index]));
  return vm.runInNewContext(`const DICTATION_LOSS_RATIO = 0.7, DICTATION_LOSS_MIN_WORDS = 5;
    ${bodies.join('\n')}; ({ ${names.join(', ')} })`, {});
}

test('the steps record carries the model, pieces and translation from the native event', () => {
  const { dictationStepsRecord } = stepsRecordFunctions();
  const record = JSON.parse(JSON.stringify(dictationStepsRecord(
    { text: 'bonjour tout le monde', translated_text: 'hello everyone', model: 'Whisper Small', pieces: ['bonjour', 'tout le monde'] },
    { steps: { after_smart: null, dictionary_changes: [], rules_text: 'Hello everyone.', polished: false } },
  )));
  assert.equal(record.translated, 'hello everyone');
  assert.equal(record.model, 'Whisper Small');
  assert.deepEqual(record.pieces, ['bonjour', 'tout le monde']);
});

test('a failed attempt record keeps the numbers and kind, and has no text unless the raw text exists', () => {
  const { dictationFailureRecord } = stepsRecordFunctions();
  const noSpeech = JSON.parse(JSON.stringify(dictationFailureRecord('no-speech', 'No speech was recognized.', {
    message: 'x', capture: { recorded_seconds: 6, speech_seconds: 0, had_speech: false, level_db: -58 }, model: 'Whisper Small',
  })));
  assert.equal(noSpeech.heard, '');
  assert.deepEqual(noSpeech.failure, { kind: 'no-speech', message: 'No speech was recognized.' });
  assert.deepEqual(noSpeech.capture, { recordedSeconds: 6, speechSeconds: 0, hadSpeech: false, levelDb: -58 });
  assert.equal(dictationFailureRecord('cleanup-failed', 'x'.repeat(500), { text: 'raw words' }).heard, 'raw words');
  assert.equal(dictationFailureRecord('cleanup-failed', 'x'.repeat(500), { text: 'raw' }).failure.message.length, 400);
});

test('history stores attempts that produced no text, but never an empty finished transcript', () => {
  const { dictationFailureRecord } = stepsRecordFunctions();
  const history = transcriptHistoryFactory(memoryStorage());
  history.add('', 'push-to-talk', dictationFailureRecord('no-speech', 'No speech was recognized.', { capture: { recorded_seconds: 6, speech_seconds: 0, had_speech: false, level_db: null } }));
  history.add('', 'push-to-talk', dictationFailureRecord('model-error', 'Local transcription failed', {}));
  history.add('raw words', 'push-to-talk', dictationFailureRecord('cleanup-failed', 'Local transcript cleanup failed', { text: 'raw words' }));
  const [cleanup, model, silent] = JSON.parse(JSON.stringify(history.list()));
  assert.equal(silent.text, '');
  assert.equal(silent.steps.failure.kind, 'no-speech');
  assert.equal(silent.steps.capture.levelDb, null);
  assert.equal(model.steps.failure.kind, 'model-error');
  assert.equal(cleanup.text, 'raw words');
  assert.throws(() => history.add('', 'push-to-talk'), /cannot be saved/);
  assert.throws(() => history.add('  ', 'push-to-talk', { heard: 'x', rulesText: 'x' }), /cannot be saved/);
  assert.throws(() => history.add('', 'push-to-talk', { ...dictationFailureRecord('cleanup-failed', 'x', {}) }), /cannot be saved/, 'cleanup-failed needs its raw text');
  assert.throws(() => history.add('', 'bogus', dictationFailureRecord('no-speech', 'x', {})), /cannot be saved/);
  history.remove(silent.id);
  assert.equal(history.list().length, 2);
});

test('word counts name the level that lost words and the history row says so', () => {
  const { dictationLostWords, dictationLossLevel, dictationLevels, dictationWordCount, dictationFailureSummary } = levelFunctions();
  assert.equal(dictationWordCount('  one  two\nthree '), 3);
  assert.equal(dictationWordCount(''), 0);
  assert.equal(dictationLostWords('a b c d', 'a'), null, 'fewer than five words is never flagged');
  assert.equal(dictationLostWords('a b c d e f g h i j', 'a b c d e f g h'), null, 'losing 20% is not flagged');
  assert.equal(dictationLostWords('a b c d e f g h i j', 'a b c d e f g').percent, 30, 'losing 30% is flagged');
  assert.equal(dictationLostWords('a b c d e f g h i j', 'a b c d e f').percent, 40);
  const entry = (steps, text) => ({ text, steps: { dictionaryChanges: [], polished: false, ...steps } });
  const lostInSmart = entry({ heard: 'so um I think we should send the invoice before noon and the the receipts to Sedhu no wait to Priya', afterSmart: 'so I think we should send the invoice Priya', rulesText: 'So I think we should send the invoice Priya.' }, 'So I think we should send the invoice Priya.');
  assert.equal(dictationLossLevel(lostInSmart), 'smart');
  assert.equal(dictationLossLevel(entry({ heard: 'one two three four five six', afterSmart: 'one two three four five six', rulesText: 'One two three four five six.' }, 'One two three four five six.')), null);
  assert.equal(dictationLossLevel(entry({ heard: 'a b c d e f g h i j', afterSmart: null, rulesText: 'A b c d e f g h i j.', polished: true }, 'A b c')), 'polish');
  assert.equal(dictationLossLevel(entry({ heard: 'a b c d e f g h', translated: 'one two three four five six seven eight', afterSmart: null, rulesText: 'One two.' }, 'One two.')), 'tidy');
  assert.equal(dictationLevels(entry({ heard: 'bonjour', translated: 'hello', afterSmart: 'hello', rulesText: 'Hello.' }, 'Hello.')).smart.before, 'hello', 'cleanup starts from the translation');
  assert.equal(dictationLossLevel({ text: 'x', steps: { failure: { kind: 'cancelled', message: 'x' }, heard: 'a b c d e f', rulesText: null } }), null);
  assert.match(dictationFailureSummary({ steps: { failure: { kind: 'no-speech', message: 'm' }, capture: { recordedSeconds: 6, levelDb: -58 } } }), /Recorded 6\.0 s, loudest level -58 dB/);
  assert.match(dictationFailureSummary({ steps: { failure: { kind: 'model-error', message: 'm' }, capture: { recordedSeconds: 9.4, levelDb: -20 } } }), /failed after 9\.4 s of audio/);
  assert.equal(dictationFailureSummary({ steps: { failure: { kind: 'capture-error', message: 'Audio capture failed' } } }), 'Audio capture failed');
  assert.equal(dictationFailureSummary({ text: 'ok' }), '');
});

test('the failed-attempt event is registered and saves one entry without text', async () => {
  assert.match(source, /\['dictation-attempt-failed', handleNativeDictationAttemptFailed\]/);
  const handler = source.match(/function handleNativeDictationAttemptFailed\(event\) \{[\s\S]*?\n        }/)?.[0];
  assert.ok(handler);
  const { dictationFailureRecord } = stepsRecordFunctions();
  const saved = [];
  const run = vm.runInNewContext(`(${handler})`, { saveDictationHistory: (...args) => saved.push(args), dictationFailureRecord });
  run({ payload: { kind: 'no-speech', message: 'No speech was recognized.', capture: { recorded_seconds: 6, speech_seconds: 0, had_speech: false, level_db: -58 } } });
  run({ payload: { kind: 'model-error' } });
  run({});
  assert.equal(saved.length, 1);
  assert.equal(saved[0][0], '');
  assert.equal(saved[0][1], 'push-to-talk');
  assert.equal(saved[0][2].failure.kind, 'no-speech');
});

test('removed words are found by comparing the raw and smart text, ignoring case and punctuation', () => {
  const functionSource = source.match(/function dictationRemovedWords\(before, after\) \{[\s\S]*?\n        }/)?.[0];
  assert.ok(functionSource);
  const diff = vm.runInNewContext(`(${functionSource})`, { Uint16Array });
  const removed = (before, after) => Array.from(diff(before, after)).filter(item => item.removed).map(item => item.word);
  assert.deepEqual(removed('so um I think we ship Friday no wait Thursday and the the notes', 'So I think we ship Thursday and the notes.'), ['um', 'Friday', 'no', 'wait', 'the']);
  assert.deepEqual(removed('nothing changes here', 'Nothing changes here.'), []);
  assert.equal(diff('a b c', 'a b c').map(item => item.word).join(' '), 'a b c', 'every raw word is still shown');
  assert.deepEqual(removed('x '.repeat(3000), 'x '.repeat(2500)), [], 'oversized comparisons are skipped, not slow');
});

test('the transcript history exposes a steps view with a back link, Escape and exactly two actions', () => {
  assert.match(source, /id="dictation-history-detail"/);
  assert.match(source, /id="dictation-history-main"/);
  assert.match(source, /event\.key === 'Escape'\) hideDictationHistoryDetail\(\)/);
  const detail = source.match(/function showDictationHistoryDetail\(id\) \{[\s\S]*?\n        }/)[0];
  assert.equal((detail.match(/copyButton\('/g) || []).length, 2, 'Copy raw and Copy final');
  assert.match(detail, /make\('a', 'dictation-history-back'/, 'Back is a link, not a button');
  assert.doesNotMatch(detail, /innerHTML/, 'transcript text is never parsed as HTML');
});

