import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

const canvas = document.getElementById('hero-avatar-canvas');
if (!canvas) throw new Error('hero-avatar-canvas not found');

/* ── Renderer ── */
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setClearColor(0x000000, 0);

const scene = new THREE.Scene();

const camera = new THREE.PerspectiveCamera(36, 300 / 560, 0.1, 20);

/* ── Lights ── */
scene.add(new THREE.AmbientLight(0xffffff, 0.6));
const key = new THREE.DirectionalLight(0xd0e8ff, 1.4);
key.position.set(1, 2, 2); scene.add(key);
const fill = new THREE.DirectionalLight(0x8fabdd, 0.5);
fill.position.set(-2, 0.5, 1); scene.add(fill);

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
let vrm = null;
const loader = new GLTFLoader();
loader.register(p => new VRMLoaderPlugin(p));

loader.load('/static/avatar.vrm', gltf => {
  vrm = gltf.userData.vrm;
  VRMUtils.removeUnnecessaryJoints(vrm.scene);
  scene.add(vrm.scene);

  requestAnimationFrame(() => {
    const box = new THREE.Box3().setFromObject(vrm.scene);
    const h   = box.max.y - box.min.y;
    const mid = box.min.y + h * 0.5;
    camera.fov = 36;
    camera.position.set(0, mid, h * 2.5);
    camera.lookAt(0, mid, 0);
    camera.updateProjectionMatrix();

    /* 기본 자세 */
    const lArm = vrm.humanoid.getNormalizedBoneNode('leftUpperArm');
    const rArm = vrm.humanoid.getNormalizedBoneNode('rightUpperArm');
    if (lArm) lArm.rotation.z = -1.0;
    if (rArm) rArm.rotation.z =  1.0;
  });
}, () => {}, () => {});

/* ── Animation state ── */
const clock = new THREE.Clock();
let wavePhase = 'idle';
let waveTimer = 0;
let nextWave  = 2.0 + Math.random() * 2;

function lerp(a, b, t) { return a + (b - a) * t; }

function animate() {
  requestAnimationFrame(animate);

  /* 히어로 뷰가 보일 때만 렌더 */
  const heroVisible = document.getElementById('view-setup')?.classList.contains('active');
  if (!heroVisible || !vrm) { renderer.render(scene, camera); return; }

  const delta   = clock.getDelta();
  const elapsed = clock.getElapsedTime();

  /* ── Idle: 호흡 + 몸 흔들기 ── */
  const spine = vrm.humanoid.getNormalizedBoneNode('spine');
  const head  = vrm.humanoid.getNormalizedBoneNode('head');
  const neck  = vrm.humanoid.getNormalizedBoneNode('neck');
  if (spine) {
    spine.rotation.x = lerp(spine.rotation.x, Math.sin(elapsed * 1.1) * 0.018, 0.05);
    spine.rotation.z = lerp(spine.rotation.z, Math.sin(elapsed * 0.7) * 0.012, 0.04);
  }
  if (head) head.rotation.z = lerp(head.rotation.z, Math.sin(elapsed * 0.5) * 0.04, 0.04);
  if (neck) neck.rotation.z = lerp(neck.rotation.z, Math.sin(elapsed * 0.5) * 0.02, 0.04);

  /* ── Wave animation ── */
  const rUpperArm = vrm.humanoid.getNormalizedBoneNode('rightUpperArm');
  const rLowerArm = vrm.humanoid.getNormalizedBoneNode('rightLowerArm');

  waveTimer += delta;

  if (wavePhase === 'idle' && waveTimer >= nextWave) {
    wavePhase = 'raising'; waveTimer = 0;
  }

  if (wavePhase === 'raising') {
    const t = Math.min(1, waveTimer / 0.45);
    if (rUpperArm) {
      rUpperArm.rotation.z = lerp( 1.0, -0.3, t);
      rUpperArm.rotation.x = lerp( 0,    0.3, t);
    }
    if (t >= 1) { wavePhase = 'waving'; waveTimer = 0; }
  }

  if (wavePhase === 'waving') {
    if (rLowerArm) rLowerArm.rotation.z = Math.sin(elapsed * 10) * 0.45;
    if (head) head.rotation.y = lerp(head.rotation.y, Math.sin(elapsed * 10) * 0.08, 0.1);
    if (waveTimer >= 2.0) { wavePhase = 'lowering'; waveTimer = 0; }
  }

  if (wavePhase === 'lowering') {
    const t = Math.min(1, waveTimer / 0.5);
    if (rUpperArm) {
      rUpperArm.rotation.z = lerp(-0.3,  1.0, t);
      rUpperArm.rotation.x = lerp( 0.3,  0,   t);
    }
    if (rLowerArm) rLowerArm.rotation.z = lerp(rLowerArm.rotation.z, 0, 0.1);
    if (t >= 1) {
      wavePhase = 'idle'; waveTimer = 0;
      nextWave  = 4.0 + Math.random() * 3;
    }
  }

  vrm.update(delta);
  renderer.render(scene, camera);
}

animate();
