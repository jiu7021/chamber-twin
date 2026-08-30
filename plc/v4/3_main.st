(* ═══════════════════════════════════════════════════════════════════
   POU 3 / 3   이름: main           종류: Program             언어: ST
   ───────────────────────────────────────────────────────────────────
   이미 만들어져 있는 main 을 그대로 쓴다.
   변수 테이블(위쪽)에 아래 VAR 들을 넣고, 본문(아래쪽)에 코드를 넣는다.

   ★ 위치(Location) 가 있는 변수는 변수 테이블의 Location 칸에 주소를 적는다.
     그 주소가 plc/modbus_master.json 의 iec_location 과 짝을 이룬다.
   ★ 자료형을 WORD 가 아니라 INT 로 쓴다 — WORD_TO_REAL 이 없을 수 있어서,
     INT_TO_REAL 로 안전하게 간다. 실제 값(압력 4000, 밸브각 2677 등)은
     전부 32767 아래라 INT 로 충분하다.
   ═══════════════════════════════════════════════════════════════════ *)

(* ─── 입력: 트윈 → PLC  (Location 칸에 적을 것) ──────────────────── *)
VAR
    IW_PRESS     AT %IW100 : INT;    (* IR0  챔버 압력      mTorr x100 *)
    IW_FORELINE  AT %IW101 : INT;    (* IR1  포어라인 압력   mTorr x10  *)
    IW_VALVE     AT %IW102 : INT;    (* IR2  밸브 각도      deg   x100 *)
    IW_OPEN      AT %IW103 : INT;    (* IR3  개방률         %     x100 *)
    IW_SEFF      AT %IW104 : INT;    (* IR4  S_eff          L/s   x10  *)
    IW_QTOTAL    AT %IW105 : INT;    (* IR5  총 스루풋       x10000    *)
    IW_EST_QLEAK AT %IW111 : INT;    (* IR11 RoR 추정 누설   x1e6      *)
    IW_EST_Q1    AT %IW112 : INT;    (* IR12 RoR 추정 q1     x1e6      *)
    IW_EST_ALPHA AT %IW113 : INT;    (* IR13 RoR 추정 alpha  x1000     *)

    IX_ROR_RUN   AT %IX100.4 : BOOL; (* DI4  RoR 진행중 *)
    IX_ROR_DONE  AT %IX100.5 : BOOL; (* DI5  RoR 완료   *)
END_VAR

(* ─── 출력: PLC → 트윈 ─────────────────────────────────────────── *)
VAR
    QW_SP         AT %QW100 : INT;    (* HR0 압력 설정값   mTorr x100 *)
    QW_MFC        AT %QW101 : INT;    (* HR1 MFC 유량 지령 x10000    *)
    QW_VALVE_CMD  AT %QW102 : INT;    (* HR2 밸브 각도 지령 deg x100  *)

    QX_AUTO       AT %QX100.0 : BOOL; (* C0 APC 자동 *)
    QX_GATE_CLOSE AT %QX100.1 : BOOL; (* C1 게이트 폐쇄 *)
    QX_ROR_START  AT %QX100.2 : BOOL; (* C2 RoR 시작 *)
    QX_PROC_RUN   AT %QX100.5 : BOOL; (* C5 공정 운전 *)
END_VAR

(* ─── HMI (SCADA 가 읽고 쓴다. Location 없이 그냥 변수로 둬도 된다) ── *)
VAR
    HMI_AUTO      : BOOL := TRUE;
    HMI_RUN       : BOOL := TRUE;
    HMI_ROR_REQ   : BOOL;
    HMI_ALM_RESET : BOOL;
    HMI_SP        : INT := 4000;      (* 40.00 mTorr *)
    HMI_MFC       : INT := 10000;     (* 1.0 Pa*m3/s *)
    HMI_MAN_VALVE : INT := 2677;      (* 26.77 deg *)

    ALM_P_HIGH      : BOOL;
    ALM_P_LOW       : BOOL;
    ALM_VALVE_DRIFT : BOOL;
    ALM_REAL_LEAK   : BOOL;
    ALM_OUTGAS      : BOOL;
    ILK_GAS_BLOCK   : BOOL;
    ILK_VALVE_SAT   : BOOL;
END_VAR

(* ─── 내부 ─────────────────────────────────────────────────────── *)
VAR
    pv_mtorr    : REAL;
    sp_mtorr    : REAL;
    valve_deg   : REAL;
    est_qleak   : REAL;
    est_q1      : REAL;

    apc      : FB_APC_PI;
    a_phi    : FB_ALARM;
    a_plo    : FB_ALARM;
    a_vdrift : FB_ALARM;
    a_leak   : FB_ALARM;
    a_og     : FB_ALARM;

    ror_state    : INT := 0;      (* 0 대기 / 1 요청 / 2 진행 / 3 완료 *)
    ror_req_trig : R_TRIG;
    ror_timeout  : TON;

    SCAN_S          : REAL := 0.1;     (* 스캔 주기 [s] — Task 설정과 맞출 것 *)
    VALVE_BASE      : REAL := 26.77;   (* 기준 밸브각 [deg]. 티칭으로 갱신 *)
    SP_HI_PCT       : REAL := 10.0;
    SP_LO_PCT       : REAL := 10.0;
    VALVE_DRIFT_PCT : REAL := 1.5;     (* 계측 분해능 0.34 % 의 약 4.4 sigma *)
    QLEAK_HI        : REAL := 0.005;   (* [Pa*m3/s] *)
END_VAR

(* ═══ 본문 ═══════════════════════════════════════════════════════ *)

(* --- 입력 스케일 해제 --- *)
pv_mtorr  := INT_TO_REAL(IW_PRESS) / 100.0;
valve_deg := INT_TO_REAL(IW_VALVE) / 100.0;
est_qleak := INT_TO_REAL(IW_EST_QLEAK) / 1000000.0;
est_q1    := INT_TO_REAL(IW_EST_Q1) / 1000000.0;
sp_mtorr  := INT_TO_REAL(HMI_SP) / 100.0;
IF sp_mtorr <= 0.0 THEN
    sp_mtorr := 40.0;
END_IF;

(* --- RoR 시퀀스 상태기계 --- *)
ror_req_trig(CLK := HMI_ROR_REQ);

IF ror_state = 0 THEN                      (* 대기 *)
    QX_ROR_START := FALSE;
    IF ror_req_trig.Q AND NOT HMI_RUN THEN (* 인터록: 공정 정지 상태에서만 허용 *)
        ror_state := 1;
    END_IF;
ELSIF ror_state = 1 THEN                   (* 요청 *)
    QX_ROR_START := TRUE;
    IF IX_ROR_RUN THEN
        QX_ROR_START := FALSE;
        ror_state := 2;
    END_IF;
ELSIF ror_state = 2 THEN                   (* 진행 중 *)
    IF IX_ROR_DONE THEN
        ror_state := 3;
    END_IF;
ELSIF ror_state = 3 THEN                   (* 완료 *)
    IF NOT HMI_ROR_REQ THEN
        ror_state := 0;
    END_IF;
END_IF;

ror_timeout(IN := (ror_state = 1) OR (ror_state = 2), PT := T#300s);
IF ror_timeout.Q THEN
    ror_state := 0;
END_IF;

(* --- APC PI 제어 --- *)
apc(PV      := pv_mtorr,
    SP      := sp_mtorr,
    KP      := 0.20,
    KI      := 0.40,
    DT      := SCAN_S,
    ENABLE  := HMI_RUN AND NOT IX_ROR_RUN,
    MAN_CMD := INT_TO_REAL(HMI_MAN_VALVE) / 100.0,
    AUTO    := HMI_AUTO);

(* --- 인터록 (래치 없음, 즉시 동작) --- *)
QX_GATE_CLOSE := (ror_state = 1) OR (ror_state = 2);
ILK_GAS_BLOCK := QX_GATE_CLOSE OR IX_ROR_RUN;
ILK_VALVE_SAT := apc.SAT_HI AND HMI_RUN AND HMI_AUTO;

(* --- 출력 --- *)
QX_AUTO      := HMI_AUTO;
QX_PROC_RUN  := HMI_RUN AND NOT ILK_GAS_BLOCK;
QW_SP        := HMI_SP;
QW_MFC       := HMI_MFC;
QW_VALVE_CMD := REAL_TO_INT(apc.CMD * 100.0);

(* --- 알람 --- *)
a_phi(TRIP  := (pv_mtorr > sp_mtorr * (1.0 + SP_HI_PCT / 100.0)) AND HMI_RUN,
      RESET := HMI_ALM_RESET,
      DELAY_N := 5);

a_plo(TRIP  := (pv_mtorr < sp_mtorr * (1.0 - SP_LO_PCT / 100.0)) AND HMI_RUN
               AND NOT IX_ROR_RUN,
      RESET := HMI_ALM_RESET,
      DELAY_N := 5);

(* 주 진단 알람 — 압력이 아니라 밸브 각도를 본다.
   실측에서 압력 변동계수가 0.027 % 였으므로 압력 알람은 사실상 울리지 않는다. *)
a_vdrift(TRIP := (valve_deg > VALVE_BASE * (1.0 + VALVE_DRIFT_PCT / 100.0))
                 AND HMI_RUN AND HMI_AUTO,
         RESET := HMI_ALM_RESET,
         DELAY_N := 20);

a_leak(TRIP := (ror_state = 3) AND (est_qleak > QLEAK_HI)
               AND (est_q1 <= 0.5 * est_qleak),
       RESET := HMI_ALM_RESET,
       DELAY_N := 1);

a_og(TRIP := (ror_state = 3) AND (est_q1 > 0.0) AND (est_q1 > 0.5 * est_qleak),
     RESET := HMI_ALM_RESET,
     DELAY_N := 1);

ALM_P_HIGH      := a_phi.ALM;
ALM_P_LOW       := a_plo.ALM;
ALM_VALVE_DRIFT := a_vdrift.ALM;
ALM_REAL_LEAK   := a_leak.ALM;
ALM_OUTGAS      := a_og.ALM;
