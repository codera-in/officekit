(function (global) {
  'use strict';
  const kinds = ['break', 'eyes', 'water', 'posture', 'meeting'];
  const corners = ['bottom-right', 'bottom-left', 'top-right', 'top-left'];
  const defaults = () => ({version:1, corner:'bottom-right', reducedMotion:false,
    quietHours:{enabled:true,startMinutes:1320,endMinutes:480},
    breaks:{enabled:false,intervalMinutes:50,durationSeconds:120,snoozeMinutes:5},
    eyes:{enabled:false,intervalMinutes:20,durationSeconds:20,snoozeMinutes:5},
    water:{enabled:false,intervalMinutes:60,durationSeconds:0,snoozeMinutes:5},
    posture:{enabled:false,dwellSeconds:20,cooldownMinutes:5,snoozeMinutes:5},
    meetings:{enabled:false,allCalendars:true,calendarIds:[],offerRecording:false}});
  const clone = value => JSON.parse(JSON.stringify(value));
  function validate(settings) {
    if (!settings || settings.version !== 1 || !corners.includes(settings.corner) || typeof settings.reducedMotion !== 'boolean') return false;
    const integer = (value,min,max) => Number.isInteger(value) && value >= min && value <= max;
    const quiet = settings.quietHours;
    if (!quiet || typeof quiet.enabled !== 'boolean' || !integer(quiet.startMinutes,0,1439) || !integer(quiet.endMinutes,0,1439) || quiet.startMinutes === quiet.endMinutes) return false;
    for (const [key,max,minDuration,maxDuration] of [['breaks',180,20,900],['eyes',120,10,120],['water',240,0,0]]) {
      const item = settings[key];
      if (!item || typeof item.enabled !== 'boolean' || !integer(item.intervalMinutes,5,max) || !integer(item.durationSeconds,minDuration,maxDuration) || !integer(item.snoozeMinutes,1,60)) return false;
    }
    const posture = settings.posture;
    const meetings = settings.meetings;
    if (meetings && (typeof meetings.enabled !== 'boolean' || typeof meetings.allCalendars !== 'boolean' || typeof meetings.offerRecording !== 'boolean' || !Array.isArray(meetings.calendarIds) || meetings.calendarIds.length > 256 || new Set(meetings.calendarIds).size !== meetings.calendarIds.length || meetings.calendarIds.some(id=>typeof id !== 'string' || !id || new TextEncoder().encode(id).length > 2048))) return false;
    return !!posture && typeof posture.enabled === 'boolean' && integer(posture.dwellSeconds,5,120) && integer(posture.cooldownMinutes,1,60) && integer(posture.snoozeMinutes,1,60);
  }
  const time = minutes => `${String(Math.floor(minutes/60)).padStart(2,'0')}:${String(minutes%60).padStart(2,'0')}`;
  const minutes = value => /^\d{2}:\d{2}$/.test(value) ? Number(value.slice(0,2))*60 + Number(value.slice(3)) : NaN;
  const motionText = {
    disabled:'Head-angle sensing is off.', 'permission-needed':'Motion access is needed. Enable sensing to request it.',
    denied:'Motion access was denied. Allow OfficeKit motion access in System Settings, then try again.',
    unavailable:'Compatible AirPods motion is unavailable on this device.', calibrating:'Sit comfortably while your baseline is measured.',
    ready:'Baseline ready. Sustained head tilt can trigger a gentle nudge.', disconnected:'AirPods disconnected. Sensing is paused.',
    stale:'Motion readings are stale. Sensing is paused until fresh readings arrive.', error:'Motion sensing could not continue. Reconnect your AirPods and try again.'
  };
  const invoke = (command,args = {}) => global.__TAURI__?.core?.invoke(command,args);
  global.OfficeKitErgonomicsCore = {defaults,validate,time,minutes,motionText};
  let root, form, state, dirty = false, busy = false, available = false, editVersion = 0, calendarSelectionDirty = false;
  const el = id => document.getElementById(`ergonomics-${id}`);
  const message = (text, state = 'info', recovery = '') => officekitOutcome.show(el('status'), { state, text, recovery });
  function numberField(key,label,min,max) {
    return `<label class="ergonomics-field"><span>${label}</span><input class="input" type="number" required step="1" min="${min}" max="${max}" data-setting="${key}" aria-label="${label}"></label>`;
  }
  function reminder(key,title,description,fields,kind) {
    return `<fieldset class="fieldset card card-border ergonomics-card" id="ergonomics-${kind}-settings"><legend class="fieldset-legend">${title}</legend><label class="ergonomics-row"><span>${description}</span><input class="toggle" type="checkbox" data-setting="${key}.enabled" aria-label="${title} reminders"></label><div class="ergonomics-fields">${fields}</div><div class="ergonomics-row"><span data-due="${kind}"></span><a href="#" class="ergonomics-link" data-preview="${kind}" aria-label="Preview ${title.toLowerCase()}">Preview</a></div></fieldset>`;
  }
  function renderMarkup() {
    root.innerHTML = `<header><h1 id="ergonomics-heading">Ergonomics</h1><p>Small reminders, on your terms.</p></header>
      <p id="ergonomics-availability" role="status"></p><form id="ergonomics-form">
      <fieldset class="fieldset card card-border ergonomics-card" id="ergonomics-meeting-settings"><legend class="fieldset-legend">Meeting reminders</legend><p>Reads calendars available in macOS Calendar. Calendar data stays on this Mac.</p><label class="ergonomics-row"><span>Show meeting countdowns · 30 minutes before</span><input class="toggle" type="checkbox" data-setting="meetings.enabled" aria-label="Show meeting countdowns"></label><label class="ergonomics-row"><span>Offer to record calls · a Record button when a meeting starts or a call app uses your microphone. Nothing records until you press it.</span><input class="toggle" type="checkbox" data-setting="meetings.offerRecording" aria-label="Offer to record calls"></label><p id="ergonomics-calendar-status" role="status">Save settings to enable meeting reminders.</p><div class="ergonomics-calendars-head" id="ergonomics-calendar-head" hidden><span>Calendars</span><span id="ergonomics-calendar-count"></span></div><div id="ergonomics-calendar-loading" class="ergonomics-calendar-loading" hidden><div class="ergonomics-loading-line"><span class="ergonomics-spinner" aria-hidden="true"></span><span>Loading your calendars…</span></div><div class="ergonomics-calendar-list" aria-hidden="true"><i></i><i></i><i></i><i></i></div></div><div id="ergonomics-calendar-list" class="ergonomics-calendar-list" role="group" aria-label="Calendars"></div><div class="ergonomics-actions"><button class="btn" type="button" data-calendar="permission">Allow calendar access</button><button class="btn btn-ghost" type="button" data-calendar="privacy" hidden>Open Calendar privacy settings</button><a href="#" class="ergonomics-link" data-preview="meeting" aria-label="Preview meeting reminder">Preview</a></div><p>Uses your companion position, quiet hours and pause setting. All-day, cancelled and declined events are skipped. The mascot checks its watch, points to your countdown and waves briefly when it starts.</p></fieldset>
      <div class="ergonomics-grid">
      ${reminder('breaks','Move &amp; stretch','Step away and move a little.',numberField('breaks.intervalMinutes','Break interval (minutes)',5,180)+numberField('breaks.durationSeconds','Break duration (seconds)',20,900)+numberField('breaks.snoozeMinutes','Break snooze (minutes)',1,60),'break')}
      ${reminder('eyes','Rest your eyes','Look away into the distance.',numberField('eyes.intervalMinutes','Eye rest interval (minutes)',5,120)+numberField('eyes.durationSeconds','Eye rest duration (seconds)',10,120)+numberField('eyes.snoozeMinutes','Eye rest snooze (minutes)',1,60),'eyes')}
      ${reminder('water','Have some water','A gentle nudge, without an intake target.',numberField('water.intervalMinutes','Water interval (minutes)',5,240)+numberField('water.snoozeMinutes','Water snooze (minutes)',1,60),'water')}
      <fieldset class="fieldset card card-border ergonomics-card" id="ergonomics-posture-settings"><legend class="fieldset-legend">Head-angle nudges</legend><p id="ergonomics-motion-status" role="status"></p><p data-due="posture"></p><div class="ergonomics-fields">${numberField('posture.dwellSeconds','Head tilt dwell (seconds)',5,120)}${numberField('posture.cooldownMinutes','Head-angle cooldown (minutes)',1,60)}${numberField('posture.snoozeMinutes','Head-angle snooze (minutes)',1,60)}</div><div class="ergonomics-row"><button class="btn" type="button" id="ergonomics-motion-primary" data-motion="enable">Enable &amp; calibrate</button></div><div class="ergonomics-row"><button class="ergonomics-link" type="button" data-motion="disable" id="ergonomics-motion-off" hidden>Turn off sensing</button><a href="#" class="ergonomics-link" data-preview="posture" aria-label="Preview head-angle nudge">Preview</a></div><p>Head angle is an estimate. It does not measure your spine or diagnose posture. Local processing; no motion history is recorded.</p></fieldset>
      </div><fieldset class="fieldset card card-border ergonomics-card"><legend class="fieldset-legend">Your companion</legend><div class="ergonomics-fields"><label class="ergonomics-field"><span>Position</span><select class="select" data-setting="corner" aria-label="Companion position">${corners.map(corner=>`<option value="${corner}">${corner.replace('-',' ')}</option>`).join('')}</select></label></div><label class="ergonomics-row"><span>Reduce motion (also follows your system preference)</span><input class="toggle" type="checkbox" data-setting="reducedMotion"></label><label class="ergonomics-row"><span>Quiet hours</span><input class="toggle" type="checkbox" data-setting="quietHours.enabled"></label><div class="ergonomics-fields"><label class="ergonomics-field"><span>Quiet hours start</span><input class="input" type="time" required data-time="startMinutes" aria-label="Quiet hours start"></label><label class="ergonomics-field"><span>Quiet hours end</span><input class="input" type="time" required data-time="endMinutes" aria-label="Quiet hours end"></label></div></fieldset>
      <p>All reminders start off. Changes apply from now. OfficeKit must remain open for reminders.</p><div class="ok-action-dock" id="ergonomics-action-dock"><span id="ergonomics-status" class="ok-action-dock__status" role="status" aria-live="polite"></span><div class="ok-action-dock__controls"><a href="#" class="ergonomics-link" id="ergonomics-pause">Pause all · 1 hour</a><button class="btn btn-primary" id="ergonomics-save" type="submit">Save settings</button></div></div></form>`;
    form = el('form');
  }
  function fill(settings) {
    settings = {...settings,meetings:settings.meetings || defaults().meetings};
    for (const field of form.querySelectorAll('[data-setting]')) {
      const value = field.dataset.setting.split('.').reduce((item,key)=>item[key],settings);
      if (field.type === 'checkbox') field.checked = value; else field.value = value;
    }
    for (const field of form.querySelectorAll('[data-time]')) field.value = time(settings.quietHours[field.dataset.time]);
  }
  function read() {
    const settings = clone(state?.settings || defaults());
    settings.meetings ||= defaults().meetings;
    for (const field of form.querySelectorAll('[data-setting]')) {
      const keys = field.dataset.setting.split('.'), last = keys.pop();
      const target = keys.reduce((item,key)=>item[key],settings);
      target[last] = field.type === 'checkbox' ? field.checked : field.type === 'number' ? (field.value === '' ? NaN : Number(field.value)) : field.value;
    }
    for (const field of form.querySelectorAll('[data-time]')) settings.quietHours[field.dataset.time] = minutes(field.value);
    const calendars = [...form.querySelectorAll('[data-calendar-id]')];
    if (calendars.length && calendarSelectionDirty) {
      settings.meetings.allCalendars = false;
      settings.meetings.calendarIds = calendars.filter(field=>field.checked).map(field=>field.dataset.calendarId);
    }
    return settings;
  }
  function calendarStatus(next) {
    const calendar = next.calendar;
    const messages = {disabled:'Save settings to enable meeting reminders.',refreshing:'Refreshing local calendars…',allowed:'Calendar access allowed.', 'permission-needed':'Allow calendar access to see upcoming meetings.',requesting:'Waiting for your calendar permission choice…',denied:'Calendar access is off. Enable it in System Settings.',restricted:'Calendar access is restricted by this Mac.',unavailable:'Local calendar reminders are currently supported on macOS only.',error:'Could not read calendars. Your settings are preserved; try again.',preview:'Showing sample meeting animation.'};
    const status = calendar?.status || (next.activitySupported === false ? 'unavailable' : 'disabled');
    officekitOutcome.show(el('calendar-status'), { state: status === 'error' ? 'error' : 'info', text: messages[status] || messages.error });
    if (status === 'allowed') {
      if (!calendar.calendars?.length) officekitOutcome.show(el('calendar-status'), { state: 'info', text: 'No calendars available. Add an account in macOS Calendar.' });
      else if (!calendar.selectedEvent) officekitOutcome.show(el('calendar-status'), { state: 'info', text: 'Calendar access allowed. No selected meeting in the next 30 minutes.' });
    }
    root.querySelector('[data-calendar="permission"]').hidden = !['disabled','permission-needed','requesting'].includes(status);
    root.querySelector('[data-calendar="privacy"]').hidden = !['denied','restricted','error'].includes(status);
    const loading = status === 'refreshing' || (status === 'allowed' && !Array.isArray(calendar?.calendars));
    el('calendar-loading').hidden = !loading;
    if (!dirty && calendar && status !== 'preview') {
      const list = el('calendar-list');
      const signature = JSON.stringify([calendar.calendars,next.settings.meetings]);
      if (list.dataset.signature !== signature) {
        list.replaceChildren(); list.dataset.signature = signature;
        const settings = next.settings.meetings || defaults().meetings;
        for (const item of calendar.calendars || []) {
          const row = document.createElement('div'); row.className='ergonomics-calendar';
          const label = document.createElement('label');
          const input = document.createElement('input'); input.type='checkbox'; input.className='checkbox'; input.dataset.calendarId=item.id;
          input.checked = settings.allCalendars || settings.calendarIds.includes(item.id);
          const name = document.createElement('span'); name.textContent = item.title; name.title = item.title;
          label.append(input,name);
          const open = document.createElement('button'); open.type='button'; open.className='ergonomics-open'; open.dataset.calendar='open'; open.textContent='↗';
          open.title = open.ariaLabel = `Open ${item.title} in Calendar`;
          row.append(label,open); list.append(row);
        }
      }
      calendarCount();
    }
  }
  function calendarCount() {
    const boxes = [...form.querySelectorAll('[data-calendar-id]')];
    el('calendar-head').hidden = !boxes.length;
    el('calendar-count').textContent = `${boxes.filter(box=>box.checked).length} of ${boxes.length} selected`;
  }
  function update(next) {
    if (!next || !validate(next.settings)) { message('Could not read reminder settings. Try reopening this tool.', 'error'); return; }
    state = next;
    if (!dirty) fill(next.settings);
    calendarStatus(next);
    el('availability').textContent = next.activitySupported === false ? 'Automatic reminders are currently supported on macOS only. Previews still work on this platform.' : 'Wellness reminders wait for recent keyboard or pointer activity, or voice activity in an existing OfficeKit capture. Meeting countdowns follow calendar time. This feature does not start a microphone.';
    officekitOutcome.show(el('motion-status'), { state: next.motion?.status === 'error' ? 'error' : 'info', text: motionText[next.motion?.status] || motionText.error });
    // One contextual button: Enable & calibrate until sensing is on, then Recalibrate; Turn off sensing is a text link.
    const sensing = !!next.settings.posture.enabled;
    const motionButton = el('motion-primary');
    motionButton.dataset.motion = sensing ? 'calibrate' : 'enable';
    motionButton.textContent = sensing ? 'Recalibrate' : 'Enable & calibrate';
    el('motion-off').hidden = !sensing;
    el('pause').textContent = next.pausedRemainingSeconds !== null ? 'Resume reminders' : 'Pause all · 1 hour';
    const postureDue = next.nextDue?.find(item=>item.kind === 'posture');
    const postureStatus = form.querySelector('[data-due="posture"]');
    officekitOutcome.show(postureStatus, { state: 'info', text: next.pausedRemainingSeconds !== null ? 'Paused' : !next.settings.posture.enabled ? 'Off' : postureDue?.seconds == null ? 'Waiting for quiet hours to end' : next.motion?.status !== 'ready' ? 'Calibration required' : postureDue.seconds > 0 ? `Cooldown · ${Math.ceil(postureDue.seconds/60)} min` : 'Cooldown clear · waiting for a sustained tilt' });
    for (const node of form.querySelectorAll('[data-due]')) {
      if (node.dataset.due === 'posture') continue;
      const due = next.nextDue?.find(item=>item.kind === node.dataset.due);
      node.textContent = next.pausedRemainingSeconds !== null ? 'Paused' : due?.seconds == null ? 'Off or waiting' : `Next in ${Math.ceil(due.seconds/60)} min`;
    }
    if (next.error) message('Reminders need attention. Your settings are preserved; try again.', 'error');
  }
  async function call(command,args,success) {
    if (!available || busy) return;
    busy = true; setDisabled();
    try { const next = await invoke(command,args); if (next?.settings) update(next); if (success) message(success, 'success'); return next; }
    catch (error) {
      // A locked app rejects every native command with license_required: not a fault, so no dialog.
      if (!global.officekitOutcome?.isLicenseRequired?.(error)) message('Could not complete that action.', 'error', 'Your changes are preserved. Try again.');
    }
    finally { busy = false; setDisabled(); }
  }
  function setDisabled() {
    for (const node of form.querySelectorAll('button')) node.disabled = !available || busy;
    el('save').disabled ||= !state;
  }
  async function start() {
    root = document.getElementById('tab-ergonomics'); if (!root) return;
    renderMarkup(); fill(defaults());
    available = typeof global.__TAURI__?.core?.invoke === 'function'; setDisabled();
    el('availability').textContent = available ? 'Checking reminder availability…' : 'Desktop only. Open OfficeKit desktop to save reminders or use AirPods sensing.';
    form.addEventListener('input',event=>{ dirty = true; editVersion++; if (event.target.dataset.calendarId) { calendarSelectionDirty = true; calendarCount(); } form.querySelector('[data-time="endMinutes"]').setCustomValidity(''); message('Unsaved changes'); });
    form.addEventListener('submit',async event=>{
      event.preventDefault(); if (!form.reportValidity()) return;
      const settings = read();
      if (!validate(settings)) { const field = form.querySelector('[data-time="endMinutes"]'); field.setCustomValidity('Use different start and end times for quiet hours.'); field.reportValidity(); field.addEventListener('input',()=>field.setCustomValidity(''),{once:true}); message('Check the timing values before saving.', 'error'); return; }
      const submittedVersion = editVersion;
      const save = el('save'); save.disabled = true; save.textContent = 'Saving…'; message('Saving…', 'working');
      const next = await call('ergonomics_update_settings',{settings});
      save.disabled = false; save.textContent = 'Save settings';
      if (next?.settings) { dirty = submittedVersion !== editVersion; if (!dirty) calendarSelectionDirty = false; update(next); message(dirty ? 'Settings saved. Newer changes are still unsaved.' : 'Settings saved.', 'success'); }
    });
    root.addEventListener('click',event=>{
      const control = event.target.closest('button,a'); if (!control) return;
      if (control.tagName === 'A') event.preventDefault();
      if (control.dataset.preview) void call('ergonomics_preview',{kind:control.dataset.preview},'Preview opened.');
      if (control.dataset.motion) void (async()=>{
        const next = await call('ergonomics_motion_action',{action:control.dataset.motion});
      })();
      if (control.dataset.calendar) void call('ergonomics_calendar_action',{action:control.dataset.calendar});
      if (control === el('pause')) void call('ergonomics_reminder_action',{reminderId:'',action:state?.pausedRemainingSeconds != null ? 'resume' : 'pause'});
    });
    if (!available) return;
    try { await global.__TAURI__?.event?.listen('ergonomics:state',event=>update(event.payload)); await call('ergonomics_get_state',{}); }
    catch (error) { if (!global.officekitOutcome?.isLicenseRequired?.(error)) message('Could not connect to desktop reminders. Reopen this tool to try again.', 'error'); }
  }
  global.OfficeKitErgonomics = {open(kind) { const name = kinds.includes(kind) ? kind : 'break'; const field = document.getElementById(`ergonomics-${name}-settings`); field?.scrollIntoView({block:'nearest'}); field?.querySelector('input')?.focus({preventScroll:true}); }};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',start,{once:true}); else void start();
})(window);
