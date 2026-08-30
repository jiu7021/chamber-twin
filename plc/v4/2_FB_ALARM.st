(* ═══════════════════════════════════════════════════════════════════
   POU 2 / 3   이름: FB_ALARM       종류: Function Block      언어: ST
   ───────────────────────────────────────────────────────────────────
   래치형 알람. TRIP 이 DELAY_N 스캔 연속 지속되면 래치되고,
   RESET 상승엣지에서만 해제된다(채터링 방지).
   ═══════════════════════════════════════════════════════════════════ *)

VAR_INPUT
    TRIP     : BOOL;
    RESET    : BOOL;
    DELAY_N  : INT := 5;   (* 트립까지 필요한 연속 스캔 수 *)
END_VAR

VAR_OUTPUT
    ALM      : BOOL;       (* 래치된 알람 *)
    ACTIVE   : BOOL;       (* 래치 없는 현재 상태 *)
END_VAR

VAR
    cnt      : INT := 0;
    rtrig    : R_TRIG;
END_VAR

(* ─── 본문 ─────────────────────────────────────────────────────── *)

ACTIVE := TRIP;

IF TRIP THEN
    IF cnt < DELAY_N THEN
        cnt := cnt + 1;
    END_IF;
ELSE
    cnt := 0;
END_IF;

IF cnt >= DELAY_N THEN
    ALM := TRUE;
END_IF;

rtrig(CLK := RESET);
IF rtrig.Q AND NOT TRIP THEN
    ALM := FALSE;
    cnt := 0;
END_IF;
