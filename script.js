/* ═══════════════════════════════════════════════════════
   SMART HOME — script.js
   All device control, UI helpers, energy, memory, push
   ═══════════════════════════════════════════════════════ */

let curtainStates = { living: false, bedroom: false, kitchen: false, balcony: false };
let windowStates  = { kitchen: false };

/* ═══════════════════════════════════════════════════════
   ACTIVITY LOG
   ═══════════════════════════════════════════════════════ */
function loadLog() {
  fetch('/get_log').then(res => res.json()).then(entries => {
    const box = document.getElementById('activity-log');
    if (!box) return;
    if (!entries.length) {
      box.innerHTML = '<p style="color:var(--text-muted);font-size:13px;text-align:center;padding:20px 0;">No activity yet.</p>';
      return;
    }
    box.innerHTML = entries.map(e =>
      `<div class="log-entry">
         <span class="log-icon">${e.icon}</span>
         <span class="log-msg">${e.message}</span>
         <span class="log-time">${e.time}</span>
       </div>`).join('');
  });
}

function clearLog() {
  fetch('/clear_log', { method: 'POST' }).then(() => loadLog());
}

/* ═══════════════════════════════════════════════════════
   LIGHTS
   ═══════════════════════════════════════════════════════ */
function toggleLight(room = 'living') {
  fetch('/toggle_light', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ room })
  }).then(res => res.json()).then(data => {
    const isOn = data.status === 'on';
    // UI updates handled by socket state_update — but do local optimistic update too
    if (typeof setPowerBtn === 'function') setPowerBtn(`pwrbtn-${room}-light`, isOn);
    if (typeof setDeviceStatus === 'function') setDeviceStatus(`${room}-light-status`, isOn);
    if (typeof setCardState === 'function') setCardState(`card-${room}-light`, isOn);
    loadLog();
  });
}

/* ═══════════════════════════════════════════════════════
   FAN SPEED — uses new dial UI
   ═══════════════════════════════════════════════════════ */
function setFanSpeed(speed, room = 'living') {
  speed = parseInt(speed);
  fetch('/set_fan_speed', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ speed, room })
  }).then(res => res.json()).then(() => {
    if (typeof setFanArc === 'function') setFanArc(room, speed);
    if (typeof setCardState === 'function') setCardState(`card-${room}-fan`, speed > 0);
    loadLog();
  });
}

/* ═══════════════════════════════════════════════════════
   CURTAINS — with visual animation + weather automation
   ═══════════════════════════════════════════════════════ */
function setCurtain(room = 'living', open = true) {
  curtainStates[room] = open;
  fetch('/toggle_curtain', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ open, room })
  }).then(res => res.json()).then(data => {
    if (typeof setCurtainVisual === 'function') setCurtainVisual(room, open);
    if (typeof setCardState === 'function') setCardState(`card-${room}-curtain`, open);
    loadLog();
  });
}

// Legacy toggle (kept for any old references)
function toggleCurtain(room = 'living') {
  setCurtain(room, !curtainStates[room]);
}

/* ─ Weather-based curtain automation ──────────────────── */
function autoCurtainByWeather(weatherData) {
  if (!weatherData) return;
  const rooms = ['living', 'bedroom', 'kitchen', 'balcony'];
  if (weatherData.is_raining) {
    // Rain: close all curtains
    rooms.forEach(room => {
      if (curtainStates[room]) {
        setCurtain(room, false);
      }
    });
    // Also close kitchen window
    setWindow('kitchen', false);
    showToast('🌧 Rain detected — curtains closed, window closed');
    if (typeof showPushNotification === 'function') {
      showPushNotification('🌧 Weather Auto-Control', 'Rain detected — curtains & window closed automatically', 'weather');
    }
  } else if (!weatherData.is_raining && weatherData.condition === 'Clear' && weatherData.is_daytime) {
    // Sunny daytime: optionally open curtains
    // (don't force open — user may prefer them closed)
    showToast('☀️ Sunny day — curtains can be opened for natural light');
  }
}

/* ═══════════════════════════════════════════════════════
   KITCHEN WINDOW — separate from curtains
   ═══════════════════════════════════════════════════════ */
function setWindow(room = 'kitchen', open = true) {
  windowStates[room] = open;
  const leftPane  = document.getElementById(`win-pane-left-${room}`);
  const rightPane = document.getElementById(`win-pane-right-${room}`);
  const statusEl  = document.getElementById(`${room}-window-status`);
  if (leftPane)  leftPane.classList.toggle('open', open);
  if (rightPane) rightPane.classList.toggle('open', open);
  if (statusEl)  statusEl.textContent = open ? 'Window Open' : 'Window Closed';
  // Log via generic curtain endpoint (closest match)
  fetch('/toggle_curtain', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ open, room })
  }).then(() => loadLog());
}

/* ═══════════════════════════════════════════════════════
   LIGHT DIMMER
   ═══════════════════════════════════════════════════════ */
function updateDimmer(value, room = 'living') {
  value = parseInt(value);
  if (typeof updateDimmerPreview === 'function') updateDimmerPreview(room, value);
  // Debounce server calls
  clearTimeout(updateDimmer._timer = updateDimmer._timer || {});
  const key = room;
  clearTimeout(updateDimmer[key]);
  updateDimmer[key] = setTimeout(() => {
    fetch('/set_dimmer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ brightness: value, room })
    }).then(res => res.json()).then(() => loadLog());
  }, 200);
}

/* ═══════════════════════════════════════════════════════
   AC CONTROL
   ═══════════════════════════════════════════════════════ */
function toggleAC(room = 'bedroom') {
  const statusEl = document.getElementById(`ac-status-text-${room}`);
  const isOn = statusEl && statusEl.textContent.includes('ON');
  const newState = !isOn;
  fetch('/toggle_ac', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status: newState, room })
  }).then(res => res.json()).then(() => {
    if (typeof setPowerBtn === 'function') setPowerBtn(`pwrbtn-${room}-ac`, newState);
    const acDisplay = document.getElementById(`ac-display-${room}`);
    if (acDisplay) acDisplay.classList.toggle('on', newState);
    if (statusEl) statusEl.textContent = newState ? 'AC is ON — Cooling Active' : 'AC is OFF';
    if (typeof setCardState === 'function') setCardState(`card-${room}-ac`, newState);
    loadLog();
  });
}

/* ═══════════════════════════════════════════════════════
   INVERTER
   ═══════════════════════════════════════════════════════ */
function toggleInverter(room = 'bedroom') {
  const statusEl = document.getElementById(`${room}-inverter-status`);
  const isOn = statusEl && statusEl.textContent.includes('ON');
  const newState = !isOn;
  fetch('/inverter', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status: newState, room })
  }).then(res => res.json()).then(data => {
    if (statusEl) statusEl.textContent = newState ? 'Inverter ON — Backup Mode' : 'Inverter OFF — Grid Power';
    if (typeof setPowerBtn === 'function') setPowerBtn(`pwrbtn-${room}-inverter`, newState);
    loadLog();
  });
}

function checkInverterStatus(room = 'bedroom') {
  const battery = parseInt(document.getElementById(`${room}-batteryLevel`)?.value || 72);
  fetch('/check_inverter_status', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ battery, room })
  }).then(res => res.json()).then(data => {
    const el = document.getElementById(`${room}-inverterStatus`);
    if (el) { el.textContent = data.message; el.style.display = 'block'; }
    // Update battery bar
    const fillEl = document.getElementById('inv-batt-fill');
    const pctEl  = document.getElementById('inv-batt-pct');
    if (fillEl) fillEl.style.width = battery + '%';
    if (pctEl)  pctEl.textContent  = battery + '%';
    loadLog();
  });
}

/* ═══════════════════════════════════════════════════════
   WATER LEVEL
   ═══════════════════════════════════════════════════════ */
function checkWaterLevel(value) {
  value = parseInt(value);
  // Update tank visual
  const fill    = document.getElementById('water-fill');
  const display = document.getElementById('water-pct-display');
  if (fill)    fill.style.height    = value + '%';
  if (display) display.textContent  = value + '%';
  fetch('/water_level', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ level: value })
  }).then(res => res.json()).then(() => {});
}

/* ═══════════════════════════════════════════════════════
   SECURITY — GAS, SMOKE, INTRUDER
   ═══════════════════════════════════════════════════════ */
function detectGas() {
  const leak = Math.random() < 0.5;
  fetch('/detect_gas', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ leak })
  }).then(res => res.json()).then(() => {
    const statusEl = document.getElementById('gas-status');
    const box      = document.getElementById('gas-status-box');
    const dot      = document.getElementById('gas-dot');
    if (statusEl) statusEl.textContent = leak ? '⚠️ Gas Leak Detected!' : 'All Clear';
    if (box) { box.className = 'security-status ' + (leak ? 'alert' : 'safe'); }
    if (dot) dot.className = 'security-dot';
    if (leak && typeof showPushNotification === 'function') {
      showPushNotification('⚠️ Gas Alert', 'Gas leak detected in kitchen!', 'alert');
    }
    loadLog();
  });
}

function detectSmoke() {
  const detected = Math.random() < 0.5;
  fetch('/detect_smoke', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ smoke: detected })
  }).then(res => res.json()).then(data => {
    const statusEl = document.getElementById('smoke-status');
    const box      = document.getElementById('smoke-status-box');
    if (statusEl) statusEl.textContent = detected ? '🔥 Smoke Detected!' : 'No Smoke';
    if (box) box.className = 'security-status ' + (detected ? 'alert' : 'safe');
    if (detected && typeof showPushNotification === 'function') {
      showPushNotification('🔥 Smoke Alert', 'Smoke detected in kitchen!', 'alert');
    }
    loadLog();
  });
}

function fireAlert() {
  fetch('/fire_alert', { method: 'POST' }).then(res => res.json()).then(data => {
    const el = document.getElementById('fire-status');
    if (el) el.textContent = data.message;
    const box = document.getElementById('smoke-status-box');
    if (box) box.className = 'security-status alert';
    if (typeof showPushNotification === 'function') {
      showPushNotification('🔥 FIRE ALERT', 'Fire detected in kitchen! Buzzer ON!', 'alert');
    }
    loadLog();
  });
}

function detectIntruder() {
  const intruder = Math.random() < 0.3;
  fetch('/detect_intruder', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ intruder })
  }).then(res => res.json()).then(data => {
    const statusEl = document.getElementById('intruder-status');
    const box      = document.getElementById('intruder-status-box');
    if (statusEl) {
      statusEl.textContent = intruder ? '🚨 Intruder Detected!' : 'All Safe ✓';
      statusEl.style.color = intruder ? 'var(--accent-red)' : 'var(--accent-green)';
    }
    if (box) box.className = 'security-status ' + (intruder ? 'alert' : 'safe');
    if (intruder && typeof showPushNotification === 'function') {
      showPushNotification('🚨 Security Alert', 'Intruder detected!', 'alert');
    }
    loadLog();
  });
}

/* ═══════════════════════════════════════════════════════
   DOOR / BELL
   ═══════════════════════════════════════════════════════ */
function unlockDoor() {
  const password = document.getElementById('doorPassword')?.value;
  fetch('/unlock_door', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password })
  }).then(res => res.json()).then(data => {
    const el = document.getElementById('lock-status');
    if (el) el.textContent = data.status === 'success' ? '✅ Door Unlocked' : '❌ Incorrect Password';
    if (data.status !== 'success' && typeof showPushNotification === 'function') {
      showPushNotification('🔒 Door Alert', 'Failed door unlock attempt!', 'alert');
    }
    loadLog();
  });
}

function ringBell() {
  fetch('/ring_bell', { method: 'POST' }).then(res => res.json()).then(data => {
    const el = document.getElementById('bell-status');
    if (el) el.textContent = data.message;
    if (typeof showPushNotification === 'function') {
      showPushNotification('🔔 Doorbell', 'Someone is at the door!', 'bell');
    }
    loadLog();
    setTimeout(() => { if (el) el.textContent = 'No visitor'; }, 5000);
  });
}

function approachDoor() {
  fetch('/approach_door', { method: 'POST' }).then(res => res.json()).then(data => {
    const el = document.getElementById('auto-door-status');
    if (el) el.textContent = data.message;
    showPushNotification('🚪 Auto Door', 'Someone approaching — door opened!', 'door');
    _showDoorAnimation();
    loadLog();
    setTimeout(() => { if (el) el.textContent = 'No one nearby'; }, 5000);
  });
}

function _showDoorAnimation() {
  document.getElementById('_door_anim_overlay')?.remove();

  if (!document.getElementById('_door_anim_style')) {
    const s = document.createElement('style');
    s.id = '_door_anim_style';
    s.textContent = `
      @keyframes _doorBgIn   { from{opacity:0} to{opacity:1} }
      @keyframes _doorBgOut  { from{opacity:1} to{opacity:0} }
      @keyframes _doorRingPulse {
        0%,100% { box-shadow: 0 0 0 0 rgba(200,169,110,0.5), 0 0 40px rgba(200,169,110,0.15); }
        50%     { box-shadow: 0 0 0 18px rgba(200,169,110,0), 0 0 60px rgba(200,169,110,0.25); }
      }
      @keyframes _doorSwing {
        0%   { transform: rotateY(0deg); }
        100% { transform: rotateY(-110deg); }
      }
      @keyframes _doorLightSpread {
        0%   { opacity:0; transform:scaleX(0.2) scaleY(0.5); }
        40%  { opacity:1; }
        100% { opacity:0.6; transform:scaleX(1) scaleY(1); }
      }
      @keyframes _doorTextIn {
        0%   { opacity:0; transform:translateX(-50%) translateY(8px); }
        100% { opacity:1; transform:translateX(-50%) translateY(0); }
      }
      #_door_anim_overlay {
        position:fixed; inset:0; z-index:99998;
        display:flex; align-items:center; justify-content:center;
        background:rgba(4,8,16,0.7);
        backdrop-filter:blur(8px);
        -webkit-backdrop-filter:blur(8px);
        animation:_doorBgIn 0.4s ease;
        cursor:pointer;
      }
      #_door_anim_overlay.fading {
        animation:_doorBgOut 0.5s ease forwards;
      }
      ._da_circle {
        position:relative;
        width:200px; height:200px;
        border-radius:50%;
        background:radial-gradient(circle at 40% 35%,
          rgba(45,28,12,0.95) 0%,
          rgba(22,13,5,0.98) 60%,
          rgba(10,6,2,1) 100%);
        border:1.5px solid rgba(200,169,110,0.25);
        box-shadow:
          0 0 0 1px rgba(200,169,110,0.08),
          0 30px 80px rgba(0,0,0,0.8),
          inset 0 1px 0 rgba(255,220,150,0.06);
        animation:_doorRingPulse 2s ease-in-out infinite;
        display:flex; align-items:center; justify-content:center;
        overflow:hidden;
      }
      ._da_perspective {
        perspective:320px;
        perspective-origin:30% 50%;
        position:relative;
        width:72px; height:104px;
      }
      ._da_door {
        width:100%; height:100%;
        transform-origin:left center;
        transform-style:preserve-3d;
        animation:_doorSwing 1.4s cubic-bezier(0.25,0.46,0.45,0.94) 0.3s forwards;
        position:relative;
      }
      ._da_door_face {
        position:absolute; inset:0;
        background:linear-gradient(135deg,
          rgba(101,67,33,0.95) 0%,
          rgba(78,50,24,0.95) 40%,
          rgba(58,36,16,0.95) 100%);
        border-radius:2px 6px 6px 2px;
        border:1px solid rgba(140,100,50,0.4);
        border-left:2px solid rgba(160,115,60,0.6);
      }
      ._da_door_panel_t {
        position:absolute; left:10px; right:10px; top:10px; height:34px;
        border:1px solid rgba(140,100,50,0.25);
        border-radius:2px;
        background:rgba(0,0,0,0.15);
      }
      ._da_door_panel_b {
        position:absolute; left:10px; right:10px; top:52px; bottom:10px;
        border:1px solid rgba(140,100,50,0.25);
        border-radius:2px;
        background:rgba(0,0,0,0.15);
      }
      ._da_knob {
        position:absolute; right:8px; top:50%;
        width:8px; height:8px; border-radius:50%;
        background:radial-gradient(circle at 35% 30%, #e8c97a, #a07830);
        box-shadow:0 2px 5px rgba(0,0,0,0.6), 0 0 6px rgba(220,180,90,0.3);
        transform:translateY(-50%);
      }
      ._da_frame {
        position:absolute; inset:0; pointer-events:none;
        border:3px solid rgba(80,50,20,0.7);
        border-radius:2px 6px 6px 2px;
      }
      ._da_light {
        position:absolute;
        left:73px; top:50%; transform:translateY(-50%);
        width:90px; height:110px;
        background:radial-gradient(ellipse at left center,
          rgba(255,200,100,0.22) 0%,
          rgba(255,180,80,0.08) 50%,
          transparent 100%);
        transform-origin:left center;
        animation:_doorLightSpread 1.4s ease 0.5s forwards;
        opacity:0;
        pointer-events:none;
        border-radius:0 50% 50% 0;
      }
      ._da_label {
        position:absolute;
        bottom:22px; left:50%;
        transform:translateX(-50%);
        font-size:11px; font-weight:600; letter-spacing:1.5px;
        color:rgba(200,169,110,0.7);
        text-transform:uppercase;
        white-space:nowrap;
        animation:_doorTextIn 0.5s ease 0.8s both;
      }
    `;
    document.head.appendChild(s);
  }

  const overlay = document.createElement('div');
  overlay.id = '_door_anim_overlay';
  overlay.innerHTML = `
    <div class="_da_circle">
      <div class="_da_perspective">
        <div class="_da_door">
          <div class="_da_door_face">
            <div class="_da_door_panel_t"></div>
            <div class="_da_door_panel_b"></div>
            <div class="_da_knob"></div>
          </div>
        </div>
        <div class="_da_frame"></div>
        <div class="_da_light"></div>
      </div>
      <div class="_da_label">Door Open</div>
    </div>
  `;
  overlay.onclick = () => {
    overlay.classList.add('fading');
    setTimeout(() => overlay.remove(), 500);
  };
  document.body.appendChild(overlay);

  setTimeout(() => {
    if (!overlay.parentElement) return;
    overlay.classList.add('fading');
    setTimeout(() => overlay.remove(), 500);
  }, 3000);
}
/* ═══════════════════════════════════════════════════════
   SCHEDULE — with device select
   ═══════════════════════════════════════════════════════ */
function setSchedule(room = 'living') {
  const deviceEl = document.getElementById(`${room}-scheduleDevice`);
  const device   = deviceEl ? deviceEl.value : 'light';
  const onTime   = document.getElementById(`${room}-onTime`)?.value;
  const offTime  = document.getElementById(`${room}-offTime`)?.value;
  if (!onTime || !offTime) {
    const el = document.getElementById(`${room}-schedule-status`);
    if (el) el.textContent = '⚠️ Please select both ON and OFF times!';
    return;
  }
  fetch('/set_schedule', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ on: onTime, off: offTime, room, device })
  }).then(res => res.json()).then(data => {
    const el = document.getElementById(`${room}-schedule-status`);
    if (el) el.textContent = '✅ ' + data.message;
    loadLog();
    loadScheduleList(room);
  });
}

function loadScheduleList(room) {
  fetch('/get_schedules').then(res => res.json()).then(all => {
    const mine   = all.filter(s => s.room === room);
    const listEl = document.getElementById(`${room}-schedule-list`);
    if (!listEl) return;
    if (!mine.length) { listEl.innerHTML = ''; return; }
    listEl.innerHTML = mine.map(s => `
      <div style="display:flex;justify-content:space-between;align-items:center;
                  padding:7px 10px;border-radius:8px;background:var(--surface-01);
                  border:1px solid var(--glass-border);margin-top:6px;font-size:12px;">
        <span style="color:var(--text-secondary);">${s.device} → ON ${s.on_time} / OFF ${s.off_time}</span>
        <button onclick="deleteSchedule('${s.room}','${s.device}')"
          style="font-size:11px;padding:3px 9px;margin:0;background:var(--btn-danger);">✕</button>
      </div>`).join('');
  });
}

function deleteSchedule(room, device) {
  fetch('/delete_schedule', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ room, device })
  }).then(() => loadScheduleList(room));
}

/* ═══════════════════════════════════════════════════════
   PLANT WATERING — with animations
   ═══════════════════════════════════════════════════════ */
function checkSoil(room = 'kitchen') {
  const dry      = Math.random() < 0.5;
  const wrapId   = room === 'balcony' ? 'plant-wrap-balcony' : 'plant-wrap';
  const dropsId  = room === 'balcony' ? 'plant-drops-balcony' : 'plant-drops';
  const statusId = room === 'balcony' ? 'balcony-plant-status' : 'plant-status';

  fetch('/check_soil', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dry })
  }).then(res => res.json()).then(data => {
    const statusEl = document.getElementById(statusId);
    const drops    = document.getElementById(dropsId);
    const wrap     = document.getElementById(wrapId);
    if (statusEl) statusEl.textContent = dry ? '💧 Watering in progress...' : '✅ Soil is moist — no watering needed';
    if (statusEl) statusEl.style.color = dry ? 'var(--accent-cyan)' : 'var(--accent-green)';
    if (dry && drops) {
      drops.parentElement?.classList.add('watering');
      setTimeout(() => { drops.parentElement?.classList.remove('watering'); if (statusEl) statusEl.textContent = '✅ Watering complete!'; }, 4000);
    }
    loadLog();
  });
}

/* ═══════════════════════════════════════════════════════
   PET FEEDER
   ═══════════════════════════════════════════════════════ */
function feedPet() {
  fetch('/feed_pet', { method: 'POST' }).then(res => res.json()).then(data => {
    const el = document.getElementById('pet-status');
    if (el) el.textContent = data.message;
    showToast('🐾 ' + data.message);
    loadLog();
  });
}

function setPetFeederAutomation() {
  const feedTime   = document.getElementById('feedTime')?.value;
  const graceDelay = parseInt(document.getElementById('graceDelay')?.value);
  if (!feedTime || isNaN(graceDelay)) {
    const el = document.getElementById('pet-feeder-status');
    if (el) el.textContent = '⚠️ Please enter both time and delay.';
    return;
  }
  fetch('/set_pet_feeder_automation', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ time: feedTime, delay: graceDelay })
  }).then(res => res.json()).then(data => {
    const el = document.getElementById('pet-feeder-status');
    if (el) el.textContent = '✅ ' + data.message;
    loadLog();
  });
}

/* ═══════════════════════════════════════════════════════
   SEARCH / FILTER
   ═══════════════════════════════════════════════════════ */
function filterCards() {
  const input = document.getElementById('searchInput')?.value.toLowerCase() || '';
  document.querySelectorAll('.card').forEach(card => {
    card.style.display = card.innerText.toLowerCase().includes(input) ? '' : 'none';
  });
}

/* ═══════════════════════════════════════════════════════
   FACE RECOGNITION SYSTEM
   ═══════════════════════════════════════════════════════ */
function faceShowTask(msg, visible = true, spinning = false) {
  const bar     = document.getElementById('face-task-bar');
  const msgEl   = document.getElementById('face-task-msg');
  const spinner = document.getElementById('face-task-spinner');
  if (bar)     bar.style.display     = visible ? 'flex' : 'none';
  if (msgEl)   msgEl.textContent     = msg;
  if (spinner) spinner.style.display = spinning ? 'inline-block' : 'none';
}

function faceRecognize() {
  const btn = document.getElementById('face-scan-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Scanning...'; }
  faceShowTask('📷 Camera opening — look at the camera!', true, true);
  const resultEl = document.getElementById('face-result');
  if (resultEl) resultEl.textContent = '';
  fetch('/face/recognize', { method: 'POST' })
    .then(res => res.json())
    .then(data => {
      if (!data.success) {
        faceShowTask('❌ ' + data.message, true, false);
        if (btn) { btn.disabled = false; btn.textContent = '📷 Scan & Identify Face'; }
      }
    })
    .catch(() => {
      faceShowTask('❌ Server error — is Flask running?', true, false);
      if (btn) { btn.disabled = false; btn.textContent = '📷 Scan & Identify Face'; }
    });
}

function _faceResetScanBtn() {
  const btn = document.getElementById('face-scan-btn');
  if (btn) { btn.disabled = false; btn.textContent = '📷 Scan & Identify Face'; }
}

function faceRegister() {
  const name = document.getElementById('face-reg-name')?.value.trim();
  if (!name) { alert('Please enter a name first!'); return; }
  const btn = document.getElementById('face-reg-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Registering...'; }
  faceShowTask(`📸 Camera opening for "${name}" — look at the camera, move slowly...`, true, true);
  fetch('/face/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name })
  }).then(res => res.json()).then(data => {
    if (!data.success) {
      faceShowTask('❌ ' + data.message, true, false);
      if (btn) { btn.disabled = false; btn.textContent = '📸 Register Face'; }
    } else {
      faceShowTask(`⏳ Capturing images for "${name}"... stay in frame!`, true, true);
    }
  }).catch(() => {
    faceShowTask('❌ Server error', true, false);
    if (btn) { btn.disabled = false; btn.textContent = '📸 Register Face'; }
  });
}

function faceTrain() {
  faceShowTask('🧠 Training model...', true, true);
  fetch('/face/train', { method: 'POST' }).then(r => r.json()).then(data => {
    faceShowTask(data.success ? `✅ ${data.message}` : `❌ ${data.message}`, true, false);
    if (data.success) {
      setTimeout(() => faceLoadUsers(), 400);
      showToast('✅ Model trained! Face scanning ready.');
    }
  }).catch(() => faceShowTask('❌ Train failed', true, false));
}

function faceLoadUsers() {
  fetch('/face/users').then(res => res.json()).then(data => {
    const container = document.getElementById('face-users-list');
    if (!container) return;
    if (!data.users || !data.users.length) {
      container.innerHTML = '<p style="font-size:13px;color:var(--text-muted);">No users registered yet.</p>';
      return;
    }
    container.innerHTML = data.users.map(name => {
      const p = data.profiles[name] || {};
      return `
        <div class="face-user-card" id="face-card-${name}">
          <div onclick="toggleFaceCard('${name}')"
            style="display:flex;justify-content:space-between;align-items:center;padding:12px 16px;cursor:pointer;user-select:none;">
            <div style="display:flex;align-items:center;gap:12px;">
              <div style="width:38px;height:38px;border-radius:50%;
                          background:linear-gradient(135deg,#004d40,#00695c);
                          display:flex;align-items:center;justify-content:center;font-size:16px;">👤</div>
              <div>
                <div style="font-size:14px;font-weight:600;color:var(--text-primary);">${name}</div>
                <div style="font-size:11px;color:var(--text-muted);margin-top:1px;">
                  💡${p.light?'ON':'OFF'} · 🌀${p.fan_speed||0} · 🔆${p.dimmer||70}% · ❄${p.ac?'ON':'OFF'}
                  ${p.music?'· 🎵 '+p.music.substring(0,14)+(p.music.length>14?'...':''):''}
                </div>
              </div>
            </div>
            <div style="display:flex;align-items:center;gap:8px;">
              <button onclick="event.stopPropagation();faceDeleteUser('${name}')"
                style="font-size:11px;padding:4px 10px;margin:0;background:var(--btn-danger);">🗑</button>
              <span id="face-card-arrow-${name}" style="font-size:13px;color:var(--text-muted);transition:transform 0.2s;">▼</span>
            </div>
          </div>
          <div id="face-card-details-${name}" style="display:none;padding:0 16px 16px;border-top:1px solid rgba(0,188,140,0.15);">
            <div style="padding-top:12px;display:grid;grid-template-columns:1fr 1fr;gap:10px;font-size:13px;">
              <label style="margin:0;color:var(--text-muted);">💡 Light
                <select onchange="faceUpdateProfile('${name}','light',this.value==='true')" style="margin:4px 0 0;padding:6px;">
                  <option value="true"  ${p.light?'selected':''}>ON</option>
                  <option value="false" ${!p.light?'selected':''}>OFF</option>
                </select>
              </label>
              <label style="margin:0;color:var(--text-muted);">🌀 Fan Speed
                <select onchange="faceUpdateProfile('${name}','fan_speed',parseInt(this.value))" style="margin:4px 0 0;padding:6px;">
                  ${[0,1,2,3,4,5].map(v=>`<option value="${v}" ${p.fan_speed===v?'selected':''}>${v}</option>`).join('')}
                </select>
              </label>
              <label style="margin:0;color:var(--text-muted);">🔆 Dimmer %
                <input type="number" min="0" max="100" value="${p.dimmer||70}"
                  onchange="faceUpdateProfile('${name}','dimmer',parseInt(this.value))" style="margin:4px 0 0;padding:6px;">
              </label>
              <label style="margin:0;color:var(--text-muted);">❄️ AC
                <select onchange="faceUpdateProfile('${name}','ac',this.value==='true')" style="margin:4px 0 0;padding:6px;">
                  <option value="false" ${!p.ac?'selected':''}>OFF</option>
                  <option value="true"  ${p.ac?'selected':''}>ON</option>
                </select>
              </label>
              <label style="margin:0;color:var(--text-muted);">💬 Greeting
                <input type="text" value="${p.greeting||'Welcome home!'}"
                  onchange="faceUpdateProfile('${name}','greeting',this.value)" style="margin:4px 0 0;padding:6px;">
              </label>
              <label style="margin:0;color:var(--text-muted);">🪟 Curtain
                <select onchange="faceUpdateProfile('${name}','curtain',this.value==='true')" style="margin:4px 0 0;padding:6px;">
                  <option value="false" ${!p.curtain?'selected':''}>Closed</option>
                  <option value="true"  ${p.curtain?'selected':''}>Open</option>
                </select>
              </label>
            </div>
            <label style="margin:10px 0 0;color:var(--text-muted);display:block;">
              🎵 Auto-play Music
              <input type="text" value="${p.music||''}" placeholder="e.g. Arijit Singh hits / lo-fi beats"
                onchange="faceUpdateProfile('${name}','music',this.value)"
                style="margin:4px 0 0;padding:8px;width:100%;border-radius:8px;">
            </label>
          </div>
        </div>`;
    }).join('');
  });
}

function toggleFaceCard(name) {
  const details = document.getElementById(`face-card-details-${name}`);
  const arrow   = document.getElementById(`face-card-arrow-${name}`);
  if (!details) return;
  const isOpen = details.style.display !== 'none';
  details.style.display = isOpen ? 'none' : 'block';
  if (arrow) arrow.style.transform = isOpen ? '' : 'rotate(180deg)';
}

const _profileCache = {};
function faceUpdateProfile(name, key, value) {
  if (!_profileCache[name]) _profileCache[name] = {};
  _profileCache[name][key] = value;
  clearTimeout(_profileCache[name]._timer);
  _profileCache[name]._timer = setTimeout(() => {
    fetch('/face/users').then(r => r.json()).then(data => {
      const current = data.profiles[name] || {};
      const updated = { ...current, ..._profileCache[name] };
      delete updated._timer;
      fetch('/face/profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, prefs: updated })
      }).then(() => loadLog());
    });
  }, 800);
}

function faceDeleteUser(name) {
  if (!confirm(`Delete ${name}'s face data and profile?`)) return;
  fetch('/face/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name })
  }).then(() => { faceLoadUsers(); loadLog(); });
}

/* ═══════════════════════════════════════════════════════
   MUSIC PLAYER
   ═══════════════════════════════════════════════════════ */
function _playAudio(audioUrl, title) {
  const audio    = document.getElementById('music-audio');
  const titleEl  = document.getElementById('music-title');
  const statusEl = document.getElementById('music-status-text');
  if (!audio) return;
  audio.src = audioUrl;
  audio.style.display = 'block';
  audio.load();
  audio.play()
    .then(() => {
      if (titleEl)  titleEl.textContent  = '▶ ' + title;
      if (statusEl) statusEl.textContent = 'playing';
    })
    .catch(err => {
      if (titleEl)  titleEl.textContent  = '⚠️ ' + title + ' (click play)';
      if (statusEl) statusEl.textContent = 'click play above';
    });
  audio.onended = () => { if (statusEl) statusEl.textContent = 'ended'; };
}

function musicSearchAndPlay(query) {
  const titleEl  = document.getElementById('music-title');
  const statusEl = document.getElementById('music-status-text');
  if (titleEl)  titleEl.textContent  = `🔍 Searching: ${query}...`;
  if (statusEl) statusEl.textContent = 'Loading...';
  fetch('/music/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query })
  }).then(r => r.json()).then(data => {
    if (!data.success) {
      if (titleEl)  titleEl.textContent  = '❌ Not found: ' + query;
      if (statusEl) statusEl.textContent = data.message || 'Error';
      return;
    }
    _playAudio(data.audio_url, data.title);
    loadLog();
  }).catch(() => {
    if (titleEl)  titleEl.textContent  = '❌ Network error';
    if (statusEl) statusEl.textContent = 'Error';
  });
}

function musicPlay() {
  const query = document.getElementById('music-search-input')?.value.trim();
  if (!query) { alert('Please enter a song name!'); return; }
  musicSearchAndPlay(query);
}

function musicStop() {
  const audio    = document.getElementById('music-audio');
  const titleEl  = document.getElementById('music-title');
  const statusEl = document.getElementById('music-status-text');
  if (audio) { audio.pause(); audio.src = ''; audio.style.display = 'none'; }
  if (titleEl)  titleEl.textContent  = 'No song playing';
  if (statusEl) statusEl.textContent = 'Stopped';
  fetch('/music/stop', { method: 'POST' });
  loadLog();
}

/* ═══════════════════════════════════════════════════════
   ROOM VOICE — Whisper STT + Kitty AI
   ═══════════════════════════════════════════════════════ */
let _roomVoiceActive = false;
let _roomMediaRecorder = null;
let _roomAudioChunks = [];

async function startRoomVoice(room) {
  if (_roomVoiceActive) return;
  const btn       = document.getElementById(`room-voice-btn-${room}`);
  const resultBox = document.getElementById(`room-voice-result-${room}`);
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch (err) {
    if (resultBox) { resultBox.style.display = 'block'; resultBox.textContent = '❌ Mic access denied!'; setTimeout(() => { resultBox.style.display = 'none'; }, 4000); }
    return;
  }
  _roomVoiceActive = true; _roomAudioChunks = [];
  const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus'
    : MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm'
    : MediaRecorder.isTypeSupported('audio/ogg;codecs=opus') ? 'audio/ogg;codecs=opus' : 'audio/mp4';
  try { _roomMediaRecorder = new MediaRecorder(stream, { mimeType }); } catch(e) { _roomMediaRecorder = new MediaRecorder(stream); }
  _roomMediaRecorder.ondataavailable = (e) => { if (e.data?.size > 0) _roomAudioChunks.push(e.data); };
  _roomMediaRecorder.onstop = async () => {
    stream.getTracks().forEach(t => t.stop());
    if (!_roomAudioChunks.length) { _resetRoomVoiceBtn(room); return; }
    if (btn) { btn.innerHTML = '⏳ <span>Processing...</span>'; btn.disabled = true; }
    if (resultBox) { resultBox.style.display = 'block'; resultBox.textContent = '⏳ Kitty is listening...'; }
    const actualMime = _roomMediaRecorder.mimeType || mimeType;
    const blob = new Blob(_roomAudioChunks, { type: actualMime }); _roomAudioChunks = [];
    const ext = actualMime.includes('ogg') ? '.ogg' : actualMime.includes('mp4') ? '.mp4' : '.webm';
    const formData = new FormData(); formData.append('audio', blob, `voice${ext}`);
    try {
      const whisperRes  = await fetch('/voice/whisper', { method: 'POST', body: formData });
      const whisperData = await whisperRes.json();
      if (!whisperData.success || !whisperData.text) {
        if (resultBox) resultBox.textContent = `❌ ${whisperData.error || 'Could not understand'}`;
        setTimeout(() => { if (resultBox) resultBox.style.display = 'none'; }, 3500);
        _resetRoomVoiceBtn(room); return;
      }
      const spokenText = whisperData.text;
      if (resultBox) resultBox.textContent = `🎤 "${spokenText}" — Sending to Kitty...`;
      const chatRes  = await fetch('/ai/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: `[${room} room] ${spokenText}`,
          lat: typeof _gpsLat !== 'undefined' ? _gpsLat : null,
          lon: typeof _gpsLon !== 'undefined' ? _gpsLon : null
        })
      });
      const chatData = await chatRes.json();
      const reply   = chatData.reply || 'Done!';
      const actions = chatData.actions || [];
      if (resultBox) {
        const actionSummary = actions.length ? ` ✅ ${actions.map(a => `${a.room} ${a.device}`).join(', ')}` : '';
        resultBox.innerHTML = `🤖 <strong>${reply.substring(0,80)}${reply.length>80?'...':''}</strong>${actionSummary}`;
      }
      showToast(`🤖 ${reply.substring(0,60)}`);
      if (actions.length) loadLog();
      setTimeout(() => { if (resultBox) resultBox.style.display = 'none'; }, 5000);
    } catch(err) {
      if (resultBox) resultBox.textContent = '❌ Server error — is Flask running?';
      setTimeout(() => { if (resultBox) resultBox.style.display = 'none'; }, 4000);
    }
    _resetRoomVoiceBtn(room);
  };
  _roomMediaRecorder.start();
  if (btn) {
    btn.innerHTML = '⏹ <span>Stop</span>';
    btn.style.background = 'linear-gradient(135deg,#880e4f,#b71c1c)';
    btn.style.boxShadow  = '0 4px 18px rgba(183,28,28,0.5)';
    btn.disabled = false;
    btn.onclick  = () => _stopRoomRecording();
  }
  if (resultBox) { resultBox.style.display = 'block'; resultBox.textContent = '🔴 Recording... press ⏹ to stop (max 8s)'; }
  setTimeout(() => { if (_roomVoiceActive) _stopRoomRecording(); }, 8000);
}

function _stopRoomRecording() {
  if (_roomMediaRecorder?.state !== 'inactive') _roomMediaRecorder?.stop();
  _roomVoiceActive = false;
}
function _resetRoomVoiceBtn(room) {
  _roomVoiceActive = false;
  const btn = document.getElementById(`room-voice-btn-${room}`);
  if (btn) {
    btn.innerHTML = '🎤 <span>Speak</span>';
    btn.style.background = 'linear-gradient(135deg,#880e4f,#c2185b)';
    btn.style.boxShadow  = '0 4px 18px rgba(194,24,91,0.5)';
    btn.disabled = false;
    btn.onclick  = () => startRoomVoice(room);
  }
}

/* ═══════════════════════════════════════════════════════
   TTS — Kitty Text-to-Speech
   ═══════════════════════════════════════════════════════ */
const KittyTTS = {
  enabled: false,
  voice: null,
  rate: 0.95, pitch: 1.1, volume: 0.9,
  _findVoice() {
    const voices = window.speechSynthesis.getVoices();
    return voices.find(v=>v.lang==='en-IN') || voices.find(v=>v.lang.startsWith('en-IN'))
        || voices.find(v=>v.lang==='en-GB')  || voices.find(v=>v.lang.startsWith('en')) || voices[0] || null;
  },
  speak(text) {
    if (!this.enabled || !text || !window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    const clean = text.replace(/[\u{1F300}-\u{1FFFF}]/gu,'').replace(/[✅❌⚠️🔔💡🌀❄️🪟🔆]/g,'').replace(/\*\*/g,'').replace(/→/g,', changed to,').trim();
    if (!clean) return;
    const utt = new SpeechSynthesisUtterance(clean);
    utt.lang = 'en-IN'; utt.rate = this.rate; utt.pitch = this.pitch; utt.volume = this.volume;
    if (!this.voice) this.voice = this._findVoice();
    if (this.voice) utt.voice = this.voice;
    window.speechSynthesis.speak(utt);
  },
  preload() {
    if (window.speechSynthesis.onvoiceschanged !== undefined) {
      window.speechSynthesis.onvoiceschanged = () => { this.voice = this._findVoice(); };
    }
    window.speechSynthesis.getVoices();
  }
};
KittyTTS.preload();

/* ═══════════════════════════════════════════════════════
   ENERGY ANALYTICS DASHBOARD
   ═══════════════════════════════════════════════════════ */
const ROOM_EMOJI   = { living:'🛋', bedroom:'🛏', kitchen:'🍳', balcony:'🌿' };
const DEVICE_EMOJI = { light:'💡', fan_speed:'🌀', ac:'❄️', inverter:'⚡', dimmer:'🔆', curtain:'🪟' };

function refreshEnergy() {
  loadEnergyToday();
  loadEnergyWeekly();
  loadEnergyTop();
  loadEnergyEvents();
}

function loadEnergyToday() {
  fetch('/energy/today').then(r => r.json()).then(data => {
    const el = id => document.getElementById(id);
    if (el('en-live-watts'))   el('en-live-watts').textContent   = `${data.live_watts||0} W`;
    if (el('en-today-kwh'))    el('en-today-kwh').textContent    = `${data.total_kwh||0} kWh`;
    if (el('en-today-cost'))   el('en-today-cost').textContent   = `₹${data.cost_inr||0}`;
    if (el('en-today-events')) el('en-today-events').textContent = data.total_events||0;
    const roomEl = el('en-room-breakdown');
    if (roomEl) {
      const rooms = data.room_kwh || {};
      roomEl.innerHTML = Object.keys(rooms).length ? Object.entries(rooms).sort((a,b)=>b[1]-a[1]).map(([room,kwh])=>
        `<div style="display:flex;justify-content:space-between;border-bottom:1px solid var(--glass-border);padding:2px 0;">
           <span>${ROOM_EMOJI[room]||'🏠'} ${room.charAt(0).toUpperCase()+room.slice(1)}</span>
           <span style="color:var(--accent-amber);font-weight:600;">${kwh} kWh</span>
         </div>`).join('') : '<span style="color:var(--text-muted);">No data yet</span>';
    }
  }).catch(()=>{});
}

function loadEnergyWeekly() {
  fetch('/energy/weekly').then(r => r.json()).then(days => {
    const chartEl = document.getElementById('en-weekly-chart');
    const labelEl = document.getElementById('en-weekly-labels');
    if (!chartEl || !labelEl) return;
    const maxKwh = Math.max(...days.map(d=>d.total_kwh), 0.001);
    chartEl.innerHTML = days.map(day => {
      const pct    = Math.round((day.total_kwh/maxKwh)*80);
      const height = Math.max(pct,4);
      const color  = day.total_kwh>1?'#FFB347':day.total_kwh>0.1?'#81d4fa':'#1e3a5f';
      return `<div class="weekly-bar">
        <span style="font-size:9px;color:var(--accent-amber);font-weight:600;">${day.total_kwh>0?day.total_kwh:''}</span>
        <div class="weekly-bar-fill" title="${day.label}: ${day.total_kwh} kWh"
          style="height:${height}px;background:${color};"
          onclick="showToast('${day.label}: ${day.total_kwh} kWh — ₹${day.cost_inr}')"></div>
      </div>`;
    }).join('');
    labelEl.innerHTML = days.map(day =>
      `<div style="flex:1;text-align:center;font-size:10px;color:var(--text-muted);">${day.label}</div>`).join('');
  }).catch(()=>{});
}

function loadEnergyTop() {
  fetch('/energy/top').then(r => r.json()).then(consumers => {
    const el = document.getElementById('en-top-consumers');
    if (!el) return;
    el.innerHTML = consumers?.length ? consumers.slice(0,5).map(c => {
      const parts  = c.device.split(' ');
      const device = parts[1] || parts[0];
      return `<div style="display:flex;justify-content:space-between;border-bottom:1px solid var(--glass-border);padding:2px 0;">
        <span>${DEVICE_EMOJI[device]||'⚡'} ${c.device}</span>
        <span style="color:#ce93d8;font-weight:600;">${c.kwh} kWh</span>
      </div>`;
    }).join('') : '<span style="color:var(--text-muted);">No data yet</span>';
  }).catch(()=>{});
}

function loadEnergyEvents() {
  fetch('/energy/events?n=15').then(r => r.json()).then(events => {
    const el = document.getElementById('en-recent-events');
    if (!el) return;
    el.innerHTML = events?.length ? events.map(ev => {
      const stateStr = typeof ev.state === 'boolean' ? (ev.state?'ON':'OFF') : String(ev.state);
      const kwh = ev.kwh_this_session > 0 ? `<span style="color:var(--accent-amber);">${ev.kwh_this_session} kWh</span>` : '';
      return `<div style="display:flex;gap:8px;align-items:center;border-bottom:1px solid var(--glass-border);padding:3px 0;">
        <span style="color:var(--text-muted);font-size:10px;white-space:nowrap;">${ev.time}</span>
        <span>${DEVICE_EMOJI[ev.device]||'⚡'}</span>
        <span style="flex:1;color:var(--text-secondary);">${ev.room} ${ev.device} → ${stateStr}</span>
        ${kwh}
        <span style="color:var(--accent-cyan);font-size:10px;">${ev.watts}W</span>
      </div>`;
    }).join('') : '<span style="color:var(--text-muted);">No events yet</span>';
  }).catch(()=>{});
}

// Energy auto-refresh on room switch
let _energyInterval = null;
function _onRoomSwitch(room) {
  clearInterval(_energyInterval);
  if (room === 'common') {
    refreshEnergy();
    _energyInterval = setInterval(refreshEnergy, 30000);
  }
}

/* ═══════════════════════════════════════════════════════
   PUSH NOTIFICATIONS
   ═══════════════════════════════════════════════════════ */
let _notificationsEnabled = false;

function checkNotificationStatus() {
  const statusEl = document.getElementById('notif-status');
  const btn      = document.getElementById('notif-enable-btn');
  if (!statusEl) return;
  if (!('Notification' in window)) {
    statusEl.textContent = "❌ Browser doesn't support notifications";
    if (btn) btn.disabled = true; return;
  }
  if (Notification.permission === 'granted') {
    statusEl.innerHTML = '<span style="color:var(--accent-green);">✅ Notifications enabled!</span>';
    _notificationsEnabled = true;
    if (btn) btn.textContent = '🔕 Enabled ✓';
  } else if (Notification.permission === 'denied') {
    statusEl.textContent = '❌ Blocked — allow in browser Settings → Site Settings → Notifications';
    if (btn) btn.disabled = true;
  } else {
    statusEl.textContent = '🔔 Click Enable to receive alerts';
  }
}

function enableNotifications() {
  if (!('Notification' in window)) { showToast("❌ Browser doesn't support notifications"); return; }
  Notification.requestPermission().then(permission => {
    const statusEl = document.getElementById('notif-status');
    if (permission === 'granted') {
      _notificationsEnabled = true;
      if (statusEl) statusEl.innerHTML = '<span style="color:var(--accent-green);">✅ Notifications enabled!</span>';
      showToast('🔔 Notifications enabled!');
      fetch('/push/subscribe', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({type:'browser',granted:true}) });
    } else {
      if (statusEl) statusEl.textContent = '❌ Permission denied';
    }
  });
}

function sendTestNotification() {
  fetch('/push/test', { method: 'POST' }).then(() => showToast('🧪 Test sent!'));
}

function showPushNotification(title, body, tag = 'smarthome') {
  showPopup(title, body, tag);
  if (_notificationsEnabled && Notification.permission === 'granted') {
    new Notification(title, { body, icon:'/static/icon-192.png', badge:'/static/icon-192.png', tag, vibrate:[200,100,200] });
  }
}

function showPopup(title, message, tag = 'smarthome') {
  // Remove existing popup with same tag to avoid stacking
  document.getElementById('_smarthome_popup_' + tag)?.remove();

  const tagColors = {
    alert:    '#e53935',
    door:     '#8d6e63',
    bell:     '#c8a96e',
    ai:       '#9575cd',
    schedule: '#a1887f',
    weather:  '#7986cb',
    smarthome:'#7986cb',
  };
  const color = tagColors[tag] || tagColors['smarthome'];

  const popup = document.createElement('div');
  popup.id = '_smarthome_popup_' + tag;
  // Inject keyframe once
  if (!document.getElementById('_popup_keyframe_style')) {
    const s = document.createElement('style');
    s.id = '_popup_keyframe_style';
    s.textContent = `
      @keyframes slideInPopup {
        from { opacity:0; transform:translateX(110%); }
        to   { opacity:1; transform:translateX(0); }
      }
      @keyframes slideDown {
        from { opacity:0; transform:translate(-50%,-20px); }
        to   { opacity:1; transform:translate(-50%,0); }
      }
    `;
    document.head.appendChild(s);
  }

  popup.style.cssText = `
    position: fixed;
    top: 16px;
    right: 16px;
    background: rgba(18, 12, 6, 0.72);
    color: #e8dcc8;
    padding: 9px 13px;
    border-radius: 10px;
    border-left: 3px solid ${color};
    box-shadow: 0 4px 18px rgba(0,0,0,0.45), 0 0 0 1px rgba(180,140,90,0.08);
    z-index: 99999;
    max-width: 240px;
    min-width: 160px;
    backdrop-filter: blur(20px) saturate(1.2);
    -webkit-backdrop-filter: blur(20px) saturate(1.2);
    font-family: 'DM Sans', sans-serif;
    animation: slideInPopup 0.3s ease;
    cursor: pointer;
  `;
  popup.innerHTML = `
    <div style="font-weight:600;font-size:12px;margin-bottom:2px;color:#f0e6d0;letter-spacing:0.2px;">${title}</div>
    <div style="font-size:11px;color:#a89880;line-height:1.35;">${message}</div>
  `;
  popup.onclick = () => popup.remove();
  document.body.appendChild(popup);

  setTimeout(() => {
    popup.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
    popup.style.opacity = '0';
    popup.style.transform = 'translateX(110%)';
    setTimeout(() => popup.remove(), 450);
  }, 4000);
}

/* ═══════════════════════════════════════════════════════
   MEMORY UI
   ═══════════════════════════════════════════════════════ */
function loadMemoryStats() {
  fetch('/memory/stats').then(r => r.json()).then(data => {
    const statsEl = document.getElementById('memory-stats-box');
    const factsEl = document.getElementById('memory-facts-box');
    if (statsEl) {
      statsEl.innerHTML = `
        <div style="line-height:2;">
          💬 Total conversations: <strong style="color:var(--text-primary);">${data.total_messages}</strong><br>
          🧠 Learned facts: <strong style="color:var(--accent-purple);">${data.learned_facts}</strong><br>
          📜 Stored messages: <strong style="color:var(--accent-cyan);">${data.history_count}</strong><br>
          🕐 Last chat: <strong style="color:var(--text-muted);">${data.last_updated||'Never'}</strong>
        </div>`;
    }
    if (factsEl && data.facts?.length) {
      factsEl.style.display = 'block';
      factsEl.innerHTML = `<strong style="color:var(--text-primary);">🧠 What Kitty knows:</strong><br>` +
        data.facts.map(f => `• ${f}`).join('<br>');
    }
  }).catch(() => {
    const el = document.getElementById('memory-stats-box');
    if (el) el.textContent = '⚠️ Could not load stats';
  });
}

function clearKittyMemory() {
  if (!confirm("Clear Kitty's chat history? (Learned facts kept)")) return;
  fetch('/memory/clear_chat', { method: 'POST' }).then(r => r.json()).then(() => {
    showToast('🗑 Chat history cleared!');
    const box = document.getElementById('kitty-chat-box');
    if (box) box.innerHTML = `<div data-placeholder style="text-align:center;padding:28px 0;">
      <div style="font-size:38px;margin-bottom:10px;">🤖</div>
      <div style="font-size:13px;color:var(--text-muted);">Memory cleared! Kitty is ready 🐱</div>
    </div>`;
    loadMemoryStats();
  });
}

function teachKitty() {
  const input = document.getElementById('memory-fact-input');
  const fact  = input?.value.trim();
  if (!fact) { showToast('❌ Enter something to teach Kitty!'); return; }
  fetch('/memory/learn', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fact })
  }).then(() => {
    showToast(`✅ Kitty learned: "${fact}"`);
    if (input) input.value = '';
    loadMemoryStats();
  });
}

/* ═══════════════════════════════════════════════════════
   TOAST NOTIFICATION
   ═══════════════════════════════════════════════════════ */
function showToast(message, duration = 3500) {
  document.getElementById('_smarthome_toast')?.remove();
  const toast = document.createElement('div');
  toast.id = '_smarthome_toast';
  toast.style.cssText = `
    position:fixed;bottom:24px;left:50%;transform:translateX(-50%);
    background:rgba(6,13,24,0.95);color:#e0f7fa;
    padding:11px 22px;border-radius:50px;
    border:1px solid rgba(41,182,246,0.25);
    box-shadow:0 8px 32px rgba(0,0,0,0.5),0 0 0 1px rgba(41,182,246,0.1);
    font-size:13px;font-weight:500;font-family:'DM Sans',sans-serif;
    z-index:9999;backdrop-filter:blur(16px);
    transition:opacity 0.3s ease;
    max-width:90vw;text-align:center;
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;`;
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 400); }, duration);
}

/* ═══════════════════════════════════════════════════════
   KITTY VOICE ANIMATION
   ═══════════════════════════════════════════════════════ */
(function injectKittyAnim() {
  if (document.getElementById('kitty-anim-bubble')) return;

  const css = `
#kitty-anim-bubble {
  position: fixed;
  bottom: 32px;
  right: 32px;
  z-index: 99998;
  width: 72px;
  height: 72px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transform: scale(0.5);
  transition: opacity 0.3s ease, transform 0.4s cubic-bezier(0.34,1.56,0.64,1);
  pointer-events: none;
}
#kitty-anim-bubble.kb-show {
  opacity: 1;
  transform: scale(1);
}
.kb-ring {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 3px solid transparent;
  animation: kb-spin 1.2s linear infinite;
}
.kb-ring-2 {
  animation-duration: 2s;
  animation-direction: reverse;
}
#kitty-anim-bubble.kb-recording .kb-ring {
  border-top-color: #ec407a;
  border-right-color: rgba(236,64,122,0.3);
}
#kitty-anim-bubble.kb-recording .kb-ring-2 {
  border-bottom-color: #f48fb1;
  border-left-color: rgba(244,143,177,0.3);
  inset: 6px;
}
#kitty-anim-bubble.kb-transcribing .kb-ring {
  border-top-color: #ffca28;
  border-right-color: rgba(255,202,40,0.3);
  animation-duration: 0.8s;
}
#kitty-anim-bubble.kb-transcribing .kb-ring-2 {
  border-bottom-color: #ffe082;
  border-left-color: rgba(255,224,130,0.3);
  inset: 6px;
  animation-duration: 1.4s;
}
.kb-core {
  position: relative;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  z-index: 1;
}
#kitty-anim-bubble.kb-recording .kb-core {
  background: radial-gradient(circle, rgba(236,64,122,0.25), rgba(194,24,91,0.15));
  box-shadow: 0 0 20px rgba(236,64,122,0.4), inset 0 0 12px rgba(236,64,122,0.15);
  animation: kb-pulse-pink 1s ease-in-out infinite;
}
#kitty-anim-bubble.kb-transcribing .kb-core {
  background: radial-gradient(circle, rgba(255,202,40,0.25), rgba(255,160,0,0.15));
  box-shadow: 0 0 20px rgba(255,202,40,0.4), inset 0 0 12px rgba(255,202,40,0.15);
  animation: kb-pulse-yellow 0.8s ease-in-out infinite;
}
.kb-bars {
  display: flex;
  align-items: center;
  gap: 3px;
}
.kb-bars span {
  display: block;
  width: 3px;
  border-radius: 3px;
  height: 6px;
}
#kitty-anim-bubble.kb-recording .kb-bars span {
  background: #f48fb1;
  animation: kb-bar-rec 0.45s ease-in-out infinite;
}
#kitty-anim-bubble.kb-transcribing .kb-bars span {
  background: #ffe082;
  animation: kb-bar-think 0.85s ease-in-out infinite;
}
.kb-bars span:nth-child(1) { animation-delay: 0s;    height: 8px;  }
.kb-bars span:nth-child(2) { animation-delay: 0.1s;  height: 14px; }
.kb-bars span:nth-child(3) { animation-delay: 0.2s;  height: 20px; }
.kb-bars span:nth-child(4) { animation-delay: 0.1s;  height: 14px; }
.kb-bars span:nth-child(5) { animation-delay: 0s;    height: 8px;  }
@keyframes kb-spin { to { transform: rotate(360deg); } }
@keyframes kb-pulse-pink {
  0%,100% { box-shadow: 0 0 20px rgba(236,64,122,0.4), inset 0 0 12px rgba(236,64,122,0.15); }
  50%      { box-shadow: 0 0 35px rgba(236,64,122,0.7), inset 0 0 20px rgba(236,64,122,0.25); }
}
@keyframes kb-pulse-yellow {
  0%,100% { box-shadow: 0 0 20px rgba(255,202,40,0.4), inset 0 0 12px rgba(255,202,40,0.15); }
  50%      { box-shadow: 0 0 35px rgba(255,202,40,0.7), inset 0 0 20px rgba(255,202,40,0.25); }
}
@keyframes kb-bar-rec {
  0%,100% { transform: scaleY(0.4); }
  50%      { transform: scaleY(1); }
}
@keyframes kb-bar-think {
  0%,100% { transform: scaleY(0.6); opacity: 0.6; }
  50%      { transform: scaleY(1);   opacity: 1; }
}
`;
  const styleEl = document.createElement('style');
  styleEl.textContent = css;
  document.head.appendChild(styleEl);

  const html = `<div id="kitty-anim-bubble">
    <div class="kb-ring"></div>
    <div class="kb-ring kb-ring-2"></div>
    <div class="kb-core">
      <div class="kb-bars">
        <span></span><span></span><span></span><span></span><span></span>
      </div>
    </div>
  </div>`;
  document.body.insertAdjacentHTML('beforeend', html);
})();

let _kittyAnimTimer = null;
let _kittyLastMode  = 'idle';

function showKittyAnim(mode) {
  const bubble = document.getElementById('kitty-anim-bubble');
  if (!bubble) return;
  if (mode === _kittyLastMode) return;
  _kittyLastMode = mode;
  clearTimeout(_kittyAnimTimer);

  bubble.className = '';

  if (mode === 'idle' || mode === 'waiting_wake') return;

  void bubble.offsetWidth;

  if (mode === 'recording') {
    bubble.classList.add('kb-show', 'kb-recording');
  } else if (mode === 'transcribing') {
    bubble.classList.add('kb-show', 'kb-transcribing');
  } else if (mode === 'executing') {
    bubble.classList.add('kb-show', 'kb-transcribing');
    _kittyAnimTimer = setTimeout(() => showKittyAnim('idle'), 2000);
  }
}

if (typeof socket !== 'undefined') {
  socket.on("voice_status", function(data) {
    if (!data.listening) { showKittyAnim('idle'); return; }
    showKittyAnim(data.mode || 'idle');
  });
  socket.on("voice_command", function() {
    showKittyAnim('executing');
  });
}

setInterval(function() {
  if (!document.hidden) {
    fetch('/voice/status').then(r => r.json()).then(data => {
      if (!data.available) return;
      if (!data.listening) { showKittyAnim('idle'); return; }
      showKittyAnim(data.mode || 'idle');
    }).catch(() => {});
  }
}, 1500);

/* ═══════════════════════════════════════════════════════
   INIT
   ═══════════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {
  checkNotificationStatus();
  if (localStorage.getItem('activeRoom') === 'common') {
    setTimeout(() => { loadMemoryStats(); refreshEnergy(); }, 500);
  }
  const currentRoom = localStorage.getItem('activeRoom') || 'living';
  loadScheduleList(currentRoom);
});