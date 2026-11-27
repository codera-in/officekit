import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../assets/officekit-ergonomics.js',import.meta.url),'utf8');
const companionSource = readFileSync(new URL('../assets/ergonomics-companion.js',import.meta.url),'utf8');
const capability = JSON.parse(readFileSync(new URL('../src-tauri/capabilities/ergonomics.json',import.meta.url),'utf8'));
const sandbox = {window:{},TextEncoder,document:{readyState:'loading',addEventListener(){}}};
vm.runInNewContext(source,sandbox);
const {defaults,validate,time,minutes} = sandbox.window.OfficeKitErgonomicsCore;

test('first use is opt-in and clones independent reminder schedules',()=>{
  const settings = defaults();
  assert.equal(validate(settings),true);
  for (const key of ['breaks','eyes','water','posture']) assert.equal(settings[key].enabled,false);
  settings.eyes.intervalMinutes = 5;
  assert.equal(defaults().eyes.intervalMinutes,20);
});

test('calendar configuration is opt-in, bounded, and rejects duplicate or malformed selections',()=>{
  assert.equal(defaults().meetings.enabled,false);
  assert.equal(defaults().meetings.allCalendars,true);
  for (const meetings of [
    {enabled:'yes',allCalendars:true,calendarIds:[]},
    {enabled:true,allCalendars:0,calendarIds:[]},
    {enabled:true,allCalendars:false,calendarIds:['work','work']},
    {enabled:true,allCalendars:false,calendarIds:['']},
    {enabled:true,allCalendars:false,calendarIds:['x'.repeat(2049)]},
    {enabled:true,allCalendars:false,calendarIds:[null]},
  ]) {
    const settings=defaults(); settings.meetings=meetings;
    assert.equal(validate(settings),false);
  }
  assert.equal(defaults().meetings.offerRecording,false,'recording is only offered when the person turns it on');
  const settings=defaults();settings.meetings={enabled:true,allCalendars:false,calendarIds:['work'],offerRecording:false};
  assert.equal(validate(settings),true);
  settings.meetings.offerRecording=true;assert.equal(validate(settings),true);
  settings.meetings.offerRecording='yes';assert.equal(validate(settings),false);
  settings.meetings.offerRecording=false;
  delete settings.meetings;assert.equal(validate(settings),true,'previous settings remain migratable');
});

test('timing validates inclusive native boundaries and rejects fractional, missing and nonfinite values',()=>{
  for (const [key,field,min,max] of [['breaks','intervalMinutes',5,180],['breaks','durationSeconds',20,900],['eyes','intervalMinutes',5,120],['eyes','durationSeconds',10,120],['water','intervalMinutes',5,240],['water','durationSeconds',0,0],['posture','dwellSeconds',5,120],['posture','cooldownMinutes',1,60]]) {
    for (const value of [min,max]) { const settings = defaults(); settings[key][field] = value; assert.equal(validate(settings),true); }
    for (const value of [min-1,max+1,NaN,Infinity,undefined,5.5,'20',null]) { const settings = defaults(); settings[key][field] = value; assert.equal(validate(settings),false,`${key}.${field}: ${value}`); }
  }
  for (const key of ['breaks','eyes','water','posture']) {
    const settings = defaults(); settings[key].snoozeMinutes = 0; assert.equal(validate(settings),false);
    settings[key].snoozeMinutes = 61; assert.equal(validate(settings),false);
    settings[key].snoozeMinutes = 60; assert.equal(validate(settings),true);
  }
});

test('quiet hours support overnight and reject equal or invalid times; corners are constrained',()=>{
  const settings = defaults();
  assert.equal(time(1320),'22:00'); assert.equal(minutes('08:00'),480);
  assert.equal(Number.isNaN(minutes('broken')),true);
  settings.quietHours.endMinutes = 1320; assert.equal(validate(settings),false);
  settings.quietHours.endMinutes = 1440; assert.equal(validate(settings),false);
  settings.quietHours.endMinutes = 480;
  for (const corner of ['top-left','top-right','bottom-left','bottom-right']) { settings.corner = corner; assert.equal(validate(settings),true); }
  settings.corner = 'center'; assert.equal(validate(settings),false);
});

test('companion has no broad event-listener capability and polls its bounded native state command',()=>{
  assert.deepEqual(capability.permissions,[]);
  assert.match(companionSource,/invoke\('ergonomics_get_state'\)/);
  assert.doesNotMatch(companionSource,/\.event\.listen\(/);
  assert.match(readFileSync(new URL('../assets/ergonomics-companion.html',import.meta.url),'utf8'),/aria-live="polite" aria-atomic="true"/);
  assert.match(companionSource,/el\('announcement'\)\.textContent/);
  assert.doesNotMatch(source,/data-setting="posture\.enabled"/);
});
