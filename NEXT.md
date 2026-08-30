# 다음에 이어갈 지점 (2026-08-31 중단)

## 지금 상태

```
Ignition (SCADA)  ──▶  OpenPLC Runtime v4 (PLC)  ──▶  챔버 트윈 (플랜트)
   태그 28개 완료          슬레이브 502 / 마스터        modbus_server.py :5020
   화면 미작성             호스트 5502                   PID 확인 필요
```

| 구성요소 | 상태 |
|---|---|
| 챔버 트윈 | `python3 -m plc.modbus_server` — 호스트 5020 |
| OpenPLC 런타임 | 컨테이너 `openplc-twin`, 8443(Editor) / 5502(SCADA용 슬레이브) |
| OpenPLC 계정 | `twin` / `twin1234` |
| Ignition | 컨테이너 `ignition81`, 8088. **정지된 상태로 두었음** |
| Ignition 디바이스 | `chamber_plc` → host.docker.internal:5502, zero-based 체크됨 |
| Ignition 태그 | `Chamber` 폴더에 28개 생성 완료 (`scada/provision_tags.py`) |

## 재개 순서

```bash
# 1) 컨테이너
/Applications/Docker.app/Contents/Resources/bin/docker start ignition81
/Applications/Docker.app/Contents/Resources/bin/docker start openplc-twin   # 꺼져 있으면

# 2) 트윈
python3 -m plc.modbus_server
```

**3) OpenPLC Editor 에서 Clean build and upload 를 아직 안 했다면 반드시 할 것.**
`main.st` 에 기동 시 오알람 억제 패치(`startup_dly` / `link_ok`)가 들어갔는데
런타임에는 아직 안 올라갔을 수 있다.

**4) Ignition 태그가 살아있는지 확인** — 8088 로그인 → Status → Tags,
또는 Designer 에서 `[default]Chamber/Pressure_mTorr` 값이 40.00 근처인지 본다.
품질이 Bad 면 OPC 항목 경로 형식(`ns=1;s=[chamber_plc]1.HR120`)부터 의심한다.

## 남은 작업

1. **Perspective 화면** (`data/projects/<이름>/com.inductiveautomation.perspective/views/.../view.json`)
   - 주 트렌드는 압력이 아니라 **밸브각 편차** (`Chamber/ValveDrift_pct`)
   - 압력·밸브각 트렌드, 설정값 입력(`SP_RAW`, ×100 변환), 자동/수동 토글(`CMD_AUTO`),
     운전/정지(`CMD_RUN`), 알람 램프 7개, 알람 리셋 버튼(`CMD_ALM_RESET`)
   - 기존 `pump_scada` 프로젝트 구조를 본뜨면 된다 (평범한 JSON)
2. 화면 완성 후 `reports/phase5_scada.md` 작성 (끝에 쉬운 요약 3~4줄)
3. 웹 시뮬레이터에 다중 운전점 진단 노출 (현재 Python 전용)
4. 미확인 상수 2건 검증 — Knudsen 2.507/3.095, 아웃가싱 α

## 주의 (이번에 데인 것)

- **OpenPLC Editor 가 켜져 있으면 `.st` 파일을 직접 고치지 말 것.**
  Editor 는 프로젝트를 **열 때만** VAR 블록을 파싱하고, 이후 빌드·저장 시
  메모리의 변수 테이블로 파일을 덮어쓴다. 순서는 반드시
  `Editor 완전 종료(⌘Q, Don't Save) → 파일 수정 → Editor 실행 → 빌드`.
  창만 닫으면 앱이 살아있다. `pgrep -f "OpenPLC Editor"` 로 확인할 것.
- **Editor 변수 테이블은 `%M` 을 받지 않는다** (`%[IQ]` 만). HMI 영역이 `%QW`/`%QX` 인 이유.
- **Editor 는 런타임 포트 8443 을 하드코딩**한다. IP 칸에는 호스트명만 넣는다.
- Ignition 태그를 스크립트로 넣을 때는 **게이트웨이를 정지**하고 할 것.
  백업은 `config.idb.bak` 로 남긴다.
