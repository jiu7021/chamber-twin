# SCADA ↔ PLC Modbus 맵 (2계층)

이 문서는 **SCADA(Ignition) ↔ PLC(OpenPLC Runtime v4)** 링크의 계약이다.
PLC ↔ 챔버 트윈 링크는 별도 문서 `plc/modbus_map.md` 이다. **둘은 다른 링크이고 주소도 다르다.**

```
Ignition ──Modbus TCP──▶ OpenPLC 슬레이브 (컨테이너 502, 호스트 5502)
OpenPLC 마스터 ──Modbus TCP──▶ 챔버 트윈 (호스트 5020)
```

## 왜 `%M` 이 아니라 `%Q` 를 쓰는가

IEC 61131-3 관례대로라면 HMI 인터페이스는 메모리 영역 `%MW`/`%MX` 가 맞다.
그러나 **OpenPLC Editor 의 변수 테이블 파서가 `%M` 을 받지 않는다** — 주소 정규식이
`/^%[IQ]W(\d+)$/`, `/^%[IQ]X(\d+)\.(\d+)$/` 로 `I`/`Q` 만 허용한다
(`app.asar`, `WORD_ADDRESS_REGEX` / `BIT_ADDRESS_REGEX`).
`%M` 으로 선언하면 해당 변수들이 조용히 버려지고 본문에서 "Undeclared variable" 로 터진다.
STruC++ 컴파일러 자체는 `%[IQM]` 을 모두 받으므로 이건 Editor 쪽 제약이다.

따라서 HMI 영역을 `%QW110~112`, `%QX110.x`(지령) / `%QW120~126`, `%QX120.x`(감시) 로 옮겼다.
`%Q` 는 Modbus 슬레이브에서 보유 레지스터·코일로 노출되고 쓰기도 가능하므로 기능상 동일하다.

같은 이유로 위치 지정 변수의 선언부 초기값도 신뢰하지 않는다. `main.st` 본문 선두의
**첫 스캔 초기화 블록**에서 `HMI_SP`/`HMI_AUTO`/`HMI_RUN` 등을 명시적으로 세운다.

## 버퍼 배치

OpenPLC Runtime v4 의 Modbus 슬레이브는 IEC 주소 영역을 **이어붙여** Modbus 주소로 만든다
(`core/src/drivers/plugins/python/modbus_slave/simple_modbus.py:586,449`).

| Modbus 영역 | 배치 | 설정 (`chamber_apc/devices/servers/scada.json`) |
|---|---|---|
| Holding Register | `[%QW][%MW][%MD][%ML]` | qw 128, mw 0 → **%QW n = HR n** |
| Coil | `[%QX][%MX]` | qx 1024, mx 0 → **%QX a.b = Coil (8a+b)** |
| Discrete Input | `[%IX]` | ix 1024 → %IX a.b = DI (8a+b) |
| Input Register | `[%IW]` | iw 128 → %IW n = IR n |

## SCADA 쓰기 — 지령

| Modbus | IEC | ST 변수 | 단위·배율 | 초기값 |
|---|---|---|---|---|
| HR 110 | `%QW110` | `HMI_SP` | mTorr ×100 | 4000 (40.00) |
| HR 111 | `%QW111` | `HMI_MFC` | Pa·m³/s ×10000 | 10000 (1.0) |
| HR 112 | `%QW112` | `HMI_MAN_VALVE` | deg ×100 | 2677 (26.77) |
| Coil 880 | `%QX110.0` | `HMI_AUTO` | 1=자동, 0=수동 | TRUE |
| Coil 881 | `%QX110.1` | `HMI_RUN` | 1=공정 운전 | TRUE |
| Coil 882 | `%QX110.2` | `HMI_ROR_REQ` | RoR 시퀀스 요청 (상승엣지) | FALSE |
| Coil 883 | `%QX110.3` | `HMI_ALM_RESET` | 래치 알람 해제 | FALSE |

## SCADA 읽기 — 감시

| Modbus | IEC | 내용 | 단위·배율 |
|---|---|---|---|
| HR 120 | `%QW120` | 챔버 압력 | mTorr ×100 |
| HR 121 | `%QW121` | 밸브 각도 | deg ×100 |
| HR 122 | `%QW122` | 유효 배기속도 S_eff | L/s ×10 |
| **HR 123** | `%QW123` | **밸브각 편차** (기준 26.77 deg 대비) | % ×100 |
| HR 124 | `%QW124` | RoR 추정 실누설 | Pa·m³/s ×1e6 |
| HR 125 | `%QW125` | RoR 추정 아웃가싱 q₁ | Pa·m³/s ×1e6 |
| HR 126 | `%QW126` | RoR 시퀀스 상태 | 0 대기 / 1 요청 / 2 진행 / 3 완료 |
| Coil 960 | `%QX120.0` | 알람 — 압력 상한 | |
| Coil 961 | `%QX120.1` | 알람 — 압력 하한 | |
| **Coil 962** | `%QX120.2` | **알람 — 밸브각 드리프트** | |
| Coil 963 | `%QX120.3` | 알람 — 실누설 | |
| Coil 964 | `%QX120.4` | 알람 — 아웃가싱 | |
| Coil 965 | `%QX120.5` | 인터록 — 가스 차단 | |
| Coil 966 | `%QX120.6` | 인터록 — 밸브 포화 | |

**HR 123(밸브각 편차)이 이 시스템의 주 진단 지표다.** 실측에서 챔버 압력의 변동계수는 0.027 % 로
사실상 상수이므로 압력 트렌드에는 정보가 없다. 배기계 열화는 밸브 각도에만 나타난다.

## 참고 — PLC 가 트윈과 주고받는 원시값

| Modbus | IEC | 내용 |
|---|---|---|
| HR 100 | `%QW100` | 트윈으로 내려간 압력 설정값 |
| HR 101 | `%QW101` | 트윈으로 내려간 MFC 지령 |
| HR 102 | `%QW102` | **트윈으로 내려간 밸브 각도 지령** |
| Coil 800 | `%QX100.0` | 트윈 APC 자동 |
| Coil 801 | `%QX100.1` | 트윈 게이트 폐쇄 |
| Coil 802 | `%QX100.2` | 트윈 RoR 시작 |
| Coil 805 | `%QX100.5` | 트윈 공정 운전 |
| IR 100~105, 111~113 | `%IW100~` | 트윈에서 올라온 원시값 (`modbus_map.md` §2 와 동일 순서) |
| DI 804, 805 | `%IX100.4/.5` | RoR 진행중 / 완료 |

## Ignition 디바이스 설정

| 항목 | 값 |
|---|---|
| Driver | Modbus TCP |
| Hostname | `host.docker.internal` |
| Port | `5502` (컨테이너 502 의 호스트 매핑) |
| Unit ID | `1` |
| **Zero-Based Addressing** | **체크** — 체크하지 않으면 위 주소가 전부 1 씩 어긋난다 |
