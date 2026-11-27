import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const outcome = readFileSync(new URL('../assets/officekit-outcome.js',import.meta.url),'utf8');
const workbench = readFileSync(new URL('../assets/officekit-ergonomics.js',import.meta.url),'utf8');
const companion = readFileSync(new URL('../assets/ergonomics-companion.js',import.meta.url),'utf8');
const companionHtml = readFileSync(new URL('../assets/ergonomics-companion.html',import.meta.url),'utf8');
const css = readFileSync(new URL('../assets/ergonomics.css',import.meta.url),'utf8');
const officekitCss = readFileSync(new URL('../dist-ui/assets/officekit.css',import.meta.url),'utf8');
const actionDock = readFileSync(new URL('../assets/officekit-tool-actions.js',import.meta.url),'utf8');

async function mount(page,options={}) {
  if (options.companion) await page.route('http://ergonomics.test/assets/ergonomics/*.png',async route=>{
    const file = new URL(route.request().url()).pathname.split('/').at(-1);
    await route.fulfill({contentType:'image/png',body:readFileSync(new URL(`../assets/ergonomics/${file}`,import.meta.url))});
  });
  if (options.companion) {
    await page.route('http://ergonomics.test/fixture',route=>route.fulfill({contentType:'text/html',body:companionHtml.replace('<head>','<head><base href="http://ergonomics.test/assets/">').replace(/<script[^>]*><\/script>/g,'').replace(/<link[^>]*>/g,'')}));
    await page.goto('http://ergonomics.test/fixture');
  } else if (options.withDock) await page.setContent('<div class="ok-app" style="height:100vh;display:flex"><div id="officekit-workspace-column"><main id="app-main"><section id="tab-ergonomics" style="min-height:1000px"></section></main><div id="officekit-tool-actions" role="group" aria-label="Current tool actions" hidden><span id="officekit-tool-action-summary"></span></div></div></div>');
  else await page.setContent('<section id="tab-ergonomics"></section>');
  if (options.companion || options.withDock) await page.addStyleTag({content:officekitCss});
  await page.addStyleTag({content:css});
  await page.evaluate(({desktop,prompt,companion,calendar})=>{
    window.calls = [];
    if (!desktop) return;
    window.testState = {settings:{version:1,corner:'bottom-right',reducedMotion:false,quietHours:{enabled:true,startMinutes:1320,endMinutes:480},breaks:{enabled:false,intervalMinutes:50,durationSeconds:120,snoozeMinutes:5},eyes:{enabled:false,intervalMinutes:20,durationSeconds:20,snoozeMinutes:5},water:{enabled:false,intervalMinutes:60,durationSeconds:0,snoozeMinutes:5},posture:{enabled:false,dwellSeconds:20,cooldownMinutes:5,snoozeMinutes:5}},activitySupported:true,pausedRemainingSeconds:null,nextDue:[],prompt:prompt || null,motion:{status:'disabled',calibrated:false,relativePitchDegrees:null,relativeRollDegrees:null,stable:false},error:null};
    window.testState.calendar = calendar || {status:'disabled',calendars:[],selectedEvent:null,preview:false};
    window.testState.settings.meetings={enabled:false,allCalendars:true,calendarIds:[],offerRecording:false};
    window.__TAURI__ = {event:{listen:async(_name,handler)=>{if(companion)throw new Error('Companion must not request broad event access');window.nativeEvent=handler;return ()=>{};}},core:{invoke:async(command,args)=>{
      window.calls.push({command,args});
      if (window.failNext) { window.failNext=false; throw new Error('secret native detail'); }
      if (command === 'ergonomics_update_settings') window.testState.settings = structuredClone(args.settings);
      if (command === 'ergonomics_reminder_action') {
        if (args.action === 'pause' && args.reminderId !== '') throw new Error('pause requires an empty reminder ID');
        if (args.action === 'pause') window.testState.pausedRemainingSeconds = 3600;
        if (args.action === 'resume') window.testState.pausedRemainingSeconds = null;
        if (args.action === 'start') window.testState.prompt.phase = 'active';
        if (['done','dismiss','close-preview','snooze'].includes(args.action)) window.testState.prompt = null;
      }
      if (command === 'ergonomics_motion_action') {window.testState.settings.posture.enabled=args.action === 'enable';window.testState.motion.status=args.action === 'enable'?'calibrating':'disabled';}
      return structuredClone(window.testState);
    }}};
  },{desktop:options.desktop !== false,prompt:options.prompt,companion:Boolean(options.companion),calendar:options.calendar});
  if (!options.companion) await page.addScriptTag({content:outcome});
  await page.addScriptTag({content:options.companion ? companion : workbench});
  if (options.withDock) await page.addScriptTag({content:actionDock});
}

test('browser fallback cannot save or start sensing',async({page})=>{
  await mount(page,{desktop:false});
  await expect(page.locator('#ergonomics-availability')).toContainText('Desktop only');
  await expect(page.getByRole('button',{name:'Save settings',exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'Enable & calibrate'})).toBeDisabled();
  expect(await page.evaluate(()=>window.calls)).toEqual([]);
});

test('calendar selection persists only deliberate changes, permission failures stay actionable',async({page})=>{
  await mount(page,{calendar:{status:'allowed',calendars:[{id:'work',title:'Work'},{id:'personal',title:'Personal <script>'}],selectedEvent:null,preview:false}});
  await expect(page.locator('[data-calendar-id="work"]')).toBeChecked();
  await expect(page.locator('#ergonomics-calendar-list')).toContainText('Personal <script>');
  await page.locator('[data-setting="water.intervalMinutes"]').fill('65');
  await page.getByRole('button',{name:'Save settings',exact:true}).click();
  expect(await page.evaluate(()=>window.testState.settings.meetings.allCalendars)).toBe(true);
  await page.locator('[data-calendar-id="personal"]').uncheck();
  await page.getByRole('button',{name:'Save settings',exact:true}).click();
  expect(await page.evaluate(()=>window.testState.settings.meetings)).toEqual({enabled:false,allCalendars:false,calendarIds:['work'],offerRecording:false});
  await page.evaluate(()=>{window.testState.calendar.status='denied';window.nativeEvent({payload:structuredClone(window.testState)});});
  await expect(page.getByRole('button',{name:'Open Calendar privacy settings'})).toBeVisible();
  await page.getByRole('button',{name:'Open Calendar privacy settings'}).click();
  expect(await page.evaluate(()=>window.calls.at(-1))).toEqual({command:'ergonomics_calendar_action',args:{action:'privacy'}});
});

test('calendar list shows a count, a loading state and an Open in Calendar row action',async({page})=>{
  await mount(page,{calendar:{status:'refreshing',calendars:[],selectedEvent:null,preview:false}});
  await expect(page.locator('#ergonomics-calendar-loading')).toBeVisible();
  await expect(page.locator('#ergonomics-calendar-loading')).toContainText('Loading your calendars');
  await page.evaluate(()=>{window.testState.calendar={status:'allowed',calendars:[{id:'work',title:'Work'},{id:'family',title:'Family'}],selectedEvent:null,preview:false};window.nativeEvent({payload:structuredClone(window.testState)});});
  await expect(page.locator('#ergonomics-calendar-loading')).toBeHidden();
  await expect(page.locator('#ergonomics-calendar-count')).toHaveText('2 of 2 selected');
  await page.locator('[data-calendar-id="family"]').uncheck();
  await expect(page.locator('#ergonomics-calendar-count')).toHaveText('1 of 2 selected');
  await page.getByRole('button',{name:'Open Work in Calendar'}).click();
  expect(await page.evaluate(()=>window.calls.at(-1))).toEqual({command:'ergonomics_calendar_action',args:{action:'open'}});
  const visible=await page.locator('button:not(.ergonomics-link):not(.ergonomics-open):visible').count();
  expect(visible).toBeLessThanOrEqual(3);
});

test('a meeting bubble and mascot fade in from 30 to 5 minutes out and stay at full strength after',async({page})=>{
  const start=Math.floor(Date.now()/1000)+1200;
  const calendar={status:'allowed',calendars:[],selectedEvent:{id:'meeting-1',title:'Design review',calendarTitle:'Work',start},preview:false};
  const opacityAt=async seconds=>{
    await page.evaluate(seconds=>{window.testState.prompt={id:'meeting-1',kind:'meeting',phase:'ready',remainingSeconds:seconds,preview:false};document.dispatchEvent(new Event('visibilitychange'));},seconds);
    await expect(page.locator('#companion-countdown')).toContainText(`${Math.floor(seconds/60)}:`);
    return page.locator('#ergonomics-companion').evaluate(el=>parseFloat(el.style.opacity));
  };
  await mount(page,{companion:true,prompt:{id:'meeting-1',kind:'meeting',phase:'ready',remainingSeconds:1740,preview:false},calendar});
  await expect(page.locator('#companion-title')).toHaveText('Design review');
  expect(await page.locator('#ergonomics-companion').evaluate(el=>parseFloat(el.style.opacity))).toBeCloseTo(0.04,2);
  expect(await opacityAt(1500)).toBeCloseTo(0.2,2);
  expect(await opacityAt(900)).toBeCloseTo(0.6,2);
  expect(await opacityAt(300)).toBe(1);
  expect(await opacityAt(120)).toBe(1);
  await page.evaluate(()=>{window.testState.prompt={id:'meeting-1',kind:'meeting',phase:'starting',remainingSeconds:0,preview:false};document.dispatchEvent(new Event('visibilitychange'));});
  await expect.poll(()=>page.locator('#ergonomics-companion').evaluate(el=>el.style.opacity)).toBe('1');
});

test('a wellness teaser fades in over two minutes with only a fully visible close button, and a preview fades in over a few seconds',async({page})=>{
  await mount(page,{companion:true,prompt:{id:'teaser-water',kind:'water',phase:'teaser',remainingSeconds:60,preview:false}});
  await expect(page.locator('#companion-title')).toHaveText('Time for a sip?');
  expect(await page.locator('#ergonomics-companion').evaluate(el=>parseFloat(el.style.opacity))).toBeCloseTo(0.5,2);
  // The close button is outside the fading area, so it is never faded.
  await expect(page.locator('body button:visible')).toHaveCount(1);
  await expect(page.locator('#companion-close')).toBeVisible();
  expect(await page.locator('#companion-close').evaluate(el=>getComputedStyle(el).opacity)).toBe('1');
  await expect(page.locator('#companion-countdown')).toHaveText('');
  await page.locator('#companion-close').click();
  expect(await page.evaluate(()=>window.calls.at(-1))).toEqual({command:'ergonomics_reminder_action',args:{reminderId:'teaser-water',action:'dismiss'}});
  await page.evaluate(()=>{window.testState.prompt={id:'teaser-water',kind:'water',phase:'teaser',remainingSeconds:6,preview:false};document.dispatchEvent(new Event('visibilitychange'));});
  await expect.poll(()=>page.locator('#ergonomics-companion').evaluate(el=>parseFloat(el.style.opacity))).toBeCloseTo(0.95,2);
  // The real reminder takes over at full strength with its buttons back.
  await page.evaluate(()=>{window.testState.prompt={id:'water-real',kind:'water',phase:'ready',remainingSeconds:null,preview:false};document.dispatchEvent(new Event('visibilitychange'));});
  await expect(page.getByRole('button',{name:'Close reminder'})).toBeVisible();
  expect(await page.locator('#ergonomics-companion').evaluate(el=>parseFloat(el.style.opacity))).toBe(1);
});

test('a preview starts transparent and fades in, and reduced motion shows it at once',async({page})=>{
  await mount(page,{companion:true,prompt:{id:'preview-water',kind:'water',phase:'ready',remainingSeconds:null,preview:true}});
  await expect(page.locator('#companion-close')).toBeVisible();
  const fade=await page.locator('#ergonomics-companion').evaluate(el=>({transition:el.style.transition,opacity:parseFloat(getComputedStyle(el).opacity)}));
  expect(fade.transition).toContain('8s');
  expect(fade.opacity).toBeLessThan(0.9);
  await expect.poll(()=>page.locator('#ergonomics-companion').evaluate(el=>parseFloat(getComputedStyle(el).opacity)),{timeout:12000}).toBe(1);
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.evaluate(()=>{window.testState.prompt={id:'preview-eyes',kind:'eyes',phase:'ready',remainingSeconds:20,preview:true};document.dispatchEvent(new Event('visibilitychange'));});
  await expect.poll(()=>page.locator('#ergonomics-companion').evaluate(el=>el.style.opacity)).toBe('1');
});

test('meeting mascot loops watch, pointing and wave stages with a readable countdown and hide action',async({page},testInfo)=>{
  await page.setViewportSize({width:300,height:460});
  const start=Math.floor(Date.now()/1000)+1200;
  const prompt={id:'meeting-1',kind:'meeting',phase:'ready',remainingSeconds:1200,preview:false};
  const calendar={status:'allowed',calendars:[],selectedEvent:{id:'meeting-1',title:'Design <review>',calendarTitle:'Work',start},preview:false};
  await mount(page,{companion:true,prompt,calendar});
  await expect(page.locator('#companion-title')).toHaveText('Design <review>');
  await expect(page.locator('#companion-countdown')).toHaveText('20:00');
  expect(await page.locator('#companion-countdown').evaluate(el=>parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThan(28);
  const frame=()=>page.locator('#companion-character').getAttribute('data-frame');
  await expect.poll(async()=>Number(await frame())).toBeGreaterThan(0);
  await page.screenshot({path:testInfo.outputPath('meeting-companion.png')});
  await page.waitForTimeout(2000);
  expect(Number(await frame())).toBeLessThan(8);
  await page.evaluate(()=>{window.testState.prompt.remainingSeconds=299;});
  await expect.poll(async()=>Number(await frame())).toBeGreaterThanOrEqual(8);
  expect(Number(await frame())).toBeLessThan(12);
  await page.evaluate(()=>{window.testState.prompt.phase='starting';window.testState.prompt.remainingSeconds=0;});
  await expect.poll(async()=>Number(await frame())).toBeGreaterThanOrEqual(12);
  await expect(page.locator('#companion-copy')).toContainText('Starting now');
  await expect(page.locator('#companion-snooze')).toBeHidden();
  await page.getByRole('button',{name:'Hide this meeting',exact:true}).click();
  expect(await page.evaluate(()=>window.calls.find(c=>c.command==='ergonomics_reminder_action'))).toEqual({command:'ergonomics_reminder_action',args:{reminderId:'meeting-1',action:'done'}});
});

const meetingCalendar=(start)=>({status:'allowed',calendars:[],selectedEvent:{id:'meeting-1',title:'Weekly sync',calendarTitle:'Work',start},preview:false});
const lastAction=page=>page.evaluate(()=>window.calls.filter(c=>c.command==='ergonomics_reminder_action').at(-1));
const visibleButtons=page=>page.locator('body button:not([hidden])');

test('a meeting reminder opens the Calendar app and keeps Hide as a quiet link',async({page})=>{
  const start=Math.floor(Date.now()/1000)+240;
  await mount(page,{companion:true,prompt:{id:'meeting-1',kind:'meeting',phase:'ready',remainingSeconds:240,preview:false,recordOffer:false,callApp:null},calendar:meetingCalendar(start)});
  await expect(page.locator('#companion-primary')).toHaveText('Open Calendar');
  await expect(page.locator('#companion-later')).toHaveText('Hide this meeting');
  await expect(visibleButtons(page)).toHaveCount(3);
  await page.locator('#companion-primary').click();
  expect(await lastAction(page)).toEqual({command:'ergonomics_reminder_action',args:{reminderId:'meeting-1',action:'open-calendar'}});
});

test('a meeting that has started offers Record, and Not now only hides the reminder',async({page})=>{
  const start=Math.floor(Date.now()/1000);
  await mount(page,{companion:true,prompt:{id:'meeting-1',kind:'meeting',phase:'starting',remainingSeconds:0,preview:false,recordOffer:true,callApp:null},calendar:meetingCalendar(start)});
  await expect(page.locator('#companion-primary')).toHaveText('Record this meeting');
  await expect(page.locator('#companion-copy')).toContainText('Record a transcript, or just coach your speaking?');
  await expect(page.locator('#companion-countdown')).toHaveText('');
  await expect(page.locator('#companion-later')).toHaveText('Not now');
  await page.locator('#companion-primary').click();
  expect(await lastAction(page)).toEqual({command:'ergonomics_reminder_action',args:{reminderId:'meeting-1',action:'record'}});
  await page.locator('#companion-later').click();
  expect(await lastAction(page)).toEqual({command:'ergonomics_reminder_action',args:{reminderId:'meeting-1',action:'done'}});
});

test('an ad-hoc call names the app, offers Record, and close only dismisses it',async({page})=>{
  await mount(page,{companion:true,prompt:{id:'call-1',kind:'call',phase:'ready',remainingSeconds:null,preview:false,recordOffer:true,callApp:'Zoom'}});
  await expect(page.locator('#companion-title')).toHaveText('Zoom call');
  await expect(page.locator('#companion-copy')).toContainText('Your microphone is in use by Zoom.');
  await expect(page.locator('#companion-primary')).toHaveText('Record this call');
  await expect(page.locator('#companion-snooze')).toBeHidden();
  await expect(page.locator('#companion-pause')).toBeHidden();
  await page.locator('#companion-close').click();
  expect(await lastAction(page)).toEqual({command:'ergonomics_reminder_action',args:{reminderId:'call-1',action:'dismiss'}});
  await page.evaluate(()=>{window.testState.prompt={id:'call-2',kind:'call',phase:'ready',remainingSeconds:null,preview:false,recordOffer:true,callApp:null};document.dispatchEvent(new Event('visibilitychange'));});
  await expect(page.locator('#companion-title')).toHaveText('Call in progress');
  await expect(page.locator('#companion-copy')).toContainText('in use by a browser');
});

// The three actions of the approved prompt are Record, Coach me and Not now; Not now is a quiet link,
// so the card has two buttons. A third `.btn` or a hidden action must fail here.
const visibleActions=page=>page.locator('body .btn:not([hidden])').allInnerTexts();
// The card is 300 x 460 on screen: every action must be visible without scrolling the reminder.
async function expectActionsFit(page){
  await page.setViewportSize({width:300,height:460});
  const fit=await page.evaluate(()=>{
    const bubble=document.querySelector('.ergonomics-bubble');
    const box=id=>document.getElementById(id).getBoundingClientRect();
    return {scrolls:bubble.scrollHeight>bubble.clientHeight+1,later:box('companion-later').bottom,coach:box('companion-coach').bottom,primary:box('companion-primary').bottom,height:window.innerHeight};
  });
  expect(fit.scrolls,'the reminder card scrolls').toBe(false);
  expect(Math.max(fit.later,fit.coach,fit.primary)).toBeLessThanOrEqual(fit.height);
}

test('a call offers Record, Coach me and Not now, all in view, with two buttons',async({page})=>{
  await mount(page,{companion:true,prompt:{id:'call-1',kind:'call',phase:'ready',remainingSeconds:null,preview:false,recordOffer:true,callApp:'Zoom'}});
  expect(await visibleActions(page)).toEqual(['Record this call','Coach me']);
  await expect(page.locator('#companion-later')).toHaveText('Not now');
  await expect(page.locator('#companion-copy')).toContainText('Nothing is recorded unless you choose Record');
  await expectActionsFit(page);
  await page.locator('#companion-coach').click();
  expect(await lastAction(page)).toEqual({command:'ergonomics_reminder_action',args:{reminderId:'call-1',action:'coach'}});
});

test('a started meeting offers Record, Coach me and Not now, all in view, with two buttons',async({page})=>{
  const start=Math.floor(Date.now()/1000);
  await mount(page,{companion:true,prompt:{id:'meeting-1',kind:'meeting',phase:'starting',remainingSeconds:0,preview:false,recordOffer:true,callApp:null},calendar:meetingCalendar(start)});
  expect(await visibleActions(page)).toEqual(['Record this meeting','Coach me']);
  await expect(page.locator('#companion-later')).toHaveText('Not now');
  await expectActionsFit(page);
  await page.locator('#companion-coach').click();
  expect(await lastAction(page)).toEqual({command:'ergonomics_reminder_action',args:{reminderId:'meeting-1',action:'coach'}});
});

test('Coach me is not offered for a reminder that has no Record offer, a preview or a teaser',async({page})=>{
  await mount(page,{companion:true,prompt:{id:'meeting-1',kind:'meeting',phase:'ready',remainingSeconds:240,preview:false,recordOffer:false,callApp:null},calendar:meetingCalendar(Math.floor(Date.now()/1000)+240)});
  await expect(page.locator('#companion-coach')).toBeHidden();
  await mount(page,{companion:true,prompt:{id:'preview',kind:'meeting',phase:'ready',remainingSeconds:12,preview:true,recordOffer:true},calendar:{status:'preview',calendars:[],selectedEvent:{id:'preview',title:'Sample',calendarTitle:'Sample',start:Math.floor(Date.now()/1000)},preview:true}});
  await expect(page.locator('#companion-coach')).toBeHidden();
  await mount(page,{companion:true,prompt:{id:'call-preview',kind:'call',phase:'ready',remainingSeconds:null,preview:true,recordOffer:true,callApp:'Zoom'}});
  await expect(page.locator('#companion-coach')).toBeHidden();
  await mount(page,{companion:true,prompt:{id:'teaser-1',kind:'call',phase:'teaser',remainingSeconds:null,preview:false,recordOffer:true,callApp:'Zoom'}});
  await expect(page.locator('#companion-coach')).toBeHidden();
});

test('a recording that cannot start shows the reason on the reminder',async({page})=>{
  await mount(page,{companion:true,prompt:{id:'call-1',kind:'call',phase:'ready',remainingSeconds:null,preview:false,recordOffer:true,callApp:'Slack'}});
  // The native side rejects with a plain sentence, as Tauri does for an Err(String).
  await page.evaluate(()=>{const invoke=window.__TAURI__.core.invoke;window.__TAURI__.core.invoke=async(command,args)=>{if(args?.action==='record') throw 'Prepare the local speech model before recording a meeting';return invoke(command,args);};});
  await page.locator('#companion-primary').click();
  await expect(page.locator('#companion-feedback')).toHaveText('Prepare the local speech model before recording a meeting');
});

test('no pose draws the feet of the pose above it at the top of the mascot',async({page})=>{
  await mount(page,{companion:true,prompt:{id:'preview',kind:'meeting',phase:'ready',remainingSeconds:12,preview:true},calendar:{status:'preview',calendars:[],selectedEvent:{id:'preview',title:'Sample meeting',calendarTitle:'Sample',start:Math.floor(Date.now()/1000)+12},preview:true}});
  // Poses in the lower rows sit under another pose; watch every frame the preview plays.
  const worst=await page.locator('#companion-character').evaluate(canvas=>new Promise(resolve=>{
    const context=canvas.getContext('2d');
    const framesSeen=new Set();
    let worstRow=0;
    const sample=()=>{
      framesSeen.add(canvas.dataset.frame);
      const opaque=context.getImageData(0,0,400,16).data.filter((value,index)=>index%4===3&&value>0).length;
      worstRow=Math.max(worstRow,opaque);
      if (framesSeen.size>=16||performance.now()>8000) resolve({worstRow,frames:framesSeen.size});
      else setTimeout(sample,40);
    };
    sample();
  }));
  expect(worst.frames).toBeGreaterThanOrEqual(12);
  expect(worst.worstRow).toBe(0);
});

test('meeting preview shows all poses and reduced motion freezes its character',async({page})=>{
  await mount(page,{companion:true,prompt:{id:'preview',kind:'meeting',phase:'ready',remainingSeconds:12,preview:true},calendar:{status:'preview',calendars:[],selectedEvent:{id:'preview',title:'Sample meeting',calendarTitle:'Sample',start:Math.floor(Date.now()/1000)+12},preview:true}});
  await expect(page.getByRole('button',{name:'Close reminder',exact:true})).toHaveCount(1);
  expect(await page.locator('body button:not(.ergonomics-link):visible').count()).toBeLessThanOrEqual(3);
  const seen=new Set();
  await expect.poll(async()=>{seen.add(Math.floor(Number(await page.locator('#companion-character').getAttribute('data-frame'))/4));return seen.size;},{timeout:6000,intervals:[100]}).toBe(4);
  await page.emulateMedia({reducedMotion:'reduce'});
  await expect(page.locator('#companion-character')).toHaveAttribute('data-frame','0');
  await page.waitForTimeout(500);
  await expect(page.locator('#companion-character')).toHaveAttribute('data-frame','0');
  await page.getByRole('button',{name:'Close reminder',exact:true}).click();
  expect(await page.evaluate(()=>window.calls.find(c=>c.command==='ergonomics_reminder_action'))).toEqual({command:'ergonomics_reminder_action',args:{reminderId:'',action:'close-preview'}});
});

test('save validates a complete snapshot and events preserve unsaved timing',async({page})=>{
  await mount(page);
  await expect(page.locator('[data-setting="water.intervalMinutes"]')).toHaveValue('60');
  await expect(page.locator('#ergonomics-availability')).toContainText('recent keyboard or pointer activity');
  await expect(page.locator('[data-due="posture"]')).toHaveText('Off');
  await page.evaluate(()=>{window.testState.activitySupported=false;window.nativeEvent({payload:structuredClone(window.testState)});});
  await expect(page.locator('#ergonomics-availability')).toContainText('supported on macOS only');
  await page.evaluate(()=>{window.testState.activitySupported=true;window.testState.settings.posture.enabled=true;window.testState.motion.status='ready';window.testState.nextDue=[{kind:'posture',seconds:90}];window.nativeEvent({payload:structuredClone(window.testState)});});
  await expect(page.locator('[data-due="posture"]')).toHaveText('Cooldown · 2 min');
  await page.evaluate(()=>{window.testState.settings.posture.enabled=false;window.testState.motion.status='disabled';window.testState.nextDue=[];window.nativeEvent({payload:structuredClone(window.testState)});});
  await page.locator('[data-setting="water.intervalMinutes"]').fill('75');
  await page.evaluate(()=>{window.testState.motion.status='stale';window.nativeEvent({payload:structuredClone(window.testState)});});
  await expect(page.locator('[data-setting="water.intervalMinutes"]')).toHaveValue('75');
  await expect(page.locator('#ergonomics-motion-status')).toContainText('stale');
  await page.getByRole('button',{name:'Save settings',exact:true}).click();
  await expect(page.locator('#ergonomics-status')).toHaveText('Settings saved.');
  await expect(page.locator('#ergonomics-status')).toHaveAttribute('data-state','success');
  await expect(page.locator('#ergonomics-status')).toHaveAttribute('role','status');
  const save = await page.evaluate(()=>window.calls.find(item=>item.command==='ergonomics_update_settings'));
  expect(save.args.settings.water).toEqual({enabled:false,intervalMinutes:75,durationSeconds:0,snoozeMinutes:5});
  expect(Object.keys(save.args)).toEqual(['settings']);
  expect(await page.locator('form:visible button:visible').count()).toBeLessThanOrEqual(3);
  await page.getByRole('link',{name:'Pause all · 1 hour',exact:true}).click();
  await expect(page.locator('#ergonomics-pause')).toHaveText('Resume reminders');
  await page.locator('#ergonomics-pause').click();
  expect(await page.evaluate(()=>window.calls.at(-1))).toEqual({command:'ergonomics_reminder_action',args:{reminderId:'',action:'resume'}});
});

test('failed save keeps edits and hides raw errors; explicit sensing leaves other drafts intact',async({page})=>{
  await mount(page);
  await page.locator('[data-setting="breaks.intervalMinutes"]').fill('65');
  await page.evaluate(()=>window.failNext=true);
  await page.getByRole('button',{name:'Save settings',exact:true}).click();
  await expect(page.locator('#ergonomics-status')).toContainText('Your changes are preserved');
  await expect(page.locator('#ergonomics-status')).not.toContainText('secret');
  await page.getByRole('button',{name:'Enable & calibrate'}).click();
  await expect(page.locator('#ergonomics-motion-status')).toContainText('baseline is measured');
  await expect(page.locator('[data-setting="posture.enabled"]')).toHaveCount(0);
  await expect(page.locator('[data-setting="breaks.intervalMinutes"]')).toHaveValue('65');
  const calls = await page.evaluate(()=>window.calls);
  expect(calls.filter(item=>item.command==='ergonomics_motion_action')).toEqual([{command:'ergonomics_motion_action',args:{action:'enable'}}]);
});

test('companion actions use the current prompt identity and native countdown phase',async({page})=>{
  await mount(page,{companion:true,prompt:{id:'reminder-1',kind:'eyes',phase:'ready',remainingSeconds:20,preview:false}});
  await expect(page.locator('#companion-primary')).toHaveText('Start eye rest');
  await page.locator('#companion-primary').click();
  // The countdown has no End early button; the close button is the way out.
  await expect(page.locator('#companion-primary')).toBeHidden();
  expect(await page.evaluate(()=>window.calls.at(-1))).toEqual({command:'ergonomics_reminder_action',args:{reminderId:'reminder-1',action:'start'}});
  await page.locator('#companion-close').click();
  await expect(page.locator('#ergonomics-companion')).toBeHidden();
  expect(await page.evaluate(()=>window.calls.at(-1))).toEqual({command:'ergonomics_reminder_action',args:{reminderId:'reminder-1',action:'dismiss'}});
});

test('Pause all uses the native global-action contract with an empty reminder ID',async({page})=>{
  await mount(page,{companion:true,prompt:{id:'reminder-pause',kind:'water',phase:'ready',remainingSeconds:null,preview:false}});
  await page.locator('#companion-pause').click();
  expect(await page.evaluate(()=>window.calls.at(-1))).toEqual({command:'ergonomics_reminder_action',args:{reminderId:'',action:'pause'}});
  await expect(page.locator('#companion-feedback')).not.toContainText('Could not update');
});

test('preview closes without acknowledging a reminder and all four corner states apply',async({page})=>{
  await mount(page,{companion:true,prompt:{id:'preview-1',kind:'water',phase:'ready',remainingSeconds:null,preview:true}});
  for (const corner of ['top-left','top-right','bottom-left','bottom-right']) {
    await page.evaluate(corner=>{window.testState.settings.corner=corner;document.dispatchEvent(new Event('visibilitychange'));},corner);
    await expect(page.locator('#ergonomics-companion')).toHaveAttribute('data-corner',corner);
  }
  await expect(page.locator('#companion-snooze')).toBeHidden();
  await page.locator('#companion-primary').click();
  expect(await page.evaluate(()=>window.calls.at(-1))).toEqual({command:'ergonomics_reminder_action',args:{reminderId:'',action:'close-preview'}});
});

test('an eye-rest preview has an explicit Close button and at most three buttons',async({page})=>{
  await mount(page,{companion:true,prompt:{id:'preview-2',kind:'eyes',phase:'ready',remainingSeconds:null,preview:true}});
  await expect(page.locator('#companion-close')).toBeVisible();
  await expect(page.locator('#companion-pause')).toBeHidden();
  expect(await page.locator('body button:not(.ergonomics-link):visible').count()).toBeLessThanOrEqual(3);
  await page.locator('#companion-close').click();
  expect(await page.evaluate(()=>window.calls.at(-1))).toEqual({command:'ergonomics_reminder_action',args:{reminderId:'',action:'close-preview'}});
});

test('the close button dismisses a live reminder without snoozing, and Escape does the same',async({page})=>{
  await mount(page,{companion:true,prompt:{id:'live-1',kind:'water',phase:'ready',remainingSeconds:null,preview:false}});
  await expect(page.locator('#companion-close')).toBeVisible();
  const box = await page.locator('#companion-close').boundingBox();
  const bubble = await page.locator('.ergonomics-bubble').boundingBox();
  expect(box.x + box.width).toBeLessThanOrEqual(bubble.x + bubble.width);
  expect(box.y).toBeGreaterThanOrEqual(bubble.y);
  expect(await page.locator('body button:not(.ergonomics-link):visible').count()).toBe(3);
  expect(await page.locator('#companion-pause').evaluate(node=>node.classList.contains('ergonomics-link'))).toBe(true);
  await page.locator('#companion-close').click();
  expect(await page.evaluate(()=>window.calls.at(-1))).toEqual({command:'ergonomics_reminder_action',args:{reminderId:'live-1',action:'dismiss'}});
  await expect(page.locator('#ergonomics-companion')).toBeHidden();
  await page.evaluate(()=>{window.testState.prompt={id:'live-2',kind:'water',phase:'ready',remainingSeconds:null,preview:false};document.dispatchEvent(new Event('visibilitychange'));});
  await expect(page.locator('#ergonomics-companion')).toBeVisible();
  await page.keyboard.press('Escape');
  expect(await page.evaluate(()=>window.calls.at(-1))).toEqual({command:'ergonomics_reminder_action',args:{reminderId:'live-2',action:'dismiss'}});
});

test('closing a meeting reminder hides that meeting through the native done action',async({page})=>{
  const start = Math.floor(Date.now()/1000)+600;
  await mount(page,{companion:true,prompt:{id:'meeting-live',kind:'meeting',phase:'ready',remainingSeconds:600,preview:false},calendar:{status:'allowed',calendars:[],selectedEvent:{id:'e1',title:'Standup',calendarTitle:'Work',start},preview:false}});
  await page.locator('#companion-close').click();
  expect(await page.evaluate(()=>window.calls.at(-1))).toEqual({command:'ergonomics_reminder_action',args:{reminderId:'meeting-live',action:'done'}});
});

test('an eye rest in progress animates poses that match each exercise instruction',async({page})=>{
  await page.setViewportSize({width:300,height:460});
  await page.clock.install();
  await mount(page,{companion:true,prompt:{id:'eyes-1',kind:'eyes',phase:'active',remainingSeconds:20,preview:false}});
  await page.clock.runFor(1000);
  await expect(page.locator('#companion-title')).toHaveText('Rest your eyes');
  await expect(page.locator('#companion-cue')).toHaveText('Look far away');
  await expect(page.locator('#companion-copy')).toContainText('20 feet');
  await expect(page.locator('#companion-countdown')).toContainText('step 1 of 3');
  await expect(page.locator('#companion-dots i')).toHaveCount(3);
  await expect(page.locator('#companion-dots i.on')).toHaveCount(1);
  const frame = () => page.locator('#companion-character').getAttribute('data-frame');
  const expectFrameIn = allowed => expect.poll(async()=>allowed.includes(Number(await frame()))).toBe(true);
  const observeFrames = () => page.evaluate(()=>{
    window.eyeExerciseFrames=[Number(document.querySelector('#companion-character').dataset.frame)];
    const character=document.querySelector('#companion-character');
    window.eyeExerciseObserver=new MutationObserver(()=>window.eyeExerciseFrames.push(Number(character.dataset.frame)));
    window.eyeExerciseObserver.observe(character,{attributes:true,attributeFilter:['data-frame']});
  });
  const expectObservedFrames = async expected => {
    const observed=await page.evaluate(()=>[...new Set(window.eyeExerciseFrames)]);
    for (const expectedFrame of expected) expect(observed).toContain(expectedFrame);
  };
  const first = await frame();
  await expectFrameIn([2,3,4,5,6,7]);
  await page.clock.runFor(1500);
  expect(await frame()).not.toBe(first);
  await observeFrames();
  // 20 s shared by three steps is about 6.7 s each.
  await page.clock.runFor(5000);
  await expect(page.locator('#companion-cue')).toHaveText('Blink slowly');
  await expect(page.locator('#companion-countdown')).toContainText('step 2 of 3');
  await page.evaluate(()=>{window.eyeExerciseFrames=[];});
  await page.clock.runFor(4000);
  await expectObservedFrames([8,9]);

  await page.clock.runFor(3000);
  await expect(page.locator('#companion-cue')).toHaveText('Look side to side');
  await expect(page.locator('#companion-countdown')).toContainText('step 3 of 3');
  await page.evaluate(()=>{window.eyeExerciseFrames=[];});
  await page.clock.runFor(3000);
  await expectObservedFrames([2,3,4,5,6,7]);

  await page.clock.runFor(3500);
  await expect(page.locator('#companion-cue')).toHaveText('Look far away');
  await expect(page.locator('#companion-countdown')).toContainText('step 1 of 3');
  await expect(page.locator('#companion-announcement')).toContainText('Step 1 of 3: Look far away');
  expect(await page.locator('body button:not(.ergonomics-link):visible').count()).toBe(2);
  expect(await page.locator('.ergonomics-bubble').evaluate(node=>node.scrollHeight-node.clientHeight)).toBeLessThanOrEqual(0);
});

test('the eye exercises start only once the rest is active',async({page})=>{
  await page.clock.install();
  await mount(page,{companion:true,prompt:{id:'eyes-2',kind:'eyes',phase:'ready',remainingSeconds:20,preview:false}});
  await page.clock.runFor(1000);
  await expect(page.locator('#companion-title')).toHaveText('Give your eyes a little rest?');
  await expect(page.locator('#companion-cue')).toBeHidden();
  await page.locator('#companion-primary').click();
  await page.clock.runFor(1000);
  await expect(page.locator('#companion-title')).toHaveText('Rest your eyes');
  await expect(page.locator('#companion-cue')).toHaveText('Look far away');
});

test('approved sprite sheets decode, loop without stopping, and reduced motion renders a still frame',async({page})=>{
  await mount(page,{companion:true,prompt:{id:'animation-water',kind:'water',phase:'ready',remainingSeconds:null,preview:true}});
  const character = page.locator('#companion-character');
  await page.evaluate(()=>{
    const canvas=document.getElementById('companion-character');
    window.frameLog=[canvas.dataset.frame];
    new MutationObserver(()=>window.frameLog.push(canvas.dataset.frame)).observe(canvas,{attributes:true,attributeFilter:['data-frame']});
  });
  await expect(character).toHaveAttribute('data-frame',/^(?:[1-9]|1[0-5])$/);
  // The last frame is shown, then the animation starts over instead of holding it.
  await page.waitForFunction(()=>{
    const log=window.frameLog,last=log.indexOf('15');
    if (last < 0) return false;
    const wrap=log.indexOf('0',last);
    return wrap > last && log.slice(wrap).includes('3');
  },null,{timeout:10000});
  await page.emulateMedia({reducedMotion:'reduce'});
  await expect(character).toHaveAttribute('data-frame','0');
  for (const kind of ['break','eyes']) {
    await page.evaluate(kind=>{window.testState.prompt={id:`animation-${kind}`,kind,phase:'ready',remainingSeconds:20,preview:true};document.dispatchEvent(new Event('visibilitychange'));},kind);
    await expect(character).toHaveAttribute('data-frame','0');
    await expect(page.locator('#companion-feedback')).not.toContainText('unavailable');
    await expect(character).toHaveAttribute('aria-label',kind==='break'?/stretches/:/blinks/);
    await page.waitForFunction(()=>{
      const pixels = document.getElementById('companion-character').getContext('2d').getImageData(0,0,400,400).data;
      return pixels.some((value,index)=>index%4===3 && value>0);
    });
  }
});

test('all companion controls fit the native window at every corner and reminder phase',async({page})=>{
  await page.setViewportSize({width:300,height:460});
  await mount(page,{companion:true,prompt:{id:'fit-water',kind:'water',phase:'ready',remainingSeconds:null,preview:false}});
  const scenarios = [
    ['water','ready'],['break','ready'],['eyes','ready'],['eyes','active'],['break','active'],['break','complete'],['posture','ready'],
  ];
  for (const [kind,phase] of scenarios) for (const corner of ['top-left','top-right','bottom-left','bottom-right']) {
    await page.evaluate(({kind,phase,corner})=>{
      window.testState.prompt={id:`fit-${kind}-${phase}`,kind,phase,remainingSeconds:phase==='active'?42:null,preview:false};
      window.testState.settings.corner=corner;
      document.dispatchEvent(new Event('visibilitychange'));
    },{kind,phase,corner});
    await expect(page.locator('#ergonomics-companion')).toHaveAttribute('data-corner',corner);
    const bounds = await page.locator('#companion-primary,#companion-snooze,#companion-pause').evaluateAll(elements=>elements.filter(el=>!el.hidden).map(el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom};}));
    for (const rect of bounds) {
      expect(rect.x).toBeGreaterThanOrEqual(0);
      expect(rect.y).toBeGreaterThanOrEqual(0);
      expect(rect.right).toBeLessThanOrEqual(300);
      expect(rect.bottom).toBeLessThanOrEqual(460);
    }
  }
});

test('a break in progress loops a guided stretch routine with a named step, dots and three buttons',async({page})=>{
  await page.setViewportSize({width:300,height:460});
  await page.clock.install();
  await mount(page,{companion:true,prompt:{id:'break-1',kind:'break',phase:'active',remainingSeconds:100,preview:false}});
  await page.clock.runFor(1000);
  await expect(page.locator('#companion-title')).toHaveText('Follow me!');
  await expect(page.locator('#companion-cue')).toHaveText('Reach up high');
  await expect(page.locator('#companion-countdown')).toContainText('step 1 of 4');
  await expect(page.locator('#companion-dots i')).toHaveCount(4);
  await expect(page.locator('#companion-dots i.on')).toHaveCount(1);
  const frame = () => page.locator('#companion-character').getAttribute('data-frame');
  const first = await frame();
  await page.clock.runFor(1000);
  expect(await frame()).not.toBe(first);
  for (const [seconds,cue,step] of [[20,'Lean to the left',2],[20,'Lean to the right',3],[20,'Roll your shoulders',4],[20,'Reach up high',1]]) {
    await page.clock.runFor(seconds*1000);
    await expect(page.locator('#companion-cue')).toHaveText(cue);
    await expect(page.locator('#companion-countdown')).toContainText(`step ${step} of 4`);
  }
  await expect(page.locator('#companion-announcement')).toContainText('Step 1 of 4: Reach up high');
  expect(await page.locator('body button:not(.ergonomics-link):visible').count()).toBe(2);
  expect(await page.locator('.ergonomics-bubble').evaluate(node=>node.scrollHeight-node.clientHeight)).toBeLessThanOrEqual(0);
});

test('reduced motion keeps one still pose per stretch step',async({page})=>{
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.clock.install();
  await mount(page,{companion:true,prompt:{id:'break-2',kind:'break',phase:'active',remainingSeconds:100,preview:false}});
  await page.clock.runFor(1000);
  await expect(page.locator('#companion-cue')).toHaveText('Reach up high');
  const first = await page.locator('#companion-character').getAttribute('data-frame');
  await page.clock.runFor(1500);
  expect(await page.locator('#companion-character').getAttribute('data-frame')).toBe(first);
  await page.clock.runFor(20000);
  await expect(page.locator('#companion-cue')).toHaveText('Lean to the left');
});

test('the routine starts only once the break is active and stops when it ends',async({page})=>{
  await page.clock.install();
  await mount(page,{companion:true,prompt:{id:'break-3',kind:'break',phase:'ready',remainingSeconds:120,preview:false}});
  await page.clock.runFor(1000);
  await expect(page.locator('#companion-title')).toHaveText('A little stretch?');
  await expect(page.locator('#companion-cue')).toBeHidden();
  await page.locator('#companion-primary').click();
  await page.clock.runFor(1000);
  await expect(page.locator('#companion-title')).toHaveText('Follow me!');
  await page.evaluate(()=>{window.testState.prompt.phase='complete';});
  await page.clock.runFor(1500);
  await expect(page.locator('#companion-title')).toHaveText('A little refreshed?');
  await expect(page.locator('#companion-cue')).toBeHidden();
});

test('companion controls follow a predictable keyboard focus order',async({page})=>{
  await mount(page,{companion:true,prompt:{id:'keyboard-water',kind:'water',phase:'ready',remainingSeconds:null,preview:false}});
  await page.keyboard.press('Tab');
  await expect(page.locator('#companion-primary')).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(page.locator('#companion-snooze')).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(page.locator('#companion-pause')).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(page.locator('#companion-close')).toBeFocused();
});

test('workbench settings dock into the shared native action area',async({page})=>{
  await mount(page,{withDock:true});
  await page.locator('#app-main').evaluate(main=>{main.scrollTop=main.scrollHeight;});
  await page.waitForTimeout(50);
  const dock = page.locator('#officekit-tool-actions');
  await expect(dock).toBeVisible();
  await expect(dock).toHaveAttribute('aria-owns','ergonomics-action-dock');
  const geometry = await page.evaluate(()=>{
    const dock=document.getElementById('officekit-tool-actions').getBoundingClientRect();
    const source=document.getElementById('ergonomics-action-dock');
    const rect=source.getBoundingClientRect();
    return {docked:source.dataset.officekitDocked,left:rect.left,top:rect.top,right:rect.right,bottom:rect.bottom,dockLeft:dock.left,dockTop:dock.top,dockRight:dock.right,dockBottom:dock.bottom};
  });
  expect(geometry.docked).toBe('true');
  expect(geometry.left).toBeGreaterThanOrEqual(geometry.dockLeft);
  expect(geometry.top).toBeGreaterThanOrEqual(geometry.dockTop);
  expect(geometry.right).toBeLessThanOrEqual(geometry.dockRight);
  expect(geometry.bottom).toBeLessThanOrEqual(geometry.dockBottom);
});

test('settings show at most three buttons and one control style; sensing uses one contextual button',async({page})=>{
  await mount(page,{desktop:true});
  const buttons = await page.locator('#tab-ergonomics .btn:visible').allTextContents();
  expect(buttons.map(text=>text.trim())).toEqual(['Allow calendar access','Enable & calibrate','Save settings']);
  expect(buttons.length).toBeLessThanOrEqual(3);
  const heights = await page.locator('#tab-ergonomics .ergonomics-field :is(.input,.select)').evaluateAll(nodes=>[...new Set(nodes.map(node=>Math.round(node.getBoundingClientRect().height)))]);
  expect(heights).toEqual([40]);
  await expect(page.locator('#ergonomics-motion-off')).toBeHidden();
  await page.evaluate(()=>{window.testState.settings.posture.enabled=true;window.nativeEvent({payload:structuredClone(window.testState)});});
  await expect(page.locator('#ergonomics-motion-primary')).toHaveText('Recalibrate');
  await expect(page.locator('#ergonomics-motion-off')).toBeVisible();
});
