#!/usr/bin/env python3
"""Ignition 태그 프로비저닝.

Ignition 8.1 은 태그 설정을 내부 SQLite (`data/db/config.idb`) 의 TAGCONFIG 테이블에
JSON 으로 보관한다. Designer 로 하나씩 만드는 대신 이 스크립트로 일괄 생성한다.

주소 계약은 `plc/scada_map.md` 이고, OPC 항목 경로 형식은
`ns=1;s=[<디바이스>]<UnitID>.<접두사><주소>` 이다 (Modbus Driver v2).
접두사: C=코일, DI=디스크리트입력, HR=보유레지스터(부호 있는 Int16), IR=입력레지스터.

반드시 **게이트웨이를 정지한 상태**에서 실행할 것. 구동 중에 쓰면 메모리 상태와
어긋나고 저장 시 덮어쓰기된다.

    docker stop ignition81
    python3 scada/provision_tags.py --idb <config.idb 경로>
    docker start ignition81
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import uuid

DEVICE = "chamber_plc"
UNIT = 1
FOLDER = "Chamber"
OPC_SERVER = "Ignition OPC UA Server"
HISTORY_PROVIDER = "NewConnection"   # 기존 MariaDB 히스토리 프로바이더


def opc(addr: str) -> str:
    """Modbus 주소를 OPC 항목 경로로."""
    return f"ns=1;s=[{DEVICE}]{UNIT}.{addr}"


# (이름, Modbus 주소, 자료형, 설명)  — 주소 근거는 plc/scada_map.md
READ_TAGS = [
    ("PRESSURE_RAW", "HR120", "Int2", "챔버 압력 [mTorr x100]"),
    ("VALVE_RAW",    "HR121", "Int2", "밸브 각도 [deg x100]"),
    ("SEFF_RAW",     "HR122", "Int2", "유효 배기속도 [L/s x10]"),
    ("VDRIFT_RAW",   "HR123", "Int2", "밸브각 편차 [% x100] — 주 진단 지표"),
    ("QLEAK_RAW",    "HR124", "Int2", "RoR 추정 실누설 [Pa*m3/s x1e6], -1 = 미측정"),
    ("Q1_RAW",       "HR125", "Int2", "RoR 추정 아웃가싱 q1 [Pa*m3/s x1e6], -1 = 미측정"),
    ("ROR_STATE",    "HR126", "Int2", "RoR 시퀀스 0 대기 /1 요청 /2 진행 /3 완료"),
]

WRITE_TAGS = [
    ("SP_RAW",        "HR110", "Int2",    "압력 설정값 [mTorr x100]"),
    ("MFC_RAW",       "HR111", "Int2",    "MFC 유량 지령 [Pa*m3/s x10000]"),
    ("MAN_VALVE_RAW", "HR112", "Int2",    "수동 밸브각 지령 [deg x100]"),
    ("CMD_AUTO",      "C880",  "Boolean", "1 = APC 자동, 0 = 수동"),
    ("CMD_RUN",       "C881",  "Boolean", "1 = 공정 운전"),
    ("CMD_ROR",       "C882",  "Boolean", "RoR 시퀀스 요청 (상승엣지)"),
    ("CMD_ALM_RESET", "C883",  "Boolean", "래치 알람 해제 (상승엣지)"),
]

# (이름, 주소, 알람 우선순위 또는 None, 설명)
ALARM_TAGS = [
    ("ALM_P_HIGH",      "C960", None,       "압력 상한"),
    ("ALM_P_LOW",       "C961", None,       "압력 하한"),
    ("ALM_VALVE_DRIFT", "C962", "High",     "밸브각 드리프트 — 배기계 열화"),
    ("ALM_REAL_LEAK",   "C963", "Critical", "실누설"),
    ("ALM_OUTGAS",      "C964", "Medium",   "아웃가싱"),
    ("ILK_GAS_BLOCK",   "C965", None,       "인터록 — 가스 차단"),
    ("ILK_VALVE_SAT",   "C966", None,       "인터록 — 밸브 포화"),
]

# 엔지니어링 단위 — 스케일링 OPC 태그.
# Ignition 의 Linear 스케일링은 쓰기 시 역변환도 적용하므로, 설정값을 4000 이 아니라
# 40.00 으로 입력할 수 있다. 배율 근거는 plc/scada_map.md 의 배율 열.
# (이름, 주소, raw 하한, raw 상한, scaled 하한, scaled 상한, 히스토리, 설명)
SCALED_TAGS = [
    ("Pressure_mTorr",  "HR120",      0, 10000,    0.0,  100.0, True,  "챔버 압력 [mTorr]"),
    ("Valve_deg",       "HR121",      0,  9000,    0.0,   90.0, True,  "밸브 각도 [deg]"),
    ("Seff_Lps",        "HR122",      0, 10000,    0.0, 1000.0, False, "유효 배기속도 [L/s]"),
    ("ValveDrift_pct",  "HR123", -10000, 10000, -100.0,  100.0, True,  "밸브각 편차 [%] — 주 진단 지표"),
    ("Setpoint_mTorr",  "HR110",      0, 10000,    0.0,  100.0, False, "압력 설정값 [mTorr] — 쓰기 가능"),
]

# 표현식 태그 — -1 이 '미측정' 마커라 선형 스케일링이 부적절한 것만 남긴다.
EXPR_TAGS = [
    ("Qleak_Pam3s", "{[.]QLEAK_RAW} / 1000000.0", "RoR 추정 실누설 [Pa*m3/s], 음수 = 미측정"),
]



def build_rows() -> list[tuple]:
    """(ID, PROVIDERID, FOLDERID, CFG, RANK, NAME) 행 목록을 만든다."""
    folder_id = str(uuid.uuid4())
    rows: list[tuple] = [
        (folder_id, 0, None, json.dumps({"name": FOLDER, "tagType": "Folder"}), 1, FOLDER)
    ]

    def add(name: str, cfg: dict) -> None:
        rows.append((str(uuid.uuid4()), 0, folder_id, json.dumps(cfg, ensure_ascii=False), 1, name))

    for name, addr, dtype, doc in READ_TAGS + WRITE_TAGS:
        add(name, {
            "name": name, "tagType": "AtomicTag", "valueSource": "opc",
            "dataType": dtype, "opcServer": OPC_SERVER, "opcItemPath": opc(addr),
            "documentation": doc,
        })

    for name, addr, prio, doc in ALARM_TAGS:
        cfg = {
            "name": name, "tagType": "AtomicTag", "valueSource": "opc",
            "dataType": "Boolean", "opcServer": OPC_SERVER, "opcItemPath": opc(addr),
            "documentation": doc,
        }
        if prio:
            cfg["alarms"] = [{"name": name, "setpointA": 1.0, "priority": prio}]
        add(name, cfg)

    for name, addr, rl, rh, sl, sh, hist, doc in SCALED_TAGS:
        cfg = {
            "name": name, "tagType": "AtomicTag", "valueSource": "opc",
            "dataType": "Float8", "opcServer": OPC_SERVER, "opcItemPath": opc(addr),
            "scaleMode": "Linear", "rawLow": rl, "rawHigh": rh,
            "scaledLow": sl, "scaledHigh": sh, "clampMode": "None",
            "documentation": doc,
        }
        if hist:
            cfg["historyEnabled"] = True
            cfg["historyProvider"] = HISTORY_PROVIDER
        add(name, cfg)

    for name, expr, doc in EXPR_TAGS:
        add(name, {
            "name": name, "tagType": "AtomicTag", "valueSource": "expr",
            "dataType": "Float8", "expression": expr, "documentation": doc,
        })

    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--idb", required=True, help="config.idb 경로")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--replace", action="store_true", help="기존 Chamber 폴더를 지우고 다시 만든다")
    args = ap.parse_args()

    rows = build_rows()
    con = sqlite3.connect(args.idb)
    cur = con.cursor()

    # 루트에 같은 이름이 있어도 무방하다. 겹치면 안 되는 것은 Chamber 폴더 자체와
    # 그 안의 태그들이므로, 루트 폴더 이름만 검사한다.
    old = list(cur.execute(
        "select ID from TAGCONFIG where PROVIDERID=0 and FOLDERID is null and NAME=?", (FOLDER,)))
    if old:
        if not args.replace:
            print(f"'{FOLDER}' 폴더가 이미 있다 — --replace 를 주거나 먼저 지울 것")
            con.close()
            raise SystemExit(1)
        fid = old[0][0]
        n = cur.execute("select count(*) from TAGCONFIG where FOLDERID=?", (fid,)).fetchone()[0]
        if not args.dry_run:
            cur.execute("delete from TAGCONFIG where FOLDERID=?", (fid,))
            cur.execute("delete from TAGCONFIG where ID=?", (fid,))
        print(f"기존 '{FOLDER}' 폴더와 태그 {n}개 삭제")

    print(f"삽입 대상 {len(rows)}행 (폴더 1 + 태그 {len(rows)-1})")
    for r in rows:
        cfg = json.loads(r[3])
        print(f"  {r[5]:<16} {cfg.get('opcItemPath') or cfg.get('expression') or cfg['tagType']}")

    if args.dry_run:
        con.close()
        return

    cur.executemany(
        "insert into TAGCONFIG (ID, PROVIDERID, FOLDERID, CFG, RANK, NAME) values (?,?,?,?,?,?)",
        rows)
    con.commit()
    print(f"\n완료. TAGCONFIG 총 {cur.execute('select count(*) from TAGCONFIG').fetchone()[0]}행")
    con.close()


if __name__ == "__main__":
    main()
