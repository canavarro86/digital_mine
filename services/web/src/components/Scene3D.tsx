import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

export const STATUS_COLOR: Record<string, number> = { planned: 0x4f8ff7, driving: 0xf4a261, done: 0x2a9d8f, closed: 0x9aa5b1 };
const STOPE_COLOR: Record<string, number> = { planned: 0x8ecae6, active: 0xe76f51, mined: 0x6c757d };
const FACE_COLOR = 0xffd166;

interface Props {
  workings?: any[]; stopes?: any[]; orebody?: any; machines?: any[]; faces?: any[];
  lines?: { a: number[]; b: number[]; color: number }[]; points?: number[][]; polylines?: { points: number[][]; color?: number }[];
  height?: number; onPick?: (obj: { kind: string; data: any }) => void; focus?: number[];
}

/** Координаты рудника (x — восток, y — север, z — отметка) → three.js (x, z вверх → y, −y → z). */
const V = (p: number[]) => new THREE.Vector3(p[0], p[2], -p[1]);

export default function Scene3D({ workings = [], stopes = [], orebody, machines = [], faces = [], lines = [], points = [], polylines = [], height = 600, onPick, focus }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current!;
    const w = el.clientWidth || 800;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x10161f);
    const camera = new THREE.PerspectiveCamera(50, w / height, 0.5, 20000);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(w, height);
    el.appendChild(renderer.domElement);
    scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const dl = new THREE.DirectionalLight(0xffffff, 1.0);
    dl.position.set(300, 500, 200);
    scene.add(dl);
    const pickables: THREE.Object3D[] = [];
    const box = new THREE.Box3();

    for (const wk of workings) {
      if (!wk.axis || wk.axis.length < 2) continue;
      const path = new THREE.CurvePath<THREE.Vector3>();
      for (let i = 0; i < wk.axis.length - 1; i++) path.add(new THREE.LineCurve3(V(wk.axis[i]), V(wk.axis[i + 1])));
      const geo = new THREE.TubeGeometry(path, Math.max(2, wk.axis.length * 2), (wk.width || 5) / 2, 6, false);
      const mat = new THREE.MeshLambertMaterial({ color: STATUS_COLOR[wk.status] ?? 0xcccccc, transparent: wk.status === "planned", opacity: wk.status === "planned" ? 0.55 : 1 });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.userData = { kind: "working", data: wk };
      scene.add(mesh);
      pickables.push(mesh);
      geo.computeBoundingBox();
      box.union(geo.boundingBox!);
    }
    for (const s of stopes) {
      const g = new THREE.BoxGeometry(s.x_hw - s.x_fw, s.level_top - s.level_bottom, s.y1 - s.y0);
      const m = new THREE.Mesh(g, new THREE.MeshLambertMaterial({ color: STOPE_COLOR[s.status] ?? 0x8ecae6, transparent: true, opacity: s.status === "mined" ? 0.25 : 0.4 }));
      m.position.set((s.x_fw + s.x_hw) / 2, (s.level_top + s.level_bottom) / 2, -(s.y0 + s.y1) / 2);
      m.userData = { kind: "stope", data: s };
      scene.add(m);
      pickables.push(m);
      box.expandByObject(m);
    }
    if (orebody?.vertices?.length) {
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.Float32BufferAttribute(orebody.vertices.flatMap((p: number[]) => [p[0], p[2], -p[1]]), 3));
      g.setIndex(orebody.faces.flat());
      g.computeVertexNormals();
      const m = new THREE.Mesh(g, new THREE.MeshLambertMaterial({ color: 0xc9a227, transparent: true, opacity: 0.18, side: THREE.DoubleSide, depthWrite: false }));
      scene.add(m);
    }
    if (lines.length) {
      const byColor = new Map<number, number[]>();
      for (const l of lines) { const a = byColor.get(l.color) || []; a.push(l.a[0], l.a[2], -l.a[1], l.b[0], l.b[2], -l.b[1]); byColor.set(l.color, a); }
      for (const [c, arr] of byColor) {
        const g = new THREE.BufferGeometry();
        g.setAttribute("position", new THREE.Float32BufferAttribute(arr, 3));
        const ls = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: c }));
        scene.add(ls);
        g.computeBoundingBox();
        box.union(g.boundingBox!);
      }
    }
    for (const pl of polylines) {
      if (pl.points.length < 2) continue;
      const g = new THREE.BufferGeometry().setFromPoints(pl.points.map(V));
      scene.add(new THREE.Line(g, new THREE.LineBasicMaterial({ color: pl.color ?? 0xffffff })));
      g.computeBoundingBox();
      box.union(g.boundingBox!);
    }
    if (points.length) {
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.Float32BufferAttribute(points.flatMap((p) => [p[0], p[2], -p[1]]), 3));
      scene.add(new THREE.Points(g, new THREE.PointsMaterial({ color: 0x90e0ef, size: 0.4 })));
      g.computeBoundingBox();
      box.union(g.boundingBox!);
    }
    for (const f of faces) {
      if (!f.pos) continue;
      const m = new THREE.Mesh(new THREE.SphereGeometry(3, 12, 8), new THREE.MeshBasicMaterial({ color: FACE_COLOR }));
      m.position.copy(V(f.pos));
      m.userData = { kind: "face", data: f };
      scene.add(m);
      pickables.push(m);
    }
    for (const mc of machines) {
      if (!mc.pos) continue;
      const col = mc.type === "dev_drill" ? 0xff006e : mc.type === "ring_drill" ? 0x8338ec : mc.type === "lhd" ? 0x3a86ff : 0xffbe0b;
      const m = new THREE.Mesh(new THREE.ConeGeometry(2.5, 6, 8), new THREE.MeshBasicMaterial({ color: col }));
      m.position.copy(V(mc.pos)).add(new THREE.Vector3(0, 7, 0));
      m.rotation.x = Math.PI;
      m.userData = { kind: "machine", data: mc };
      scene.add(m);
      pickables.push(m);
    }
    if (box.isEmpty()) box.setFromCenterAndSize(new THREE.Vector3(), new THREE.Vector3(100, 100, 100));
    const center = focus ? V(focus) : box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3()).length();
    camera.position.copy(center).add(new THREE.Vector3(size * 0.6, size * 0.45, size * 0.6));
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.copy(center);
    controls.update();
    const ray = new THREE.Raycaster();
    const onClick = (e: MouseEvent) => {
      if (!onPick) return;
      const r = renderer.domElement.getBoundingClientRect();
      ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
      const hit = ray.intersectObjects(pickables)[0];
      if (hit) onPick(hit.object.userData as { kind: string; data: any });
    };
    renderer.domElement.addEventListener("click", onClick);
    let raf = 0;
    const loop = () => { raf = requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); };
    loop();
    const onResize = () => { const ww = el.clientWidth; camera.aspect = ww / height; camera.updateProjectionMatrix(); renderer.setSize(ww, height); };
    window.addEventListener("resize", onResize);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      renderer.domElement.removeEventListener("click", onClick);
      controls.dispose();
      scene.traverse((o: any) => { o.geometry?.dispose?.(); o.material?.dispose?.(); });
      renderer.dispose();
      el.removeChild(renderer.domElement);
    };
  }, [workings, stopes, orebody, machines, faces, lines, points, polylines, height]);
  return <div ref={ref} style={{ width: "100%", height, borderRadius: 6, overflow: "hidden" }} />;
}
