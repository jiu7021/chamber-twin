# Phase 0 — 데이터 실사 보고서

데이터 출처: Zenodo DOI 10.5281/zenodo.17122442, "A Multi-Model Dataset for BOSCH Plasma-Etching", CC BY 4.0
(Sayyed, Seifert, Zieger, Schwarzenberg, Deshmukh, Haase, Langer — Chemnitz University of Technology / Fraunhofer ENAS)

다운로드 파일(합계 9.9 MB, `scripts/download.sh` 참조): Readme.pdf, Dictionary_process.nc, Process_data.nc,
Lot_status.xlsx, Si_Oxide_etch_89_points.csv, Si_Oxide_etch_9_points.csv, Wafer_layout.pdf.
OES 스펙트럼(Day_*.nc, Dictionary_OES.nc)은 지침에 따라 다운로드하지 않았다.

## 1. 실험 설계 (Readme.pdf 요약)

- 장비: SPTS Omega i2L DSi Rapier. BOSCH 공정 = SF6(에칭) / C4F8(패시베이션) 교대.
- 사이클: 1초 점화 + 100사이클 × (SF6 4.5초 + C4F8 1.5초).
- 웨이퍼: 200 mm Si, ⟨100⟩, 89개 1 mm² 정사각형 노출 영역 + 1 µm SiO2 마스크.
- 로트 구조: 2단계 클리닝(O2 → O2/SF6) → 30분 더미런 → 컨디셔닝(1/3/9회, 대상: 척/Si웨이퍼/SiO2웨이퍼) → 웨이퍼 10장 연속 처리(클리닝 없음, 웨이퍼 간 1분 휴지).
- 로트 7은 장비 고장으로 마지막 4장 웨이퍼 데이터 없음 → 6장만 존재.
- 측정은 2회: 실험 당일 9점 측정, 2025년 2월 89점 재측정(89점이 더 완전함).

## 2. Process_data.nc / Dictionary_process.nc 구조

`Process_data.nc`는 웨이퍼별 NetCDF 그룹(`Day_YYYY_MM_DD_Wafer_NN`)으로 구성되며, 각 그룹은
`times`(float64, 초 단위 Unix epoch), `feature`(문자열 배열, 변수명), `data`(uint16, 16비트 딕셔너리 인덱스)를 가진다.
실제 값은 `Dictionary_process.nc`의 `data`(float32, shape (49290,)) 룩업테이블을 `data[encoded]`로 디코딩해야 얻어진다.

- 그룹(웨이퍼) 수: **96개** = 9일 × 10장 + 2024-08-05(로트7) × 6장. Lot_status.xlsx의 총계(96)와 일치.
- 샘플링 주기: dt 중앙값 0.2 s → **5.0 Hz** (Readme 기재값과 일치).
- 웨이퍼 1개당 시계열 길이: 3193~3835 샘플 (지속시간 638.4~766.8 s). 100사이클×6초+점화1초=601초 기준과 정합적(전후 여유 포함).
- **변수 개수가 그룹마다 다르다** (Readme의 "31종" 기재와 불일치, 반드시 알아둘 것):
  - 86개 그룹(2024-07-05 이후 9일): **31개 변수**
  - 10개 그룹(2024-07-02, 첫날만): **44개 변수** (31개 + Gas6Flow, Heater5~8Temp, ThermoCouple1~4Temp, SourceRF/SourceRF2 LoadCapacitor, attenuatorRatio, moriOuterCurrent 추가)
  - 첫날에만 있는 13개 채널은 전부 분산 0(상수, 대부분 0.0 또는 1.0) → 실질 정보 없음. Phase 1에서는 **31개 공통 변수만** 사용.

전체 변수 목록·min/max/mean/std는 [`reports/phase0_feature_stats.csv`](phase0_feature_stats.csv) 참조(96개 그룹 전체 집계).
그룹별 메타데이터(day, wafer, 샘플수, 지속시간)는 [`reports/phase0_group_meta.csv`](phase0_group_meta.csv) 참조.

### 압력 채널 (3개, 전체 96그룹 존재)
| 변수 | min | max | mean | std | 단위(미확인) |
|---|---|---|---|---|---|
| Stat3_Etch_MV_Pressure | 0.0006 | 0.0804 | 0.0405 | 0.0093 | 확인 필요 — 값 범위상 Torr일 가능성 (등가 0.6~80.4 mTorr, DRIE 챔버압 통상범위와 정합) |
| Stat3_Etch_MV_ForeLinePressure | 19.53 | 159.31 | 127.03 | 35.38 | 확인 필요 |
| Stat3_Etch_MV_HeliumBPPressure | -0.004 | 15.00 | 14.36 | 2.98 | 확인 필요 (배면 He 압력, 음수는 센서 오프셋으로 추정) |

**단위는 스펙시트 없이 추정 금지 — Phase 1 진입 전 반드시 확인/사용자 확인 필요 (아래 5절 참조).**

### 가스 유량 채널 (Gas1~8Flow, 전체 96그룹 존재, 종류 라벨 없음)
| 변수 | min | max | mean | std | 비고 |
|---|---|---|---|---|---|
| Gas1Flow | 0 | 200.0 | 7.28 | 35.0 | 짧은 초기 펄스 후 낮은 값 drift. 정체 불명 |
| Gas2Flow | 3.27 | 4.82 | 4.10 | 0.17 | 저분산, 상시 소량 흐름(퍼지/He일 가능성) |
| Gas3Flow | 0 | 0 | 0 | 0 | 미사용(상수 0) |
| Gas4Flow | 0 | 300.05 | 71.07 | 121.65 | **주기적 구형파, 짧은 ON구간(~1.5s)** |
| Gas5Flow | 0 | 600.05 | 405.85 | 271.50 | **주기적 구형파, 긴 ON구간(~4.4s), Gas4와 상보적** |
| Gas6Flow | 0 | 0 | 0 | 0 | 미사용(첫날 그룹에만 존재, 상수 0) |
| Gas7Flow | 1.70 | 2.24 | 2.06 | 0.07 | 저분산, 상시 소량 흐름 |
| Gas8Flow | 0 | 0 | 0 | 0 | 미사용(상수 0) |

Gas4/Gas5의 시계열을 0.2 s 해상도로 직접 확인한 결과(2024-07-05_Wafer_02, t=20~60 s 구간):
Gas5는 ON~4.4 s / OFF~1.2~1.4 s로 반복, Gas4는 정확히 Gas5가 OFF인 구간에 ON(상보적 구형파).
Readme의 SF6 4.5 s / C4F8 1.5 s duty와 지속시간이 정합적이며, 유량 크기(SF6가 C4F8보다 큰 것이 통상적 BOSCH 레시피 특성)와도 부합한다.
→ **Gas5Flow = SF6 후보, Gas4Flow = C4F8 후보로 추정(가정치, 미확정)**. 밸브 라벨이나 스펙시트로 교차 확인 전에는 확정하지 않는다.

### 근-제로 분산 채널 (96그룹 기준 std < 1e-6)
Gas3Flow, Gas8Flow, SourceRF2LoadPower, SourceRF2ReflectedPower (전체 96그룹) /
Gas6Flow, Heater5~8Temp, SourceRF2LoadCapacitor, SourceRFLoadCapacitor, ThermoCouple1~4Temp, attenuatorRatio, moriOuterCurrent (첫날 10그룹에만 존재, 전부 상수)
→ 이 레시피에서는 실질 정보가 없는 채널. 모델링에서 제외 후보.

## 3. Si_Oxide_etch CSV 구조

| 파일 | shape | 고유 웨이퍼 수 | 컬럼 |
|---|---|---|---|
| Si_Oxide_etch_9_points.csv | 684×11 | 76 | experiment_key, lot_number, wafer_number, loc_id, X, Y, preox_thickness, postox_thickness, stepheight, oxide_etch, si_etch |
| Si_Oxide_etch_89_points.csv | 7832×11 | **88** | experiment_key, lot_number, wafer_number, X, Y, preox_thickness, postox_thickness, postox_thickness_nan, stepheight, oxide_etch, si_etch |

- `experiment_key` = `YYYY-MM-DD_WW` (날짜_웨이퍼번호, 2자리 zero-padded). Process_data.nc의 `Day_YYYY_MM_DD_Wafer_WW` 그룹명과 1:1 매핑 가능.
- 값 단위는 Readme 명시: 전부 µm.
- 89점 CSV의 88개 experiment_key는 Process_data.nc의 96개 그룹 중 8개(2024-07-02_07, 2024-08-21_09, 2024-08-22_05~10)를 제외한 정확히 88개와 **완전히 일치**(교차검증 완료). 이 8개는 측정 데이터가 없어 제외된 것으로 보인다(원인 미확인, Phase 1 진입에는 영향 없음).

## 4. Lot_status.xlsx — 로트/웨이퍼/순번 매핑

단일 시트(Tabelle1), 10개 로트:

| Lot | 날짜 | 웨이퍼 수 | 측정 | 컨디셔닝 Type |
|---|---|---|---|---|
| 1 | 2024-07-02 | 10 | 89&9점 | 3C |
| 2 | 2024-07-05 | 10 | 89&9점 | 1C |
| 3 | 2024-07-09 | 10 | 89&9점 | 9C |
| 4 | 2024-07-11 | 10 | 89&9점 | 3C-Si |
| 5 | 2024-07-19 | 10 | 89&9점 | 1C-Si |
| 6 | 2024-08-01 | 10 | 89&9점 | 9C-Si |
| 7 | 2024-08-05 | **6** | 89&9점 | 3C-SiO2 |
| 8 | 2024-08-07 | 10 | 89점만 | 3C-SiO2 |
| 9 | 2024-08-21 | 10 | 89&9점 | 3C |
| 10 | 2024-08-22 | 10 | 89점만 | 3C-SiO2 |

합계 96장(파일 내 명시값과 일치). 하단에 89점 측정 중 FRT 보간 NaN 개수 표(로트/웨이퍼/na_count)가 별도로 포함되어 있음 — Phase 1에서 데이터 품질 가중치로 활용 가능.

## 5. Phase 0 게이트 판정

| 조건 | 결과 |
|---|---|
| (a) 챔버 압력 채널 존재 | **충족** — Stat3_Etch_MV_Pressure 외 2종, 전체 96그룹에 5 Hz 연속 시계열로 존재 |
| (b) 가스 유량(SF6, C4F8) 채널 존재 | **조건부 충족** — Gas4Flow/Gas5Flow가 레시피 duty(4.5 s/1.5 s)와 정합하는 상보적 구형파로 존재. 다만 채널명에 가스 종류 라벨이 없어 SF6/C4F8 대응은 추정(가정치)이며 Phase 1에서 확정 필요 |
| (c) 압력·유량이 88장 전체에 시계열로 존재 | **충족** — 89점 CSV 기준 88개 experiment_key 전부 Process_data.nc에 대응 그룹 존재, 압력·가스 채널 결측 없음 |

**분기 결과: 셋 다 충족(조건 (b)는 각서 조건부) → Phase 1 진행 가능.**

## 6. Phase 1 진입 전 미해결 사항 (반드시 확인)

1. **압력 채널 단위 미확인.** Pressure/ForeLinePressure/HeliumBPPressure의 실제 단위(Torr/mTorr/Pa 등)가 메타데이터에 없다. 스펙시트(SPTS Omega i2L DSi Rapier 게이지 사양) 확인 또는 사용자 확인 필요. 값 범위만으로 Torr로 "추정"할 수는 있으나 CLAUDE.md 규칙상 출처 없이 단정하지 않는다.
2. **가스 채널 종류 라벨 미확인.** Gas1~8Flow 중 어느 것이 SF6/C4F8/O2/N2인지 장비 벤더 문서나 실험자 확인 없이는 채널명만으로 확정할 수 없다. Gas5=SF6, Gas4=C4F8 추정은 duty cycle 정합성에 근거한 가정치이며 민감도 분석(반대로 가정 시 결론이 바뀌는지) 필요.
3. **유량 단위 미확인.** sccm으로 보이나(값 스케일 100~600) 확정 아님.
4. Gas1Flow, Gas2Flow, Gas7Flow의 물리적 역할(He 백사이드? 퍼지? 레퍼런스?) 불명 — 배기속도 역산 모델에 포함할지 여부는 Phase 1에서 결정.
5. 첫날(2024-07-02, 10그룹)만 변수 44개인 이유 불명(장비 설정 변경 추정) — Phase 1 파이프라인은 공통 31개 변수만 사용.

보고 및 정지: Phase 0 게이트 통과, 위 미해결 사항 확인 후 Phase 1 착수 요청.

---

## 쉬운 요약

독일 대학이 공개한 반도체 식각 장비 데이터를 받아서 무엇이 들어 있는지 확인했다.
웨이퍼 96장에 대해 1초에 5번씩 31개 센서값이 기록돼 있었고, 웨이퍼를 얼마나 깎았는지 잰 결과도 88장분 있었다.
필요한 압력과 가스 유량이 다 들어 있어서 다음 단계로 갈 수 있다고 판단했다.
다만 압력의 단위(Torr인지 mbar인지)와 어느 가스가 어느 채널인지는 문서에 없어서 확정하지 못했다.
