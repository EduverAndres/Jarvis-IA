(function () {
  "use strict";

  const PAL = {
    idle:      { core: 0x00d4ff, mid: 0x003a5c, px: 0x44bbff },
    thinking:  { core: 0xcc55ff, mid: 0x3d0066, px: 0xaa33ff },
    listening: { core: 0x00ff99, mid: 0x004433, px: 0x44ffaa },
    speaking:  { core: 0xff8800, mid: 0x441800, px: 0xffbb44 },
  };

  const MAX_PARTICLES = 60;

  function wobble(x, y, z, t, speed, freq) {
    return Math.sin(x * freq + t * speed) *
           Math.sin(y * freq + t * speed * 0.8) *
           Math.sin(z * freq + t * speed * 1.3);
  }

  const Orb = {
    _state: "idle",
    _prevState: "idle",
    _transition: 1,

    init(container) {
      this._container = container;
      this._clock = new THREE.Clock();
      this._particles = [];
      this._particleSpawnTimer = 0;
      this._phases = Array.from({ length: 14 }, () => Math.random() * Math.PI * 2);
      this._bh = new Array(28).fill(0.02);
      this._btgt = new Array(28).fill(0.04);
      this._mouseTarget = { x: 0, y: 0 };
      this._mouseCurrent = { x: 0, y: 0 };
      this._frame = 0;
      this._voiceLevel = 0;

      this._curCol = {
        core: new THREE.Color(PAL.idle.core),
        mid:  new THREE.Color(PAL.idle.mid),
        px:   new THREE.Color(PAL.idle.px),
      };
      this._tgtCol = {
        core: new THREE.Color(PAL.idle.core),
        mid:  new THREE.Color(PAL.idle.mid),
        px:   new THREE.Color(PAL.idle.px),
      };

      this._buildScene();
      this._bindEvents();
      requestAnimationFrame(() => this._tick());
    },

    setState(name) {
      if (!PAL[name] || name === this._state) return;
      this._state = name;
      this._tgtCol.core.set(PAL[name].core);
      this._tgtCol.mid.set(PAL[name].mid);
      this._tgtCol.px.set(PAL[name].px);
      this._particles = [];
      this._voiceLevel = 0;
    },

    setLevel(level) {
      this._voiceLevel = Math.max(0, Math.min(1, level));
    },

    _buildScene() {
      const w = this._container.clientWidth || 800;
      const h = this._container.clientHeight || 250;

      this._scene = new THREE.Scene();
      this._camera = new THREE.PerspectiveCamera(42, w / h, 0.1, 100);
      this._camera.position.set(0, 0, 4.4);

      this._renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      this._renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      this._renderer.setSize(w, h);
      this._renderer.setClearColor(0x000000, 0);
      this._container.appendChild(this._renderer.domElement);

      this._scene.add(new THREE.AmbientLight(0xffffff, 0.32));

      this._keyLight = new THREE.PointLight(0xffffff, 1.3, 14);
      this._keyLight.position.set(-2.2, 2.0, 3.2);
      this._scene.add(this._keyLight);

      this._rimLight = new THREE.PointLight(PAL.idle.core, 1.6, 14);
      this._rimLight.position.set(2.4, -1.2, -2.6);
      this._scene.add(this._rimLight);

      this._orbGroup = new THREE.Group();
      this._scene.add(this._orbGroup);

      const coreGeo = new THREE.IcosahedronGeometry(1, 5);
      this._basePositions = coreGeo.attributes.position.array.slice();
      this._coreMat = new THREE.MeshStandardMaterial({
        color: PAL.idle.mid,
        emissive: PAL.idle.core,
        emissiveIntensity: 0.55,
        roughness: 0.28,
        metalness: 0.2,
      });
      this._coreMesh = new THREE.Mesh(coreGeo, this._coreMat);
      this._orbGroup.add(this._coreMesh);

      this._glowMats = [];
      [[1.16, 0.32], [1.38, 0.13]].forEach(([scale, opacity]) => {
        const mat = new THREE.MeshBasicMaterial({
          color: PAL.idle.core,
          transparent: true,
          opacity,
          side: THREE.BackSide,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        });
        const mesh = new THREE.Mesh(new THREE.SphereGeometry(scale, 32, 32), mat);
        this._orbGroup.add(mesh);
        this._glowMats.push(mat);
      });

      this._buildOrbitOrbs();
      this._buildListenBars();
      this._buildSpeakBars();
      this._buildParticles();

      const ro = new ResizeObserver(() => this._onResize());
      ro.observe(this._container);
    },

    _buildOrbitOrbs() {
      this._orbitGroup = new THREE.Group();
      this._orbitOrbs = [];
      for (let i = 0; i < 5; i++) {
        const mat = new THREE.MeshBasicMaterial({
          color: PAL.thinking.core,
          transparent: true,
          opacity: 0.85,
          blending: THREE.AdditiveBlending,
        });
        const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.07, 12, 12), mat);
        this._orbitGroup.add(mesh);
        this._orbitOrbs.push({
          mesh, mat,
          a: i * (2 * Math.PI / 5),
          spd: 0.9 + i * 0.16,
          rFrac: 1.5 + i * 0.07,
        });
      }
      this._orbitGroup.visible = false;
      this._orbGroup.add(this._orbitGroup);
    },

    _buildListenBars() {
      this._listenGroup = new THREE.Group();
      this._listenBars = [];
      const n = 14, gap = 0.145;
      for (const side of [-1, 1]) {
        for (let i = 0; i < n; i++) {
          const geo = new THREE.BoxGeometry(0.05, 1, 0.05);
          const mat = new THREE.MeshBasicMaterial({
            color: PAL.listening.core, transparent: true, opacity: 0.7,
            blending: THREE.AdditiveBlending,
          });
          const mesh = new THREE.Mesh(geo, mat);
          mesh.position.x = side * (1.55 + i * gap);
          this._listenGroup.add(mesh);
          this._listenBars.push({ mesh, mat, i });
        }
      }
      this._listenGroup.visible = false;
      this._orbGroup.add(this._listenGroup);
    },

    _buildSpeakBars() {
      this._speakGroup = new THREE.Group();
      this._speakBarsMeshes = [];
      const n = 28;
      for (let i = 0; i < n; i++) {
        const geo = new THREE.BoxGeometry(0.045, 1, 0.045);
        geo.translate(0, 0.5, 0);
        const mat = new THREE.MeshBasicMaterial({
          color: PAL.speaking.core, transparent: true, opacity: 0.75,
          blending: THREE.AdditiveBlending,
        });
        const mesh = new THREE.Mesh(geo, mat);
        const angle = (i / n) * Math.PI * 2;
        mesh.position.set(Math.cos(angle) * 1.05, Math.sin(angle) * 1.05, 0);
        mesh.rotation.z = angle - Math.PI / 2;
        this._speakGroup.add(mesh);
        this._speakBarsMeshes.push(mesh);
      }
      this._speakGroup.visible = false;
      this._orbGroup.add(this._speakGroup);
    },

    _buildParticles() {
      const geo = new THREE.BufferGeometry();
      const positions = new Float32Array(MAX_PARTICLES * 3);
      const colors = new Float32Array(MAX_PARTICLES * 3);
      geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
      const mat = new THREE.PointsMaterial({
        size: 0.05, vertexColors: true, transparent: true,
        blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true,
      });
      this._points = new THREE.Points(geo, mat);
      this._orbGroup.add(this._points);
    },

    _spawnParticle() {
      if (this._particles.length >= MAX_PARTICLES) return;
      const s = this._state;
      const angle = Math.random() * Math.PI * 2;
      if (s === "thinking") {
        this._particles.push({
          type: "orbit", a: angle, spd: 0.55 + Math.random() * 0.5,
          r: 1.7 + Math.random() * 0.5, z: (Math.random() - 0.5) * 0.6,
          life: 1, decay: 0.008,
        });
      } else if (s === "listening") {
        const spd = 0.02 + Math.random() * 0.03;
        this._particles.push({
          type: "dot", x: Math.cos(angle) * 1.05, y: Math.sin(angle) * 1.05, z: (Math.random() - 0.5) * 0.4,
          vx: Math.cos(angle) * spd, vy: Math.sin(angle) * spd, vz: 0,
          life: 1, decay: 0.03,
        });
      } else if (s === "speaking") {
        const spd = 0.03 + Math.random() * 0.05;
        this._particles.push({
          type: "dot", x: Math.cos(angle) * 1.1, y: Math.sin(angle) * 1.1, z: (Math.random() - 0.5) * 0.5,
          vx: Math.cos(angle) * spd, vy: Math.sin(angle) * spd, vz: 0,
          life: 1, decay: 0.05,
        });
      } else {
        const dist = 1.3 + Math.random() * 0.5;
        this._particles.push({
          type: "dot", x: Math.cos(angle) * dist, y: Math.sin(angle) * dist, z: (Math.random() - 0.5) * 0.5,
          vx: (Math.random() - 0.5) * 0.006, vy: 0.004 + Math.random() * 0.008, vz: 0,
          life: 1, decay: 0.008,
        });
      }
    },

    _updateParticles(dt) {
      const cadence = { idle: 22, thinking: 9, listening: 5, speaking: 4 }[this._state] || 20;
      this._particleSpawnTimer++;
      if (this._particleSpawnTimer >= cadence) {
        this._particleSpawnTimer = 0;
        this._spawnParticle();
      }

      const alive = [];
      for (const p of this._particles) {
        p.life -= p.decay;
        if (p.life <= 0) continue;
        if (p.type === "orbit") {
          p.a += p.spd * dt;
        } else {
          p.x += p.vx; p.y += p.vy; p.z += p.vz;
          p.vy += 0.0002;
        }
        alive.push(p);
      }
      this._particles = alive;

      const posAttr = this._points.geometry.attributes.position;
      const colAttr = this._points.geometry.attributes.color;
      const px = this._curCol.px;
      for (let i = 0; i < MAX_PARTICLES; i++) {
        const p = this._particles[i];
        if (!p) {
          posAttr.setXYZ(i, 0, 9999, 0);
          colAttr.setXYZ(i, 0, 0, 0);
          continue;
        }
        let x, y, z;
        if (p.type === "orbit") {
          x = Math.cos(p.a) * p.r; y = Math.sin(p.a) * p.r; z = p.z;
        } else {
          x = p.x; y = p.y; z = p.z;
        }
        posAttr.setXYZ(i, x, y, z);
        colAttr.setXYZ(i, px.r * p.life, px.g * p.life, px.b * p.life);
      }
      posAttr.needsUpdate = true;
      colAttr.needsUpdate = true;
    },

    _updateWobble(t, amplitude, freq, speed) {
      const pos = this._coreMesh.geometry.attributes.position;
      const base = this._basePositions;
      for (let i = 0; i < pos.count; i++) {
        const ix = i * 3;
        const x0 = base[ix], y0 = base[ix + 1], z0 = base[ix + 2];
        const n = wobble(x0, y0, z0, t, speed, freq);
        const r = 1 + n * amplitude;
        pos.setXYZ(i, x0 * r, y0 * r, z0 * r);
      }
      pos.needsUpdate = true;
      this._coreMesh.geometry.computeVertexNormals();
    },

    _tick() {
      requestAnimationFrame(() => this._tick());
      const dt = Math.min(this._clock.getDelta(), 0.05);
      const t = this._clock.getElapsedTime();
      this._frame++;

      this._curCol.core.lerp(this._tgtCol.core, 0.05);
      this._curCol.mid.lerp(this._tgtCol.mid, 0.05);
      this._curCol.px.lerp(this._tgtCol.px, 0.05);
      this._coreMat.emissive.copy(this._curCol.core);
      this._coreMat.color.copy(this._curCol.mid);
      this._rimLight.color.copy(this._curCol.core);
      this._glowMats.forEach((m) => m.color.copy(this._curCol.core));

      let scale = 1, wobAmp = 0.012, wobFreq = 1.6, wobSpeed = 1.2;

      if (this._state === "idle") {
        scale = 0.94 + 0.06 * (Math.sin(t * 0.85 * Math.PI) * 0.5 + 0.5);
        this._orbitGroup.visible = false;
        this._listenGroup.visible = false;
        this._speakGroup.visible = false;
      } else if (this._state === "thinking") {
        scale = 0.95 + 0.05 * Math.sin(t * Math.PI * 3.5);
        wobAmp = 0.03; wobFreq = 2.4; wobSpeed = 2.0;
        this._orbitGroup.visible = true;
        this._listenGroup.visible = false;
        this._speakGroup.visible = false;
        for (const o of this._orbitOrbs) {
          o.a += o.spd * dt;
          const r = o.rFrac;
          o.mesh.position.set(Math.cos(o.a) * r, Math.sin(o.a) * r, Math.sin(o.a * 2) * 0.35);
          o.mat.color.copy(this._curCol.core);
        }
      } else if (this._state === "listening") {
        // Sin nivel real de mic aquí (ver nota en core/voice.py sobre streams
        // concurrentes de PyAudio) — animación sintética por estado.
        scale = 0.93 + 0.07 * Math.sin(t * Math.PI * 4.0);
        this._orbitGroup.visible = false;
        this._listenGroup.visible = true;
        this._speakGroup.visible = false;
        const nBars = 14, maxH = 1.6;
        let energy = 0;
        for (const b of this._listenBars) {
          const phase = this._phases[b.i % this._phases.length];
          const wave = Math.sin(t * (2.0 + b.i * 0.22) + phase) * 0.5 + 0.5;
          const taper = 1 - Math.pow(b.i / nBars, 1.7);
          const h = Math.max(0.03, maxH * wave * taper);
          b.mesh.scale.y = h;
          b.mat.color.copy(this._curCol.core);
          energy = Math.max(energy, wave * taper);
        }
        wobAmp = 0.015 + energy * 0.02;
      } else if (this._state === "speaking") {
        const lvl = this._voiceLevel;
        if (this._frame % 3 === 0) {
          for (let i = 0; i < this._btgt.length; i++) {
            if (Math.random() < 0.44) {
              const dist = Math.abs(i - this._btgt.length / 2) / (this._btgt.length / 2);
              this._btgt[i] = 0.05 + 1.3 * (1 - Math.pow(dist, 1.3));
            }
          }
        }
        for (let i = 0; i < this._bh.length; i++) {
          this._bh[i] += (this._btgt[i] - this._bh[i]) * 0.15;
          this._speakBarsMeshes[i].scale.y = this._bh[i] * (0.15 + 0.85 * lvl);
          this._speakBarsMeshes[i].material.color.copy(this._curCol.core);
        }
        scale = 0.95 + 0.08 * lvl;
        wobAmp = 0.01 + lvl * 0.04;
        this._orbitGroup.visible = false;
        this._listenGroup.visible = false;
        this._speakGroup.visible = true;
      }

      this._orbGroup.scale.setScalar(scale);
      this._updateWobble(t, wobAmp, wobFreq, wobSpeed);
      this._updateParticles(dt);

      this._mouseCurrent.x += (this._mouseTarget.x - this._mouseCurrent.x) * 0.06;
      this._mouseCurrent.y += (this._mouseTarget.y - this._mouseCurrent.y) * 0.06;
      this._orbGroup.rotation.y = this._mouseCurrent.x * 0.35;
      this._orbGroup.rotation.x = this._mouseCurrent.y * 0.22;

      this._renderer.render(this._scene, this._camera);
    },

    _onResize() {
      const w = this._container.clientWidth || 800;
      const h = this._container.clientHeight || 250;
      this._renderer.setSize(w, h);
      this._camera.aspect = w / h;
      this._camera.updateProjectionMatrix();
    },

    _bindEvents() {
      this._container.addEventListener("mousemove", (e) => {
        const rect = this._container.getBoundingClientRect();
        this._mouseTarget.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
        this._mouseTarget.y = ((e.clientY - rect.top) / rect.height) * 2 - 1;
      });
      this._container.addEventListener("mouseleave", () => {
        this._mouseTarget.x = 0;
        this._mouseTarget.y = 0;
      });
    },
  };

  window.JarvisOrb = Orb;
})();
