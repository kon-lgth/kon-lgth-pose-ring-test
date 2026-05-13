/**
 * PoseRing — Operator Screen
 * ==========================
 * - Socket.IO live state display
 * - Camera feed refresh via MJPEG src
 * - Game control commands (start, set origin/targets, reset)
 * - Color marker status + proximity bars
 * - BLE status polling
 */

'use strict';

const COLOR_ORDER = ['RED', 'YELLOW', 'BLUE', 'GREEN'];
const COLOR_NAMES = { RED: 'R.Arm', YELLOW: 'L.Arm', BLUE: 'R.Leg', GREEN: 'L.Leg' };

/* ── Socket.IO ── */
const socket = io();

socket.on('connect',    () => console.log('[Operator] connected'));
socket.on('disconnect', () => console.log('[Operator] disconnected'));

socket.on('game_state', applyState);
socket.on('audio_settings', applyAudioSettings);
socket.on('pose_library', renderPoseLibrary);
socket.on('lobby_setup', applyLobbySetup);
socket.on('pose_selected', pose => {
  if (pose && pose.name) flash(`Loaded pose: ${pose.name}`, 'green');
});
socket.on('pose_error', data => {
  flash((data && data.error) || 'Pose error', 'red');
});

function applyLobbySetup(setup) {
  if (!setup || setup.status !== 'ready_for_operator') return;
  if (Array.isArray(setup.players) && setup.players.length) {
    const playersInput = document.getElementById('s-players');
    if (playersInput) playersInput.value = setup.players.join(', ');
  }
  const type = setup.type ? String(setup.type).toUpperCase() : 'MULTIPLAYER';
  const first = setup.first_player ? ` | First: ${setup.first_player}` : '';
  flash(`${type} ready on player screen${first}. Press START / RESUME when ready.`, 'green');
}

/* ── Commands ── */
window.startGame = function () {
  const players = document.getElementById('s-players').value
    .split(',').map(s => s.trim()).filter(Boolean);
  socket.emit('cmd_start_game', {
    players:         players.length ? players : ['Player 1'],
    difficulty:      document.getElementById('s-difficulty').value,
    poses_per_round: parseInt(document.getElementById('s-poses').value),
    num_rounds:      parseInt(document.getElementById('s-rounds').value),
  });
    flash('Start requested', 'green');
};

window.setOrigin  = function () { socket.emit('cmd_set_origin');  flash('Origin is handled by saved A/B targets', 'yellow'); };
window.setTargets = function () { socket.emit('cmd_set_targets'); flash('Saving target pose...', 'blue'); };
window.resetGame  = function () { socket.emit('cmd_reset');       flash('Reset!', 'red'); };
window.nextPose   = function () { socket.emit('cmd_next_pose');   flash('Next pose!', 'green'); };

/* ── Pose library ── */
let poseLibrary = [];
let selectedPoseId = '';

function difficultyLabel(value) {
  if (value === 'hard') return 'HIGH';
  return String(value || 'medium').toUpperCase();
}

function renderPoseLibrary(poses) {
  poseLibrary = Array.isArray(poses) ? poses : [];
  const select = document.getElementById('poseSelect');
  const meta = document.getElementById('poseMeta');
  if (!select) return;

  const prev = selectedPoseId || select.value;
  select.innerHTML = '<option value="">SELECT SAVED POSE</option>' + poseLibrary.map(pose => (
    `<option value="${pose.id}">${pose.name} — ${difficultyLabel(pose.difficulty)}</option>`
  )).join('');

  if (poseLibrary.some(pose => pose.id === prev)) {
    select.value = prev;
    selectedPoseId = prev;
  } else {
    selectedPoseId = '';
  }
  updatePoseMeta();
  if (meta && poseLibrary.length === 0) {
    meta.textContent = 'No saved poses yet.';
  }
}

function updatePoseMeta() {
  const select = document.getElementById('poseSelect');
  const meta = document.getElementById('poseMeta');
  if (!select || !meta) return;
  selectedPoseId = select.value;
  const pose = poseLibrary.find(p => p.id === selectedPoseId);
  if (!pose) {
    meta.textContent = poseLibrary.length ? 'Choose a saved pose.' : 'No saved poses yet.';
    return;
  }

  const pointCount = COLOR_ORDER.filter(color => (
    ['A', 'B', 'SIM'].some(setName => Array.isArray(pose.sets && pose.sets[setName] && pose.sets[setName][color]))
  )).length;
  const counts = ['A', 'B', 'SIM'].map(setName => {
    const set = pose.sets && pose.sets[setName];
    if (!set) return null;
    const count = COLOR_ORDER.filter(color => Array.isArray(set[color])).length;
    return `${setName}:${count}/4`;
  }).filter(Boolean).join(' ');

  meta.textContent = `${difficultyLabel(pose.difficulty)} | ${pointCount} free target point${pointCount === 1 ? '' : 's'} | ${counts || 'no coordinates'}`;
  const diff = document.getElementById('s-difficulty');
  if (diff) diff.value = pose.difficulty || 'medium';
}

window.openPoseModal = function () {
  const modal = document.getElementById('poseModal');
  const name = document.getElementById('poseName');
  const difficulty = document.getElementById('poseDifficulty');
  const confirm = document.getElementById('poseConfirmText');
  if (name) name.value = '';
  if (difficulty) difficulty.value = document.getElementById('s-difficulty')?.value || 'medium';
  if (confirm) confirm.textContent = 'Current live coordinates from A/B camera sets will be stored locally.';
  if (modal) modal.classList.add('show');
};

window.closePoseModal = function () {
  document.getElementById('poseModal')?.classList.remove('show');
};

window.savePoseFromModal = async function () {
  const name = document.getElementById('poseName')?.value.trim();
  const difficulty = document.getElementById('poseDifficulty')?.value || 'medium';
  if (!name) {
    flash('Pose name is required', 'red');
    return;
  }
  if (!confirm(`Save current 3D coordinates as "${name}" (${difficultyLabel(difficulty)})?`)) {
    return;
  }

  const res = await fetch('/api/poses', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, difficulty }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    flash(body.error || 'Could not save pose', 'red');
    return;
  }
  closePoseModal();
  selectedPoseId = body.id;
  flash(`Saved pose: ${body.name}`, 'green');
};

window.loadSelectedPose = function () {
  const select = document.getElementById('poseSelect');
  const id = select && select.value;
  if (!id) {
    flash('Choose a saved pose first', 'yellow');
    return;
  }
  socket.emit('cmd_load_pose', { id });
};

window.deleteSelectedPose = async function () {
  const select = document.getElementById('poseSelect');
  const id = select && select.value;
  const pose = poseLibrary.find(p => p.id === id);
  if (!pose) {
    flash('Choose a saved pose first', 'yellow');
    return;
  }
  if (!confirm(`Delete saved pose "${pose.name}"?`)) return;

  const res = await fetch(`/api/poses/${encodeURIComponent(id)}`, { method: 'DELETE' });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    flash(body.error || 'Could not delete pose', 'red');
    return;
  }
  selectedPoseId = '';
  flash('Pose deleted', 'red');
};

async function fetchPoseLibrary() {
  const res = await fetch('/api/poses');
  if (!res.ok) return;
  renderPoseLibrary(await res.json());
}

/* ── Operator audio controls ── */
const audioSettings = {
  music_volume: 0.22,
  effects_volume: 0.85,
  music_enabled: true,
  effects_enabled: true,
};

function emitAudioSettings() {
  socket.emit('cmd_audio_settings', audioSettings);
}

function applyAudioSettings(settings) {
  if (!settings) return;
  Object.assign(audioSettings, settings);

  const music = document.getElementById('musicVol');
  const effects = document.getElementById('effectsVol');
  const musicVal = document.getElementById('musicVolVal');
  const effectsVal = document.getElementById('effectsVolVal');
  const musicToggle = document.getElementById('musicEnabled');
  const effectsToggle = document.getElementById('effectsEnabled');

  if (music) music.value = Math.round(audioSettings.music_volume * 100);
  if (effects) effects.value = Math.round(audioSettings.effects_volume * 100);
  if (musicVal) musicVal.textContent = `${Math.round(audioSettings.music_volume * 100)}%`;
  if (effectsVal) effectsVal.textContent = `${Math.round(audioSettings.effects_volume * 100)}%`;
  if (musicToggle) musicToggle.checked = !!audioSettings.music_enabled;
  if (effectsToggle) effectsToggle.checked = !!audioSettings.effects_enabled;
}

function bindAudioControls() {
  const music = document.getElementById('musicVol');
  const effects = document.getElementById('effectsVol');
  const musicToggle = document.getElementById('musicEnabled');
  const effectsToggle = document.getElementById('effectsEnabled');

  if (music) {
    music.addEventListener('input', () => {
      audioSettings.music_volume = Number(music.value) / 100;
      applyAudioSettings(audioSettings);
      emitAudioSettings();
    });
  }
  if (effects) {
    effects.addEventListener('input', () => {
      audioSettings.effects_volume = Number(effects.value) / 100;
      applyAudioSettings(audioSettings);
      emitAudioSettings();
    });
  }
  if (musicToggle) {
    musicToggle.addEventListener('change', () => {
      audioSettings.music_enabled = musicToggle.checked;
      emitAudioSettings();
    });
  }
  if (effectsToggle) {
    effectsToggle.addEventListener('change', () => {
      audioSettings.effects_enabled = effectsToggle.checked;
      emitAudioSettings();
    });
  }
}

/* ── Flash notification ── */
function flash(msg, color) {
  const el = document.getElementById('opMsg');
  if (!el) return;
  const colors = { green:'#4ade80', yellow:'#facc15', blue:'#60a5fa', red:'#f87171' };
  el.style.color    = colors[color] || '#fff';
  el.textContent    = msg;
  setTimeout(() => { el.style.color = ''; el.textContent = '—'; }, 2500);
}

/* ── Build / update color status panel ── */
function buildColorStatus() {
  const container = document.getElementById('colorStatus');
  if (!container || container.dataset.built) return;
  container.dataset.built = '1';
  container.innerHTML     = '';

  COLOR_ORDER.forEach(color => {
    const row = document.createElement('div');
    row.className  = 'color-status';
    row.id         = `cs-${color}`;
    row.innerHTML  = `
      <div class="color-row">
        <div class="color-dot ${color}"></div>
        <div class="color-info">
          <div class="color-name">${color} — ${COLOR_NAMES[color]}</div>
          <div class="color-detail" id="cd-${color}">—</div>
        </div>
        <div class="color-badge NO-DATA" id="cb-${color}">—</div>
      </div>
      <div class="prox-mini-bar ${color}">
        <div class="prox-mini-fill" id="pm-${color}" style="width:0%"></div>
      </div>
    `;
    container.appendChild(row);
  });
}

function updateColorStatus(colors) {
  buildColorStatus();
  COLOR_ORDER.forEach(color => {
    const data = (colors && colors[color]) || {};
    const det  = document.getElementById(`cd-${color}`);
    const badge= document.getElementById(`cb-${color}`);
    const bar  = document.getElementById(`pm-${color}`);
    if (!det || !badge || !bar) return;

    const status = data.status || 'NO DATA';
    const dist   = data.distance != null ? `${Math.round(data.distance)}mm` : '—';
    const src    = data.source || 'NO DATA';
    const prox   = data.proximity || 0;
    const targetLabel = data.target_index
      ? `target ${data.target_index}/${data.target_count || '?'}`
      : 'no target';
    const tgt = data.target
      ? `${targetLabel} [${data.target.map(v => v.toFixed(0)).join(', ')}]`
      : targetLabel;

    det.textContent  = `${dist} | src:${src} | tgt:${tgt}`;
    badge.textContent= status;
    badge.className  = `color-badge ${status.replace(/\s/g, '-')}`;
    bar.style.width  = `${prox * 100}%`;
  });
}

/* ── Score table ── */
function updateScores(players, scores) {
  const table = document.getElementById('scoreTable');
  if (!table) return;
  if (!players || players.length === 0) return;
  const sorted = [...players].sort((a, b) => (scores[b] || 0) - (scores[a] || 0));
  table.innerHTML = sorted.map((name, i) => {
    const medal = ['🥇','🥈','🥉'][i] || '';
    return `<tr>
      <td>${medal} ${name}</td>
      <td>${scores[name] || 0}</td>
    </tr>`;
  }).join('');
}

/* ── State badge ── */
const STATE_LABELS = {
  IDLE:       'IDLE',
  COUNTDOWN:  'COUNTDOWN',
  PLAYING:    'PLAYING',
  POSE_CLEAR: 'CLEARED!',
  TIME_UP:    "TIME'S UP",
  ROUND_END:  'ROUND END',
  GAME_OVER:  'GAME OVER',
  GAME_CLEAR: 'GAME CLEAR!',
};
function updateStateBadge(gs) {
  const el = document.getElementById('stateBadge');
  if (!el) return;
  el.textContent = STATE_LABELS[gs] || gs;
  el.className   = `op-state-badge ${gs}`;
}

/* ── Countdown overlay ── */
let _opPrevCountdown = null;  // null | -1 (GO! shown) | number

function updateOpCountdown(gs, countdown) {
  const ov  = document.getElementById('op-countdown');
  const num = document.getElementById('opCdNum');
  const sub = document.getElementById('opCdSub');
  if (!ov || !num || !sub) return;

  if (gs === 'COUNTDOWN') {
    ov.classList.add('show');
    const n = countdown;
    if (n !== _opPrevCountdown) {
      num.textContent = String(n > 0 ? n : 3);
      num.className   = '';
      void num.offsetWidth;
      num.className   = 'op-cd-number';
      sub.textContent = 'GET READY!';
      _opPrevCountdown = n;
    }
  } else if (gs === 'PLAYING' && _opPrevCountdown !== null && _opPrevCountdown !== -1) {
    // Flash GO!
    ov.classList.add('show');
    num.textContent  = 'GO!';
    num.className    = '';
    void num.offsetWidth;
    num.className    = 'op-cd-number op-cd-go';
    sub.textContent  = '';
    _opPrevCountdown = -1;
    setTimeout(() => { ov.classList.remove('show'); _opPrevCountdown = null; }, 700);
  } else if (gs !== 'PLAYING' || _opPrevCountdown === null) {
    if (_opPrevCountdown !== -1) {
      ov.classList.remove('show');
      _opPrevCountdown = null;
    }
  }
}

/* ── Main state apply ── */
function applyState(state) {
  const gs = state.game_state;
  updateStateBadge(gs);
  updateOpCountdown(gs, state.countdown);

  const msg = document.getElementById('opMsg');
  if (msg) msg.textContent = state.message || '—';

  const opRound = document.getElementById('opRound');
  const opPose  = document.getElementById('opPose');
  if (opRound) opRound.textContent = `${state.round || 1} / ${state.num_rounds || 3}`;
  if (opPose)  opPose.textContent  = `${state.pose  || 0} / ${state.poses_per_round || 5}`;

  const isEnd = gs === 'GAME_OVER' || gs === 'GAME_CLEAR';
  const timer = document.getElementById('opTimer');
  if (timer)  timer.textContent = isEnd ? '—' : `${Math.ceil(state.time_left || 0)}s`;

  const holdEl = document.getElementById('opHold');
  if (holdEl) holdEl.style.width = `${(state.hold_progress || 0) * 100}%`;

  // Show NEXT POSE button when waiting for snapshot acknowledgement
  const nextBtn = document.getElementById('nextPoseBtn');
  if (nextBtn) {
    const waiting = gs === 'POSE_CLEAR' || gs === 'TIME_UP';
    nextBtn.style.display = waiting ? 'block' : 'none';
  }

  updateColorStatus(state.colors);
  updateScores(state.players, state.scores || {});

  const simBadge = document.getElementById('simBadge');
  if (simBadge) {
    simBadge.textContent = state.simulation ? '⚠ SIMULATION MODE' : '🟢 LIVE';
    simBadge.style.color = state.simulation ? '#facc15' : '#4ade80';
  }
}

/* ── BLE status polling ── */
function pollBLE() {
  fetch('/api/ble_status')
    .then(r => r.json())
    .then(status => {
      const el = document.getElementById('bleStatus');
      if (!el) return;
      const keys = Object.keys(status);
      if (keys.length === 0 || status.enabled === false) {
        el.innerHTML = `<div class="ble-row">
          <span class="ble-dot disconnected"></span>BLE disabled
        </div>`;
        return;
      }
      if (status.simulation) {
        el.innerHTML = `<div class="ble-row">
          <span class="ble-dot disconnected"></span>simulation mode
        </div>`;
        return;
      }

      const connected = !!status.connected;
      const cls = connected ? 'connected' : 'disconnected';
      const visible = status.stage_visible ? 'stage visible' : 'out of stage';
      const value = status.value == null ? '—' : status.value;
      el.innerHTML = `
        <div class="ble-row"><span class="ble-dot ${cls}"></span>${status.device || 'XIAO'}: ${connected ? 'connected' : 'searching'}</div>
        <div class="ble-row">target: ${status.target_color || '—'} | value: ${value}</div>
        <div class="ble-row">${visible}</div>
      `;
    })
    .catch(() => {});
}

setInterval(pollBLE, 3000);
pollBLE();

/* ── Init ── */
buildColorStatus();
bindAudioControls();
applyAudioSettings(audioSettings);
fetchPoseLibrary();
document.getElementById('poseSelect')?.addEventListener('change', updatePoseMeta);
