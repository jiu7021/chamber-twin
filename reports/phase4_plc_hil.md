# Phase 4 — OpenPLC 실 PLC 연동 및 HIL 폐루프 검증

작성 2026-08-31. 대상: `chamber_apc` (OpenPLC Editor 프로젝트) ↔ OpenPLC Runtime v4.1.8 (Docker) ↔ 진공 챔버 트윈 (Modbus TCP 슬레이브, 호스트 5020).

## 1. 결론

실제 PLC가 물리 트윈을 폐루프 제어하는 것을 확인했다. 밸브 각도 정상상태 값이 해석해와 **4자리 유효숫자까지 일치**했고, 외란 정정시간은 사전 예측(`plc/hil_check.py`) 4.1 s 대비 실측 4.07 s 로 **오차 0.7 %** 였다.

이로써 Phase 1 이후의 핵심 주장 — *제어변수(압력)가 아니라 조작변수(밸브 각도)가 상태 정보를 갖는다* — 가 시뮬레이션이 아니라 실제 IEC 61131-3 PLC 스캔 루프 위에서 재현되었다.

## 2. 구성

```
OpenPLC Editor (macOS)
   │  HTTPS :8443  (프로그램 업로드 · 디버거)
   ▼
OpenPLC Runtime v4.1.8  [Docker: openplc-twin]
   │  Modbus TCP 마스터, 폴링 100 ms
   ▼  host.docker.internal:5020
진공 챔버 트윈 (physics/chamber.py + plc/modbus_server.py)
```

PLC 프로그램은 POU 3개다.

| POU | 종류 | 역할 |
|---|---|---|
| `FB_APC_PI` | Function Block | 압력 PI 제어, 되계산 와인드업 방지 |
| `FB_ALARM` | Function Block | N-스캔 지연 래치 알람 |
| `main` | Program | 스케일 해제, RoR 상태기계, 인터록, 알람 |

Task: `task0`, Cyclic, **T#100ms**. ST 안의 `SCAN_S := 0.1` 과 일치해야 한다 (§5 참조).

## 3. Modbus 매핑

`plc/modbus_master.json` — 런타임 컨테이너에서 회수한 실제 사용본이다. 개별 포인트 18개가 아니라 **연속 그룹 5개**로 묶었다. `iec_location` 은 그룹의 시작 주소이고 `len` 만큼 순차 할당된다.

| FC | Offset | len | IEC 시작 | 내용 |
|---|---|---|---|---|
| 4 (Read Input Registers) | 0x0000 | 6 | `%IW100` | 압력·포어라인·밸브각·개방률·S_eff·스루풋 |
| 4 | 0x000B | 3 | `%IW111` | RoR 추정 누설·q₁·α |
| 2 (Read Discrete Inputs) | 0x0004 | 2 | `%IX100.4` | RoR 진행중·완료 |
| 16 (Write Multiple Registers) | 0x0000 | 3 | `%QW100` | 설정압력·MFC·밸브각 지령 |
| 15 (Write Multiple Coils) | 0x0000 | 6 | `%QX100.0` | 자동·게이트·RoR·알람리셋·시뮬리셋·운전 |

쓰기 그룹에 FC 6/5(단일) 대신 **FC 16/15(다중)** 를 쓴 이유: 그룹 길이가 3과 6이라 단일 쓰기 FC로는 의미가 모호하다. 트윈 슬레이브는 `plc/modbus_tcp.py:144,153` 에 FC 15/16 이 구현돼 있다.

코일 6개를 한 그룹으로 묶으면 ST가 쓰지 않는 C3(`ALARM_RESET`)·C4(`SIM_RESET`)에도 매 스캔 0 이 기록된다. 두 코일 모두 **상승엣지 트리거**라 상시 0 쓰기는 무해하다.

폴링 주기는 그룹 전부 **100 ms**. Phase 3 의 HIL 여유 분석에서 루프 지연 300 ms 까지가 KP=0.20/KI=0.40 의 검증 범위였고, 500 ms 에서 오버슈트 22 %, 1 s 에서 67 %, 2 s 에서 발산했다.

## 4. 폐루프 검증

### 4-1. 정상상태 (외란 없음)

| 항목 | 실측 |
|---|---|
| 압력 | 40.00 ± 0.01 mTorr |
| 밸브각 | 26.77 deg |
| S_eff | 187.5 L/s |
| 코일 상태 | `100001` (C0 AUTO=1, C5 RUN=1) — ST의 HMI 기본값과 일치 |

### 4-2. 계단 외란 — 실누설 0.05 Pa·m³/s 주입 (기저 스루풋의 +5.00 %)

주입은 HR16 `INJ_QLEAK` (시뮬레이터 전용 레지스터). 샘플 342개, 평균 주기 53 ms.

| 항목 | 실측 | 비고 |
|---|---|---|
| 피크 압력 | 41.300 mTorr (+3.25 %) | |
| 언더슈트 | +0.000 % | 단조 복귀, 진동 없음 |
| **최종 압력** | **40.000 mTorr, 잔류편차 +0.000 %** | 압력에는 정보가 남지 않는다 |
| **밸브각** | **26.766 → 27.540 deg (+2.892 %)** | 여기에 정보가 남는다 |
| S_eff | 187.5 → 196.9 L/s (+5.00 %) | 외란 스루풋 증가분과 정확히 일치 |
| 정정시간 (±0.1 %) | 4.07 s | 예측 4.1 s, 오차 0.7 % |
| 정정시간 (±0.5 %) | 2.47 s | |
| 정정시간 (±1.0 %) | 1.84 s | |

### 4-3. 해석해 대조

정상상태에서 `P = Q / S_eff`, 직렬 컨덕턴스 `1/S_eff = 1/C + 1/S_pump`, 나비형 밸브 `C(θ) = C_max(1 − cos θ)`.

상수: `S_pump = 1.500 m³/s` (통상범위, DRIE용 TMP 1000~2000 L/s), `C_max = 2.000 m³/s` (가정치, 시험대 설정), `P = 40 mTorr = 5.3329 Pa`.

| Q [Pa·m³/s] | S_eff [L/s] | C [L/s] | θ 해석해 [deg] |
|---|---|---|---|
| 1.00 (기저) | 187.5 | 214.3 | 26.7668 |
| 1.05 (누설 후) | 196.9 | 226.6 | 27.5411 |

해석 예측 변화 **+2.893 %**, HIL 실측 **+2.890 %**. 절대각 오차 **0.00 %** (27.5411 vs 27.540).

즉 트윈의 밸브각은 임의로 만든 값이 아니라 진공 정상상태 방정식이 강제하는 값이며, 실제 PLC의 PI 제어기가 독립적으로 그 값에 수렴했다.

## 5. 과정에서 잡은 문제

| # | 문제 | 원인 | 조치 |
|---|---|---|---|
| 1 | Editor Connect 실패 | IP 칸에 `https://localhost:8444` 입력. Editor 내부가 `https://{입력값}:8443` 으로 조립해 URL이 깨짐 | 호스트명만 (`localhost`) 입력 |
| 2 | Connect 실패 (계속) | `RUNTIME_API_PORT = 8443` 이 `app.asar` 에 **하드코딩**. 컨테이너는 8444 매핑 | 컨테이너를 `-p 8443:8443` 으로 재생성 |
| 3 | 자체서명 인증서 의심 | — (원인 아님) | `rejectUnauthorized` 가 환경변수 미설정 시 `false`. 검증하지 않음 |
| 4 | Remote Devices 화면 무반응 | GUI 렌더링 문제 (capability `modbusTcpRemote` 는 true) | `project.json` 의 `data.remoteDevices` 에 직접 기록. 재시작 후 GUI가 정상 표시되었고, Editor가 저장 시 `chamber_apc/devices/remote/chamber_twin.json` 으로 정규화해 옮겼다 — 이쪽이 정본이다 |
| 5 | 적분 5배 과대 | Task 기본 `T#20ms` 인데 ST는 `SCAN_S := 0.1` 하드코딩 → 실효 KI=2.00, 오버슈트 36.71 %, 교차 117회 | Task를 `T#100ms` 로 변경 |

## 6. 한계

- 트윈은 실제 챔버가 아니다. `C_max = 2.000 m³/s` 는 **가정치**이고, 이 값이 바뀌면 밸브각 절대값이 바뀐다. 다만 §4-3 의 검증은 "PLC가 물리식이 요구하는 각도에 수렴하는가"를 보는 것이므로 가정치 여부와 무관하게 성립한다.
- 측정 잡음은 게이지 양자화 모델(상대 0.25 %)만 반영했다. 실장비의 드리프트·온도의존성은 없다.
- SCADA(HMI) 계층은 아직 붙이지 않았다. 현재 HMI 변수는 ST 안의 기본값으로 고정돼 있다.
- 단일 운전점 진단에서는 TMP 열화와 밸브 마모가 분리되지 않는다. 다중 운전점 스윕으로 0.5 % 오차까지 분리되며, 이는 아직 Python 쪽에만 구현돼 있고 PLC 로직에는 없다.

## 7. 재현 방법

```bash
# 1) 런타임 (8443 이어야 함 — Editor가 이 포트를 하드코딩)
docker run -d --name openplc-twin -p 8443:8443 -p 5502:502 \
  --add-host=host.docker.internal:host-gateway \
  ghcr.io/autonomy-logic/openplc-runtime:latest

# 2) 계정 생성 (v4 는 웹 UI 없이 API 전용)
curl -sk -X POST https://localhost:8443/api/create-user \
  -H 'Content-Type: application/json' \
  -d '{"name":"twin","username":"twin","email":"twin@local","password":"twin1234"}'

# 3) 트윈 기동
python3 -m plc.modbus_server

# 4) Editor: chamber_apc 열기 → Device/Configuration →
#    Device "OpenPLC Runtime v4", IP Address "localhost" → Connect
#    → ⬇ Clean build and upload
```

---

## 쉬운 요약

챔버 압력을 일정하게 지켜주는 진짜 PLC를 도커 안에 띄우고, 우리가 만든 가짜 챔버(트윈)와 100분의 1초 단위로 대화하게 붙였다.

챔버에 구멍이 난 것처럼 가스를 5 % 더 새게 만들었더니, PLC가 밸브를 26.77도에서 27.54도로 열어서 4초 만에 압력을 원래대로 되돌렸다. 압력은 완전히 제자리로 돌아와서 아무 흔적이 없는데, **밸브 각도에는 흔적이 남았다.**

그 27.54도가 얼마인지 손으로 계산해봤더니 27.5411도였다. 소수점 셋째 자리까지 맞았다.

그러니까 "고장을 보려면 압력이 아니라 밸브 각도를 봐야 한다"는 이 프로젝트의 결론이, 시뮬레이션이 아니라 진짜 PLC 위에서 그대로 재현된 것이다.
