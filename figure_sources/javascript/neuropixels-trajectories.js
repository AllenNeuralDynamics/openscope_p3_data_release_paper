import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const data = JSON.parse(document.getElementById("neuropixels-trajectory-data").textContent);
const elements = {
  areaBar: document.getElementById("area-bar"),
  areaList: document.getElementById("area-list"),
  brainOpacity: document.getElementById("brain-opacity"),
  camera: document.getElementById("camera-select"),
  canvas: document.getElementById("brain-canvas"),
  interactiveView: document.getElementById("interactive-view"),
  modeButtons: [...document.querySelectorAll(".mode-button")],
  mouse: document.getElementById("mouse-select"),
  orientationCanvas: document.getElementById("orientation-canvas"),
  probeInputs: [...document.querySelectorAll("[data-probe]")],
  renderStatus: document.getElementById("render-status"),
  reset: document.getElementById("reset-view"),
  selectionMeta: document.getElementById("selection-meta"),
  selectionProbe: document.getElementById("selection-probe"),
  selectionSource: document.getElementById("selection-source"),
  selectionTitle: document.getElementById("selection-title"),
  sourceSummary: document.getElementById("source-summary"),
  staticView: document.getElementById("static-view"),
  visibleCount: document.getElementById("visible-count"),
  viewer: document.getElementById("trajectory-viewer"),
};

const state = {
  mouse: "all",
  probes: new Set(Object.keys(data.probeColors)),
  selected: null,
};
const trajectoryById = new Map(data.insertions.map((record) => [record.id, record]));
const meshById = new Map();
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
let hoveredMesh = null;
let selectionHalo = null;
let pointerDown = null;

elements.sourceSummary.textContent = `${data.summary.insertions} localized insertions · `
  + `${data.summary.localizedSessions} sessions · ${data.summary.subjects} mice`;

const mouseIds = [...new Set(data.insertions.map((record) => record.mouseId))].sort();
elements.mouse.append(new Option("All mice", "all"));
mouseIds.forEach((mouseId) => elements.mouse.append(new Option(mouseId, mouseId)));

const BASE_VERTICAL_FOV = 32;
const REFERENCE_ASPECT = 1.4;
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(BASE_VERTICAL_FOV, 1, 10, 60000);
const renderer = new THREE.WebGLRenderer({
  alpha: true,
  antialias: true,
  canvas: elements.canvas,
  powerPreference: "high-performance",
  preserveDrawingBuffer: true,
});
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;

const orientationRenderer = new THREE.WebGLRenderer({
  alpha: true,
  antialias: true,
  canvas: elements.orientationCanvas,
  preserveDrawingBuffer: true,
});
orientationRenderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
orientationRenderer.setSize(88, 88, false);
orientationRenderer.outputColorSpace = THREE.SRGBColorSpace;
const orientationScene = new THREE.Scene();
const orientationCamera = new THREE.PerspectiveCamera(35, 1, 0.1, 10);

function orientationLabel(text, color) {
  const labelCanvas = document.createElement("canvas");
  labelCanvas.width = 64;
  labelCanvas.height = 64;
  const context = labelCanvas.getContext("2d");
  context.beginPath();
  context.arc(32, 32, 23, 0, 2 * Math.PI);
  context.fillStyle = "rgba(255, 255, 255, 0.9)";
  context.fill();
  context.fillStyle = color;
  context.font = "600 30px IBM Plex Mono, monospace";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(text, 32, 33);
  const material = new THREE.SpriteMaterial({
    depthTest: false,
    map: new THREE.CanvasTexture(labelCanvas),
    transparent: true,
  });
  const sprite = new THREE.Sprite(material);
  sprite.scale.set(0.62, 0.62, 1);
  return sprite;
}

for (const [label, direction, color, cssColor] of [
  ["L", new THREE.Vector3(1, 0, 0), 0xd1495b, "#A82F41"],
  ["D", new THREE.Vector3(0, 1, 0), 0x2a9d6f, "#18734D"],
  ["A", new THREE.Vector3(0, 0, 1), 0x3157b7, "#244493"],
]) {
  orientationScene.add(
    new THREE.ArrowHelper(direction, new THREE.Vector3(), 1.05, color, 0.23, 0.13),
  );
  const sprite = orientationLabel(label, cssColor);
  sprite.position.copy(direction).multiplyScalar(1.38);
  orientationScene.add(sprite);
}
orientationScene.add(
  new THREE.Mesh(
    new THREE.SphereGeometry(0.09, 12, 8),
    new THREE.MeshBasicMaterial({ color: 0x41504c }),
  ),
);

const controls = new OrbitControls(camera, elements.canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.075;
controls.minDistance = 6500;
controls.maxDistance = 30000;
controls.target.set(0, 0, 0);

scene.add(new THREE.HemisphereLight(0xffffff, 0x9ba7a2, 2.4));
const keyLight = new THREE.DirectionalLight(0xffffff, 2.3);
keyLight.position.set(6000, 10000, 8000);
scene.add(keyLight);
const fillLight = new THREE.DirectionalLight(0xb9d9d8, 1.2);
fillLight.position.set(-9000, 2000, -6000);
scene.add(fillLight);

const shape = data.brainSurface.annotationShape;
const atlasCenter = new THREE.Vector3(
  shape[2] * 12.5,
  shape[1] * 12.5,
  shape[0] * 12.5,
);

function worldPoint(point) {
  return new THREE.Vector3(
    atlasCenter.x - point[2],
    atlasCenter.y - point[1],
    atlasCenter.z - point[0],
  );
}

const brainPositions = new Float32Array(data.brainSurface.vertices.length * 3);
data.brainSurface.vertices.forEach((point, index) => {
  worldPoint(point).toArray(brainPositions, index * 3);
});
const brainIndices = new Uint32Array(data.brainSurface.faces.flat());
const brainGeometry = new THREE.BufferGeometry();
brainGeometry.setAttribute("position", new THREE.BufferAttribute(brainPositions, 3));
brainGeometry.setIndex(new THREE.BufferAttribute(brainIndices, 1));
brainGeometry.computeVertexNormals();
const brainMaterial = new THREE.MeshPhysicalMaterial({
  color: 0xc8d6d0,
  depthWrite: false,
  opacity: Number(elements.brainOpacity.value) / 100,
  roughness: 0.72,
  side: THREE.DoubleSide,
  transparent: true,
});
const brainMesh = new THREE.Mesh(brainGeometry, brainMaterial);
brainMesh.renderOrder = 0;
scene.add(brainMesh);

function sampledWorldPoints(record, maximum = 34) {
  const step = Math.max(1, Math.ceil(record.points.length / maximum));
  const sampled = record.points.filter((_, index) => index % step === 0);
  if (sampled.at(-1) !== record.points.at(-1)) sampled.push(record.points.at(-1));
  return sampled.map(worldPoint);
}

function trajectoryGeometry(record, radius = 22) {
  const points = sampledWorldPoints(record);
  const curve = new THREE.CatmullRomCurve3(points, false, "centripetal", 0.45);
  return new THREE.TubeGeometry(curve, Math.max(18, points.length - 1), radius, 5, false);
}

data.insertions.forEach((record) => {
  const material = new THREE.MeshBasicMaterial({
    color: record.color,
    opacity: 0.48,
    transparent: true,
  });
  const mesh = new THREE.Mesh(trajectoryGeometry(record), material);
  mesh.userData.trajectoryId = record.id;
  mesh.renderOrder = 2;
  meshById.set(record.id, mesh);
  scene.add(mesh);
});

function visibleRecords() {
  return data.insertions.filter((record) => (
    (state.mouse === "all" || record.mouseId === state.mouse)
    && state.probes.has(record.probe)
  ));
}

function updateVisibility() {
  const visibleIds = new Set(visibleRecords().map((record) => record.id));
  meshById.forEach((mesh, id) => { mesh.visible = visibleIds.has(id); });
  elements.visibleCount.textContent = `${visibleIds.size} of ${data.summary.insertions} insertions`;
  if (!state.selected || !visibleIds.has(state.selected.id)) {
    selectTrajectory(visibleRecords()[0] || null);
  }
}

function renderAreaProfile(record) {
  elements.areaBar.replaceChildren();
  elements.areaList.replaceChildren();
  record.areas.forEach((area) => {
    const length = Math.max(1, area.endDepthUm - area.startDepthUm);
    const segment = document.createElement("span");
    segment.style.background = area.color;
    segment.style.flexGrow = String(length);
    segment.title = `${area.acronym}: ${(area.startDepthUm / 1000).toFixed(2)}–${(area.endDepthUm / 1000).toFixed(2)} mm`;
    elements.areaBar.append(segment);

    const item = document.createElement("li");
    const swatch = document.createElement("span");
    swatch.className = "area-swatch";
    swatch.style.background = area.color;
    const label = document.createElement("strong");
    label.textContent = area.acronym;
    label.title = area.name;
    const depth = document.createElement("small");
    depth.textContent = `${(area.startDepthUm / 1000).toFixed(2)}–${(area.endDepthUm / 1000).toFixed(2)}`;
    item.append(swatch, label, depth);
    elements.areaList.append(item);
  });
}

function selectTrajectory(record) {
  if (selectionHalo) {
    scene.remove(selectionHalo);
    selectionHalo.geometry.dispose();
    selectionHalo.material.dispose();
    selectionHalo = null;
  }
  meshById.forEach((mesh) => { mesh.material.opacity = 0.48; });
  state.selected = record;
  if (!record) {
    elements.selectionProbe.textContent = "No probe";
    elements.selectionTitle.textContent = "No localized insertion";
    elements.selectionMeta.textContent = "";
    elements.areaBar.replaceChildren();
    elements.areaList.replaceChildren();
    return;
  }
  const selectedMesh = meshById.get(record.id);
  selectedMesh.material.opacity = 1;
  selectionHalo = new THREE.Mesh(
    trajectoryGeometry(record, 50),
    new THREE.MeshBasicMaterial({ color: 0x202728, opacity: 0.2, transparent: true }),
  );
  selectionHalo.renderOrder = 1;
  scene.add(selectionHalo);
  elements.selectionProbe.textContent = `Probe ${record.probe}`;
  elements.selectionProbe.style.color = record.color;
  elements.selectionTitle.textContent = `Mouse ${record.mouseId}`;
  elements.selectionMeta.textContent = `${record.date} · ${(record.lengthUm / 1000).toFixed(2)} mm localized shank`;
  elements.selectionSource.href = `https://dandiarchive.org/dandiset/001637/draft/files?location=${encodeURIComponent(record.sourcePath)}`;
  renderAreaProfile(record);
}

const cameraPresets = {
  oblique: { position: [11200, 7300, 11600], up: [0, 1, 0] },
  dorsal: { position: [0, 17500, 0.01], up: [0, 0, 1] },
  coronal: { position: [0, 1000, 17500], up: [0, 1, 0] },
  sagittal: { position: [17500, 1000, 0], up: [0, 1, 0] },
};

function setCameraPreset(name) {
  const preset = cameraPresets[name] || cameraPresets.oblique;
  camera.position.set(...preset.position);
  camera.up.set(...preset.up);
  controls.target.set(0, 0, 0);
  controls.update();
}

function fittedVerticalFov(aspect) {
  if (aspect >= REFERENCE_ASPECT) return BASE_VERTICAL_FOV;
  const baseRadians = THREE.MathUtils.degToRad(BASE_VERTICAL_FOV);
  return THREE.MathUtils.radToDeg(
    2 * Math.atan(Math.tan(baseRadians / 2) * REFERENCE_ASPECT / aspect),
  );
}

function resizeRenderer() {
  const width = elements.canvas.clientWidth;
  const height = elements.canvas.clientHeight;
  if (width <= 0 || height <= 0) return;
  const pixelRatio = renderer.getPixelRatio();
  if (
    elements.canvas.width !== Math.floor(width * pixelRatio)
    || elements.canvas.height !== Math.floor(height * pixelRatio)
  ) {
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.fov = fittedVerticalFov(camera.aspect);
    camera.updateProjectionMatrix();
  }
}

function renderOrientationGizmo() {
  const cameraDirection = camera.position.clone().sub(controls.target).normalize();
  orientationCamera.position.copy(cameraDirection.multiplyScalar(6.5));
  orientationCamera.up.copy(camera.up).normalize();
  orientationCamera.lookAt(0, 0, 0);
  orientationRenderer.render(orientationScene, orientationCamera);
}

function trajectoryAtEvent(event) {
  const bounds = elements.canvas.getBoundingClientRect();
  pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1;
  pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const visibleMeshes = [...meshById.values()].filter((mesh) => mesh.visible);
  const hit = raycaster.intersectObjects(visibleMeshes, false)[0];
  return hit ? meshById.get(hit.object.userData.trajectoryId) : null;
}

elements.canvas.addEventListener("pointerdown", (event) => {
  pointerDown = { x: event.clientX, y: event.clientY };
});
elements.canvas.addEventListener("pointermove", (event) => {
  const mesh = trajectoryAtEvent(event);
  if (mesh !== hoveredMesh) {
    hoveredMesh = mesh;
    elements.canvas.classList.toggle("selectable", Boolean(mesh));
  }
});
elements.canvas.addEventListener("pointerup", (event) => {
  if (!pointerDown || Math.hypot(event.clientX - pointerDown.x, event.clientY - pointerDown.y) > 5) return;
  const mesh = trajectoryAtEvent(event);
  if (mesh) selectTrajectory(trajectoryById.get(mesh.userData.trajectoryId));
});
elements.canvas.addEventListener("pointerleave", () => {
  hoveredMesh = null;
  elements.canvas.classList.remove("selectable");
});

elements.mouse.addEventListener("change", () => {
  state.mouse = elements.mouse.value;
  updateVisibility();
});
elements.probeInputs.forEach((input) => input.addEventListener("change", () => {
  if (input.checked) state.probes.add(input.dataset.probe);
  else state.probes.delete(input.dataset.probe);
  updateVisibility();
}));
elements.brainOpacity.addEventListener("input", () => {
  brainMaterial.opacity = Number(elements.brainOpacity.value) / 100;
  brainMaterial.visible = brainMaterial.opacity > 0;
});
elements.camera.addEventListener("change", () => setCameraPreset(elements.camera.value));
elements.reset.addEventListener("click", () => {
  elements.camera.value = "oblique";
  setCameraPreset("oblique");
});
elements.modeButtons.forEach((button) => button.addEventListener("click", () => {
  const view = button.dataset.view;
  elements.modeButtons.forEach((candidate) => {
    const active = candidate === button;
    candidate.classList.toggle("active", active);
    candidate.setAttribute("aria-pressed", String(active));
  });
  elements.interactiveView.hidden = view !== "interactive";
  elements.staticView.hidden = view !== "static";
  elements.viewer.classList.toggle("static-active", view === "static");
  if (view === "interactive") resizeRenderer();
}));

const resizeObserver = new ResizeObserver(resizeRenderer);
resizeObserver.observe(elements.canvas.parentElement);
setCameraPreset("oblique");
updateVisibility();
selectTrajectory(
  data.insertions.find((record) => (
    record.mouseId === "830846" && record.date === "2026-03-09" && record.probe === "A"
  )) || data.insertions[0],
);
elements.renderStatus.textContent = "";
elements.renderStatus.hidden = true;

function animate() {
  controls.update();
  resizeRenderer();
  renderer.render(scene, camera);
  renderOrientationGizmo();
  requestAnimationFrame(animate);
}
animate();