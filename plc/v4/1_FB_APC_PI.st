(* ═══════════════════════════════════════════════════════════════════
   POU 1 / 3   이름: FB_APC_PI      종류: Function Block      언어: ST
   ───────────────────────────────────────────────────────────────────
   Editor 에서:  Function Blocks 우클릭 → 새 POU → 이름 FB_APC_PI, 언어 ST
                 아래 VAR 블록은 변수 테이블에, 그 아래 본문은 코드 영역에 넣는다.
   ═══════════════════════════════════════════════════════════════════

   압력 PI 제어기. 조작변수는 스로틀 밸브 각도다.
   오차 e = PV − SP 가 양이면(압력이 높으면) 밸브를 더 열어 배기를 늘린다.
   포화 시에는 되계산(back-calculation)으로 적분을 되끌어온다 — 조건분기식
   와인드업 방지는 미분에 계단 불연속을 만들어 적분기를 불안정하게 한다.

   이득 KP=0.20, KI=0.40 은 plc/hil_check.py 로 검증한 값이다.
   루프 지연 300 ms 가 챔버 시정수 0.267 s 와 맞먹어, 이득을 키우면 진동한다.
     KP 0.40 / KI 1.60  → 위상여유 +20.0°, 오버슈트 +22.94 %, 설정값 교차 138회  (부적합)
     KP 0.20 / KI 0.40  → 위상여유 +83.3°, 오버슈트  +7.14 %, 교차 1회          (채택)
*)

VAR_INPUT
    PV       : REAL;   (* 측정 압력 [mTorr] *)
    SP       : REAL;   (* 설정 압력 [mTorr] *)
    KP       : REAL;   (* 비례이득 [deg/mTorr] *)
    KI       : REAL;   (* 적분이득 [deg/(mTorr*s)] *)
    DT       : REAL;   (* 스캔 주기 [s] *)
    ENABLE   : BOOL;   (* FALSE 면 적분 정지 *)
    MAN_CMD  : REAL;   (* 수동 각도 지령 [deg] *)
    AUTO     : BOOL;   (* TRUE = 자동 *)
END_VAR

VAR_OUTPUT
    CMD      : REAL;   (* 밸브 각도 지령 [deg] *)
    SAT_HI   : BOOL;
    SAT_LO   : BOOL;
    ERR      : REAL;
END_VAR

VAR
    integ    : REAL := 0.0;
    raw      : REAL;
    KAW      : REAL := 20.0;   (* 되계산 이득 [1/s] = 1/tau_valve, tau_valve = 0.05 s *)
    TH_MIN   : REAL := 0.0;
    TH_MAX   : REAL := 90.0;
END_VAR

(* ─── 본문 ─────────────────────────────────────────────────────── *)

ERR := PV - SP;

IF AUTO THEN
    raw := KP * ERR + integ;
    CMD := LIMIT(TH_MIN, raw, TH_MAX);

    IF ENABLE THEN
        (* dI/dt = Ki*e + Kaw*(CMD_sat − CMD_raw) — 연속이라 점프 불연속이 없다 *)
        integ := integ + (KI * ERR + KAW * (CMD - raw)) * DT;
    END_IF;

    SAT_HI := (raw >= TH_MAX);
    SAT_LO := (raw <= TH_MIN);
ELSE
    CMD    := LIMIT(TH_MIN, MAN_CMD, TH_MAX);
    integ  := CMD;                  (* 무충격 절체 — 수동값으로 적분항을 맞춘다 *)
    SAT_HI := FALSE;
    SAT_LO := FALSE;
END_IF;
