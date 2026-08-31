#!/usr/bin/env python3
"""Perspective 화면(view.json) 생성.

Designer 로 그리는 대신 JSON 을 직접 만든다. 바인딩은 두 종류만 쓴다.
  - tag  (bidirectional=true) : 조작용. 기존 pump_scada 프로젝트에서 동작 확인된 형식.
  - expr                      : 표시용. numberFormat / if 로 서식과 색을 정한다.
태그 경로 근거는 scada/provision_tags.py, 주소 계약은 plc/scada_map.md.

    python3 scada/build_view.py > view.json
"""
import json, sys

T = "[default]Chamber/"
BG, CARD, LINE = "#12151C", "#1B2029", "#2A3140"
FG, MUTED = "#E6EAF2", "#8A93A5"
ACCENT, BLUE = "#F2A33C", "#4C9AFF"
ALM_ON, ALM_OFF = "#E5484D", "#262C38"

kids = []
def C(t, name, x, y, w, h, props=None, pc=None):
    c = {"type": t, "meta": {"name": name},
         "position": {"x": x, "y": y, "width": w, "height": h},
         "props": props or {}}
    if pc: c["propConfig"] = pc
    kids.append(c); return c

def expr(e):   return {"binding": {"type": "expr", "config": {"expression": e}}}
def tag(p, bi=False):
    return {"binding": {"type": "tag", "config": {
        "mode": "direct", "fallbackDelay": 2.5, "tagPath": p, **({"bidirectional": True} if bi else {})}}}

def label(name, x, y, w, h, text=None, size=14, color=FG, weight=400,
          align="left", pc=None, bg=None, extra=None):
    st = {"fontSize": size, "color": color, "fontWeight": weight,
          "textAlign": align, "display": "flex", "alignItems": "center",
          "justifyContent": {"left": "flex-start", "center": "center"}[align]}
    if bg: st["backgroundColor"] = bg
    if extra: st.update(extra)
    return C("ia.display.label", name, x, y, w, h, {"text": text or "", "style": st}, pc)

# ── 머리말 ────────────────────────────────────────────────────────────
label("Title", 20, 14, 1000, 36, "식각 챔버 진공 진단 — APC 스로틀 밸브 감시", 24, FG, 600)
label("Subtitle", 20, 52, 1000, 24,
      "서보 계통에서는 제어변수(압력)가 아니라 조작변수(밸브 각도)가 상태 정보를 갖는다", 13, MUTED)

# ── 상단 카드 4개 ─────────────────────────────────────────────────────
CARDS = [
    ("Pressure", "챔버 압력",      "Pressure_mTorr", "0.00", "mTorr", FG),
    ("Valve",    "밸브 각도",      "Valve_deg",      "0.00", "deg",   FG),
    ("Seff",     "유효 배기속도",  "Seff_Lps",       "0.0",  "L/s",   FG),
    ("Drift",    "밸브각 편차",    "ValveDrift_pct", "+0.00;-0.00", "%", ACCENT),
]
for i, (key, cap, tagname, fmt, unit, col) in enumerate(CARDS):
    x = 20 + i * 340
    border = f"2px solid {ACCENT}" if key == "Drift" else f"1px solid {LINE}"
    label(f"Card_{key}", x, 88, 320, 104, "", bg=CARD,
          extra={"border": border, "borderRadius": "8px"})
    label(f"Cap_{key}", x + 16, 98, 288, 22, cap, 13, MUTED)
    label(f"Val_{key}", x + 16, 120, 288, 46, None, 34, col, 600,
          pc={"props.text": expr(f"numberFormat({{{T}{tagname}}}, '{fmt}')")})
    label(f"Unit_{key}", x + 16, 164, 288, 20, unit, 12, MUTED)
label("DriftNote", 1056, 176, 288, 16, "주 진단 지표", 11, ACCENT)

# ── 공정 미믹 ────────────────────────────────────────────────────────
label("MimicBg", 20, 208, 1000, 330, "", bg=CARD, extra={"border": f"1px solid {LINE}", "borderRadius": "8px"})
label("MimicTitle", 36, 220, 400, 24, "공정 계통", 15, FG, 600)

PIPE = {"backgroundColor": "#3A4356", "borderRadius": "3px"}
def pipe(name, x, y, w):
    label(name, x, y, w, 6, "", extra=PIPE)

# MFC 가스 유입
label("MfcCap", 34, 320, 96, 20, "MFC 가스", 12, MUTED, align="center")
label("MfcVal", 34, 340, 96, 22, None, 13, FG, 500, "center",
      pc={"props.text": expr(f"numberFormat({{{T}MFC_RAW}} / 10000.0, '0.000')")})
label("MfcUnit", 34, 362, 96, 18, "Pa·m³/s", 10, MUTED, align="center")
pipe("Pipe1", 134, 352, 56)
label("Arrow1", 150, 330, 24, 20, "▶", 12, MUTED, align="center")

# 챔버
label("PvOver", 190, 244, 170, 26, None, 17, BLUE, 600, "center",
      pc={"props.text": expr(f"numberFormat({{{T}Pressure_mTorr}}, '0.00') + ' mTorr'")})
C("ia.symbol.vessel", "Chamber", 190, 274, 170, 160,
  {"orientation": "vertical", "displayStand": False, "displayAgitator": False,
   "displayFillLevel": False, "label": {"text": "챔버", "location": "bottom", "justify": "center"}},
  {"props.state": expr(f"if({{{T}ALM_P_HIGH}} || {{{T}ALM_P_LOW}}, 'faulted', 'running')")})

pipe("Pipe2", 364, 352, 62)
label("Arrow2", 382, 330, 24, 20, "▶", 12, MUTED, align="center")

# 스로틀 밸브 (APC 조작변수)
C("ia.symbol.valve", "ThrottleValve", 430, 300, 108, 108,
  {"label": {"text": "스로틀 밸브 (APC)", "location": "bottom", "justify": "center"},
   "value": {"text": ""}},
  {"props.state": expr(f"if({{{T}ALM_VALVE_DRIFT}}, 'faulted', if({{{T}CMD_AUTO}}, 'running', 'default'))")})
label("ValveOver", 400, 268, 170, 26, None, 17, ACCENT, 600, "center",
      pc={"props.text": expr(f"numberFormat({{{T}Valve_deg}}, '0.00') + '°'")})
label("ValveDriftOver", 400, 444, 170, 22, None, 12, ACCENT, 500, "center",
      pc={"props.text": expr(f"'편차 ' + numberFormat({{{T}ValveDrift_pct}}, '+0.00;-0.00') + ' %'")})

pipe("Pipe3", 542, 352, 62)
label("Arrow3", 560, 330, 24, 20, "▶", 12, MUTED, align="center")

# 터보분자펌프
C("ia.symbol.pump", "TMP", 608, 296, 118, 118,
  {"variant": "vacuum", "orientation": "horizontal", "feet": True,
   "label": {"text": "TMP", "location": "bottom", "justify": "center"}},
  {"props.state": expr(f"if({{{T}CMD_RUN}}, 'running', 'stopped')")})
label("SeffOver", 590, 444, 156, 22, None, 12, MUTED, 500, "center",
      pc={"props.text": expr(f"'S_eff ' + numberFormat({{{T}Seff_Lps}}, '0.0') + ' L/s'")})

pipe("Pipe4", 730, 352, 86)
label("Arrow4", 760, 330, 24, 20, "▶", 12, MUTED, align="center")
label("ForelineCap", 820, 330, 160, 20, "포어라인 → 배기", 12, MUTED)
label("MimicNote", 36, 496, 950, 20,
      "APC 는 압력을 일정하게 유지하려고 밸브 각도를 바꾼다. 배기계가 나빠지면 압력이 아니라 각도가 움직인다.",
      11, MUTED)

# ── 제어 패널 ─────────────────────────────────────────────────────────
PX = 1040
label("CtrlBg", PX, 208, 330, 330, "", bg=CARD, extra={"border": f"1px solid {LINE}", "borderRadius": "8px"})
label("CtrlTitle", PX + 16, 218, 298, 22, "제어", 15, FG, 600)

label("SpCap", PX + 16, 246, 298, 18, "압력 설정값 [mTorr]", 12, MUTED)
C("ia.input.numeric-entry-field", "SetpointInput", PX + 16, 266, 298, 38,
  {"style": {"fontSize": 18}},
  {"props.value": tag(T + "Setpoint_mTorr", bi=True)})

TOGGLES = [
    ("Auto",  "APC 자동 / 수동",                  "CMD_AUTO",      314),
    ("Run",   "공정 운전 / 정지",                 "CMD_RUN",       360),
    ("Ror",   "RoR 시퀀스 요청 (올렸다 내리기)",  "CMD_ROR",       406),
    ("Reset", "알람 리셋 (올렸다 내리기)",        "CMD_ALM_RESET", 452),
]
for name, cap, tg, y in TOGGLES:
    label(f"Cap_{name}", PX + 16, y, 210, 34, cap, 12, FG)
    C("ia.input.toggle-switch", f"Tgl_{name}", PX + 240, y + 4, 74, 26, {},
      {"props.selected": tag(T + tg, bi=True)})

label("RorState", PX + 16, 500, 298, 22, None, 12, MUTED,
      pc={"props.text": expr(
          "'RoR 상태: ' + case({%sROR_STATE}, 0,'대기', 1,'요청', 2,'진행', 3,'완료', '?')" % T)})

# ── 트렌드 ────────────────────────────────────────────────────────────
label("ChartBg", 20, 556, 1350, 340, "", bg=CARD, extra={"border": f"1px solid {LINE}", "borderRadius": "8px"})
C("ia.chart.powerchart", "Trend", 28, 564, 1334, 324, {
    "config": {"mode": "realtime", "refreshRate": 1000, "pointCount": 300,
               "unitOfTime": 10, "measureOfTime": "minutes",
               "tagBrowserStartPath": "histprov:NewConnection:/tag:Chamber",
               "penNamePathDepth": 1},
    "title": {"text": "압력 vs 밸브각 편차 — 압력은 평탄, 편차만 움직인다"},
    "pens": [
        {"name": "압력 [mTorr]", "visible": True, "enabled": True, "selectable": True,
         "plot": 0, "display": {"stroke": {"color": BLUE, "width": 2}},
         "data": {"source": "histprov:NewConnection:/tag:Chamber/Pressure_mTorr",
                  "aggregateMode": "MinMax"}},
        {"name": "밸브각 편차 [%]", "visible": True, "enabled": True, "selectable": True,
         "plot": 1, "display": {"stroke": {"color": ACCENT, "width": 2}},
         "data": {"source": "histprov:NewConnection:/tag:Chamber/ValveDrift_pct",
                  "aggregateMode": "MinMax"}},
    ],
    "plots": [{"height": 1}, {"height": 1}],
})

# ── 알람 램프 ─────────────────────────────────────────────────────────
LAMPS = [
    ("압력 상한", "ALM_P_HIGH"), ("압력 하한", "ALM_P_LOW"),
    ("밸브각 드리프트", "ALM_VALVE_DRIFT"), ("실누설", "ALM_REAL_LEAK"),
    ("아웃가싱", "ALM_OUTGAS"), ("인터록 가스차단", "ILK_GAS_BLOCK"),
    ("인터록 밸브포화", "ILK_VALVE_SAT"),
]
label("AlmTitle", 20, 910, 400, 22, "알람 · 인터록", 15, FG, 600)
for i, (cap, tg) in enumerate(LAMPS):
    x = 20 + i * 193
    label(f"Lamp_{tg}", x, 938, 185, 44, cap, 12, FG, 500, "center",
          pc={"props.style.backgroundColor": expr(f"if({{{T}{tg}}}, '{ALM_ON}', '{ALM_OFF}')")},
          extra={"border": f"1px solid {LINE}", "borderRadius": "6px"})

# ── 알람 이력 ─────────────────────────────────────────────────────────
label("JournalTitle", 20, 996, 400, 22, "활성 알람", 15, FG, 600)
C("ia.display.alarmstatustable", "AlarmTable", 20, 1024, 1350, 156, {})

view = {"custom": {}, "params": {}, "props": {"defaultSize": {"width": 1400, "height": 1200}},
        "root": {"type": "ia.container.coord", "meta": {"name": "root"},
                 "props": {"style": {"backgroundColor": BG}}, "children": kids}}
json.dump(view, sys.stdout, ensure_ascii=False, indent=2)
