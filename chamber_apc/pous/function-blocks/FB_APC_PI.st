FUNCTION_BLOCK FB_APC_PI
  VAR_INPUT
    PV : REAL;
    SP : REAL;
    KP : REAL;
    KI : REAL;
    DT : REAL;
    ENABLE : BOOL;
    MAN_CMD : REAL;
    AUTO : BOOL;
  END_VAR
  VAR_OUTPUT
    CMD : REAL;
    SAT_HI : BOOL;
    SAT_LO : BOOL;
    ERR : REAL;
  END_VAR
  VAR
    integ : REAL := 0.0;
    raw : REAL;
    KAW : REAL := 20.0;
    TH_MIN : REAL := 0.0;
    TH_MAX : REAL := 90.0;
  END_VAR

ERR := PV - SP;

IF AUTO THEN
    raw := KP * ERR + integ;
    CMD := LIMIT(TH_MIN, raw, TH_MAX);
    IF ENABLE THEN
        integ := integ + (KI * ERR + KAW * (CMD - raw)) * DT;
    END_IF;
    SAT_HI := (raw >= TH_MAX);
    SAT_LO := (raw <= TH_MIN);
ELSE
    CMD := LIMIT(TH_MIN, MAN_CMD, TH_MAX);
    integ := CMD;
    SAT_HI := FALSE;
    SAT_LO := FALSE;
END_IF;

END_FUNCTION_BLOCK