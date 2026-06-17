import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

const screen  = document.getElementById('loading-screen');
const canvas  = document.getElementById('loading-canvas');
if (!screen || !canvas) throw new Error('loading-screen elements not found');

/* ── Renderer ── */
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setClearColor(0x000000, 0);

const scene  = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(24, window.innerWidth / window.innerHeight, 0.1, 30);

scene.add(new THREE.AmbientLight(0xffffff, 0.65));
const key  = new THREE.DirectionalLight(0xd0e8ff, 1.4);
key.position.set(1, 2, 2); scene.add(key);
const fill = new THREE.DirectionalLight(0x8fabdd, 0.5);
fill.position.set(-2, 0.5, 1); scene.add(fill);

function resize() {
  renderer.setSize(window.innerWidth, window.innerHeight);
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);
resize();

/* ── State ── */
let vrm         = null;
let modelH      = 1.6;
let midY        = 0.8;
let elapsed     = 0;
let walkStarted = false;
let fadeStarted = false;

const WALK_DUR = 2.6;
const FADE_DUR = 0.55;

function lerp(a, b, t) { return a + (b - a) * t; }
function easeOut3(t) { return 1 - Math.pow(1 - t, 3); }

/* ── Fallback timeout ── */
setTimeout(() => {
  if (!fadeStarted) triggerFade();
}, 9000);

function triggerFade() {
  if (fadeStarted) return;
  fadeStarted = true;
  screen.style.transition = `opacity ${FADE_DUR}s ease`;
  screen.style.opacity    = '0';
  setTimeout(() => { screen.style.display = 'none'; renderer.dispose(); }, FADE_DUR * 1000 + 80);
}

/* ── Load VRM ── */
const loader = new GLTFLoader();
loader.register(p => new VRMLoaderPlugin(p));

loader.load('/static/avatar.vrm', gltf => {
  vrm = gltf.userData.vrm;
  VRMUtils.removeUnnecessaryJoints(vrm.scene);
  scene.add(vrm.scene);

  requestAnimationFrame(() => {
    const box = new THREE.Box3().setFromObject(vrm.scene);
    modelH = box.max.y - box.min.y;
    midY   = box.min.y + modelH * 0.5;

    /* Camera: fixed, looking at model center */
    camera.fov = 24;
    camera.position.set(0, midY * 0.7, modelH * 2.4);
    camera.lookAt(0, midY * 0.7, 0);
    camera.updateProjectionMatrix();

    /* VRM starts behind origin (away from camera) */
    vrm.scene.position.z = -modelH * 4.0;

    /* Arm A-pose */
    const lA = vrm.humanoid.getNormalizedBoneNode('leftUpperArm');
    const rA = vrm.humanoid.getNormalizedBoneNode('rightUpperArm');
    if (lA) lA.rotation.z = -0.75;
    if (rA) rA.rotation.z =  0.75;

    walkStarted = true;
  });
}, () => {}, () => { triggerFade(); });

/* ── Animation ── */
const clock = new THREE.Clock();

function animate() {
  requestAnimationFrame(animate);
  const delta = clock.getDelta();

  if (!vrm) { renderer.render(scene, camera); return; }
  if (!walkStarted) { renderer.render(scene, camera); return; }

  elapsed += delta;

  const walkT   = Math.min(1, elapsed / WALK_DUR);
  const walked  = easeOut3(walkT);

  /* Advance VRM toward camera — stop at comfortable distance */
  vrm.scene.position.z = lerp(-modelH * 4.0, -modelH * 1.2, walked);

  /* Walk cycle — fades out in last 15% */
  const wFade = walkT < 0.85 ? 1 : 1 - (walkT - 0.85) / 0.15;
  const phase = elapsed * 2.3 * Math.PI * 2;

  const lUL   = vrm.humanoid.getNormalizedBoneNode('leftUpperLeg');
  const rUL   = vrm.humanoid.getNormalizedBoneNode('rightUpperLeg');
  const lLL   = vrm.humanoid.getNormalizedBoneNode('leftLowerLeg');
  const rLL   = vrm.humanoid.getNormalizedBoneNode('rightLowerLeg');
  const lArm  = vrm.humanoid.getNormalizedBoneNode('leftUpperArm');
  const rArm  = vrm.humanoid.getNormalizedBoneNode('rightUpperArm');
  const spine = vrm.humanoid.getNormalizedBoneNode('spine');
  const head  = vrm.humanoid.getNormalizedBoneNode('head');

  if (lUL)   lUL.rotation.x  =  Math.sin(phase)        * 0.45 * wFade;
  if (rUL)   rUL.rotation.x  = -Math.sin(phase)        * 0.45 * wFade;
  if (lLL)   lLL.rotation.x  =  Math.max(0, -Math.sin(phase)) * 0.55 * wFade;
  if (rLL)   rLL.rotation.x  =  Math.max(0,  Math.sin(phase)) * 0.55 * wFade;
  if (lArm) { lArm.rotation.z = -0.75; lArm.rotation.x = -Math.sin(phase) * 0.28 * wFade; }
  if (rArm) { rArm.rotation.z =  0.75; rArm.rotation.x =  Math.sin(phase) * 0.28 * wFade; }
  if (spine)  spine.rotation.z =  Math.sin(phase) * 0.024 * wFade;

  /* Subtle head bob toward camera as it approaches */
  if (head) head.rotation.y = lerp(head.rotation.y, 0, 0.04);

  /* After walk completes → fade loading screen */
  if (walkT >= 1 && !fadeStarted) {
    setTimeout(triggerFade, 350);
  }

  vrm.update(delta);
  renderer.render(scene, camera);
}

animate();
