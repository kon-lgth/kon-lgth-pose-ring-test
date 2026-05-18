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
const DIFFICULTY_RADIUS_MM = { easy: 500, medium: 390, hard: 250 };

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

let cameraModalShown = false;
let latestCameraError = '';
const failedFeeds = new Set();
let latestState = {};
let pendingStartPayload = null;
let clearRadiusTouched = false;

const operatorSound = {
  ctx: null,
  context() {
    if (!this.ctx) this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    if (this.ctx.state === 'suspended') this.ctx.resume();
    return this.ctx;
  },
  effectsAllowed() {
    return audioSettings.effects_enabled !== false && Number(audioSettings.effects_volume || 0) > 0;
  },
  tone(freq, duration = 0.12, volume = 0.16, type = 'square') {
    if (!this.effectsAllowed()) return;
    const ctx = this.context();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type;
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.0001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(volume * audioSettings.effects_volume, ctx.currentTime + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + duration);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(ctx.currentTime);
    osc.stop(ctx.currentTime + duration + 0.02);
  },
  beep(n) {
    this.playCountdownBeep(n);
  },
  playCountdownBeep(n) {
    if (!this.effectsAllowed()) return;
    const ctx = this.context();
    const t = ctx.currentTime;
    const play = (freq, when, duration, volume) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'square';
      osc.frequency.setValueAtTime(freq, when);
      gain.gain.setValueAtTime(volume * audioSettings.effects_volume, when);
      gain.gain.exponentialRampToValueAtTime(0.0001, when + duration);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(when);
      osc.stop(when + duration + 0.02);
    };
    play(n > 0 ? 440 : 880, t, n > 0 ? 0.12 : 0.05, n > 0 ? 0.35 : 0.55);
    if (n === 0) {
      [880, 1047, 1319].forEach((freq, i) => {
        play(freq, t + 0.06 + i * 0.06, 0.12, 0.35);
      });
    }
  },
  click() {
    if (!this.effectsAllowed()) return;
    const ctx = this.context();
    const play = (freq, when, duration, volume) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'square';
      osc.frequency.setValueAtTime(freq, when);
      gain.gain.setValueAtTime(0.0001, when);
      gain.gain.exponentialRampToValueAtTime(volume * audioSettings.effects_volume, when + 0.025);
      gain.gain.exponentialRampToValueAtTime(0.0001, when + duration);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(when);
      osc.stop(when + duration + 0.04);
    };
    const t = ctx.currentTime + 0.01;
    play(740, t, 0.06, 0.034);
    play(988, t + 0.055, 0.08, 0.028);
  },
  modalOpen() {
    this.tone(523, 0.09, 0.1, 'triangle');
    setTimeout(() => this.tone(784, 0.12, 0.08, 'triangle'), 70);
  },
  cameraShutter() {
    if (!this.effectsAllowed()) return;
    const ctx = this.context();
    const t = ctx.currentTime;
    const bufferSize = Math.floor(ctx.sampleRate * 0.09);
    const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < bufferSize; i++) {
      data[i] = (Math.random() * 2 - 1) * (1 - i / bufferSize);
    }
    const noise = ctx.createBufferSource();
    const gain = ctx.createGain();
    noise.buffer = buffer;
    gain.gain.setValueAtTime(0.35 * audioSettings.effects_volume, t);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.09);
    noise.connect(gain);
    gain.connect(ctx.destination);
    noise.start(t);
  },
};

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
  const noTimeLimit = document.getElementById('s-time-mode')?.value === 'unlimited';
  const seconds = parseFloat(document.getElementById('s-time-seconds')?.value || '60');
  requestStartGame({
    players:         players.length ? players : ['Player 1'],
    difficulty:      document.getElementById('s-difficulty').value,
    clear_dist_mm:   parseFloat(document.getElementById('s-clear-radius')?.value || ''),
    required_target_count: parseInt(document.getElementById('s-target-count')?.value || '4', 10),
    poses_per_round: parseInt(document.getElementById('s-poses').value),
    num_rounds:      parseInt(document.getElementById('s-rounds').value),
    no_time_limit:   noTimeLimit,
    time_per_pose:   noTimeLimit ? null : seconds,
  });
};

function emitStartGame(payload) {
  socket.emit('cmd_start_game', payload);
  flash('Start requested', 'green');
}

function applyDifficultyRadius(force = false) {
  const diff = document.getElementById('s-difficulty')?.value || 'medium';
  const radius = document.getElementById('s-clear-radius');
  if (!radius) return;
  if (force || !clearRadiusTouched) {
    radius.value = String(DIFFICULTY_RADIUS_MM[diff] || DIFFICULTY_RADIUS_MM.medium);
  }
}

function cameraIssuesForStart() {
  const status = latestState.camera_status || {};
  const issues = [];
  ['cam0', 'cam1', 'cam2', 'cam3'].forEach((cam, index) => {
    if (status[cam] === false) issues.push({ cam, label: `CAM ${index}`, front: index < 2 });
  });
  failedFeeds.forEach(label => {
    const index = Number(String(label).replace('CAM ', ''));
    const cam = `cam${index}`;
    if (!issues.some(issue => issue.cam === cam)) {
      issues.push({ cam, label, front: index < 2 });
    }
  });
  const errorText = latestState.live_error || latestState.camera_error || '';
  if (errorText && issues.length === 0) {
    const front = /A Cam[01]|cam[01]|CAM [01]/i.test(errorText);
    issues.push({ cam: 'unknown', label: errorText, front });
  }
  return issues;
}

function showStartCameraModal(issues, canProceed) {
  const modal = document.getElementById('startCameraModal');
  const text = document.getElementById('startCameraModalText');
  const actions = document.getElementById('startCameraModalActions');
  const list = issues.map(issue => issue.label).join(', ');
  if (text) {
    text.innerHTML = canProceed
      ? `Camera warning:<br>${list}<br><br>Do you want to proceed anyway?`
      : `Cannot start the game.<br><br>The front camera must be working:<br>${list}`;
  }
  if (actions) {
    actions.innerHTML = canProceed
      ? `<button class="ctrl-btn reset" onclick="closeStartCameraModal()">CANCEL</button>
         <button class="ctrl-btn start" onclick="proceedStartAfterCameraWarning()">PROCEED</button>`
      : `<button class="ctrl-btn start" onclick="closeStartCameraModal()">OK</button>`;
  }
  modal?.classList.add('show');
  operatorSound.modalOpen();
}

function requestStartGame(payload) {
  const issues = cameraIssuesForStart();
  if (!issues.length) {
    emitStartGame(payload);
    return;
  }
  pendingStartPayload = payload;
  const frontMissing = issues.some(issue => issue.front);
  showStartCameraModal(issues, !frontMissing);
}

window.closeStartCameraModal = function () {
  document.getElementById('startCameraModal')?.classList.remove('show');
  pendingStartPayload = null;
};

window.proceedStartAfterCameraWarning = function () {
  const payload = pendingStartPayload;
  closeStartCameraModal();
  if (payload) emitStartGame({ ...payload, allow_camera_warning: true });
};

window.setOrigin  = function () { socket.emit('cmd_set_origin');  flash('Origin is handled by saved A/B targets', 'yellow'); };
window.setTargets = function () { socket.emit('cmd_set_targets'); flash('Saving target pose...', 'blue'); };
window.resetGame  = function () { socket.emit('cmd_reset');       flash('Reset!', 'red'); };
window.nextPose   = function () { socket.emit('cmd_next_pose');   flash('Next pose!', 'green'); };
window.closeCameraModal = function () {
  document.getElementById('cameraModal')?.classList.remove('show');
};

function showCameraModal(message) {
  if (cameraModalShown) return;
  cameraModalShown = true;
  const text = document.getElementById('cameraModalText');
  if (text) text.textContent = message;
  document.getElementById('cameraModal')?.classList.add('show');
  operatorSound.modalOpen();
}

/* ── Pose library ── */
let poseLibrary = [];
let selectedPoseId = '';
let previewPoseId = '';
let capturedPoseDraft = null;
let poseCaptureBusy = false;

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
    ['A', 'B'].some(setName => Array.isArray(pose.sets && pose.sets[setName] && pose.sets[setName][color]))
  )).length;
  const counts = ['A', 'B'].map(setName => {
    const set = pose.sets && pose.sets[setName];
    if (!set) return null;
    const count = COLOR_ORDER.filter(color => Array.isArray(set[color])).length;
    return `${setName}:${count}/4`;
  }).filter(Boolean).join(' ');

  meta.textContent = `${difficultyLabel(pose.difficulty)} | ${pointCount} free target point${pointCount === 1 ? '' : 's'} | ${counts || 'no coordinates'}`;
  const diff = document.getElementById('s-difficulty');
  if (diff) diff.value = pose.difficulty || 'medium';
  clearRadiusTouched = false;
  applyDifficultyRadius(true);
}

function openSavedPosePreview(poseId) {
  const pose = poseLibrary.find(p => p.id === poseId);
  if (!pose) return;
  previewPoseId = pose.id;
  selectedPoseId = pose.id;

  const title = document.getElementById('savedPosePreviewTitle');
  const meta = document.getElementById('savedPosePreviewMeta');
  const cam0 = document.getElementById('savedPosePreviewCam0');
  const cam1 = document.getElementById('savedPosePreviewCam1');
  if (title) title.textContent = pose.name || 'SAVED POSE';

  const selectedColors = Array.isArray(pose.selected_colors) && pose.selected_colors.length
    ? pose.selected_colors.join(', ')
    : COLOR_ORDER.filter(color => ['A', 'B'].some(setName => pose.sets?.[setName]?.[color])).join(', ');
  if (meta) {
    meta.textContent = `${difficultyLabel(pose.difficulty)} | Colors: ${selectedColors || '—'}`;
  }
  if (cam0) {
    if (pose.setup_photos?.cam0 || pose.setup_photo) cam0.src = `data:image/jpeg;base64,${pose.setup_photos?.cam0 || pose.setup_photo}`;
    else cam0.removeAttribute('src');
  }
  if (cam1) {
    if (pose.setup_photos?.cam1) cam1.src = `data:image/jpeg;base64,${pose.setup_photos.cam1}`;
    else cam1.removeAttribute('src');
  }

  document.getElementById('savedPosePreviewModal')?.classList.add('show');
  operatorSound.modalOpen();
}

window.closeSavedPosePreview = function () {
  document.getElementById('savedPosePreviewModal')?.classList.remove('show');
};

window.confirmLoadPreviewPose = function () {
  const id = previewPoseId || selectedPoseId;
  const pose = poseLibrary.find(p => p.id === id);
  if (!pose) {
    flash('Choose a saved pose first', 'yellow');
    return;
  }
  const select = document.getElementById('poseSelect');
  if (select) select.value = id;
  selectedPoseId = id;
  updatePoseMeta();
  socket.emit('cmd_load_pose', { id });
  closeSavedPosePreview();
};

window.deletePreviewPose = async function () {
  const id = previewPoseId || selectedPoseId;
  const pose = poseLibrary.find(p => p.id === id);
  if (!pose) {
    flash('Choose a saved pose first', 'yellow');
    return;
  }
  const res = await fetch(`/api/poses/${encodeURIComponent(id)}`, { method: 'DELETE' });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    flash(body.error || 'Could not delete pose', 'red');
    return;
  }
  selectedPoseId = '';
  previewPoseId = '';
  closeSavedPosePreview();
  flash('Pose deleted', 'red');
};

window.openPoseModal = function () {
  const modal = document.getElementById('poseModal');
  const name = document.getElementById('poseName');
  const difficulty = document.getElementById('poseDifficulty');
  const colorCount = document.getElementById('poseColorCount');
  const confirm = document.getElementById('poseConfirmText');
  const colorSelect = document.getElementById('poseColorSelect');
  capturedPoseDraft = null;
  poseCaptureBusy = false;
  if (name) name.value = '';
  if (difficulty) difficulty.value = document.getElementById('s-difficulty')?.value || 'medium';
  if (colorCount) colorCount.value = document.getElementById('s-target-count')?.value || '4';
  const cam0 = document.getElementById('poseReviewCam0');
  const cam1 = document.getElementById('poseReviewCam1');
  if (cam0) cam0.removeAttribute('src');
  if (cam1) cam1.removeAttribute('src');
  if (colorSelect) {
    colorSelect.style.display = 'none';
    colorSelect.innerHTML = '';
  }
  setPoseCaptureStage('edit');
  if (confirm) confirm.textContent = 'Check both front cameras, then confirm. A 5, 4, 3, 2, 1 countdown will capture the pose coordinates and photos.';
  if (modal) modal.classList.add('show');
  operatorSound.modalOpen();
};

window.closePoseModal = function () {
  document.getElementById('poseModal')?.classList.remove('show');
};

function setPoseCaptureStage(stage, message) {
  const live = document.getElementById('poseLivePreview');
  const review = document.getElementById('poseReviewPreview');
  const editActions = document.getElementById('poseEditActions');
  const reviewActions = document.getElementById('poseReviewActions');
  const text = document.getElementById('poseConfirmText');
  if (live) live.style.display = stage === 'review' ? 'none' : 'grid';
  if (review) review.style.display = stage === 'review' ? 'grid' : 'none';
  editActions?.classList.toggle('show', stage !== 'review');
  if (editActions) editActions.style.display = stage === 'review' ? 'none' : 'flex';
  reviewActions?.classList.toggle('show', stage === 'review');
  if (text && message) text.textContent = message;
}

function poseCaptureInputs() {
  const name = document.getElementById('poseName')?.value.trim();
  const difficulty = document.getElementById('poseDifficulty')?.value || 'medium';
  const poseColorCount = parseInt(document.getElementById('poseColorCount')?.value || '4', 10);
  if (!name) {
    flash('Pose name is required', 'red');
    return null;
  }
  return { name, difficulty, pose_color_count: Math.max(1, Math.min(4, poseColorCount || 4)) };
}

function wait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function runPoseCaptureCountdown() {
  const overlay = document.getElementById('poseCaptureCountdown');
  const number = document.getElementById('poseCaptureNumber');
  if (!overlay) return;
  overlay.classList.add('show');
  for (const n of [5, 4, 3, 2, 1]) {
    if (number) {
      number.textContent = String(n);
      number.className = 'countdown-number';
      void number.offsetWidth;
      number.className = 'countdown-number';
    }
    operatorSound.beep(n);
    await wait(850);
  }
  operatorSound.cameraShutter();
  overlay.classList.remove('show');
}

async function capturePoseDraft() {
  const inputs = poseCaptureInputs();
  if (!inputs || poseCaptureBusy) return null;
  poseCaptureBusy = true;
  setPoseCaptureStage('capture', 'Hold still. Capturing pose in 5, 4, 3, 2, 1...');
  await runPoseCaptureCountdown();

  const res = await fetch('/api/poses/capture', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(inputs),
  });
  const body = await res.json().catch(() => ({}));
  poseCaptureBusy = false;
  if (!res.ok) {
    setPoseCaptureStage('edit', 'Capture failed. Check cameras and marker visibility, then try again.');
    flash(body.error || 'Could not capture pose', 'red');
    return null;
  }
  capturedPoseDraft = { ...body, ...inputs };
  const cam0 = document.getElementById('poseReviewCam0');
  const cam1 = document.getElementById('poseReviewCam1');
  if (cam0) {
    if (body.setup_photos?.cam0) cam0.src = `data:image/jpeg;base64,${body.setup_photos.cam0}`;
    else cam0.removeAttribute('src');
  }
  if (cam1) {
    if (body.setup_photos?.cam1) cam1.src = `data:image/jpeg;base64,${body.setup_photos.cam1}`;
    else cam1.removeAttribute('src');
  }
  renderPoseColorSelection(body.detected_colors || [], inputs.pose_color_count);
  setPoseCaptureStage('review', 'Is this pose photo OK? Select the colors to save, then confirm.');
  operatorSound.modalOpen();
  return capturedPoseDraft;
}

function renderPoseColorSelection(detectedColors, requestedCount) {
  const container = document.getElementById('poseColorSelect');
  if (!container) return;
  const colors = (detectedColors || []).filter(color => COLOR_ORDER.includes(color));
  const limit = Math.max(1, Math.min(4, Number(requestedCount) || 4));
  if (!colors.length) {
    container.style.display = 'block';
    container.innerHTML = 'No colors detected.';
    return;
  }
  container.style.display = 'block';
  container.innerHTML = `
    <div style="margin-bottom:0.5rem;">Choose ${limit} color${limit === 1 ? '' : 's'} to save:</div>
    <div style="display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:0.45rem; text-align:left;">
      ${colors.map((color, index) => `
        <label style="display:flex; align-items:center; gap:0.45rem;">
          <input type="checkbox" class="pose-save-color" value="${color}" ${index < limit ? 'checked' : ''}/>
          <span>${color}</span>
        </label>
      `).join('')}
    </div>
  `;
}

function selectedPoseSaveColors() {
  return Array.from(document.querySelectorAll('.pose-save-color:checked')).map(input => input.value);
}

window.savePoseFromModal = async function () {
  await capturePoseDraft();
};

window.retakePoseCapture = async function () {
  capturedPoseDraft = null;
  await capturePoseDraft();
};

window.confirmCapturedPose = async function () {
  if (!capturedPoseDraft?.capture_id) {
    flash('Capture the pose first', 'yellow');
    return;
  }
  const selectedColors = selectedPoseSaveColors();
  const requestedCount = Math.max(1, Math.min(4, Number(capturedPoseDraft.pose_color_count) || 4));
  if (selectedColors.length !== requestedCount) {
    flash(`Select exactly ${requestedCount} color${requestedCount === 1 ? '' : 's'} to save`, 'yellow');
    return;
  }
  const res = await fetch('/api/poses', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: capturedPoseDraft.name,
      difficulty: capturedPoseDraft.difficulty,
      capture_id: capturedPoseDraft.capture_id,
      pose_color_count: capturedPoseDraft.pose_color_count,
      selected_colors: selectedColors,
    }),
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
  openSavedPosePreview(id);
};

window.deleteSelectedPose = function () {
  const select = document.getElementById('poseSelect');
  const id = select && select.value;
  const pose = poseLibrary.find(p => p.id === id);
  if (!pose) {
    flash('Choose a saved pose first', 'yellow');
    return;
  }
  openSavedPosePreview(id);
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
      operatorSound.playCountdownBeep(n > 0 ? n : 0);
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
    operatorSound.playCountdownBeep(0);
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
  latestState = state || {};
  const gs = state.game_state;
  latestCameraError = state.camera_error || state.live_error || '';
  if (latestCameraError) {
    setTimeout(() => showCameraModal(`Camera startup failed: ${latestCameraError}`), 2200);
  }
  updateStateBadge(gs);
  updateOpCountdown(gs, state.countdown);

  const msg = document.getElementById('opMsg');
  if (msg) msg.textContent = state.message || '—';

  const opRound = document.getElementById('opRound');
  const opPose  = document.getElementById('opPose');
  if (opRound) opRound.textContent = `${state.round || 1} / ${state.num_rounds || 3}`;
  if (opPose)  opPose.textContent  = `${state.pose  || 0} / ${state.poses_per_round || 3}`;

  const isEnd = gs === 'GAME_OVER' || gs === 'GAME_CLEAR';
  const timer = document.getElementById('opTimer');
  if (timer) {
    timer.textContent = state.no_time_limit
      ? `NO LIMIT | ${Number(state.elapsed_time || 0).toFixed(1)}s`
      : (isEnd ? '—' : `${Math.ceil(state.time_left || 0)}s`);
  }

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
    simBadge.textContent = latestCameraError ? '⚠ CAMERA ERROR' : '🟢 LIVE CAMERAS';
    simBadge.style.color = latestCameraError ? '#f87171' : '#4ade80';
  }
}

function bindTimeControls() {
  const mode = document.getElementById('s-time-mode');
  const row = document.getElementById('timeSecondsRow');
  if (!mode || !row) return;
  const sync = () => {
    row.style.display = mode.value === 'unlimited' ? 'none' : 'block';
  };
  mode.addEventListener('change', sync);
  sync();
}

function bindDifficultyControls() {
  const diff = document.getElementById('s-difficulty');
  const radius = document.getElementById('s-clear-radius');
  if (!diff || !radius) return;
  diff.addEventListener('change', () => {
    clearRadiusTouched = false;
    applyDifficultyRadius(true);
  });
  radius.addEventListener('input', () => {
    clearRadiusTouched = true;
  });
  applyDifficultyRadius(true);
}

function bindCameraFeedWarnings() {
  ['feed0', 'feed1', 'feed2', 'feed3'].forEach((id) => {
    const img = document.getElementById(id);
    if (!img) return;
    img.addEventListener('error', () => {
      failedFeeds.add(id.replace('feed', 'CAM '));
      setTimeout(() => {
        if (!failedFeeds.size) return;
        showCameraModal(`No image received from: ${Array.from(failedFeeds).join(', ')}. Check camera connections and the B-set sender.`);
      }, 2200);
    });
    img.addEventListener('load', () => {
      failedFeeds.delete(id.replace('feed', 'CAM '));
    });
  });
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
bindTimeControls();
bindDifficultyControls();
bindCameraFeedWarnings();
document.addEventListener('click', (event) => {
  if (event.target.closest('button')) {
    operatorSound.click();
  }
});
applyAudioSettings(audioSettings);
fetchPoseLibrary();
document.getElementById('poseSelect')?.addEventListener('change', updatePoseMeta);
document.getElementById('poseSelect')?.addEventListener('change', (event) => {
  if (event.target.value) openSavedPosePreview(event.target.value);
});
