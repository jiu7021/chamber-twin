/**
 * ═══════════════════════════════════════════════════════════════════════
 * Chamber Twin — 3D Interactive Semiconductor Vacuum Chamber Engine
 * Three.js r128 Procedural Hardware Digital Twin
 * ═══════════════════════════════════════════════════════════════════════
 */

(function(window) {
  'use strict';

  let scene, camera, renderer;
  let container, canvas;
  let isInitialized = false;
  let isActive = true;
  let animId = null;

  // 3D Scene Objects
  let rootGroup, chamberGroup;
  let plasmaMesh, plasmaGlowMesh, plasmaCoreMesh, waferMesh, susceptorMesh, waferMat;
  let valveDiscGroup, valveShaft;
  let tmpRotorGroup;
  let gasParticles, gasParticleGeo;
  let leakMeshGroup;
  let mfcLed, dryPumpGroup;
  let pointLight, plasmaLight;

  // Animation States
  let bladeAngle = 0;
  let plasmaPhase = 0;
  let targetTheta = 0.467; // ~26.77 deg
  let currentTheta = 0.467;

  // Camera & Orbit Interaction
  let isDragging = false;
  let prevMouseX = 0, prevMouseY = 0;
  let rotX = 0.18, rotY = -0.45;
  let targetRotX = 0.18, targetRotY = -0.45;
  let zoomDist = 23.5;
  let targetZoomDist = 23.5;
  let initialPinchDist = 0;

  function init(containerId) {
    container = document.getElementById(containerId);
    if (!container) return false;

    if (typeof THREE === 'undefined') {
      console.warn('Three.js is not loaded.');
      return false;
    }

    try {
      canvas = document.createElement('canvas');
      canvas.id = 'chamber-3d-canvas';
      container.appendChild(canvas);

      // 1. Scene & Camera Setup
      scene = new THREE.Scene();
      scene.fog = new THREE.FogExp2(0x0e0e12, 0.022);

      const width = container.clientWidth || 460;
      const height = container.clientHeight || 340;
      camera = new THREE.PerspectiveCamera(38, width / height, 0.1, 100);
      camera.position.set(0.7, -0.1, zoomDist);

      // 2. Renderer Setup
      renderer = new THREE.WebGLRenderer({
        canvas: canvas,
        antialias: true,
        alpha: true,
        powerPreference: 'high-performance'
      });
      renderer.setSize(width, height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.15;

      // 3. Lighting Setup
      const ambientLight = new THREE.AmbientLight(0xffffff, 0.65);
      scene.add(ambientLight);

      const keyLight = new THREE.DirectionalLight(0xffffff, 1.1);
      keyLight.position.set(6, 10, 8);
      scene.add(keyLight);

      const fillLight = new THREE.DirectionalLight(0x00f0ff, 0.65);
      fillLight.position.set(-6, -4, 4);
      scene.add(fillLight);

      plasmaLight = new THREE.PointLight(0x00f0ff, 2.2, 8);
      plasmaLight.position.set(0, 2.4, 0);
      scene.add(plasmaLight);

      // 4. Construct Procedural 3D Hardware Model
      rootGroup = new THREE.Group();
      chamberGroup = new THREE.Group();
      rootGroup.add(chamberGroup);
      scene.add(rootGroup);

      buildChamberHardware();
      buildGasParticleStream();
      buildLeakEffect();

      // 5. Setup Orbit & Touch Interaction
      setupInteraction();

      // 6. Setup Resize Observer
      const ro = new ResizeObserver(() => resize());
      ro.observe(container);

      isInitialized = true;
      startLoop();
      return true;
    } catch (err) {
      console.warn('Three.js Chamber3D init error (falling back to 2D):', err);
      if (canvas && canvas.parentNode) {
        canvas.parentNode.removeChild(canvas);
      }
      isInitialized = false;
      return false;
    }
  }

  function buildChamberHardware() {
    // ── 공통 재질 정의 ──
    const metalMat = new THREE.MeshStandardMaterial({
      color: 0x222630,
      metalness: 0.85,
      roughness: 0.28
    });

    const steelMat = new THREE.MeshStandardMaterial({
      color: 0x3a404f,
      metalness: 0.9,
      roughness: 0.2
    });

    const darkMetalMat = new THREE.MeshStandardMaterial({
      color: 0x151820,
      metalness: 0.8,
      roughness: 0.4
    });

    const glassMat = new THREE.MeshPhysicalMaterial({
      color: 0x334455,
      transparent: true,
      opacity: 0.18,
      roughness: 0.08,
      metalness: 0.1,
      transmission: 0.85,
      ior: 1.45,
      side: THREE.DoubleSide
    });

    const glowCyanMat = new THREE.MeshBasicMaterial({
      color: 0x00f0ff,
      transparent: true,
      opacity: 0.45,
      blending: THREE.AdditiveBlending
    });

    waferMat = new THREE.MeshStandardMaterial({
      color: 0x0a1c2e,
      metalness: 0.95,
      roughness: 0.1,
      emissive: 0x002244,
      emissiveIntensity: 0.3
    });

    const valveDiscMat = new THREE.MeshStandardMaterial({
      color: 0x00f0ff,
      metalness: 0.88,
      roughness: 0.22,
      emissive: 0x005577,
      emissiveIntensity: 0.35,
      side: THREE.DoubleSide
    });

    // ── [1] 상단 가스 주입구 (MFC & Showerhead & 가스 공급 배관) ──
    const topFlange = new THREE.Mesh(new THREE.CylinderGeometry(2.5, 2.5, 0.22, 32), metalMat);
    topFlange.position.y = 4.3;
    chamberGroup.add(topFlange);

    const mfcInlet = new THREE.Mesh(new THREE.CylinderGeometry(0.26, 0.26, 0.7, 20), steelMat);
    mfcInlet.position.set(0, 4.75, 0);
    chamberGroup.add(mfcInlet);

    // 가스 공급 수평 배관 (좌측 -> 중앙 인렛으로 유입)
    const gasFeedPipe = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 2.2, 16), steelMat);
    gasFeedPipe.rotation.z = Math.PI / 2;
    gasFeedPipe.position.set(-1.1, 5.05, 0);
    chamberGroup.add(gasFeedPipe);

    const gasElbow = new THREE.Mesh(new THREE.TorusGeometry(0.18, 0.1, 12, 16, Math.PI / 2), steelMat);
    gasElbow.position.set(0, 4.95, 0);
    gasElbow.rotation.z = Math.PI / 2;
    chamberGroup.add(gasElbow);

    // MFC 가스 질량유량제어기 유닛 (배관 상의 직사각형 컨트롤러)
    const mfcBoxGeo = new THREE.BoxGeometry(0.75, 0.45, 0.4);
    const mfcBox = new THREE.Mesh(mfcBoxGeo, darkMetalMat);
    mfcBox.position.set(-1.4, 5.2, 0);
    chamberGroup.add(mfcBox);

    // MFC 상태 LED (정상: 초록, 차단: 빨강)
    mfcLed = new THREE.Mesh(new THREE.SphereGeometry(0.065, 12, 12), new THREE.MeshBasicMaterial({ color: 0x30d158 }));
    mfcLed.position.set(-1.4, 5.32, 0.22);
    chamberGroup.add(mfcLed);

    const showerhead = new THREE.Mesh(new THREE.CylinderGeometry(2.1, 2.1, 0.15, 32), darkMetalMat);
    showerhead.position.y = 4.15;
    chamberGroup.add(showerhead);

    // ── [2] 메인 식각 챔버 바디 (반투명 쿼츠 & 알루미늄 구조) ──
    const chamberBody = new THREE.Mesh(new THREE.CylinderGeometry(2.4, 2.4, 3.2, 32, 1, true), glassMat);
    chamberBody.position.y = 2.6;
    chamberGroup.add(chamberBody);

    const bottomFlange = new THREE.Mesh(new THREE.CylinderGeometry(2.5, 2.5, 0.25, 32), metalMat);
    bottomFlange.position.y = 0.95;
    chamberGroup.add(bottomFlange);

    // ── [3] 서셉터(Chuck) 및 200mm 실리콘 웨이퍼 ──
    susceptorMesh = new THREE.Mesh(new THREE.CylinderGeometry(1.85, 1.95, 0.35, 32), darkMetalMat);
    susceptorMesh.position.y = 1.25;
    chamberGroup.add(susceptorMesh);

    waferMesh = new THREE.Mesh(new THREE.CylinderGeometry(1.6, 1.6, 0.05, 32), waferMat);
    waferMesh.position.y = 1.45;
    chamberGroup.add(waferMesh);

    // ── [4] 에칭 플라즈마 방전 글로우 (Pulsing Glow) ──
    plasmaMesh = new THREE.Mesh(new THREE.CylinderGeometry(1.75, 1.75, 1.8, 32), glowCyanMat);
    plasmaMesh.position.y = 2.6;
    chamberGroup.add(plasmaMesh);

    plasmaCoreMesh = new THREE.Mesh(new THREE.SphereGeometry(1.15, 24, 24), new THREE.MeshBasicMaterial({
      color: 0x8b5cf6,
      transparent: true,
      opacity: 0.4,
      blending: THREE.AdditiveBlending
    }));
    plasmaCoreMesh.position.y = 2.6;
    plasmaMesh.add(plasmaCoreMesh);

    // ── [5] 진공 배기 배관 (챔버 바닥 -> 스로틀 밸브) ──
    const exhaustFunnel = new THREE.Mesh(new THREE.CylinderGeometry(2.2, 0.8, 0.8, 32), metalMat);
    exhaustFunnel.position.y = 0.45;
    chamberGroup.add(exhaustFunnel);

    const upperExhaustPipe = new THREE.Mesh(new THREE.CylinderGeometry(0.78, 0.78, 0.6, 28), steelMat);
    upperExhaustPipe.position.y = -0.25;
    chamberGroup.add(upperExhaustPipe);

    // ── [6] 3D 스로틀 밸브 (버터플라이 밸브 & 개도각 회전) ──
    const valveHousing = new THREE.Mesh(new THREE.CylinderGeometry(0.85, 0.85, 1.1, 28, 1, true), glassMat);
    valveHousing.position.y = -1.1;
    chamberGroup.add(valveHousing);

    const valveRingTop = new THREE.Mesh(new THREE.TorusGeometry(0.85, 0.06, 12, 28), metalMat);
    valveRingTop.rotation.x = Math.PI / 2;
    valveRingTop.position.y = -0.55;
    chamberGroup.add(valveRingTop);

    const valveRingBottom = new THREE.Mesh(new THREE.TorusGeometry(0.85, 0.06, 12, 28), metalMat);
    valveRingBottom.rotation.x = Math.PI / 2;
    valveRingBottom.position.y = -1.65;
    chamberGroup.add(valveRingBottom);

    // 회전 디스크 그룹 (Y=-1.1 위치)
    valveDiscGroup = new THREE.Group();
    valveDiscGroup.position.set(0, -1.1, 0);
    chamberGroup.add(valveDiscGroup);

    // 회전 샤프트 축 (X축 방향)
    valveShaft = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 1.9, 16), steelMat);
    valveShaft.rotation.z = Math.PI / 2;
    valveDiscGroup.add(valveShaft);

    // 버터플라이 원판 디스크 (샤프트 축을 중심으로 회전)
    const valvePlate = new THREE.Mesh(new THREE.CylinderGeometry(0.76, 0.76, 0.04, 32), valveDiscMat);
    valvePlate.rotation.x = Math.PI / 2;
    valveDiscGroup.add(valvePlate);

    // ── [7] 배기관 (스로틀 밸브 -> TMP) ──
    const midExhaustPipe = new THREE.Mesh(new THREE.CylinderGeometry(0.78, 0.78, 0.6, 28), steelMat);
    midExhaustPipe.position.y = -1.95;
    chamberGroup.add(midExhaustPipe);

    // ── [8] 3D 터보분자펌프 (TMP Stator & Rotor Blades) ──
    const tmpHousing = new THREE.Mesh(new THREE.CylinderGeometry(1.25, 1.25, 1.8, 32), darkMetalMat);
    tmpHousing.position.y = -3.15;
    chamberGroup.add(tmpHousing);

    const tmpFlange = new THREE.Mesh(new THREE.CylinderGeometry(1.35, 1.35, 0.18, 32), metalMat);
    tmpFlange.position.y = -2.25;
    chamberGroup.add(tmpFlange);

    // TMP 회전 로터 그룹
    tmpRotorGroup = new THREE.Group();
    tmpRotorGroup.position.set(0, -3.15, 0);
    chamberGroup.add(tmpRotorGroup);

    const tmpRotorHub = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.35, 1.6, 16), steelMat);
    tmpRotorGroup.add(tmpRotorHub);

    // 다단 회전 터빈 블레이드 (3단 x 8블레이드)
    const bladeMat = new THREE.MeshStandardMaterial({
      color: 0x64a0f0,
      metalness: 0.9,
      roughness: 0.25
    });

    for (let stage = 0; stage < 3; stage++) {
      const stageY = 0.45 - stage * 0.45;
      for (let b = 0; b < 8; b++) {
        const bladeAngle = (b * Math.PI * 2) / 8;
        const bladeGeo = new THREE.BoxGeometry(0.7, 0.04, 0.18);
        const blade = new THREE.Mesh(bladeGeo, bladeMat);
        blade.position.set(Math.cos(bladeAngle) * 0.7, stageY, Math.sin(bladeAngle) * 0.7);
        blade.rotation.y = -bladeAngle;
        blade.rotation.z = 0.45 * (stage % 2 === 0 ? 1 : -1);
        tmpRotorGroup.add(blade);
      }
    }

    // ── [9] 포어라인 배관 (TMP 아래 -> 러핑 펌프로 90도 굴절) ──
    const forelineJoint = new THREE.Mesh(new THREE.CylinderGeometry(0.65, 0.65, 0.6, 24), steelMat);
    forelineJoint.position.y = -4.35;
    chamberGroup.add(forelineJoint);

    const elbowMesh = new THREE.Mesh(new THREE.TorusGeometry(0.65, 0.22, 16, 24, Math.PI / 2), steelMat);
    elbowMesh.position.set(0.65, -4.65, 0);
    elbowMesh.rotation.z = Math.PI;
    chamberGroup.add(elbowMesh);

    const forelineHori = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.22, 1.4, 20), steelMat);
    forelineHori.rotation.z = Math.PI / 2;
    forelineHori.position.set(1.35, -4.65, 0);
    chamberGroup.add(forelineHori);

    const forelineEndFlange = new THREE.Mesh(new THREE.CylinderGeometry(0.38, 0.38, 0.12, 20), metalMat);
    forelineEndFlange.rotation.z = Math.PI / 2;
    forelineEndFlange.position.set(2.05, -4.65, 0);
    chamberGroup.add(forelineEndFlange);

    // ── [10] 2차 드라이 러핑펌프 (Dry Backing Pump 3D 모델) ──
    dryPumpGroup = new THREE.Group();
    dryPumpGroup.position.set(2.85, -4.65, 0);
    chamberGroup.add(dryPumpGroup);

    // 드라이 펌프 메인 케이싱 블록
    const pumpBodyGeo = new THREE.BoxGeometry(1.3, 0.85, 0.85);
    const dryPumpBody = new THREE.Mesh(pumpBodyGeo, darkMetalMat);
    dryPumpGroup.add(dryPumpBody);

    // 드라이 펌프 구동 모터 실린더 (오른쪽 돌출)
    const motorGeo = new THREE.CylinderGeometry(0.34, 0.34, 0.75, 20);
    const dryMotor = new THREE.Mesh(motorGeo, steelMat);
    dryMotor.rotation.z = Math.PI / 2;
    dryMotor.position.set(0.9, 0, 0);
    dryPumpGroup.add(dryMotor);

    // 모터 냉각 핀 (Cooling Fins)
    for (let f = 0; f < 3; f++) {
      const fin = new THREE.Mesh(new THREE.TorusGeometry(0.36, 0.02, 8, 20), metalMat);
      fin.rotation.y = Math.PI / 2;
      fin.position.set(0.7 + f * 0.16, 0, 0);
      dryPumpGroup.add(fin);
    }

    // 상단 배기 덕트 포트 (Exhaust Port)
    const exhPort = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.14, 0.35, 16), steelMat);
    exhPort.position.set(-0.2, 0.55, 0);
    dryPumpGroup.add(exhPort);

    // 하단 방진 고무 마운트 (Vibration Damper Feet)
    for (let fx = -0.4; fx <= 0.4; fx += 0.8) {
      for (let fz = -0.28; fz <= 0.28; fz += 0.56) {
        const foot = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.07, 0.1, 12), darkMetalMat);
        foot.position.set(fx, -0.46, fz);
        dryPumpGroup.add(foot);
      }
    }
  }

  function buildGasParticleStream() {
    const particleCount = 65;
    gasParticleGeo = new THREE.BufferGeometry();
    const positions = new Float32Array(particleCount * 3);
    const speeds = new Float32Array(particleCount);

    for (let i = 0; i < particleCount; i++) {
      positions[i * 3] = (Math.random() - 0.5) * 2.2;
      positions[i * 3 + 1] = 1.6 + Math.random() * 2.4;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 2.2;
      speeds[i] = 0.8 + Math.random() * 1.5;
    }

    gasParticleGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));

    const particleMat = new THREE.PointsMaterial({
      color: 0x00f0ff,
      size: 0.12,
      transparent: true,
      opacity: 0.75,
      blending: THREE.AdditiveBlending
    });

    gasParticles = new THREE.Points(gasParticleGeo, particleMat);
    gasParticles.userData.speeds = speeds;
    chamberGroup.add(gasParticles);
  }

  function buildLeakEffect() {
    leakMeshGroup = new THREE.Group();
    leakMeshGroup.position.set(2.45, 2.5, 0);

    const leakCone = new THREE.Mesh(
      new THREE.ConeGeometry(0.35, 1.2, 16),
      new THREE.MeshBasicMaterial({
        color: 0xff9f0a,
        transparent: true,
        opacity: 0.75,
        blending: THREE.AdditiveBlending
      })
    );
    leakCone.rotation.z = -Math.PI / 2;
    leakCone.position.x = 0.6;
    leakMeshGroup.add(leakCone);

    const leakRing = new THREE.Mesh(
      new THREE.TorusGeometry(0.25, 0.04, 12, 24),
      new THREE.MeshBasicMaterial({ color: 0xff453a })
    );
    leakRing.rotation.y = Math.PI / 2;
    leakMeshGroup.add(leakRing);

    leakMeshGroup.visible = false;
    chamberGroup.add(leakMeshGroup);
  }

  function setupInteraction() {
    if (!canvas) return;

    // 마우스 드래그 이벤트
    canvas.addEventListener('mousedown', (e) => {
      isDragging = true;
      prevMouseX = e.clientX;
      prevMouseY = e.clientY;
    });

    window.addEventListener('mousemove', (e) => {
      if (!isDragging || !isActive) return;
      const deltaX = e.clientX - prevMouseX;
      const deltaY = e.clientY - prevMouseY;
      prevMouseX = e.clientX;
      prevMouseY = e.clientY;

      targetRotY += deltaX * 0.008;
      targetRotX += deltaY * 0.008;
      targetRotX = Math.max(-0.6, Math.min(0.6, targetRotX));
    });

    window.addEventListener('mouseup', () => { isDragging = false; });

    // 마우스 휠 줌
    canvas.addEventListener('wheel', (e) => {
      if (!isActive) return;
      e.preventDefault();
      targetZoomDist += e.deltaY * 0.012;
      targetZoomDist = Math.max(10, Math.min(28, targetZoomDist));
    }, { passive: false });

    // 터치 1손가락 회전 & 2손가락 핀치 줌 (iPad 지원)
    canvas.addEventListener('touchstart', (e) => {
      if (e.touches.length === 1) {
        isDragging = true;
        prevMouseX = e.touches[0].clientX;
        prevMouseY = e.touches[0].clientY;
      } else if (e.touches.length === 2) {
        isDragging = false;
        initialPinchDist = Math.hypot(
          e.touches[0].clientX - e.touches[1].clientX,
          e.touches[0].clientY - e.touches[1].clientY
        );
      }
    }, { passive: true });

    canvas.addEventListener('touchmove', (e) => {
      if (!isActive) return;
      if (e.touches.length === 1 && isDragging) {
        const deltaX = e.touches[0].clientX - prevMouseX;
        const deltaY = e.touches[0].clientY - prevMouseY;
        prevMouseX = e.touches[0].clientX;
        prevMouseY = e.touches[0].clientY;

        targetRotY += deltaX * 0.008;
        targetRotX += deltaY * 0.008;
        targetRotX = Math.max(-0.6, Math.min(0.6, targetRotX));
      } else if (e.touches.length === 2 && initialPinchDist > 0) {
        const currentDist = Math.hypot(
          e.touches[0].clientX - e.touches[1].clientX,
          e.touches[0].clientY - e.touches[1].clientY
        );
        const pinchDelta = initialPinchDist - currentDist;
        targetZoomDist += pinchDelta * 0.02;
        targetZoomDist = Math.max(10, Math.min(28, targetZoomDist));
        initialPinchDist = currentDist;
      }
    }, { passive: true });

    canvas.addEventListener('touchend', () => {
      isDragging = false;
      initialPinchDist = 0;
    });

    // 더블클릭 시 기본 정면 뷰포트 복원
    canvas.addEventListener('dblclick', () => {
      targetRotX = 0.18;
      targetRotY = -0.45;
      targetZoomDist = 23.5;
    });
  }

  function resize() {
    if (!renderer || !camera || !container) return;
    const width = container.clientWidth;
    const height = container.clientHeight;
    if (width === 0 || height === 0) return;

    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
  }

  function update(s, dtReal) {
    if (!isInitialized) return;

    // 1. 실시간 밸브 개도각 (s.theta) 업데이트
    if (s && typeof s.theta === 'number') {
      targetTheta = s.theta;
    }
    // 부드러운 각도 보간 (Lerp)
    currentTheta += (targetTheta - currentTheta) * Math.min(dtReal * 12, 1);
    if (valveDiscGroup) {
      valveDiscGroup.rotation.x = currentTheta;
    }

    // 2. TMP 로터 회전 업데이트 (유효 배기속도 비례)
    const isProcessing = s && s.isProcessing !== false;
    if (tmpRotorGroup && s) {
      const speedNorm = (isProcessing && s.sEff > 0) ? Math.min(s.sEff / 0.15, 2.5) : 0.0;
      bladeAngle += speedNorm * 18 * dtReal;
      tmpRotorGroup.rotation.y = bladeAngle;
    }

    // 3. 플라즈마 글로우 펄스 & 가스 유입 상태 연동
    if (plasmaMesh) {
      plasmaPhase += dtReal * 3.5;
      const isClosed = s && s.gateClosed;
      const isBosch = s && s.boschMode;
      const isPass = isBosch && s.boschPhase === 'pass';

      plasmaMesh.visible = isProcessing && !isClosed;
      if (plasmaCoreMesh) plasmaCoreMesh.visible = isProcessing && !isClosed;

      if (!isProcessing) {
        if (plasmaLight) plasmaLight.intensity = 0;
        if (waferMat) waferMat.emissiveIntensity = 0;
      } else {

      // 보쉬 모드: SF₆ 식각(고광도 시안-바이올렛) vs C₄F₈ 보호막(초강력 네온 라임/에메랄드 그린)
      if (isPass) {
        plasmaMesh.material.color.setHex(0x00ff55); // 초강력 형광 네온 그린
        plasmaMesh.material.opacity = isClosed ? 0.08 : (0.72 + 0.06 * Math.sin(plasmaPhase));
        if (plasmaCoreMesh) {
          plasmaCoreMesh.material.color.setHex(0x00ff88);
          plasmaCoreMesh.material.opacity = 0.65;
        }
        if (plasmaLight) {
          plasmaLight.color.setHex(0x00ff55);
          plasmaLight.intensity = isClosed ? 0.3 : 3.5;
        }
        if (waferMat) {
          waferMat.emissive.setHex(0x00cc44);
          waferMat.emissiveIntensity = 0.85;
        }
      } else {
        plasmaMesh.material.color.setHex(0x00f0ff); // 눈부신 일렉트릭 시안
        plasmaMesh.material.opacity = isClosed ? 0.08 : (0.52 + 0.08 * Math.sin(plasmaPhase));
        if (plasmaCoreMesh) {
          plasmaCoreMesh.material.color.setHex(0x9d4edd);
          plasmaCoreMesh.material.opacity = 0.4;
        }
        if (plasmaLight) {
          plasmaLight.color.setHex(0x00f0ff);
          plasmaLight.intensity = isClosed ? 0.3 : (2.4 + 0.6 * Math.sin(plasmaPhase));
        }
        if (waferMat) {
          waferMat.emissive.setHex(0x003366);
          waferMat.emissiveIntensity = 0.35;
        }
      }
    }
  }

    // MFC LED 상태
    if (mfcLed && s) {
      if (!isProcessing) {
        mfcLed.material.color.setHex(0x4a5568);
      } else 
      if (s.gateClosed) {
        mfcLed.material.color.setHex(0xff453a);
      } else if (s.boschMode) {
        mfcLed.material.color.setHex(s.boschPhase === 'etch' ? 0x00f0ff : 0x00ff55);
      } else {
        mfcLed.material.color.setHex(0x30d158);
      }
    }

    // 4. 가스 유동 파티클 애니메이션
    if (gasParticles && gasParticleGeo) {
      const pos = gasParticleGeo.attributes.position.array;
      const speeds = gasParticles.userData.speeds;
      const count = pos.length / 3;
      const isFlowing = !(s && s.gateClosed);
      const isPass = s && s.boschMode && s.boschPhase === 'pass';

      gasParticles.material.color.setHex(isPass ? 0x00ff55 : 0x00f0ff);
      const flowMult = isPass ? 1.4 : 2.5;

      gasParticles.visible = isFlowing && isProcessing;
      if (isFlowing) {
        for (let i = 0; i < count; i++) {
          pos[i * 3 + 1] -= speeds[i] * dtReal * flowMult;
          if (pos[i * 3 + 1] < 1.5) {
            pos[i * 3 + 1] = 4.1;
            pos[i * 3] = (Math.random() - 0.5) * 2.0;
            pos[i * 3 + 2] = (Math.random() - 0.5) * 2.0;
          }
        }
        gasParticleGeo.attributes.position.needsUpdate = true;
      }
    }

    // 5. 리크(Leak) 고장 표시 연동
    if (leakMeshGroup && s) {
      const hasLeak = (s.qLeak && s.qLeak > 0) || (s.q1 && s.q1 > 0);
      leakMeshGroup.visible = !!hasLeak;
      if (hasLeak) {
        leakMeshGroup.scale.setScalar(0.9 + 0.2 * Math.sin(performance.now() * 0.01));
      }
    }
  }

  function startLoop() {
    function render() {
      animId = requestAnimationFrame(render);
      if (!isActive) return;

      rotX += (targetRotX - rotX) * 0.1;
      rotY += (targetRotY - rotY) * 0.1;
      zoomDist += (targetZoomDist - zoomDist) * 0.1;

      rootGroup.rotation.x = rotX;
      rootGroup.rotation.y = rotY;
      camera.position.z = zoomDist;

      renderer.render(scene, camera);
    }
    render();
  }

  function setActive(active) {
    isActive = active;
    if (container) {
      container.style.display = active ? 'flex' : 'none';
    }
    if (active) {
      resize();
    }
  }

  function resetView() {
    targetRotX = 0.18;
    targetRotY = -0.45;
    targetZoomDist = 23.5;
  }

  window.Chamber3D = {
    init,
    update,
    resize,
    setActive,
    resetView
  };

})(window);
