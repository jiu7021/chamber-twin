(*
   식각 챔버 진공 제어 — OpenPLC (IEC 61131-3 Structured Text)

   구성: Hardware-in-the-Loop
       이 PLC 프로그램이 제어기, plc/modbus_server.py 가 플랜트(챔버 물리)다.
       OpenPLC 를 Modbus 마스터로 두고 트윈(슬레이브, 포트 5020)을 폴링한다.

   담당 기능
       1. APC 압력제어 PI 루프 (되계산 와인드업 방지)  → 밸브 각도 지령 출력
       2. 알람 처리 (압력 상하한, 밸브각 드리프트, 누설/아웃가싱)
       3. 인터록 (게이트 폐쇄 중 가스 차단, 밸브 포화 지속)
       4. Rate-of-Rise 진단 시퀀스 상태기계

   설계 근거
       실측 96 웨이퍼 분석 결과 챔버 압력은 APC 로 설정값에 고정되어(변동계수 0.027 %)
       고장 정보를 담지 않는다. 정보는 **밸브 각도**(조작변수)에 실린다.
       따라서 주 진단 알람은 압력이 아니라 ALM_VALVE_DRIFT 다.

   스케일 규약은 plc/modbus_map.md §1 을 따른다.
   내부 계산은 REAL 공학단위(mTorr, deg)로 하고, I/O 경계에서만 정수 배율을 적용한다.
*)

(* ================================================================= 상수 *)
VAR_GLOBAL CONSTANT
    K_P100      : REAL := 100.0;   (* 압력 배율   mTorr x100 *)
    K_DEG100    : REAL := 100.0;   (* 각도 배율   deg   x100 *)
    K_Q1E6      : REAL := 1000000.0;
    K_1E3       : REAL := 1000.0;
    THETA_MAX   : REAL := 90.0;    (* 밸브 최대 각도 [deg] *)
    THETA_MIN   : REAL := 0.0;
    SCAN_S      : REAL := 0.1;     (* 스캔 주기 [s] — OpenPLC 설정과 일치시킬 것 *)
END_VAR

(* ================================================================= PI 제어기 *)
FUNCTION_BLOCK FB_APC_PI
(*
   압력 PI 제어기. 조작변수는 스로틀 밸브 각도다.

   오차 e = PV - SP 가 양이면(압력이 높으면) 밸브를 더 열어 배기를 늘린다.
   포화 시에는 되계산(back-calculation)으로 적분을 되끌어온다.
   조건분기식 와인드업 방지는 미분에 계단 불연속을 만들어 적분기를 불안정하게 하므로 쓰지 않는다.
*)
VAR_INPUT
    PV       : REAL;    (* 측정 압력 [mTorr] *)
    SP       : REAL;    (* 설정 압력 [mTorr] *)
    KP       : REAL;    (* 비례이득 [deg/mTorr] *)
    KI       : REAL;    (* 적분이득 [deg/(mTorr*s)] *)
    DT       : REAL;    (* 스캔 주기 [s] *)
    ENABLE   : BOOL;    (* FALSE 면 적분 정지, 출력 유지 *)
    MAN_CMD  : REAL;    (* 수동 각도 지령 [deg] *)
    AUTO     : BOOL;    (* TRUE = 자동 *)
END_VAR
VAR_OUTPUT
    CMD      : REAL;    (* 밸브 각도 지령 [deg] *)
    SAT_HI   : BOOL;
    SAT_LO   : BOOL;
    ERR      : REAL;
END_VAR
VAR
    integ    : REAL := 0.0;
    raw      : REAL;
    kaw      : REAL := 20.0;   (* 되계산 이득 [1/s] = 1/tau_valve, tau_valve = 0.05 s *)
    initd    : BOOL := FALSE;
END_VAR

IF NOT AUTO THEN
    CMD    := LIMIT(THETA_MIN, MAN_CMD, THETA_MAX);
    integ  := CMD;                       (* 무충격 절체 — 수동값으로 적분항을 맞춘다 *)
    ERR    := PV - SP;
    SAT_HI := FALSE;
    SAT_LO := FALSE;
    RETURN;
END_IF;

ERR := PV - SP;
raw := KP * ERR + integ;
CMD := LIMIT(THETA_MIN, raw, THETA_MAX);

IF ENABLE THEN
    (* dI/dt = Ki*e + Kaw*(CMD_sat - CMD_raw)  — 연속이므로 불연속 점프가 없다 *)
    integ := integ + (KI * ERR + kaw * (CMD - raw)) * DT;
END_IF;

SAT_HI := (raw >= THETA_MAX);
SAT_LO := (raw <= THETA_MIN);
END_FUNCTION_BLOCK

(* ================================================================= 알람 처리 *)
FUNCTION_BLOCK FB_ALARM
(*
   래치형 알람. TRIP 이 서면 래치되고 RESET 상승엣지에서만 해제된다.
   DELAY 스캔 동안 지속되어야 트립한다(채터링 방지).
*)
VAR_INPUT
    TRIP     : BOOL;
    RESET    : BOOL;
    DELAY_N  : INT := 5;    (* 연속 스캔 수 *)
END_VAR
VAR_OUTPUT
    ALM      : BOOL;
    ACTIVE   : BOOL;        (* 래치 없는 현재 상태 *)
END_VAR
VAR
    cnt      : INT := 0;
    rtrig    : R_TRIG;
END_VAR

ACTIVE := TRIP;
IF TRIP THEN
    IF cnt < DELAY_N THEN cnt := cnt + 1; END_IF;
ELSE
    cnt := 0;
END_IF;

IF cnt >= DELAY_N THEN ALM := TRUE; END_IF;

rtrig(CLK := RESET);
IF rtrig.Q AND NOT TRIP THEN
    ALM := FALSE;
    cnt := 0;
END_IF;
END_FUNCTION_BLOCK

(* ================================================================= 메인 *)
PROGRAM MAIN
VAR
    (* ---- 입력: 트윈 Input Register (OpenPLC Modbus 마스터가 %IW 로 매핑) ---- *)
    IW_PRESS      AT %IW100 : WORD;   (* IR0  챔버 압력      mTorr x100 *)
    IW_FORELINE   AT %IW101 : WORD;   (* IR1  포어라인 압력   mTorr x10  *)
    IW_VALVE      AT %IW102 : WORD;   (* IR2  밸브 각도      deg   x100 *)
    IW_OPEN       AT %IW103 : WORD;   (* IR3  개방률         %     x100 *)
    IW_SEFF       AT %IW104 : WORD;   (* IR4  S_eff          L/s   x10  *)
    IW_QTOTAL     AT %IW105 : WORD;   (* IR5  총 스루풋       x10000    *)
    IW_EST_QLEAK  AT %IW111 : WORD;   (* IR11 RoR 추정 누설   x1e6      *)
    IW_EST_Q1     AT %IW112 : WORD;   (* IR12 RoR 추정 q1     x1e6      *)
    IW_EST_ALPHA  AT %IW113 : WORD;   (* IR13 RoR 추정 alpha  x1000     *)

    (* ---- 입력: 트윈 Discrete Input ---- *)
    IX_ROR_RUN    AT %IX100.4 : BOOL; (* DI4  RoR 진행중 *)
    IX_ROR_DONE   AT %IX100.5 : BOOL; (* DI5  RoR 완료   *)

    (* ---- 출력: 트윈 Holding Register ---- *)
    QW_SP         AT %QW100 : WORD;   (* HR0 압력 설정값   mTorr x100 *)
    QW_MFC        AT %QW101 : WORD;   (* HR1 MFC 유량 지령 x10000    *)
    QW_VALVE_CMD  AT %QW102 : WORD;   (* HR2 밸브 각도 지령 deg x100  *)

    (* ---- 출력: 트윈 Coil ---- *)
    QX_AUTO       AT %QX100.0 : BOOL; (* C0 APC 자동 *)
    QX_GATE_CLOSE AT %QX100.1 : BOOL; (* C1 게이트 폐쇄 *)
    QX_ROR_START  AT %QX100.2 : BOOL; (* C2 RoR 시작 *)
    QX_PROC_RUN   AT %QX100.5 : BOOL; (* C5 공정 운전 *)

    (* ---- SCADA 인터페이스 (OpenPLC 내장 슬레이브, 포트 502) ---- *)
    HMI_AUTO      AT %QX0.0 : BOOL;   (* 자동/수동 선택 *)
    HMI_RUN       AT %QX0.1 : BOOL;   (* 공정 운전 지령 *)
    HMI_ROR_REQ   AT %QX0.2 : BOOL;   (* RoR 시퀀스 요청 *)
    HMI_ALM_RESET AT %QX0.3 : BOOL;   (* 알람 리셋 *)
    HMI_SP        AT %QW0   : WORD;   (* 압력 설정값 mTorr x100 *)
    HMI_MFC       AT %QW1   : WORD;   (* MFC 지령 x10000 *)
    HMI_MAN_VALVE AT %QW2   : WORD;   (* 수동 밸브각 deg x100 *)

    ALM_P_HIGH    AT %QX1.0 : BOOL;
    ALM_P_LOW     AT %QX1.1 : BOOL;
    ALM_VALVE_DRIFT AT %QX1.2 : BOOL;
    ALM_REAL_LEAK AT %QX1.3 : BOOL;
    ALM_OUTGAS    AT %QX1.4 : BOOL;
    ILK_GAS_BLOCK AT %QX1.5 : BOOL;
    ILK_VALVE_SAT AT %QX1.6 : BOOL;

    (* ---- 내부 ---- *)
    pv_mtorr      : REAL;
    sp_mtorr      : REAL;
    valve_deg     : REAL;
    valve_base    : REAL := 26.77;   (* 기준 밸브각 [deg] — 정상 운전점. 티칭으로 갱신한다 *)
    est_qleak     : REAL;
    est_q1        : REAL;

    apc           : FB_APC_PI;
    a_phi, a_plo  : FB_ALARM;
    a_vdrift      : FB_ALARM;
    a_leak, a_og  : FB_ALARM;

    (* 알람 임계 *)
    sp_hi_pct     : REAL := 10.0;    (* 설정값 대비 상한 [%] *)
    sp_lo_pct     : REAL := 10.0;
    valve_drift_pct : REAL := 1.5;   (* 기준 대비 밸브각 드리프트 임계 [%]
       근거: 밸브각 계측 분해능이 기준각의 0.34 % 이므로 1.5 % 는 약 4.4 sigma 다.
       검출 범위(시뮬레이션 실측): TMP 80 % 저하 +1.88 %, 70 % +3.27 % → 검출
                                  TMP 90 % +0.81 %, 95 % +0.39 %      → 미검출
                                  밸브마모 95 % +2.65 % 이하 전부       → 검출
       즉 밸브 마모는 초기에, 펌프 저하는 20 % 이상 진행해야 잡힌다. 한계로 문서화한다. *)
    qleak_hi      : REAL := 0.005;   (* [Pa*m3/s] *)

    (* RoR 시퀀스 상태기계 *)
    ror_state     : INT := 0;        (* 0 대기 / 1 요청 / 2 진행 / 3 완료 *)
    ror_req_trig  : R_TRIG;
    ror_timeout   : TON;
END_VAR

(* ---------------- 입력 스케일 해제 ---------------- *)
pv_mtorr  := WORD_TO_REAL(IW_PRESS) / K_P100;
valve_deg := WORD_TO_REAL(IW_VALVE) / K_DEG100;
est_qleak := WORD_TO_REAL(IW_EST_QLEAK) / K_Q1E6;
est_q1    := WORD_TO_REAL(IW_EST_Q1) / K_Q1E6;
sp_mtorr  := WORD_TO_REAL(HMI_SP) / K_P100;
IF sp_mtorr <= 0.0 THEN sp_mtorr := 40.0; END_IF;   (* HMI 미설정 시 기본값 *)

(* ---------------- RoR 시퀀스 상태기계 ---------------- *)
ror_req_trig(CLK := HMI_ROR_REQ);
CASE ror_state OF
    0:  (* 대기 *)
        QX_ROR_START := FALSE;
        IF ror_req_trig.Q AND NOT HMI_RUN THEN     (* 인터록: 공정 정지 상태에서만 허용 *)
            ror_state := 1;
        END_IF;
    1:  (* 요청 — 트윈에 시작 지령 *)
        QX_ROR_START := TRUE;
        IF IX_ROR_RUN THEN
            QX_ROR_START := FALSE;
            ror_state := 2;
        END_IF;
    2:  (* 진행 중 *)
        IF IX_ROR_DONE THEN ror_state := 3; END_IF;
    3:  (* 완료 — HMI 요청이 내려가면 대기로 *)
        IF NOT HMI_ROR_REQ THEN ror_state := 0; END_IF;
END_CASE;
ror_timeout(IN := (ror_state = 1) OR (ror_state = 2), PT := T#300s);
IF ror_timeout.Q THEN ror_state := 0; END_IF;      (* 응답 없으면 복귀 *)

(* ---------------- APC PI 제어 ---------------- *)
(*
   PI 이득 — plc/hil_check.py 로 검증한 값이다.

   루프 지연: Modbus 폴링 200 ms + 스캔 100 ms/2 + 밸브 지연 50 ms = 300 ms.
   챔버 시정수 V/S_eff = 0.267 s 이므로 지연/시정수 = 1.13 이다. 지연이 시정수와 맞먹으므로
   이득을 크게 잡으면 진동한다.

   검증 결과 (초기 28 mTorr -> 설정값 40 mTorr 스텝):
       KP=0.40 KI=1.60 (초기안)  위상여유 +20.0 deg, 오버슈트 +22.94 %, 설정값 교차 138 회  → 부적합
       KP=0.20 KI=0.40 (채택)    위상여유 +83.3 deg, 오버슈트  +7.14 %, 교차 1 회
                                 스텝 정착 1.6 s, 외란(누설) 정착 4.1 s
*)
apc(PV      := pv_mtorr,
    SP      := sp_mtorr,
    KP      := 0.20,      (* [deg/mTorr]     hil_check.py 검증값 *)
    KI      := 0.40,      (* [deg/(mTorr*s)] hil_check.py 검증값 *)
    DT      := SCAN_S,
    ENABLE  := HMI_RUN AND NOT IX_ROR_RUN,
    MAN_CMD := WORD_TO_REAL(HMI_MAN_VALVE) / K_DEG100,
    AUTO    := HMI_AUTO);

(* ---------------- 출력 ---------------- *)
QX_AUTO      := HMI_AUTO;
QX_PROC_RUN  := HMI_RUN AND NOT ILK_GAS_BLOCK;
QW_SP        := HMI_SP;
QW_MFC       := HMI_MFC;
QW_VALVE_CMD := REAL_TO_WORD(apc.CMD * K_DEG100);
QX_GATE_CLOSE := (ror_state = 1) OR (ror_state = 2);

(* ---------------- 알람 ---------------- *)
a_phi(TRIP  := pv_mtorr > sp_mtorr * (1.0 + sp_hi_pct / 100.0) AND HMI_RUN,
      RESET := HMI_ALM_RESET);
a_plo(TRIP  := pv_mtorr < sp_mtorr * (1.0 - sp_lo_pct / 100.0) AND HMI_RUN
               AND NOT IX_ROR_RUN,
      RESET := HMI_ALM_RESET);

(* 주 진단 알람 — 압력이 아니라 밸브 각도를 본다.
   실측에서 압력 변동계수가 0.027 % 였으므로 압력 알람은 사실상 울리지 않는다. *)
a_vdrift(TRIP  := (valve_deg > valve_base * (1.0 + valve_drift_pct / 100.0)) AND HMI_RUN
                  AND HMI_AUTO,
         RESET := HMI_ALM_RESET,
         DELAY_N := 20);

a_leak(TRIP  := (ror_state = 3) AND (est_qleak > qleak_hi) AND (est_q1 <= 0.5 * est_qleak),
       RESET := HMI_ALM_RESET, DELAY_N := 1);
a_og(TRIP    := (ror_state = 3) AND (est_q1 > 0.0) AND (est_q1 > 0.5 * est_qleak),
     RESET   := HMI_ALM_RESET, DELAY_N := 1);

ALM_P_HIGH      := a_phi.ALM;
ALM_P_LOW       := a_plo.ALM;
ALM_VALVE_DRIFT := a_vdrift.ALM;
ALM_REAL_LEAK   := a_leak.ALM;
ALM_OUTGAS      := a_og.ALM;

(* ---------------- 인터록 (래치 없음, 즉시 동작) ---------------- *)
(* 게이트가 닫힌 상태에서 가스를 넣으면 압력이 무한정 상승한다 *)
ILK_GAS_BLOCK := QX_GATE_CLOSE OR IX_ROR_RUN;
(* 밸브가 완전개방에서 지속 포화하면 더 이상 압력을 낮출 수 없다 — PM 요구 신호 *)
ILK_VALVE_SAT := apc.SAT_HI AND HMI_RUN AND HMI_AUTO;
END_PROGRAM

CONFIGURATION Config0
    RESOURCE Res0 ON PLC
        TASK MainTask(INTERVAL := T#100ms, PRIORITY := 0);
        PROGRAM Inst0 WITH MainTask : MAIN;
    END_RESOURCE
END_CONFIGURATION
