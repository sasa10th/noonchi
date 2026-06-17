import { FaceLandmarker, FilesetResolver }
  from 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/vision_bundle.mjs';

/* ── 얼굴 인덱스 ── */
const FACE_OVAL = [10,338,297,332,284,251,389,356,454,323,361,288,397,365,
                   379,378,400,377,152,148,176,149,150,136,172,58,132,93,
                   234,127,162,21,54,103,67,109];
const L_EYE  = [362, 385, 387, 263, 373, 380];
const R_EYE  = [33,  160, 158, 133, 153, 144];
// 서버로 보낼 최소 랜드마크 (EAR + 헤드포즈 + 움직임 + 시선)
const KEY_IDX = [1, 10, 33, 133, 144, 152, 153, 158, 160, 263, 362, 373, 380, 385, 387];

/* ── DOM ── */
const video  = document.getElementById('cam-video');
const canvas = document.getElementById('cam-canvas');
const ctx    = canvas.getContext('2d');

/* ── 서버 소켓 (face_data 전용) ── */
const socket = io();

let focusState    = 'no_face';
let showOverlay   = true;
let landmarker    = null;
let lastVideoTime = -1;
let lastEmitTime  = 0;
const EMIT_MS     = 1000 / 15;  // 서버 전송 15fps로 제한

socket.on('state', s => { focusState = s.focus_state; });

/* ── 수학 유틸 ── */
function d2d(a, b) { return Math.hypot(a.x - b.x, a.y - b.y); }

function computeEAR(lm) {
  const ear = idx => {
    const p = idx.map(i => lm[i]);
    const c = d2d(p[0], p[3]);
    return c < 1e-6 ? 0.3 : (d2d(p[1], p[5]) + d2d(p[2], p[4])) / (2 * c);
  };
  return (ear(L_EYE) + ear(R_EYE)) / 2;
}

function headPose(lm) {
  const nose = lm[1], top = lm[10], chin = lm[152], le = lm[263], re = lm[33];
  const ecx = (le.x + re.x) / 2, ecy = (le.y + re.y) / 2;
  return {
    pitch: Math.max(-60, Math.min(60, (nose.y - ecy) / (d2d(top, chin) + 1e-6) * 75)),
    yaw:   Math.max(-90, Math.min(90, (nose.x - ecx) / (d2d(le,  re)   + 1e-6) * 55)),
  };
}

/* ── 오버레이 그리기 ── */
function drawOverlay(lm) {
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  if (!showOverlay) return;

  const color = focusState === 'focused'    ? '#30d158'
              : focusState === 'sleepy'     ? '#60a5fa'
              : focusState === 'no_face'    ? 'rgba(255,255,255,0.25)'
              :                               '#ff453a';

  ctx.fillStyle = ctx.strokeStyle = color;

  // 랜드마크 점
  ctx.lineWidth = 1;
  for (const p of lm) {
    ctx.beginPath();
    ctx.arc(p.x * w, p.y * h, 1, 0, 2 * Math.PI);
    ctx.fill();
  }

  // 얼굴 윤곽
  ctx.beginPath();
  FACE_OVAL.forEach((i, n) => {
    const p = lm[i];
    n === 0 ? ctx.moveTo(p.x * w, p.y * h) : ctx.lineTo(p.x * w, p.y * h);
  });
  ctx.closePath();
  ctx.stroke();

  // 모서리 테두리
  const m = 12, r = 20;
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.roundRect(m, m, w - 2 * m, h - 2 * m, r);
  ctx.stroke();
}

/* ── 감지 루프 ── */
function detectLoop() {
  requestAnimationFrame(detectLoop);
  if (!landmarker || !video || video.readyState < 2) return;
  if (video.currentTime === lastVideoTime) return;
  lastVideoTime = video.currentTime;

  const result = landmarker.detectForVideo(video, performance.now());

  if (result.faceLandmarks?.length) {
    const lm  = result.faceLandmarks[0];
    const ear = computeEAR(lm);
    const { pitch, yaw } = headPose(lm);

    drawOverlay(lm);

    const now = performance.now();
    if (now - lastEmitTime >= EMIT_MS) {
      lastEmitTime = now;
      const lmData = {};
      for (const i of KEY_IDX) lmData[i] = { x: lm[i].x, y: lm[i].y, z: lm[i].z ?? 0 };
      socket.emit('face_data', { has_face: true, ear, pitch, yaw, landmarks: lmData });
    }
  } else {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const now = performance.now();
    if (now - lastEmitTime >= EMIT_MS) {
      lastEmitTime = now;
      socket.emit('face_data', { has_face: false, ear: 0, pitch: 0, yaw: 0, landmarks: {} });
    }
  }
}

/* ── 초기화 ── */
async function init() {
  // 상태 메시지
  const statusEl = document.getElementById('cam-init-msg');
  if (statusEl) statusEl.textContent = 'AI 모델 로딩 중…';

  const fs = await FilesetResolver.forVisionTasks(
    'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm'
  );
  landmarker = await FaceLandmarker.createFromOptions(fs, {
    baseOptions: {
      modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task',
      delegate: 'GPU',
    },
    runningMode: 'VIDEO',
    numFaces: 1,
    outputFaceBlendshapes: false,
  });

  if (statusEl) statusEl.textContent = '카메라 연결 중…';

  const stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } },
  });
  video.srcObject = stream;

  await new Promise(resolve => {
    video.onloadedmetadata = () => {
      canvas.width  = video.videoWidth  || 640;
      canvas.height = video.videoHeight || 480;
      video.play();
      resolve();
    };
  });

  if (statusEl) statusEl.remove();
  detectLoop();
}

/* ── 오버레이 토글 (외부 호출) ── */
window.toggleOverlayClient = () => {
  showOverlay = !showOverlay;
  if (!showOverlay) ctx.clearRect(0, 0, canvas.width, canvas.height);
  return showOverlay;
};

init().catch(err => {
  console.error('[FaceClient] 초기화 실패:', err);
  const el = document.getElementById('cam-init-msg');
  if (el) {
    el.textContent = '카메라 접근 실패: ' + err.message;
    el.style.color = '#ff453a';
  }
});
