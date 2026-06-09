let currentPhase = 'setup';
let goalMinutes   = 30;
let isPaused      = false;
let reportChart   = null;
let sessions      = [];
let sidebarVisible = true;  // Sidebar 상태 추적
let voiceActive    = false;
let voiceToastTimer = null;

/* SocketIO */
const socket = io();
socket.on('connect',    () => console.log('[FL] 연결됨'));
socket.on('disconnect', () => console.log('[FL] 끊김'));

socket.on('state', (s) => {
  sessions = s.sessions || [];

  if (s.phase !== currentPhase) {
    if (s.phase === 'completed' && currentPhase === 'running') {
      showCompleted(s);
    }
    currentPhase = s.phase;
  }

  if (currentPhase !== 'running' && currentPhase !== 'paused') return;

  updateStatus(s.focus_state);
  updateDebug(s.ear, s.pitch, s.yaw);
  updateTimer(s.focused_time, s.session_time, s.goal_seconds);
  updateRing(s.focused_time, s.goal_seconds);
  updateProgressBar(s.focused_time, s.goal_seconds);
  updateDistractionReason(s.focus_state, s.focus_reason);
  updateLumToast(s.lum_toast);
  updateScreenStatus(s.screen_state, s.screen_reason);
});

/* View switching */
function showView(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById('view-' + name).classList.add('active');

  // Update nav links
  document.querySelectorAll('.nav-link').forEach(l => {
    l.classList.toggle('active', l.dataset.view === name);
  });

  // Hide nav on focus view for immersion
  document.getElementById('global-nav').style.display =
    name === 'focus' ? 'none' : '';

  if (name === 'report') renderReport();
}

/* Setup */
const goalSlider  = document.getElementById('goal-slider');
const goalDisplay = document.getElementById('goal-display');

goalSlider.addEventListener('input', () => {
  goalMinutes = parseInt(goalSlider.value);
  goalDisplay.textContent = goalMinutes;
});

document.getElementById('btn-start').addEventListener('click', () => {
  document.querySelector('.config-section').scrollIntoView({ behavior: 'smooth' });
});
document.getElementById('btn-start-2').addEventListener('click', startSession);

async function startSession() {
  try {
    const res = await fetch('/api/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal_minutes: goalMinutes }),
    });
    if (!res.ok) throw new Error(`서버 오류: ${res.status}`);
    isPaused = false;
    updatePauseBtn(false);
    document.getElementById('ring-goal').textContent = `/ ${goalMinutes}분`;
    showView('focus');
    currentPhase = 'running';
  } catch (err) {
    console.error('[FL] 세션 시작 실패:', err);
    alert('세션을 시작할 수 없습니다. 서버 연결을 확인하세요.');
  }
}

/* Focus controls */
async function togglePause() {
  if (!isPaused) {
    await fetch('/api/pause', { method: 'POST' });
    isPaused = true;
    currentPhase = 'paused';
  } else {
    await fetch('/api/resume', { method: 'POST' });
    isPaused = false;
    currentPhase = 'running';
  }
  updatePauseBtn(isPaused);
}

function updatePauseBtn(paused) {
  const label = document.getElementById('pause-label');
  const icon  = document.getElementById('pause-icon');
  if (paused) {
    label.textContent = '재개';
    icon.innerHTML = '<polygon points="3,2 13,7 3,12" fill="currentColor"/>';
  } else {
    label.textContent = '일시정지';
    icon.innerHTML = `
      <rect x="2" y="1" width="3.5" height="12" rx="1" fill="currentColor"/>
      <rect x="8.5" y="1" width="3.5" height="12" rx="1" fill="currentColor"/>
    `;
  }
}

async function resetSession() {
  if (!confirm('세션을 초기화하고 설정 화면으로 돌아가시겠습니까?')) return;
  await fetch('/api/reset', { method: 'POST' });
  currentPhase = 'setup';
  isPaused = false;
  updatePauseBtn(false);
  showView('setup');
}

/* Sidebar 토글 */
function toggleSidebar() {
  const sidebar   = document.querySelector('.stats-sidebar');
  const grid      = document.querySelector('.monitor-grid');
  const toggleBtn = document.getElementById('btn-toggle-sidebar');

  sidebarVisible = !sidebarVisible;

  if (sidebarVisible) {
    sidebar.classList.remove('hidden');
    grid.classList.remove('fullscreen-camera');
    toggleBtn.classList.remove('sidebar-hidden');
  } else {
    sidebar.classList.add('hidden');
    grid.classList.add('fullscreen-camera');
    toggleBtn.classList.add('sidebar-hidden');
  }
}

/* Status / Badge */
function updateStatus(focusState) {
  const pill = document.getElementById('status-pill');
  const text = document.getElementById('status-text');
  const ring = document.getElementById('cam-state-ring');

  const map = {
    focused:    ['pill-focused',    '집중 중',    'ring-focused'],
    distracted: ['pill-distracted', '집중 아님',  'ring-distracted'],
    no_face:    ['pill-noface',     '얼굴 없음',  ''],
    hold:       ['pill-hold',       '조도 변화',  ''],
  };

  const [pillCls, label, ringCls] = map[focusState] || map['no_face'];

  pill.className = `status-pill ${pillCls}`;
  text.textContent = label;

  ring.className = `cam-ring ${ringCls}`;
}

/* Debug */
function updateDebug(ear, pitch, yaw) {
  document.getElementById('d-ear').textContent   = ear.toFixed(3);
  document.getElementById('d-pitch').textContent = (pitch >= 0 ? '+' : '') + pitch.toFixed(1) + '°';
  document.getElementById('d-yaw').textContent   = (yaw   >= 0 ? '+' : '') + yaw.toFixed(1)   + '°';
}

/* Time formatting */
function fmtTime(secs) {
  const s  = Math.floor(secs);
  const m  = Math.floor(s / 60);
  const ss = s % 60;
  return String(m).padStart(2,'0') + ':' + String(ss).padStart(2,'0');
}

/* Timer */
function updateTimer(focused, session, goal) {
  document.getElementById('ring-time').textContent    = fmtTime(focused);
  document.getElementById('session-time').textContent = fmtTime(session);
}

/* Ring */
const CIRC = 2 * Math.PI * 82; // r=82 → 515.22

function updateRing(focused, goal) {
  const pct    = Math.min(focused / Math.max(goal, 1), 1.0);
  const offset = CIRC * (1 - pct);
  const color  = pct >= 1.0 ? '#ffd60a' : '#30d158';

  const fill  = document.getElementById('ring-fill');
  const pctEl = document.getElementById('ring-pct');

  fill.setAttribute('stroke-dashoffset', offset.toFixed(2));
  fill.style.stroke = color;

  pctEl.textContent = Math.floor(pct * 100) + '%';
  pctEl.style.fill  = color;
}

/* Progress bar */
function updateProgressBar(focused, goal) {
  const pct   = Math.min(focused / Math.max(goal, 1), 1.0) * 100;
  const color = pct >= 100 ? '#ffd60a' : '#30d158';

  const fill  = document.getElementById('prog-fill');
  const label = document.getElementById('prog-pct-label');

  fill.style.width      = pct.toFixed(1) + '%';
  fill.style.background = color;
  label.textContent     = pct.toFixed(1) + '%';
  label.style.color     = color;

  const goalMin = Math.floor(goal / 60);
  document.getElementById('prog-times').textContent =
    `${fmtTime(focused)} / ${String(goalMin).padStart(2,'0')}:00`;
}

/* Distraction reason */
function updateDistractionReason(focusState, reason) {
  const overlay = document.getElementById('distract-overlay');
  const msg     = document.getElementById('distract-reason');
  if (focusState === 'distracted' && reason && reason !== '집중 중') {
    msg.textContent = '⚠ ' + reason;
    overlay.classList.remove('hidden');
  } else {
    overlay.classList.add('hidden');
  }
}

/* Tablet screen status */
function updateScreenStatus(screenState, screenReason) {
  const pill   = document.getElementById('screen-state-pill');
  const reason = document.getElementById('screen-reason-text');
  if (!pill || !reason) return;

  const map = {
    study:      ['screen-study',      '공부 중'],
    distracted: ['screen-distracted', '화면 산만'],
    unknown:    ['screen-unknown',    '—'],
  };
  const [cls, label] = map[screenState] || map['unknown'];

  pill.className   = `screen-pill ${cls}`;
  pill.textContent = label;

  // "iPad 창 없음" 처럼 파이프라인이 진짜 연결 끊김으로 판단한 경우만 표시
  // 빈 문자열이거나 일시적 에러 메시지면 이유 숨김
  const isGenuineDisconnect = screenReason === 'iPad 창 없음';
  reason.textContent = isGenuineDisconnect ? '연결 없음' : (screenState !== 'unknown' ? screenReason : '');
}

/* Luminance toast */
function updateLumToast(active) {
  document.getElementById('lum-toast').classList.toggle('hidden', !active);
}

/* Completed */
function showCompleted(s) {
  const rate = s.session_time > 0
    ? (s.focused_time / s.session_time * 100).toFixed(0)
    : 0;
  document.getElementById('sum-session').textContent = fmtTime(s.session_time);
  document.getElementById('sum-focused').textContent = fmtTime(s.focused_time);
  document.getElementById('sum-rate').textContent    = rate + '%';
  showView('completed');
}

/* Overlay toggle */
async function toggleOverlay() {
  const res  = await fetch('/api/overlay/toggle', { method: 'POST' });
  const data = await res.json();
  updateOverlayBtn(data.show);
}

function updateOverlayBtn(show) {
  const btn  = document.getElementById('btn-overlay');
  const icon = document.getElementById('overlay-icon');
  if (!btn || !icon) return;
  if (show) {
    btn.classList.remove('overlay-off');
    icon.innerHTML = `
      <ellipse cx="7" cy="7" rx="6" ry="4" stroke="currentColor" stroke-width="1.3"/>
      <circle cx="7" cy="7" r="2" fill="currentColor"/>`;
  } else {
    btn.classList.add('overlay-off');
    icon.innerHTML = `
      <ellipse cx="7" cy="7" rx="6" ry="4" stroke="currentColor" stroke-width="1.3"/>
      <line x1="2" y1="2" x2="12" y2="12" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>`;
  }
}

socket.on('overlay_status', (data) => {
  updateOverlayBtn(data.show);
  const label = data.show ? '마스크 표시됨' : '마스크 숨겨짐';
  showVoiceToast(label);
});

/* Voice recognition */
async function toggleVoice() {
  try {
    const res  = await fetch('/api/voice/toggle', { method: 'POST' });
    const data = await res.json();
    if (!data.ok) {
      alert('음성 인식을 사용할 수 없습니다.\npip install SpeechRecognition PyAudio 후 서버를 재시작하세요.');
      return;
    }
    voiceActive = data.active;
    updateVoiceBtns(voiceActive, 'active', false);
  } catch (err) {
    console.error('[Voice] 토글 실패:', err);
  }
}

function updateVoiceBtns(active, mode, listening) {
  ['btn-voice-focus', 'btn-voice-setup'].forEach(id => {
    const btn = document.getElementById(id);
    if (!btn) return;
    btn.classList.remove('voice-active', 'voice-listening', 'voice-wake');
    if (!active)        { /* 기본 스타일 */ }
    else if (listening) btn.classList.add('voice-listening');
    else if (mode === 'wake') btn.classList.add('voice-wake');
    else                btn.classList.add('voice-active');
  });

  const setupLabel = document.getElementById('voice-setup-label');
  if (setupLabel) {
    if (!active)             setupLabel.textContent = '음성 명령';
    else if (listening)      setupLabel.textContent = '듣는 중…';
    else if (mode === 'wake') setupLabel.textContent = '"음성 켜" 대기';
    else                     setupLabel.textContent = '음성 켜짐';
  }
}

socket.on('voice_status', (data) => {
  voiceActive = data.active;
  updateVoiceBtns(data.active, data.mode || 'active', data.listening);
  if (data.error) console.warn('[Voice] 오류:', data.error);
});

const VOICE_LABELS = {
  start: '집중 시작', pause: '일시정지', resume: '재개', reset: '초기화',
  voice_off: '음성 대기 모드', set_time: '목표 시간 설정',
  overlay_on: '마스크 표시', overlay_off: '마스크 숨김', overlay_toggle: '마스크 전환',
};

socket.on('voice_command', (data) => {
  // 시간 설정
  if (data.command === 'set_time') {
    goalMinutes = data.minutes;
    goalSlider.value  = goalMinutes;
    goalDisplay.textContent = goalMinutes;
    document.getElementById('ring-goal').textContent = `/ ${goalMinutes}분`;
    showVoiceToast(`목표 ${goalMinutes}분으로 설정됨`);
    return;
  }

  // 음성 끄기 (wake 모드 전환)
  if (data.command === 'voice_off') {
    updateVoiceBtns(true, 'wake', false);
    showVoiceToast('"음성 켜" 라고 말하면 재활성화됩니다');
    return;
  }

  showVoiceToast(`"${data.text}" → ${VOICE_LABELS[data.command] || data.command}`);

  if (data.command === 'pause') {
    isPaused = true;
    currentPhase = 'paused';
    updatePauseBtn(true);
  } else if (data.command === 'resume') {
    isPaused = false;
    currentPhase = 'running';
    updatePauseBtn(false);
  } else if (data.command === 'reset') {
    currentPhase = 'setup';
    isPaused = false;
    updatePauseBtn(false);
    showView('setup');
  } else if (data.command === 'start') {
    isPaused = false;
    currentPhase = 'running';
    updatePauseBtn(false);
    document.getElementById('ring-goal').textContent = `/ ${goalMinutes}분`;
    showView('focus');
  }
});

function showVoiceToast(text) {
  const toast  = document.getElementById('voice-toast');
  const textEl = document.getElementById('voice-toast-text');
  if (!toast || !textEl) return;
  textEl.textContent = text;
  toast.classList.remove('hidden');
  if (voiceToastTimer) clearTimeout(voiceToastTimer);
  voiceToastTimer = setTimeout(() => toast.classList.add('hidden'), 2500);
}

/* Report */
function renderReport() {
  const last7   = sessions.slice(-7);
  const empty   = document.getElementById('report-empty');
  const content = document.getElementById('report-content');

  if (last7.length === 0) {
    empty.classList.remove('hidden');
    content.style.display = 'none';
    return;
  }
  empty.classList.add('hidden');
  content.style.display = '';

  const avgFocus = last7.reduce((a, s) => a + s.focused, 0) / last7.length;
  const best     = Math.max(...last7.map(s => s.focused));
  const avgRate  = last7.reduce((a, s) => a + s.rate, 0) / last7.length;

  document.getElementById('stat-avg').textContent  = fmtTime(avgFocus);
  document.getElementById('stat-best').textContent = fmtTime(best);
  document.getElementById('stat-rate').textContent = avgRate.toFixed(1) + '%';

  // Chart
  const labels = last7.map(s => s.date);
  const rates  = last7.map(s => s.rate);
  const mins   = last7.map(s => Math.floor(s.focused / 60));

  if (reportChart) reportChart.destroy();

  const ctx = document.getElementById('report-chart').getContext('2d');
  reportChart = new Chart(ctx, {
    data: {
      labels,
      datasets: [
        {
          type: 'line',
          label: '집중률 (%)',
          data: rates,
          borderColor: '#1a7a33',
          backgroundColor: 'rgba(26,122,51,0.06)',
          tension: 0.4,
          pointBackgroundColor: '#1a7a33',
          pointRadius: 4,
          pointHoverRadius: 6,
          yAxisID: 'y',
          borderWidth: 2,
        },
        {
          type: 'bar',
          label: '집중 시간 (분)',
          data: mins,
          backgroundColor: 'rgba(29,29,31,0.08)',
          borderRadius: 6,
          yAxisID: 'y2',
        },
      ],
    },
    options: {
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          labels: {
            color: '#86868b',
            font: { family: 'Inter', size: 12 },
            boxWidth: 8,
            boxHeight: 8,
            borderRadius: 2,
          },
        },
        tooltip: {
          backgroundColor: '#1d1d1f',
          titleColor: '#f5f5f7',
          bodyColor: '#86868b',
          borderColor: 'rgba(255,255,255,0.08)',
          borderWidth: 1,
        },
      },
      scales: {
        x: {
          ticks: { color: '#86868b', font: { size: 11 } },
          grid:  { color: 'rgba(0,0,0,0.05)' },
          border: { display: false },
        },
        y: {
          ticks: { color: '#86868b', font: { size: 11 } },
          grid:  { color: 'rgba(0,0,0,0.05)' },
          min: 0, max: 105,
          title: { display: false },
          border: { display: false },
        },
        y2: {
          position: 'right',
          ticks: { color: '#86868b', font: { size: 11 } },
          grid:  { display: false },
          border: { display: false },
        },
      },
    },
  });

  // History list
  const list = document.getElementById('history-list');
  list.innerHTML = '';
  [...last7].reverse().forEach((s, i) => {
    const row = document.createElement('div');
    row.className = 'hist-row';
    row.innerHTML = `
      <span class="hist-num">#${last7.length - i}</span>
      <span class="hist-date">${s.date}</span>
      <span class="hist-time">${fmtTime(s.focused)}</span>
      <span class="hist-rate">${s.rate}%</span>
    `;
    list.appendChild(row);
  });
}
