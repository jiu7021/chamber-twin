FUNCTION_BLOCK FB_ALARM
VAR_INPUT
    TRIP : BOOL;
    RESET : BOOL;
    DELAY_N : INT := 5;
END_VAR

VAR_OUTPUT
    ALM : BOOL;
    ACTIVE : BOOL;
END_VAR

VAR
    cnt : INT := 0;
    rtrig : R_TRIG;
END_VAR

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

END_FUNCTION_BLOCK