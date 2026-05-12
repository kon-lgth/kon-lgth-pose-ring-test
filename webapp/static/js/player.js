/**
 * PoseRing — Player Screen
 * ========================
 * Handles:
 *  - Socket.IO state updates (game_state + snapshot_event)
 *  - Nintendo-style UI rendering
 *  - Web Audio API proximity sounds (sonar/radar pings per limb)
 *  - Countdown beeps (Mario Kart style)
 *  - POSE CLEAR victory fanfare (Final Fantasy style)
 *  - Camera shutter sound
 *  - Game Over / Game Clear jingles
 *  - Star field background
 *  - Snapshot photo display with NEXT button
 */

'use strict';

/* ═══════════════════════════════════════════
   Sound System  (Web Audio API — no files needed)
═══════════════════════════════════════════ */

const COLOR_ORDER = ['RED', 'YELLOW', 'BLUE', 'GREEN'];

// Base frequencies (pentatonic scale — sounds pleasant together)
const COLOR_FREQ = { RED: 392, YELLOW: 523, BLUE: 659, GREEN: 784 };
// Waveforms per limb (distinctive timbres)
const COLOR_WAVE = { RED: 'sine', YELLOW: 'triangle', BLUE: 'sine', GREEN: 'triangle' };

class SoundSystem {
  constructor() {
    this.ctx         = null;
    this.masterGain  = null;
    this.musicGain   = null;
    this.effectsGain = null;
    this.enabled     = true;
    this.audioReady  = false;
    this.musicEnabled = true;
    this.effectsEnabled = true;
    this.musicVolume = 0.22;
    this.effectsVolume = 0.85;
    this._nextPing   = {};   // color → next allowed ping time (audioCtx time)
    this._pingRate   = {};   // color → seconds between pings
    this._proxCache  = {};   // color → last proximity 0..1
    this._rafId      = null;
    this._musicTimer = null;
    this._musicStep  = 0;
    COLOR_ORDER.forEach(c => {
      this._nextPing[c]  = 0;
      this._pingRate[c]  = 3.0;
      this._proxCache[c] = 0;
    });
  }

  _ensureCtx() {
    if (this.ctx) return this.ctx;
    this.ctx        = new (window.AudioContext || window.webkitAudioContext)();
    this.masterGain = this.ctx.createGain();
    this.musicGain  = this.ctx.createGain();
    this.effectsGain = this.ctx.createGain();

    this.masterGain.gain.value = 1.0;
    this.musicGain.gain.value = this.musicEnabled ? this.musicVolume : 0;
    this.effectsGain.gain.value = this.effectsEnabled ? this.effectsVolume : 0;
    this.musicGain.connect(this.masterGain);
    this.effectsGain.connect(this.masterGain);
    this.masterGain.connect(this.ctx.destination);
    this._startLoop();
    this._startMusicLoop();
    return this.ctx;
  }

  async unlock() {
    const ctx = this._ensureCtx();
    if (ctx.state !== 'running') {
      await ctx.resume();
    }
    this.audioReady = ctx.state === 'running';
    this.applySettings({});
    return this.audioReady;
  }

  applySettings(settings) {
    this.musicVolume = Number.isFinite(settings.music_volume)
      ? settings.music_volume
      : this.musicVolume;
    this.effectsVolume = Number.isFinite(settings.effects_volume)
      ? settings.effects_volume
      : this.effectsVolume;
    if (typeof settings.music_enabled === 'boolean') this.musicEnabled = settings.music_enabled;
    if (typeof settings.effects_enabled === 'boolean') this.effectsEnabled = settings.effects_enabled;

    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    this.musicGain.gain.setTargetAtTime(this.musicEnabled ? this.musicVolume : 0, t, 0.08);
    this.effectsGain.gain.setTargetAtTime(this.effectsEnabled ? this.effectsVolume : 0, t, 0.04);
  }

  _connectEffect(gain) {
    gain.connect(this.effectsGain || this.masterGain);
  }

  toggle() {
    this.effectsEnabled = !this.effectsEnabled;
    this.applySettings({});
    return this.effectsEnabled;
  }

  /* ── Proximity update (called each state tick) ── */
  updateProximity(colorData) {
    if (!this.audioReady) return;
    this._ensureCtx();
    let strongest = null;
    let strongestValue = 0;
    COLOR_ORDER.forEach(c => {
      const prox = (colorData[c] && colorData[c].proximity) || 0;
      if (prox > strongestValue) {
        strongest = c;
        strongestValue = prox;
      }
    });

    COLOR_ORDER.forEach(c => {
      const prox = (colorData[c] && colorData[c].proximity) || 0;
      // Avoid a rapid four-color cascade: only the closest marker emits sonar.
      this._proxCache[c] = c === strongest ? prox : 0;
      // Ping interval: 2.8s when far, 0.45s max rate when close.
      this._pingRate[c] = c === strongest && prox > 0.05
        ? Math.max(0.45, 2.8 * Math.pow(1 - prox, 1.8))
        : 9999;
    });
  }

  /* ── Tick loop — fires pings on schedule ── */
  _startLoop() {
    const tick = () => {
      if (!this.ctx || !this.enabled) { this._rafId = requestAnimationFrame(tick); return; }
      const now = this.ctx.currentTime;
      COLOR_ORDER.forEach(c => {
        if (this._proxCache[c] < 0.02) return;
        if (now >= this._nextPing[c]) {
          this._ping(c, now);
          this._nextPing[c] = now + this._pingRate[c];
        }
      });
      this._rafId = requestAnimationFrame(tick);
    };
    this._rafId = requestAnimationFrame(tick);
  }

  _startMusicLoop() {
    if (this._musicTimer) return;
    const scale = [196, 247, 294, 330, 392, 330, 294, 247];
    const bass = [98, 98, 123, 123, 147, 147, 123, 123];

    const tick = () => {
      if (!this.ctx) return;
      if (this.audioReady && this.musicEnabled) {
        const t = this.ctx.currentTime;
        const step = this._musicStep % scale.length;
        this._musicNote(scale[step], t, 0.12, 'triangle', 0.045);
        if (step % 2 === 0) this._musicNote(bass[step], t, 0.45, 'sine', 0.035);
        this._musicStep += 1;
      }
      this._musicTimer = setTimeout(tick, 360);
    };
    this._musicTimer = setTimeout(tick, 360);
  }

  _musicNote(freq, time, dur, wave, vol) {
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    osc.connect(gain);
    gain.connect(this.musicGain);
    osc.type = wave;
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0, time);
    gain.gain.linearRampToValueAtTime(vol, time + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.001, time + dur);
    osc.start(time);
    osc.stop(time + dur + 0.02);
  }

  /* ── Single sonar ping ── */
  _ping(color, time) {
    const prox   = this._proxCache[color];
    const freq   = COLOR_FREQ[color] * (1 + prox * 0.25);
    const vol    = 0.08 + prox * 0.18;
    const dur    = 0.06 + prox * 0.05;

    const osc  = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    osc.connect(gain);
    this._connectEffect(gain);

    osc.type            = COLOR_WAVE[color];
    osc.frequency.value = freq;

    gain.gain.setValueAtTime(0, time);
    gain.gain.linearRampToValueAtTime(vol, time + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.001, time + dur);

    osc.start(time);
    osc.stop(time + dur + 0.01);
  }

  /* ── Mario Kart countdown beep ── */
  playCountdownBeep(n) {
    if (!this.audioReady || !this.effectsEnabled) return;
    this._ensureCtx();
    if (!this.enabled) return;
    const t    = this.ctx.currentTime;
    // n = 3,2,1 → low beep; n = 0 (GO!) → high fanfare
    const freq = n > 0 ? 440 : 880;
    const vol  = n > 0 ? 0.35 : 0.55;
    const dur  = n > 0 ? 0.12 : 0.05;

    const osc  = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    osc.connect(gain);
    this._connectEffect(gain);
    osc.type            = 'square';
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(vol, t);
    gain.gain.exponentialRampToValueAtTime(0.001, t + dur);
    osc.start(t);
    osc.stop(t + dur + 0.01);

    if (n === 0) {
      // GO! — add a quick rising flourish
      const notes = [880, 1047, 1319];
      notes.forEach((f, i) => {
        const o2 = this.ctx.createOscillator();
        const g2 = this.ctx.createGain();
        o2.connect(g2); this._connectEffect(g2);
        o2.type = 'square'; o2.frequency.value = f;
        const st = t + 0.06 + i * 0.06;
        g2.gain.setValueAtTime(0.35, st);
        g2.gain.exponentialRampToValueAtTime(0.001, st + 0.12);
        o2.start(st); o2.stop(st + 0.13);
      });
    }
  }

  /* ── Camera shutter click ── */
  playCameraShutter() {
    if (!this.audioReady || !this.effectsEnabled) return;
    this._ensureCtx();
    if (!this.enabled) return;
    const t = this.ctx.currentTime;

    // White-noise click
    const bufSize = Math.ceil(this.ctx.sampleRate * 0.06);
    const buf     = this.ctx.createBuffer(1, bufSize, this.ctx.sampleRate);
    const data    = buf.getChannelData(0);
    for (let i = 0; i < bufSize; i++) {
      data[i] = (Math.random() * 2 - 1) * Math.exp(-i / bufSize * 12);
    }
    const noise     = this.ctx.createBufferSource();
    noise.buffer    = buf;
    const noiseGain = this.ctx.createGain();
    noise.connect(noiseGain);
    this._connectEffect(noiseGain);
    noiseGain.gain.setValueAtTime(0.45, t);
    noiseGain.gain.exponentialRampToValueAtTime(0.001, t + 0.06);
    noise.start(t);

    // Mechanical "click" tone
    const osc  = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    osc.connect(gain);
    this._connectEffect(gain);
    osc.type = 'sine';
    osc.frequency.setValueAtTime(2400, t);
    osc.frequency.exponentialRampToValueAtTime(400, t + 0.05);
    gain.gain.setValueAtTime(0.25, t);
    gain.gain.exponentialRampToValueAtTime(0.001, t + 0.05);
    osc.start(t);
    osc.stop(t + 0.06);
  }

  /* ── Final Fantasy-style victory fanfare (POSE CLEAR) ── */
  playVictoryFanfare() {
    if (!this.audioReady || !this.effectsEnabled) return;
    this._ensureCtx();
    if (!this.enabled) return;
    const t = this.ctx.currentTime;
    // Classic triumphant pattern: da-da-da DA, da-DA
    const notes = [
      { f: 523, d: 0.09, v: 0.35 },   // C5
      { f: 523, d: 0.09, v: 0.35 },   // C5
      { f: 523, d: 0.09, v: 0.35 },   // C5
      { f: 659, d: 0.28, v: 0.45 },   // E5
      { f: 415, d: 0.09, v: 0.28 },   // Ab4
      { f: 466, d: 0.09, v: 0.28 },   // Bb4
      { f: 523, d: 0.50, v: 0.50 },   // C5 (held)
    ];
    let off = 0;
    notes.forEach(({ f, d, v }) => {
      const osc  = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      osc.connect(gain); this._connectEffect(gain);
      osc.type = 'square'; osc.frequency.value = f;
      gain.gain.setValueAtTime(v, t + off);
      gain.gain.exponentialRampToValueAtTime(0.001, t + off + d);
      osc.start(t + off); osc.stop(t + off + d + 0.01);
      off += d + 0.04;
    });
  }

  /* ── Hold ticking sound (ascending while holding) ── */
  playHoldTick(progress) {
    if (!this.audioReady || !this.effectsEnabled) return;
    this._ensureCtx();
    if (!this.enabled) return;
    const t    = this.ctx.currentTime;
    const freq = 440 + progress * 440;
    const osc  = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    osc.connect(gain); this._connectEffect(gain);
    osc.type = 'square'; osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.15, t);
    gain.gain.exponentialRampToValueAtTime(0.001, t + 0.06);
    osc.start(t); osc.stop(t + 0.07);
  }

  /* ── Round end fanfare ── */
  playRoundEnd() {
    if (!this.audioReady || !this.effectsEnabled) return;
    this._ensureCtx();
    if (!this.enabled) return;
    const t     = this.ctx.currentTime;
    const notes = [523, 659, 784, 659, 784, 1047];
    const durs  = [0.15, 0.15, 0.15, 0.10, 0.10, 0.50];
    let off = 0;
    notes.forEach((f, i) => {
      const osc  = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      osc.connect(gain); this._connectEffect(gain);
      osc.type = 'square'; osc.frequency.value = f;
      gain.gain.setValueAtTime(0.25, t + off);
      gain.gain.exponentialRampToValueAtTime(0.001, t + off + durs[i]);
      osc.start(t + off); osc.stop(t + off + durs[i] + 0.01);
      off += durs[i] + 0.03;
    });
  }

  /* ── Game Over melody (descending) ── */
  playGameOver() {
    if (!this.audioReady || !this.effectsEnabled) return;
    this._ensureCtx();
    if (!this.enabled) return;
    const t     = this.ctx.currentTime;
    const notes = [523, 494, 440, 392];
    notes.forEach((f, i) => {
      const osc  = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      osc.connect(gain); this._connectEffect(gain);
      osc.type = 'square'; osc.frequency.value = f;
      gain.gain.setValueAtTime(0.25, t + i * 0.3);
      gain.gain.exponentialRampToValueAtTime(0.001, t + i * 0.3 + 0.5);
      osc.start(t + i * 0.3); osc.stop(t + i * 0.3 + 0.55);
    });
  }

  /* ── GAME CLEAR extended fanfare ── */
  playGameClear() {
    if (!this.audioReady || !this.effectsEnabled) return;
    this._ensureCtx();
    if (!this.enabled) return;
    const t     = this.ctx.currentTime;
    const notes = [523, 659, 784, 1047];
    const durs  = [0.12, 0.12, 0.16, 0.75];
    let off = 0;
    notes.forEach((f, i) => {
      const osc  = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      osc.connect(gain); this._connectEffect(gain);
      osc.type = 'square'; osc.frequency.value = f;
      gain.gain.setValueAtTime(0.32, t + off);
      gain.gain.exponentialRampToValueAtTime(0.001, t + off + durs[i]);
      osc.start(t + off); osc.stop(t + off + durs[i] + 0.01);
      off += durs[i] + 0.04;
    });
  }
}

const sound = new SoundSystem();
let _lastResultSoundKey = null;
let _lastEndSoundKey = null;

function getPlayerText(key) {
  const lang = localStorage.getItem('poseringLanguage') === 'en' ? 'en' : 'ja';
  const table = (window.POSERING_PLAYER_TEXT && window.POSERING_PLAYER_TEXT[lang]) || {};
  return table[key] || key;
}

window.enablePlayerAudio = async () => {
  const ready = await sound.unlock();
  document.body.classList.toggle('audio-ready', ready);
  const btn = document.getElementById('soundBtn');
  if (btn) btn.textContent = ready ? getPlayerText('audioReady') : getPlayerText('audioButton');
};

window.toggleSound = () => {
  window.enablePlayerAudio();
};

window.openFinishModal = () => {
  document.getElementById('finishModal')?.classList.add('show');
};

window.closeFinishModal = () => {
  document.getElementById('finishModal')?.classList.remove('show');
};

window.confirmFinishGame = () => {
  socket.emit('cmd_reset');
  _lobbySetup = null;
  _latestState = null;
  _lastPlayers = [];
  localStorage.removeItem('poseringPreparedGame');
  window.closeFinishModal();
  setTimeout(() => {
    window.location.href = '/';
  }, 150);
};


/* ═══════════════════════════════════════════
   Star field
═══════════════════════════════════════════ */

(function initStars() {
  const canvas = document.createElement('canvas');
  canvas.id    = 'stars';
  Object.assign(canvas.style, { position:'fixed', inset:'0', zIndex:'0', pointerEvents:'none' });
  document.body.prepend(canvas);
  const ctx = canvas.getContext('2d');
  let stars = [];

  function resize() { canvas.width = innerWidth; canvas.height = innerHeight; }
  function init() {
    stars = Array.from({ length: 160 }, () => ({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      r: Math.random() * 1.6 + 0.2,
      a: Math.random(),
      s: Math.random() * 0.006 + 0.002,
    }));
  }
  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    stars.forEach(s => {
      s.a = (s.a + s.s) % 1;
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(255,255,255,${s.a})`;
      ctx.fill();
    });
    requestAnimationFrame(draw);
  }
  addEventListener('resize', () => { resize(); init(); });
  resize(); init(); draw();
})();


/* ═══════════════════════════════════════════
   Build proximity ring cards
═══════════════════════════════════════════ */

const COLOR_LABEL = {
  RED: '🔴 R.ARM', YELLOW: '🟡 L.ARM', BLUE: '🔵 R.LEG', GREEN: '🟢 L.LEG'
};

function buildProxRings() {
  const wrap = document.getElementById('proxRings');
  if (!wrap) return;
  COLOR_ORDER.forEach(color => {
    const card = document.createElement('div');
    card.className    = 'prox-card';
    card.dataset.color = color;
    card.innerHTML = `
      <div class="prox-ring-wrap">
        <svg class="prox-ring-svg" viewBox="0 0 80 80">
          <circle class="prox-ring-bg"  cx="40" cy="40" r="32"/>
          <circle class="prox-ring-arc" cx="40" cy="40" r="32" id="arc-${color}"/>
        </svg>
        <div class="prox-dot" id="dot-${color}"></div>
      </div>
      <div class="prox-label">${COLOR_LABEL[color]}</div>
    `;
    wrap.appendChild(card);
  });
}
buildProxRings();

const CIRCUMFERENCE = 2 * Math.PI * 32;

function updateProxRing(color, proximity) {
  const arc = document.getElementById(`arc-${color}`);
  const dot = document.getElementById(`dot-${color}`);
  if (!arc || !dot) return;

  arc.style.strokeDashoffset = CIRCUMFERENCE * (1 - proximity);

  if (proximity >= 0.95) {
    dot.classList.add('inside');
  } else {
    dot.classList.remove('inside');
    const scale = 0.7 + proximity * 0.6;
    dot.style.transform = `translate(-50%,-50%) scale(${scale})`;
    dot.style.boxShadow = proximity > 0.5
      ? `0 0 ${proximity * 20}px currentColor`
      : 'none';
  }
}


/* ═══════════════════════════════════════════
   Score cards
═══════════════════════════════════════════ */

let _lastPlayers = [];

const DEFAULT_PLAYER_COLORS = ['#2563eb', '#ef4444', '#16a34a', '#f59e0b'];

function getPlayerColor(name, players = [], playerColors = {}) {
  if (playerColors && playerColors[name]) return playerColors[name];
  const index = Math.max(0, players.indexOf(name));
  return DEFAULT_PLAYER_COLORS[index % DEFAULT_PLAYER_COLORS.length];
}

function buildScoreCards(players, scores, currentPlayer = null, playerColors = {}) {
  if (!players || players.length === 0) return;
  if (JSON.stringify(players) !== JSON.stringify(_lastPlayers)) {
    _lastPlayers = [...players];
    const row = document.getElementById('scoresRow');
    if (!row) return;
    row.innerHTML = '';
    players.forEach(name => {
      const card   = document.createElement('div');
      card.className = 'score-card';
      card.id        = `sc-${name}`;
      card.style.setProperty('--player-color', getPlayerColor(name, players, playerColors));
      card.innerHTML = `
        <div class="score-crown" id="crown-${name}" style="display:none;">👑</div>
        <div class="score-name">${name}</div>
        <div class="score-value" id="sv-${name}">0</div>
      `;
      row.appendChild(card);
    });
  }
  let maxScore = -1;
  players.forEach(name => {
    const val = (scores && scores[name]) || 0;
    const el  = document.getElementById(`sv-${name}`);
    if (el) el.textContent = val;
    if (val > maxScore) maxScore = val;
  });
  players.forEach(name => {
    const val   = (scores && scores[name]) || 0;
    const card  = document.getElementById(`sc-${name}`);
    const crown = document.getElementById(`crown-${name}`);
    const isTop = maxScore > 0 && val === maxScore;
    if (card) {
      card.style.setProperty('--player-color', getPlayerColor(name, players, playerColors));
      card.classList.toggle('top-score', isTop);
      card.classList.toggle('active-turn', name === currentPlayer);
    }
    if (crown) crown.style.display = isTop ? 'block' : 'none';
  });
}

function updateTurnBanner(currentPlayer, players = [], playerColors = {}, gameState = 'IDLE') {
  const banner = document.getElementById('turnBanner');
  const nameEl = document.getElementById('turnName');
  if (!banner || !nameEl) return;
  const shouldShow = Boolean(currentPlayer) && !['GAME_OVER', 'GAME_CLEAR', 'ROUND_END'].includes(gameState);
  banner.classList.toggle('show', shouldShow);
  if (!shouldShow) return;
  banner.style.setProperty('--turn-color', getPlayerColor(currentPlayer, players, playerColors));
  nameEl.textContent = currentPlayer;
}


/* ═══════════════════════════════════════════
   Pose pips
═══════════════════════════════════════════ */

let _lastPosesPerRound = 0;

function buildPips(posesPerRound, currentPose) {
  const row = document.getElementById('posePips');
  if (!row) return;
  if (posesPerRound !== _lastPosesPerRound) {
    _lastPosesPerRound = posesPerRound;
    row.innerHTML = '';
    for (let i = 0; i < posesPerRound; i++) {
      const pip = document.createElement('div');
      pip.className = 'pip';
      pip.id        = `pip-${i}`;
      row.appendChild(pip);
    }
  }
  for (let i = 0; i < posesPerRound; i++) {
    const pip = document.getElementById(`pip-${i}`);
    if (pip) pip.classList.toggle('done', i < currentPose);
  }
}


/* ═══════════════════════════════════════════
   COUNTDOWN overlay
═══════════════════════════════════════════ */

// null = not in countdown, -1 = GO! shown (hiding), else = last shown number
let _prevCountdown = null;

function updateCountdownOverlay(gs, countdown, poseName) {
  const ov  = document.getElementById('overlay-countdown');
  const num = document.getElementById('cdNumber');
  const sub = document.getElementById('cdSub');
  if (!ov) return;

  if (gs === 'COUNTDOWN') {
    ov.classList.add('show');
    const n = countdown;
    if (n !== _prevCountdown) {
      num.textContent = String(n > 0 ? n : 3);
      num.style.color = n === 1 ? '#facc15' : '#c4b5fd';
      // Force CSS animation restart
      num.className = '';
      void num.offsetWidth;
      num.className = 'countdown-number ' + (n === 1 ? 'glow-yellow' : 'glow-purple');
      sub.textContent = poseName ? `POSE: ${poseName}` : 'GET READY!';
      if (n > 0) sound.playCountdownBeep(n);
      _prevCountdown = n;
    }

  } else if (gs === 'PLAYING' && _prevCountdown !== null && _prevCountdown !== -1) {
    // Engine just went COUNTDOWN → PLAYING: flash "GO!" once
    ov.classList.add('show');
    num.textContent = 'GO!';
    num.style.color = '#4ade80';
    num.className   = '';
    void num.offsetWidth;
    num.className   = 'countdown-number glow-green countdown-go';
    sub.textContent = '';
    sound.playCountdownBeep(0);   // high "GO!" beep
    _prevCountdown  = -1;
    setTimeout(() => { ov.classList.remove('show'); _prevCountdown = null; }, 700);

  } else if (gs !== 'PLAYING' || _prevCountdown === null) {
    // Any other non-countdown state: hide overlay and reset
    if (_prevCountdown !== -1) {
      ov.classList.remove('show');
      _prevCountdown = null;
    }
  }
}


/* ═══════════════════════════════════════════
   RESULT overlay (POSE CLEAR / TIME'S UP)
   Shown when snapshot_event arrives
═══════════════════════════════════════════ */

function showResultOverlay(result, snapshots) {
  const ov    = document.getElementById('overlay-result');
  const title = document.getElementById('resultTitle');
  const sub   = document.getElementById('resultSub');
  const row   = document.getElementById('snapshotRow');
  const btn   = document.getElementById('nextBtn');
  if (!ov) return;

  if (result === 'cleared') {
    title.textContent = '⭐ POSE CLEAR! ⭐';
    title.style.color = '#facc15';
    sub.textContent   = 'Strike a pose — you nailed it!';
  } else {
    title.textContent = "TIME'S UP!";
    title.style.color = '#a78bfa';
    sub.textContent   = 'Better luck next pose!';
  }

  const soundKey = `${result}:${snapshots.round || 0}:${snapshots.pose || 0}`;
  if (soundKey !== _lastResultSoundKey) {
    _lastResultSoundKey = soundKey;
    if (result === 'cleared') {
      sound.playVictoryFanfare();
      setTimeout(() => sound.playCameraShutter(), 650);
    } else {
      sound.playCameraShutter();
    }
  }

  // Build snapshot images
  row.innerHTML = '';
  const labels = { cam0: '📷 CAM 0 — FRONT', cam1: '📷 CAM 1 — SIDE' };
  ['cam0', 'cam1'].forEach(key => {
    const frame = document.createElement('div');
    frame.className = 'snapshot-frame';
    if (snapshots && snapshots[key]) {
      frame.innerHTML = `
        <img src="data:image/jpeg;base64,${snapshots[key]}" alt="${labels[key]}"/>
        <div class="snapshot-label">${labels[key]}</div>
      `;
    } else {
      frame.innerHTML = `
        <div class="snapshot-placeholder">
          <span>${labels[key]}<br><br>(no image)</span>
        </div>
      `;
    }
    row.appendChild(frame);
  });

  btn.textContent = result === 'cleared' ? '▶ NEXT POSE' : '▶ CONTINUE';
  ov.classList.add('show');
}

function hideResultOverlay() {
  document.getElementById('overlay-result')?.classList.remove('show');
}


/* ═══════════════════════════════════════════
   END overlay (GAME OVER / GAME CLEAR)
═══════════════════════════════════════════ */

function showEndOverlay(gs, state) {
  const ov     = document.getElementById('overlay-end');
  const title  = document.getElementById('endTitle');
  const sub    = document.getElementById('endSub');
  const scores = document.getElementById('endScores');
  const star   = document.getElementById('endStar');
  if (!ov) return;

  const sorted = Object.entries(state.scores || {}).sort((a, b) => b[1] - a[1]);
  const medals = ['🥇', '🥈', '🥉'];
  const lines  = sorted.map((e, i) =>
    `${medals[i] || '  '} ${e[0]}: ${e[1]} pts`
  ).join('\n');

  if (gs === 'GAME_CLEAR') {
    title.textContent = '🏆 GAME CLEAR! 🏆';
    title.style.color = '#facc15';
    sub.textContent   = 'YOU CLEARED EVERY POSE!';
    star.style.display = 'block';
    const soundKey = `${gs}:${state.round || 0}:${state.pose || 0}:${Object.values(state.scores || {}).join(',')}`;
    if (soundKey !== _lastEndSoundKey) {
      _lastEndSoundKey = soundKey;
      sound.playGameClear();
      setTimeout(() => sound.playCameraShutter(), 900);
    }
  } else {
    title.textContent  = 'GAME OVER!';
    title.style.color  = '#ef4444';
    sub.textContent    = 'Thanks for playing!';
    star.style.display = 'none';
    const soundKey = `${gs}:${state.round || 0}:${state.pose || 0}:${Object.values(state.scores || {}).join(',')}`;
    if (soundKey !== _lastEndSoundKey) {
      _lastEndSoundKey = soundKey;
      sound.playGameOver();
    }
  }

  scores.textContent = lines;
  ov.classList.add('show');
}

function hideEndOverlay() {
  document.getElementById('overlay-end')?.classList.remove('show');
}


/* ═══════════════════════════════════════════
   NEXT button — sends cmd_next_pose
═══════════════════════════════════════════ */

window.sendNextPose = function () {
  socket.emit('cmd_next_pose');
  hideResultOverlay();
};


/* ═══════════════════════════════════════════
   Main state machine  (SocketIO → UI)
═══════════════════════════════════════════ */

let _prevState     = null;
let _lastHoldSound = 0;
let _lobbySetup    = null;
let _latestState   = null;

function applyState(state) {
  _latestState = state;
  const gs     = state.game_state;
  const colors = state.colors || {};
  const lobbyPlayers = (_lobbySetup && Array.isArray(_lobbySetup.players)) ? _lobbySetup.players : [];
  const activePlayers = (gs === 'IDLE' && lobbyPlayers.length) ? lobbyPlayers : (state.players || []);
  const playerColors = Object.assign(
    {},
    (_lobbySetup && _lobbySetup.player_colors) || {},
    state.player_colors || {}
  );
  const currentPlayer = (
    gs === 'IDLE' && _lobbySetup && _lobbySetup.status === 'ready_for_operator'
  )
    ? (_lobbySetup.first_player || activePlayers[0] || null)
    : (state.current_player || activePlayers[0] || null);

  // ── Proximity rings + sonar sounds ──
  if (gs === 'PLAYING') {
    sound.updateProximity(colors);
  }
  COLOR_ORDER.forEach(c => {
    updateProxRing(c, (colors[c] && colors[c].proximity) || 0);
  });

  // ── Timer ──
  const tl  = Math.ceil(state.time_left || 0);
  const tel = document.getElementById('timerDisplay');
  if (tel) {
    tel.textContent = (gs === 'GAME_OVER' || gs === 'GAME_CLEAR') ? '—' : String(tl).padStart(2, '0');
    tel.className   = 'timer-val ' + (tl > 20 ? 'ok' : tl > 10 ? 'warning' : 'danger');
  }

  // ── Round / pose ──
  const rdEl = document.getElementById('roundDisplay');
  if (rdEl) rdEl.textContent = `${state.round} / ${state.num_rounds}`;
  buildPips(state.poses_per_round || 5, state.pose || 0);

  // ── Status message ──
  const smEl = document.getElementById('statusMsg');
  if (smEl) {
    smEl.textContent = (
      gs === 'IDLE' && _lobbySetup && _lobbySetup.status === 'ready_for_operator'
    )
      ? `Waiting for operator to start ${(_lobbySetup.type || 'multiplayer').toUpperCase()}`
      : (state.message || '');
    smEl.style.color =
      gs === 'GAME_OVER'   ? '#ef4444' :
      gs === 'GAME_CLEAR'  ? '#facc15' :
      gs === 'POSE_CLEAR'  ? '#facc15' :
      gs === 'TIME_UP'     ? '#a78bfa' :
      gs === 'COUNTDOWN'   ? '#c4b5fd' :
      state.all_inside     ? '#16a34a' : '#111';
  }

  // ── Hold bar ──
  const hw  = document.getElementById('holdBarWrap');
  const hf  = document.getElementById('holdBarFill');
  const hp  = state.hold_progress || 0;
  if (hw && hf) {
    hw.style.display = (gs === 'PLAYING' && state.all_inside) ? 'block' : 'none';
    hf.style.width   = `${hp * 100}%`;
    const now = Date.now();
    if (gs === 'PLAYING' && state.all_inside && now - _lastHoldSound > 400) {
      sound.playHoldTick(hp);
      _lastHoldSound = now;
    }
  }

  // ── Scores ──
  updateTurnBanner(currentPlayer, activePlayers, playerColors, gs);
  if (gs === 'IDLE' && _lobbySetup && Array.isArray(_lobbySetup.players) && _lobbySetup.players.length) {
    buildScoreCards(
      _lobbySetup.players,
      Object.fromEntries(_lobbySetup.players.map(name => [name, 0])),
      currentPlayer,
      playerColors
    );
  } else {
    buildScoreCards(state.players, state.scores, currentPlayer, playerColors);
  }

  // ── Countdown overlay ──
  updateCountdownOverlay(gs, state.countdown, state.current_pose_name);

  // ── End overlay (fire once on transition) ──
  const prev = _prevState;

  if (gs === 'GAME_OVER' && prev !== 'GAME_OVER') {
    hideResultOverlay();
    showEndOverlay('GAME_OVER', state);
  }
  if (gs === 'GAME_CLEAR' && prev !== 'GAME_CLEAR') {
    hideResultOverlay();
    showEndOverlay('GAME_CLEAR', state);
  }
  if (gs === 'ROUND_END' && prev !== 'ROUND_END') {
    hideResultOverlay();
    sound.playRoundEnd();
  }
  if (gs === 'IDLE' && prev && prev !== 'IDLE') {
    hideResultOverlay();
    hideEndOverlay();
  }

  _prevState = gs;
}


/* ═══════════════════════════════════════════
   Socket.IO
═══════════════════════════════════════════ */

const socket = io();

socket.on('connect',    () => console.log('[Player] connected'));
socket.on('disconnect', () => console.log('[Player] disconnected'));

socket.on('game_state', state => {
  applyState(state);
});

socket.on('audio_settings', settings => {
  sound.applySettings(settings || {});
});

socket.on('lobby_setup', setup => {
  _lobbySetup = setup || null;
  if (_latestState) applyState(_latestState);
});

/* One-shot snapshot event: show result overlay with photos */
socket.on('snapshot_event', ev => {
  console.log('[Player] snapshot_event', ev.result);
  showResultOverlay(ev.result, ev);
});
