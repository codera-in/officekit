(function (global) {
  'use strict';
  const el = id => document.getElementById(`companion-${id}`);
  const root = document.getElementById('ergonomics-companion');
  const canvas = el('character'), context = canvas.getContext('2d');
  const reduced = global.matchMedia('(prefers-reduced-motion: reduce)');
  const appearance = global.matchMedia('(prefers-color-scheme: dark)');
  function syncTheme() {
    let preference;
    try { preference = global.localStorage.getItem('officekit.theme'); } catch { /* System appearance remains available. */ }
    document.documentElement.dataset.theme = preference === 'dark' || (preference !== 'light' && appearance.matches) ? 'dark' : 'light';
  }
  syncTheme();
  appearance.addEventListener('change',syncTheme);
  global.addEventListener('storage',event=>{ if (event.key === 'officekit.theme') syncTheme(); });
  const definitions = {
    water:{title:'Time for a sip?',copy:'Have some water when it suits you.',sheet:'water',alt:'Companion opens a large water bottle, drinks, and replaces the cap.'},
    break:{title:'A little stretch?',copy:'Step away and move comfortably for a moment.',sheet:'stretch',alt:'Companion reaches up, stretches gently to each side, then relaxes.'},
    eyes:{title:'Give your eyes a little rest?',copy:'Look away from your screen into the distance.',sheet:'eyes',alt:'Companion looks into the distance, slowly blinks, and rests its eyes.'},
    posture:{title:'A comfortable reset?',copy:'Your head has stayed tilted from your comfortable baseline.',sheet:'eyes',alt:'Companion rests in a comfortable neutral pose.'},
    call:{title:'Call in progress',copy:'',sheet:'meeting',alt:'Companion waves and offers to record the call.'},
    meeting:{title:'Your next meeting',copy:'',sheet:'meeting',alt:'Companion checks its watch, points to the countdown and waves when the meeting starts.'}
  };
  let state, prompt, image, started = 0, token = 0, frameRequest = 0, busy = false, polling = false;
  const images = new Map();
  const invoke = (command,args={}) => global.__TAURI__.core.invoke(command,args);
  function draw(frame) {
    context.clearRect(0,0,400,400);
    if (!image) return;
    const width = image.naturalWidth/4, height = image.naturalHeight/4, scale = Math.min(400/width,400/height);
    // The feet of each pose run a few pixels into the cell below, so every cell skips its top edge.
    const trim = height*0.05;
    context.drawImage(image,(frame%4)*width,Math.floor(frame/4)*height+trim,width,height-trim,(400-width*scale)/2,(400-height*scale)/2+trim*scale,width*scale,(height-trim)*scale);
    canvas.dataset.frame = String(frame);
  }
  function still() { return reduced.matches || state?.settings.reducedMotion || prompt?.kind === 'posture'; }
  function tick(now) {
    const meeting = prompt?.kind === 'meeting';
    const elapsed = Math.floor((now-started)/220);
    const frame = still() ? 0 : meeting ? (prompt.preview ? elapsed%16 : prompt.phase === 'starting' ? 12+elapsed%4 : prompt.remainingSeconds <= 300 ? 8+elapsed%4 : elapsed%8) : Math.floor((now-started)/250)%16;
    draw(frame);
    if (!still() && prompt) frameRequest = global.requestAnimationFrame(tick);
  }
  // A break in progress loops a guided routine of real stretches built from the poses in the stretch sheet.
  // An eye rest in progress walks through three eye exercises in words; the mascot keeps its own animation
  // (a step can gain `frames` later to pose the mascot). The steps share the rest length, 5 to 10 seconds each.
  const routines = {
    break:{title:'Follow me!',stepMs:()=>20000,steps:[
      {cue:'Reach up high',hint:'Breathe in slowly, stretch tall.',frames:[2,3,7,3]},
      {cue:'Lean to the left',hint:'Hold it, keep breathing.',frames:[4,5,6,5]},
      {cue:'Lean to the right',hint:'Hold it, keep breathing.',frames:[8,9,10,9]},
      {cue:'Roll your shoulders',hint:'Loose and easy.',frames:[12,13,14,13]}
    ]},
    eyes:{title:'Rest your eyes',stepMs:()=>Math.min(10000,Math.max(5000,(state?.settings?.eyes?.durationSeconds || 20)*1000/3)),steps:[
      {cue:'Look far away',hint:'Pick something about 20 feet (6 m) away and let your eyes soften.',frames:[2,3,4,5,6,7]},
      {cue:'Blink slowly',hint:'Close your eyes gently, then open them. Repeat.',frames:[8,8,8,9,9,8,8,8]},
      {cue:'Look side to side',hint:'Follow my gaze slowly from left to right, keeping your head relaxed.',frames:[2,3,4,5,6,7]}
    ]}
  };
  const FRAME_MS = 500;
  let routineTimer = 0, routineStart = 0, routineStep = -1;
  const routineActive = () => !!routines[prompt?.kind] && prompt.phase === 'active';
  const currentRoutine = () => routines[prompt?.kind];
  function routineText() {
    const { title, steps } = currentRoutine(), routine = steps;
    const step = routine[Math.max(0,routineStep)];
    el('title').textContent = title;
    el('cue').textContent = step.cue; el('cue').hidden = false;
    el('copy').textContent = step.hint;
    const dots = el('dots'); dots.hidden = false;
    if (dots.children.length !== routine.length) dots.replaceChildren(...routine.map(()=>document.createElement('i')));
    [...dots.children].forEach((dot,index)=>dot.classList.toggle('on',index === Math.max(0,routineStep)));
  }
  function routineTick() {
    if (!routineActive()) { stopRoutine(); return; }
    const elapsed = global.performance.now() - routineStart;
    const { steps: routine, stepMs } = currentRoutine();
    const index = Math.floor(elapsed/stepMs()) % routine.length, step = routine[index];
    if (index !== routineStep) {
      routineStep = index; routineText();
      el('announcement').textContent = `Step ${index+1} of ${routine.length}: ${step.cue}. ${step.hint}`;
    }
    if (image && step.frames) draw(still() ? step.frames[0] : step.frames[Math.floor(elapsed/FRAME_MS) % step.frames.length]);
  }
  const routineAnimates = () => !!currentRoutine()?.steps[0].frames;
  function startRoutine() {
    if (routineTimer) return;
    routineStart = global.performance.now(); routineStep = -1;
    if (routineAnimates()) global.cancelAnimationFrame(frameRequest);
    routineTimer = global.setInterval(routineTick,250);
    routineTick();
  }
  function stopRoutine() {
    if (routineTimer) global.clearInterval(routineTimer);
    routineTimer = 0; routineStep = -1;
    el('cue').hidden = true; el('dots').hidden = true;
  }
  function play() {
    if (routineActive()) { startRoutine(); routineTick(); if (routineAnimates()) return; }
    global.cancelAnimationFrame(frameRequest); started = global.performance.now();
    frameRequest = global.requestAnimationFrame(tick);
  }
  // The bubble and mascot fade in as a teaser: a meeting from 30 to 5 minutes out, a wellness reminder over
  // its last two minutes. A preview fades in over a few seconds so the effect can be seen.
  const clamp01 = value => Math.min(1,Math.max(0,value));
  function fadeLevel() {
    const left = prompt.remainingSeconds;
    if (prompt.preview || left == null) return 1;
    if (prompt.phase === 'teaser') return clamp01((120-left)/120);
    if (prompt.kind === 'meeting' && prompt.phase === 'ready') return clamp01((1800-left)/1500);
    return 1;
  }
  function previewFade() {
    root.style.transition = 'none'; root.style.opacity = still() ? '1' : '0';
    if (still()) return;
    void root.offsetWidth;
    root.style.transition = 'opacity 8s linear'; root.style.opacity = '1';
  }
  async function load(kind) {
    const generation = ++token; image = null; draw(0);
    const definition = definitions[kind];
    canvas.setAttribute('aria-label',definition.alt);
    try {
      let next = images.get(definition.sheet);
      if (!next) { next = new Image(); next.src = `ergonomics/${definition.sheet}.png`; await next.decode(); images.set(definition.sheet,next); }
      if (generation !== token) return;
      image = next; play();
    } catch { if (generation === token) el('feedback').textContent = 'Animation unavailable. Your reminder controls still work.'; }
  }
  function buttons() {
    for (const button of [...root.querySelectorAll('button'),el('close')]) button.disabled = busy;
  }
  // The close button sits outside the fading bubble, so it is placed over the bubble's top-right corner.
  function placeClose() {
    const bubble = root.querySelector('.ergonomics-bubble'), close = el('close');
    const box = bubble.getBoundingClientRect();
    if (!box.width) return;
    close.style.top = `${box.top+12}px`;
    close.style.left = `${box.right-12-close.offsetWidth}px`;
    close.style.right = 'auto';
  }
  function update(next) {
    if (!next?.settings) return;
    const previous = prompt; state = next; prompt = next.prompt;
    root.hidden = !prompt;
    el('close').hidden = !prompt;
    root.dataset.corner = next.settings.corner;
    if (!prompt || !definitions[prompt.kind]) { root.hidden = true; el('close').hidden = true; token++; image = null; global.cancelAnimationFrame(frameRequest); return; }
    const definition = definitions[prompt.kind];
    const meeting = prompt.kind === 'meeting';
    const call = prompt.kind === 'call';
    const event = next.calendar?.selectedEvent;
    el('title').textContent = meeting ? event?.title || 'Your next meeting' : call ? prompt.callApp ? `${prompt.callApp} call` : 'Call in progress' : prompt.phase === 'complete' ? 'A little refreshed?' : definition.title;
    const recordAsk = 'Record a transcript, or just coach your speaking? Nothing is recorded unless you choose Record.';
    el('copy').textContent = call ? `${prompt.callApp ? `Your microphone is in use by ${prompt.callApp}.` : 'Your microphone is in use by a browser.'} ${recordAsk}` : meeting ? `${prompt.phase === 'starting' ? 'Starting now' : `Starts at ${new Date(event.start*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}`} · ${event?.calendarTitle || 'Calendar'}${prompt.recordOffer ? ` · ${recordAsk}` : ''}` : definition.copy;
    if (routineActive()) startRoutine(); else stopRoutine();
    const teaser = prompt.phase === 'teaser';
    el('countdown').textContent = prompt.remainingSeconds == null || teaser || prompt.recordOffer ? '' : `${Math.floor(prompt.remainingSeconds/60)}:${String(prompt.remainingSeconds%60).padStart(2,'0')}${meeting ? '' : ' remaining'}${routineActive() && routineStep >= 0 ? ` · step ${routineStep+1} of ${currentRoutine().steps.length}` : ''}`;
    el('countdown').classList.toggle('ergonomics-meeting-countdown',meeting);
    const starts = prompt.phase === 'ready' && ['break','eyes'].includes(prompt.kind);
    el('primary').textContent = call ? 'Record this call' : meeting ? prompt.preview ? 'Close preview' : prompt.recordOffer ? 'Record this meeting' : 'Open Calendar' : starts ? prompt.kind === 'break' ? 'Start break' : 'Start eye rest' : 'Done';
    // A teaser is only a preview of what is coming: nothing on it can be pressed until the reminder is due.
    // While a break counts down the close button is the way out, so there is no End early.
    el('primary').hidden = teaser || (meeting && prompt.preview) || prompt.phase === 'active';
    const item = next.settings[prompt.kind === 'break' ? 'breaks' : prompt.kind];
    el('snooze').textContent = `Snooze · ${item?.snoozeMinutes || 5} min`;
    el('snooze').hidden = teaser || meeting || call || prompt.preview || prompt.phase === 'complete';
    // Coach me coaches the speaker's own voice with the Live Workspace and records nothing.
    el('coach').hidden = teaser || !!prompt.preview || !(call || (meeting && prompt.recordOffer));
    el('replay').hidden = !prompt.preview;
    el('pause').hidden = teaser || meeting || call || !!prompt.preview;
    // A quiet way out that only hides the reminder: for a meeting it is the old "Hide this meeting".
    el('later').hidden = teaser || !!prompt.preview || !(meeting || call);
    el('later').textContent = meeting && !prompt.recordOffer ? 'Hide this meeting' : 'Not now';
    if (!prompt.preview) { root.style.transition = still() ? 'none' : 'opacity 1s linear'; root.style.opacity = String(fadeLevel()); }
    if (!previous || previous.id !== prompt.id) {
      if (prompt.preview) previewFade();
      el('feedback').textContent = prompt.preview ? 'Preview · no reminder schedule is changed.' : '';
      el('announcement').textContent = `${prompt.preview ? 'Reminder preview' : 'Reminder'}: ${meeting ? event?.title || 'Upcoming meeting' : definition.title} ${definition.copy}`;
      void load(prompt.kind);
    } else if (still() && !routineActive()) { global.cancelAnimationFrame(frameRequest); draw(0); }
    if (routineActive()) routineText();
    buttons();
    placeClose();
  }
  async function action(actionName) {
    if (busy || !prompt) return;
    const reminderId = prompt.id;
    busy = true; buttons();
    try {
      const next = await invoke('ergonomics_reminder_action',{reminderId:['close-preview','pause'].includes(actionName) ? '' : reminderId,action:actionName});
      if (next?.settings) update(next);
    } catch (error) {
      // Native errors are short sentences written for the person (for example, the speech model is not ready).
      el('feedback').textContent = typeof error === 'string' && error && error.length < 160 ? error : 'Could not update this reminder. Try again.';
    }
    finally { busy = false; buttons(); }
  }
  el('primary').addEventListener('click',()=>{
    if (!prompt) return;
    const meetingAction = prompt.recordOffer ? 'record' : 'open-calendar';
    void action(prompt.kind === 'call' ? 'record' : prompt.kind === 'meeting' && !prompt.preview ? meetingAction : prompt.phase === 'ready' && ['break','eyes'].includes(prompt.kind) ? 'start' : prompt.preview ? 'close-preview' : 'done');
  });
  el('later').addEventListener('click',()=>{ if (prompt) void action(prompt.kind === 'call' ? 'dismiss' : 'done'); });
  el('coach').addEventListener('click',()=>void action('coach'));
  el('snooze').addEventListener('click',()=>void action('snooze'));
  el('pause').addEventListener('click',()=>void action('pause'));
  // The close button ends the reminder without snoozing: a preview just closes, a meeting is hidden, and
  // anything else is dismissed so the next one comes at its normal interval.
  const closeAction = () => prompt.preview ? 'close-preview' : prompt.kind === 'meeting' ? 'done' : 'dismiss';
  el('close').addEventListener('click',()=>{ if (prompt) void action(closeAction()); });
  el('replay').addEventListener('click',()=>{ if (prompt?.preview) previewFade(); play(); });
  reduced.addEventListener('change',()=>{if (prompt) play();});
  global.addEventListener('keydown',event=>{if (event.key === 'Escape' && prompt) void action(closeAction());});
  global.addEventListener('resize',placeClose);
  if (global.ResizeObserver) new global.ResizeObserver(placeClose).observe(root.querySelector('.ergonomics-bubble'));
  async function refresh() {
    if (polling) return;
    polling = true;
    try { update(await invoke('ergonomics_get_state')); }
    catch { el('feedback').textContent = 'Could not refresh this reminder. Reopen OfficeKit to try again.'; }
    finally { polling = false; }
  }
  async function start() {
    if (!global.__TAURI__?.core?.invoke) return;
    try { await refresh(); global.setInterval(()=>void refresh(),1000); document.addEventListener('visibilitychange',()=>void refresh()); }
    catch { root.hidden = false; el('feedback').textContent = 'Desktop reminders are unavailable. Reopen OfficeKit to try again.'; for (const button of root.querySelectorAll('button')) button.disabled = true; }
  }
  void start();
})(window);
