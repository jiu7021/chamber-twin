PROGRAM main
  VAR
    IW_PRESS : INT AT %IW100;
    IW_FORELINE : INT AT %IW101;
    IW_VALVE : INT AT %IW102;
    IW_OPEN : INT AT %IW103;
    IW_SEFF : INT AT %IW104;
    IW_QTOTAL : INT AT %IW105;
    IW_EST_QLEAK : INT AT %IW111;
    IW_EST_Q1 : INT AT %IW112;
    IW_EST_ALPHA : INT AT %IW113;
    IX_ROR_RUN : BOOL AT %IX100.4;
    IX_ROR_DONE : BOOL AT %IX100.5;
    QW_SP : INT AT %QW100;
    QW_MFC : INT AT %QW101;
    QW_VALVE_CMD : INT AT %QW102;
    QX_AUTO : BOOL AT %QX100.0;
    QX_GATE_CLOSE : BOOL AT %QX100.1;
    QX_ROR_START : BOOL AT %QX100.2;
    QX_PROC_RUN : BOOL AT %QX100.5;
    HMI_AUTO : BOOL := TRUE;
    HMI_RUN : BOOL := TRUE;
    HMI_ROR_REQ : BOOL;
    HMI_ALM_RESET : BOOL;
    HMI_SP : INT := 4000;
    HMI_MFC : INT := 10000;
    HMI_MAN_VALVE : INT := 2677;
    ALM_P_HIGH : BOOL;
    ALM_P_LOW : BOOL;
    ALM_VALVE_DRIFT : BOOL;
    ALM_REAL_LEAK : BOOL;
    ALM_OUTGAS : BOOL;
    ILK_GAS_BLOCK : BOOL;
    ILK_VALVE_SAT : BOOL;
    pv_mtorr : REAL;
    sp_mtorr : REAL;
    valve_deg : REAL;
    est_qleak : REAL;
    est_q1 : REAL;
    apc : FB_APC_PI;
    a_phi : FB_ALARM;
    a_plo : FB_ALARM;
    a_vdrift : FB_ALARM;
    a_leak : FB_ALARM;
    a_og : FB_ALARM;
    ror_state : INT := 0;
    ror_req_trig : R_TRIG;
    ror_timeout : TON;
    SCAN_S : REAL := 0.1;
    VALVE_BASE : REAL := 26.77;
    SP_HI_PCT : REAL := 10.0;
    SP_LO_PCT : REAL := 10.0;
    VALVE_DRIFT_PCT : REAL := 1.5;
    QLEAK_HI : REAL := 0.005;
  END_VAR

pv_mtorr := INT_TO_REAL(IW_PRESS) / 100.0;
valve_deg := INT_TO_REAL(IW_VALVE) / 100.0;
est_qleak := INT_TO_REAL(IW_EST_QLEAK) / 1000000.0;
est_q1 := INT_TO_REAL(IW_EST_Q1) / 1000000.0;
sp_mtorr := INT_TO_REAL(HMI_SP) / 100.0;
IF sp_mtorr <= 0.0 THEN
    sp_mtorr := 40.0;
END_IF;

ror_req_trig(CLK := HMI_ROR_REQ);

IF ror_state = 0 THEN
    QX_ROR_START := FALSE;
    IF ror_req_trig.Q AND NOT HMI_RUN THEN
        ror_state := 1;
    END_IF;
ELSIF ror_state = 1 THEN
    QX_ROR_START := TRUE;
    IF IX_ROR_RUN THEN
        QX_ROR_START := FALSE;
        ror_state := 2;
    END_IF;
ELSIF ror_state = 2 THEN
    IF IX_ROR_DONE THEN
        ror_state := 3;
    END_IF;
ELSIF ror_state = 3 THEN
    IF NOT HMI_ROR_REQ THEN
        ror_state := 0;
    END_IF;
END_IF;

ror_timeout(IN := (ror_state = 1) OR (ror_state = 2), PT := T#300s);
IF ror_timeout.Q THEN
    ror_state := 0;
END_IF;

apc(PV := pv_mtorr,
    SP := sp_mtorr,
    KP := 0.20,
    KI := 0.40,
    DT := SCAN_S,
    ENABLE := HMI_RUN AND NOT IX_ROR_RUN,
    MAN_CMD := INT_TO_REAL(HMI_MAN_VALVE) / 100.0,
    AUTO := HMI_AUTO);

QX_GATE_CLOSE := (ror_state = 1) OR (ror_state = 2);
ILK_GAS_BLOCK := QX_GATE_CLOSE OR IX_ROR_RUN;
ILK_VALVE_SAT := apc.SAT_HI AND HMI_RUN AND HMI_AUTO;

QX_AUTO := HMI_AUTO;
QX_PROC_RUN := HMI_RUN AND NOT ILK_GAS_BLOCK;
QW_SP := HMI_SP;
QW_MFC := HMI_MFC;
QW_VALVE_CMD := REAL_TO_INT(apc.CMD * 100.0);

a_phi(TRIP := (pv_mtorr > sp_mtorr * (1.0 + SP_HI_PCT / 100.0)) AND HMI_RUN,
      RESET := HMI_ALM_RESET,
      DELAY_N := 5);

a_plo(TRIP := (pv_mtorr < sp_mtorr * (1.0 - SP_LO_PCT / 100.0)) AND HMI_RUN AND NOT IX_ROR_RUN,
      RESET := HMI_ALM_RESET,
      DELAY_N := 5);

a_vdrift(TRIP := (valve_deg > VALVE_BASE * (1.0 + VALVE_DRIFT_PCT / 100.0)) AND HMI_RUN AND HMI_AUTO,
         RESET := HMI_ALM_RESET,
         DELAY_N := 20);

a_leak(TRIP := (ror_state = 3) AND (est_qleak > QLEAK_HI) AND (est_q1 <= 0.5 * est_qleak),
       RESET := HMI_ALM_RESET,
       DELAY_N := 1);

a_og(TRIP := (ror_state = 3) AND (est_q1 > 0.0) AND (est_q1 > 0.5 * est_qleak),
     RESET := HMI_ALM_RESET,
     DELAY_N := 1);

ALM_P_HIGH := a_phi.ALM;
ALM_P_LOW := a_plo.ALM;
ALM_VALVE_DRIFT := a_vdrift.ALM;
ALM_REAL_LEAK := a_leak.ALM;
ALM_OUTGAS := a_og.ALM;

END_PROGRAM