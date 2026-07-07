(function () {
  "use strict";

  // Paleta única rojo/negro (coincide con las variables --brand-* de style.css).
  const BRAND = {
    dark:    0x141414,
    core:    0xd90429, // brand-600
    hi:      0xff8a94, // highlight rosado
    accent:  0xff3245, // brand-500
    accent2: 0xff6b78, // brand-400
  };

  const MAX_PARTICLES = 60;
  const DOT_COUNT = 380;

  // Dirección de luz fija — el patrón de color queda "pintado" sobre cada
  // punto según su posición original y gira rígido con la esfera, igual
  // que en la referencia (no es una relumbrado dinámico).
  const LIGHT_DIR = new THREE.Vector3(-0.95, 0.2, 0.25).normalize();

  function wobble(x, y, z, t, speed, freq) {
    return Math.sin(x * freq + t * speed) *
           Math.sin(y * freq + t * speed * 0.8) *
           Math.sin(z * freq + t * speed * 1.3);
  }

  // Distribuye N puntos de forma pareja sobre una esfera unitaria (esfera de Fibonacci).
  function fibonacciSphere(samples) {
    const points = [];
    const goldenAngle = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < samples; i++) {
      const y = 1 - (i / (samples - 1)) * 2;
      const radius = Math.sqrt(Math.max(0, 1 - y * y));
      const theta = goldenAngle * i;
      points.push(new THREE.Vector3(Math.cos(theta) * radius, y, Math.sin(theta) * radius));
    }
    return points;
  }

  function litColor(dir, coreHex, hiHex) {
    coreHex = coreHex != null ? coreHex : BRAND.core;
    hiHex   = hiHex   != null ? hiHex   : BRAND.hi;
    const t = Math.max(0, dir.dot(LIGHT_DIR));
    const c = new THREE.Color();
    if (t < 0.55) {
      c.setHex(BRAND.dark).lerp(new THREE.Color(coreHex), t / 0.55);
    } else {
      c.setHex(coreHex).lerp(new THREE.Color(hiHex), (t - 0.55) / 0.45);
    }
    return c;
  }

  const Orb = {
    _state: "idle",

    init(container) {
      this._container = container;
      this._clock = new THREE.Clock();
      this._particles = [];
      this._particleSpawnTimer = 0;
      this._mouseTarget = { x: 0, y: 0 };
      this._mouseCurrent = { x: 0, y: 0 };
      this._frame = 0;
      this._autoRotation = 0;
      this._voiceLevel = 0;
      this._smoothLevel = 0;

      // Estado de "efectos de música" — reacciona al género/tempo/energía
      // de lo que suene por el reproductor embebido de Spotify (no hay
      // audio real accesible por DRM, así que el color sale del género del
      // artista y el pulso del tempo/energía reales de la canción).
      this._musicActive    = false;
      this._musicTempo     = 100;
      this._musicEnergy    = 0.5;
      this._musicPositionMs = 0;
      this._musicReceivedAt = 0;
      this._prevCore   = new THREE.Color(BRAND.core);
      this._prevHi     = new THREE.Color(BRAND.hi);
      this._targetCore = new THREE.Color(BRAND.core);
      this._targetHi   = new THREE.Color(BRAND.hi);
      this._colorT = 1; // 1 = ya llegó, sin transición pendiente

      this._buildScene();
      this._bindEvents();
      requestAnimationFrame(() => this._tick());
    },

    setState(name) {
      if (name === this._state) return;
      this._state = name;
      this._particles = [];
      this._voiceLevel = 0;
    },

    setLevel(level) {
      this._voiceLevel = Math.max(0, Math.min(1, level));
    },

    // active: hay música sonando por el reproductor de Jarvis.
    // colorHex: color según el género del artista (null = no recambiar,
    //   solo reanclar tempo/posición — se usa en cada tick del SDK que no
    //   sea una canción nueva, para no recalcular la paleta de más).
    setMusicStyle(active, colorHex, tempo, energy, positionMs) {
      this._musicActive = !!active;
      if (this._musicActive) {
        if (positionMs != null) { this._musicPositionMs = positionMs; this._musicReceivedAt = performance.now(); }
        if (tempo  != null) this._musicTempo  = tempo;
        if (energy != null) this._musicEnergy = energy;
      }
      const targetHex = this._musicActive ? colorHex : BRAND.core;
      if (targetHex == null) return;
      this._beginColorTransition(targetHex);
    },

    _beginColorTransition(coreHex) {
      const e = this._colorT * (2 - this._colorT); // ease-out del tramo anterior
      this._prevCore = this._prevCore.clone().lerp(this._targetCore, e);
      this._prevHi   = this._prevHi.clone().lerp(this._targetHi, e);
      this._targetCore = new THREE.Color(coreHex);
      this._targetHi   = (coreHex === BRAND.core)
        ? new THREE.Color(BRAND.hi)
        : this._targetCore.clone().lerp(new THREE.Color(0xffffff), 0.55);
      this._colorT = 0;
    },

    _recolorDots(coreHex, hiHex) {
      for (let i = 0; i < DOT_COUNT; i++) {
        this._dotMesh.setColorAt(i, litColor(this._dotDirs[i], coreHex, hiHex));
      }
      this._dotMesh.instanceColor.needsUpdate = true;
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

      this._rimLight = new THREE.PointLight(BRAND.core, 1.6, 14);
      this._rimLight.position.set(2.4, -1.2, -2.6);
      this._scene.add(this._rimLight);

      this._orbGroup = new THREE.Group();
      this._scene.add(this._orbGroup);

      this._dotDirs  = fibonacciSphere(DOT_COUNT);
      this._dotPhase = this._dotDirs.map(() => Math.random() * Math.PI * 2);
      this._dotDummy = new THREE.Object3D();

      const dotGeo = new THREE.SphereGeometry(0.048, 8, 8);
      this._dotMat = new THREE.MeshStandardMaterial({
        color: 0xffffff,
        emissive: BRAND.core,
        emissiveIntensity: 0.28,
        roughness: 0.3,
        metalness: 0.25,
      });
      this._dotMesh = new THREE.InstancedMesh(dotGeo, this._dotMat, DOT_COUNT);
      for (let i = 0; i < DOT_COUNT; i++) {
        this._dotMesh.setColorAt(i, litColor(this._dotDirs[i]));
      }
      this._dotMesh.instanceColor.needsUpdate = true;
      this._orbGroup.add(this._dotMesh);

      this._glowMats = [];
      [[1.18, 0.14], [1.42, 0.05]].forEach(([scale, opacity]) => {
        const mat = new THREE.MeshBasicMaterial({
          color: BRAND.core,
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
      this._buildParticles();

      const ro = new ResizeObserver(() => this._onResize());
      ro.observe(this._container);
    },

    _buildOrbitOrbs() {
      this._orbitGroup = new THREE.Group();
      this._orbitOrbs = [];
      for (let i = 0; i < 5; i++) {
        const mat = new THREE.MeshBasicMaterial({
          color: BRAND.accent,
          transparent: true,
          opacity: 0.85,
          blending: THREE.AdditiveBlending,
        });
        const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.07, 12, 12), mat);
        this._orbitGroup.add(mesh);
        this._orbitOrbs.push({
          mesh,
          a: i * (2 * Math.PI / 5),
          spd: 0.9 + i * 0.16,
          rFrac: 1.5 + i * 0.07,
        });
      }
      this._orbitGroup.visible = false;
      this._orbGroup.add(this._orbitGroup);
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
      this._particleColor = new THREE.Color(BRAND.accent2);
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
      const px = this._particleColor;
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

    _updateDots(t, amplitude, freq, speed) {
      const lvl      = this._smoothLevel;
      const dummy    = this._dotDummy;
      const posAmp   = amplitude * (0.4 + 0.6 * lvl);
      const scaleAmp = 0.10 + lvl * 0.20;
      for (let i = 0; i < DOT_COUNT; i++) {
        const dir = this._dotDirs[i];
        const n   = wobble(dir.x, dir.y, dir.z, t + this._dotPhase[i], speed, freq);
        const r   = 1 + n * posAmp;
        dummy.position.set(dir.x * r, dir.y * r, dir.z * r);
        dummy.scale.setScalar(1 + n * scaleAmp);
        dummy.updateMatrix();
        this._dotMesh.setMatrixAt(i, dummy.matrix);
      }
      this._dotMesh.instanceMatrix.needsUpdate = true;
    },

    _tick() {
      requestAnimationFrame(() => this._tick());
      const dt = Math.min(this._clock.getDelta(), 0.05);
      const t = this._clock.getElapsedTime();
      this._frame++;
      this._smoothLevel += (this._voiceLevel - this._smoothLevel) * 0.12;

      if (this._colorT < 1) {
        this._colorT = Math.min(1, this._colorT + dt / 0.8);
        const e = this._colorT * (2 - this._colorT);
        const curCore = this._prevCore.clone().lerp(this._targetCore, e);
        const curHi   = this._prevHi.clone().lerp(this._targetHi, e);
        this._recolorDots(curCore.getHex(), curHi.getHex());
        this._glowMats.forEach((m) => m.color.copy(curCore));
        this._rimLight.color.copy(curCore);
      }

      let scale = 1, wobAmp = 0.010, wobFreq = 1.2, wobSpeed = 0.9;

      if (this._state === "idle") {
        if (this._musicActive) {
          // Sin acceso al audio real (DRM de Spotify): el pulso sigue el
          // tempo/energía reales de la canción actual (audio-features),
          // proyectando la posición conocida sobre el tiempo transcurrido.
          const elapsedMs = this._musicPositionMs + (performance.now() - this._musicReceivedAt);
          const beatPhase = (elapsedMs / 1000) * (this._musicTempo / 60) * Math.PI * 2;
          const pulse = Math.abs(Math.sin(beatPhase));
          const energy = this._musicEnergy;
          scale = 0.94 + (0.05 + energy * 0.06) * pulse;
          wobAmp = 0.012 + energy * 0.022;
          wobSpeed = 0.9 + energy * 0.6;
        } else {
          scale = 0.94 + 0.06 * (Math.sin(t * 0.85 * Math.PI) * 0.5 + 0.5);
        }
        this._orbitGroup.visible = false;
      } else if (this._state === "thinking") {
        scale = 0.95 + 0.05 * Math.sin(t * Math.PI * 3.5);
        wobAmp = 0.020; wobFreq = 1.7; wobSpeed = 1.4;
        this._orbitGroup.visible = true;
        for (const o of this._orbitOrbs) {
          o.a += o.spd * dt;
          const r = o.rFrac;
          o.mesh.position.set(Math.cos(o.a) * r, Math.sin(o.a) * r, Math.sin(o.a * 2) * 0.35);
        }
      } else if (this._state === "listening") {
        // Sin nivel real de mic aquí (ver nota en core/voice.py sobre streams
        // concurrentes de PyAudio) — pulso sintético; la onda se ve en los
        // puntos de la esfera (_updateDots), no en elementos aparte.
        const energy = Math.sin(t * 3.0) * 0.5 + 0.5;
        scale = 0.93 + 0.07 * Math.sin(t * Math.PI * 4.0);
        this._orbitGroup.visible = false;
        wobAmp = 0.010 + energy * 0.012;
      } else if (this._state === "speaking") {
        const lvl = this._smoothLevel;
        scale = 0.95 + 0.06 * lvl;
        wobAmp = 0.008 + lvl * 0.020;
        this._orbitGroup.visible = false;
      }

      this._orbGroup.scale.setScalar(scale);
      this._updateDots(t, wobAmp, wobFreq, wobSpeed);
      this._updateParticles(dt);

      this._autoRotation += dt * (Math.PI * 2 / 24);
      this._mouseCurrent.x += (this._mouseTarget.x - this._mouseCurrent.x) * 0.06;
      this._mouseCurrent.y += (this._mouseTarget.y - this._mouseCurrent.y) * 0.06;
      this._orbGroup.rotation.y = this._autoRotation + this._mouseCurrent.x * 0.35;
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
      // El orbe ahora es un fondo fijo con pointer-events:none (para no
      // bloquear el chat/header por encima), así que el paralaje escucha
      // el movimiento del mouse en toda la ventana en vez de solo el contenedor.
      window.addEventListener("mousemove", (e) => {
        const rect = this._container.getBoundingClientRect();
        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;
        this._mouseTarget.x = Math.max(-1, Math.min(1, (e.clientX - cx) / (window.innerWidth / 2)));
        this._mouseTarget.y = Math.max(-1, Math.min(1, (e.clientY - cy) / (window.innerHeight / 2)));
      });
      window.addEventListener("mouseout", (e) => {
        if (!e.relatedTarget) {
          this._mouseTarget.x = 0;
          this._mouseTarget.y = 0;
        }
      });
    },
  };

  window.JarvisOrb = Orb;
})();
