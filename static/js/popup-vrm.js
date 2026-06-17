import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

const canvas = document.getElementById('avatar-canvas');
if (!canvas) throw new Error('avatar-canvas not found');

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.setPixelRatio(1);
renderer.setClearColor(0x000000, 0);

const scene = new THREE.Scene();

const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 20);
camera.position.set(0, 0.8, 3.5);
camera.lookAt(0, 0.8, 0);

scene.add(new THREE.AmbientLight(0xffffff, 0.6));

const key = new THREE.DirectionalLight(0xd0e8ff, 1.5);
key.position.set(0.6, 2.0, 1.5);
scene.add(key);

const fill = new THREE.DirectionalLight(0x8fabdd, 0.5);
fill.position.set(-1.2, 0.5, 1.0);
scene.add(fill);

function onResize() {
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  if (!w || !h) return;
  
  canvas.width = w;
  canvas.height = h;
  
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
new ResizeObserver(onResize).observe(canvas);
onResize();

let vrm = null;
let focusState = 'no_face';

let exprTarget = { blink: 0, happy: 0, angry: 0, sad: 0 };
let exprSmooth = { blink: 0, happy: 0, angry: 0, sad: 0 };
let blinkTimer = 0, blinkPhase = 0, nextBlink = 2.0 + Math.random() * 3.0;

const loader = new GLTFLoader();
loader.register(parser => new VRMLoaderPlugin(parser));

loader.load(
  'http://localhost:5000/static/avatar.vrm',
  gltf => {
    vrm = gltf.userData.vrm;
    VRMUtils.removeUnnecessaryJoints(vrm.scene);
    scene.add(vrm.scene);

    const lArm = vrm.humanoid.getNormalizedBoneNode('leftUpperArm');
    const rArm = vrm.humanoid.getNormalizedBoneNode('rightUpperArm');
    if (lArm) lArm.rotation.z = -1.1;
    if (rArm) rArm.rotation.z =  1.1;

    requestAnimationFrame(() => {
      const box    = new THREE.Box3().setFromObject(vrm.scene);
      const modelH = box.max.y - box.min.y;
      const centerY = (box.max.y + box.min.y) / 2;

      const fov = 30;
      const halfFovRad = (fov / 2) * (Math.PI / 180);
      const dist = (modelH * 1.15 / 2) / Math.tan(halfFovRad);

      camera.fov = fov;
      camera.position.set(0, centerY, dist);
      camera.lookAt(0, centerY, 0);
      camera.updateProjectionMatrix();
    });
  },
  () => {},
  err => console.error('[Popup VRM] 로드 실패:', err)
);

function lerp(a, b, t) { return a + (b - a) * t; }

function setExpr(name, val) {
  try { vrm.expressionManager?.setValue(name, Math.max(0, Math.min(1, val))); } catch (_) {}
}

const clock = new THREE.Clock();

function animate() {
  requestAnimationFrame(animate);
  const delta   = clock.getDelta();
  const elapsed = clock.getElapsedTime();

  if (!vrm) { renderer.render(scene, camera); return; }

  /* idle breathing */
  const chest = vrm.humanoid.getNormalizedBoneNode('chest')
             || vrm.humanoid.getNormalizedBoneNode('spine');
  if (chest) {
    chest.rotation.x = lerp(chest.rotation.x, Math.sin(elapsed * 0.6) * 0.012, 0.05);
  }

  /* auto blink */
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

  exprTarget.happy = focusState === 'focused'    ? 0.45 : 0;
  exprTarget.angry = focusState === 'distracted' ? 0.35 : 0;
  exprTarget.sad   = focusState === 'sleepy'     ? 0.30 : 0;

  const bf = Math.min(1, delta * 30);
  const ef = Math.min(1, delta * 5);
  exprSmooth.blink = lerp(exprSmooth.blink, exprTarget.blink, bf);
  exprSmooth.happy = lerp(exprSmooth.happy, exprTarget.happy, ef);
  exprSmooth.angry = lerp(exprSmooth.angry, exprTarget.angry, ef);
  exprSmooth.sad   = lerp(exprSmooth.sad,   exprTarget.sad,   ef);

  setExpr('blinkLeft',  exprSmooth.blink);
  setExpr('blinkRight', exprSmooth.blink);
  setExpr('blink',      exprSmooth.blink);
  setExpr('happy', exprSmooth.happy); setExpr('joy',    exprSmooth.happy);
  setExpr('angry', exprSmooth.angry);
  setExpr('sad',   exprSmooth.sad);   setExpr('sorrow', exprSmooth.sad);

  vrm.update(delta);
  renderer.render(scene, camera);
}

animate();

/* 외부에서 호출: focusState 업데이트 */
window.popupVRM = {
  setFocusState(s) { focusState = s; }
};
