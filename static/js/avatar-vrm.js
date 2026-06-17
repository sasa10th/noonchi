import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

/* ── Renderer ── */
const canvas = document.getElementById('avatar-canvas');
if (!canvas) throw new Error('avatar-canvas not found');

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setClearColor(0x000000, 0);

/* ── Scene ── */
const scene = new THREE.Scene();

/* ── Camera ── */
const camera = new THREE.PerspectiveCamera(20, 1, 0.1, 20);
camera.position.set(0, 1.55, 0.9);
camera.lookAt(0, 1.45, 0);

/* ── Lights ── */
scene.add(new THREE.AmbientLight(0xffffff, 0.55));

const keyLight = new THREE.DirectionalLight(0xd0e8ff, 1.5);
keyLight.position.set(0.8, 2.0, 1.5);
scene.add(keyLight);

const fillLight = new THREE.DirectionalLight(0x8fabdd, 0.6);
fillLight.position.set(-1.5, 0.5, 1.0);
scene.add(fillLight);

const rimLight = new THREE.DirectionalLight(0x446688, 0.35);
rimLight.position.set(0, 1.0, -2.0);
scene.add(rimLight);

/* ── State ── */
let vrm = null;
const lookTarget = new THREE.Object3D();
scene.add(lookTarget);

let faceData = { ear: 0.3, pitch: 0, yaw: 0, focus_state: 'no_face' };
let headY = 1.45;  // 로드 후 auto-frame으로 갱신됨
let smoothed = { ear: 0.3, pitch: 0, yaw: 0 };

let exprTarget = { blink: 0, happy: 0, angry: 0, sad: 0 };
let exprSmooth = { blink: 0, happy: 0, angry: 0, sad: 0 };

let blinkTimer = 0, blinkPhase = 0, nextBlink = 2.5 + Math.random() * 2.5;

/* ── Resize ── */
function onResize() {
  const w = canvas.offsetWidth, h = canvas.offsetHeight;
  if (!w || !h) return;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
new ResizeObserver(onResize).observe(canvas);
onResize();

/* ── Load VRM ── */
const loader = new GLTFLoader();
loader.register(parser => new VRMLoaderPlugin(parser));

loader.load(
  '/static/avatar.vrm',
  gltf => {
    vrm = gltf.userData.vrm;
    VRMUtils.removeUnnecessaryJoints(vrm.scene);
    scene.add(vrm.scene);
    if (vrm.lookAt) vrm.lookAt.target = lookTarget;

    /* 팔 T-포즈 수정 */
    const lArm = vrm.humanoid.getNormalizedBoneNode('leftUpperArm');
    const rArm = vrm.humanoid.getNormalizedBoneNode('rightUpperArm');
    if (lArm) lArm.rotation.z = -1.1;
    if (rArm) rArm.rotation.z =  1.1;

    /* 렌더 1프레임 후 카메라 프레이밍 */
    requestAnimationFrame(() => {
      const box = new THREE.Box3().setFromObject(vrm.scene);
      const modelH = box.max.y - box.min.y;

      // 머리 본이 모델 상단 40% 안에 있을 때만 신뢰
      const rawHead = vrm.humanoid.getRawBoneNode('head');
      if (rawHead) {
        const wp = new THREE.Vector3();
        rawHead.getWorldPosition(wp);
        headY = wp.y > box.min.y + modelH * 0.6 ? wp.y : box.max.y - modelH * 0.12;
      } else {
        headY = box.max.y - modelH * 0.12;
      }

      const midY = box.min.y + modelH * 0.5;
      camera.fov = 32;
      camera.position.set(0, midY, modelH * 2.0);
      camera.lookAt(0, midY, 0);
      camera.updateProjectionMatrix();
      console.log('[VRM] 머리 Y:', headY.toFixed(2), '/ 모델 높이:', modelH.toFixed(2));
    });
  },
  () => {},
  err => console.error('[VRM] 로드 실패 — /static/avatar.vrm 파일을 확인하세요:', err)
);

/* ── Helpers ── */
function lerp(a, b, t) { return a + (b - a) * t; }

function setExpr(name, value) {
  try {
    vrm.expressionManager?.setValue(name, Math.max(0, Math.min(1, value)));
  } catch (_) {}
}

/* ── Animation loop ── */
const clock = new THREE.Clock();

function animate() {
  requestAnimationFrame(animate);
  const delta   = clock.getDelta();
  const elapsed = clock.getElapsedTime();

  if (!vrm) { renderer.render(scene, camera); return; }

  /* ── Smooth face data ── */
  const posLerp  = Math.min(1, delta * 14);
  const earLerp  = Math.min(1, delta * 20);
  smoothed.ear   = lerp(smoothed.ear,   faceData.ear,   earLerp);
  smoothed.pitch = lerp(smoothed.pitch, faceData.pitch, posLerp);
  smoothed.yaw   = lerp(smoothed.yaw,   faceData.yaw,   posLerp);

  /* ── Bones (1:1 매핑 — 감쇄 없음) ── */
  const pitchRad =  smoothed.pitch * (Math.PI / 180) - 0.18;
  const yawRad   =  smoothed.yaw   * (Math.PI / 180);

  const head  = vrm.humanoid.getNormalizedBoneNode('head');
  const neck  = vrm.humanoid.getNormalizedBoneNode('neck');
  const spine = vrm.humanoid.getNormalizedBoneNode('spine');

  if (head) {
    head.rotation.x = lerp(head.rotation.x, pitchRad * 0.60, 0.22);
    head.rotation.y = lerp(head.rotation.y, yawRad   * 0.60, 0.22);
  }
  if (neck) {
    neck.rotation.x = lerp(neck.rotation.x, pitchRad * 0.40, 0.18);
    neck.rotation.y = lerp(neck.rotation.y, yawRad   * 0.40, 0.18);
  }
  if (spine) {
    spine.rotation.x = lerp(spine.rotation.x, Math.sin(elapsed * 0.38) * 0.007, 0.05);
  }

  /* ── LookAt (기하학적 계산) ── */
  const yR =  smoothed.yaw  * Math.PI / 180;
  const pR = smoothed.pitch * Math.PI / 180;
  const D  = 3.0;
  lookTarget.position.set(
    Math.sin(yR) * D,
    headY - Math.sin(pR) * D,
    Math.cos(yR) * D
  );

  /* ── Blink ── */
  const earBlink = Math.max(0, Math.min(1, 1 - (smoothed.ear - 0.17) / 0.13));
  const faceVisible = faceData.focus_state !== 'no_face';

  if (faceVisible) {
    // 얼굴 감지 중: EAR만 사용, 자연 깜빡 억제
    exprTarget.blink = earBlink;
    blinkPhase = 0; blinkTimer = 0;
  } else {
    // 얼굴 없음: 자연 깜빡 폴백
    blinkTimer += delta;
    if (blinkPhase === 0 && blinkTimer >= nextBlink) {
      blinkPhase = 1; blinkTimer = 0;
    }
    if (blinkPhase === 1) {
      exprTarget.blink = Math.min(1, blinkTimer / 0.07);
      if (blinkTimer >= 0.07) { blinkPhase = 2; blinkTimer = 0; }
    }
    if (blinkPhase === 2) {
      exprTarget.blink = Math.max(0, 1 - blinkTimer / 0.10);
      if (blinkTimer >= 0.10) {
        blinkPhase = 0; blinkTimer = 0;
        nextBlink = 2.0 + Math.random() * 4.0;
        exprTarget.blink = 0;
      }
    }
  }

  /* ── Emotion ── */
  exprTarget.happy = faceData.focus_state === 'focused'    ? 0.45 : 0;
  exprTarget.angry = faceData.focus_state === 'distracted' ? 0.35 : 0;
  exprTarget.sad   = faceData.focus_state === 'sleepy'     ? 0.30 : 0;

  /* ── Smooth expressions ── */
  const bf = Math.min(1, delta * 30); // 깜빡: 빠르게
  const ef = Math.min(1, delta * 5);  // 감정: 천천히
  exprSmooth.blink = lerp(exprSmooth.blink, exprTarget.blink, bf);
  exprSmooth.happy = lerp(exprSmooth.happy, exprTarget.happy, ef);
  exprSmooth.angry = lerp(exprSmooth.angry, exprTarget.angry, ef);
  exprSmooth.sad   = lerp(exprSmooth.sad,   exprTarget.sad,   ef);

  /* VRM 0.x ('joy','sorrow') 와 1.x ('happy','sad') 동시 지원 */
  setExpr('blinkLeft',  exprSmooth.blink);
  setExpr('blinkRight', exprSmooth.blink);
  setExpr('blink',      exprSmooth.blink);
  setExpr('happy',  exprSmooth.happy); setExpr('joy',    exprSmooth.happy);
  setExpr('angry',  exprSmooth.angry);
  setExpr('sad',    exprSmooth.sad);   setExpr('sorrow', exprSmooth.sad);

  vrm.update(delta);
  renderer.render(scene, camera);
}

animate();

/* ── 공개 API (main.js에서 window.avatarCtrl.update(s) 호출) ── */
window.avatarCtrl = {
  update(s) {
    if (s.ear         != null) faceData.ear         = s.ear;
    if (s.pitch       != null) faceData.pitch       = s.pitch;
    if (s.yaw         != null) faceData.yaw         = s.yaw;
    if (s.focus_state != null) faceData.focus_state = s.focus_state;
  }
};
