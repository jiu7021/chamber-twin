"""PM 주기 최적화 관점의 예측력 평가.

질문: 로트·순번을 모르는 상태에서, 공정 중 측정되는 설비 채널만으로
      웨이퍼의 식각깊이를 예측할 수 있는가? (가상계측 / PM 지표로 쓸 수 있는가)

평가: Leave-One-Lot-Out 교차검증 (9개 로트로 학습 → 나머지 1개 로트 예측).
      새 로트가 들어왔을 때의 상황을 모사한다. 로트 내 정보를 학습에 쓰지 않으므로
      낙관 편향이 없다.

인과 주장 없음. 예측 연관만 평가한다.
단위 불가지론 — 채널은 원시 단위, 식각깊이만 µm.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, RidgeCV
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.phase2_0_extract import etch_metrics  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

RF_CH = ["PlatenRFTuningCapacitor", "PlatenRFLoadCapacitor", "PlatenRFPeakToPeak",
         "PlatenRFLoadPower", "PlatenRFReflectedPower", "PlatenDcBias",
         "SourceRFPeakToPeak", "SourceRFLoadPower", "SourceRFReflectedPower",
         "SourceRF2PeakToPeak", "moriInnerCurrent"]
VAC_CH = ["ForeLinePressure", "Pressure", "HeliumBPFlow", "HeliumBPPressure"]
GAS_CH = ["Gas1Flow", "Gas2Flow", "Gas4Flow", "Gas5Flow", "Gas7Flow"]
TEMP_CH = ["Heater1Temp", "Heater2Temp", "Heater3Temp", "Heater4Temp"]
ALL_CH = RF_CH + VAC_CH + GAS_CH + TEMP_CH


def lolo_cv(d: pd.DataFrame, feats: list[str], tgt: str, ridge: bool = True) -> dict:
    """Leave-One-Lot-Out 교차검증. 학습 폴드에서만 표준화·계수 추정."""
    pred = np.full(len(d), np.nan)
    for lot in sorted(d["lot"].unique()):
        tr, te = d["lot"] != lot, d["lot"] == lot
        if tr.sum() < len(feats) + 5:
            continue
        sc = StandardScaler().fit(d.loc[tr, feats])
        Xtr, Xte = sc.transform(d.loc[tr, feats]), sc.transform(d.loc[te, feats])
        mdl = (RidgeCV(alphas=np.logspace(-3, 4, 40)) if ridge else LinearRegression())
        mdl.fit(Xtr, d.loc[tr, tgt])
        pred[te.values] = mdl.predict(Xte)
    y = d[tgt].values
    m = np.isfinite(pred)
    resid = y[m] - pred[m]
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((y[m] - y[m].mean()) ** 2))
    return {"R2": 1 - ss_res / ss_tot, "RMSE": float(np.sqrt(np.mean(resid ** 2))),
            "MAE": float(np.mean(np.abs(resid))), "n": int(m.sum()),
            "pred": pred}


def main() -> None:
    df = pd.read_csv(RESULTS / "phase2_channels_31.csv").merge(
        etch_metrics(), on="exp_key", how="left")
    d = df[df["si_etch_mean"].notna()].reset_index(drop=True)
    tgt = "si_etch_mean"
    y = d[tgt]

    print("=" * 84)
    print("PM 관점 예측력 — Leave-One-Lot-Out 교차검증 (목표: si_etch_mean, n=88)")
    print("=" * 84)
    print(f"  목표 변수: 평균 {y.mean():.4f} µm, 표준편차 {y.std():.4f} µm, "
          f"범위 {y.min():.3f}~{y.max():.3f} µm")
    print(f"  로트 내 순번 효과 크기(참고): 10장에 −1.1885 µm\n")

    sets = {
        "① 순번만 (웨이퍼 장수 세기)": ["seq"],
        "② 진공 채널만 (4개)": VAC_CH,
        "③ 온도 채널만 (4개)": TEMP_CH,
        "④ 가스 유량만 (5개)": GAS_CH,
        "⑤ RF 채널만 (11개)": RF_CH,
        "⑥ RF 커패시터 2개만": ["PlatenRFTuningCapacitor", "PlatenRFLoadCapacitor"],
        "⑦ 전체 설비 채널 (24개)": ALL_CH,
        "⑧ 전체 + 순번": ALL_CH + ["seq"],
        "⑨ RF + 순번": RF_CH + ["seq"],
    }
    print(f"  {'특징 집합':32s} {'CV R²':>9s} {'RMSE[µm]':>10s} {'MAE[µm]':>9s}")
    print("  " + "-" * 63)
    res = {}
    for name, feats in sets.items():
        f = [c for c in feats if c in d.columns and d[c].std() > 0]
        r = lolo_cv(d, f, tgt)
        res[name] = r
        print(f"  {name:32s} {r['R2']:9.4f} {r['RMSE']:10.4f} {r['MAE']:9.4f}")
    base_sd = float(np.sqrt(np.mean((y - y.mean()) ** 2)))
    print("  " + "-" * 63)
    print(f"  {'(무모형: 전체 평균으로 예측)':32s} {0.0:9.4f} {base_sd:10.4f} "
          f"{float(np.mean(np.abs(y - y.mean()))):9.4f}")

    print("\n" + "=" * 84)
    print("로트 간 절대 수준까지 맞출 수 있는가 — 로트별 예측 오차")
    print("=" * 84)
    best = "⑤ RF 채널만 (11개)"
    d2 = d.assign(pred_rf=res[best]["pred"], pred_seq=res["① 순번만 (웨이퍼 장수 세기)"]["pred"])
    g = d2.groupby("lot").apply(
        lambda s: pd.Series({
            "실측평균": s[tgt].mean(),
            "RF예측평균": s["pred_rf"].mean(),
            "RF편향": s["pred_rf"].mean() - s[tgt].mean(),
            "RF_로트내_r": np.corrcoef(s["pred_rf"], s[tgt])[0, 1] if len(s) > 2 else np.nan,
            "순번예측평균": s["pred_seq"].mean(),
        }), include_groups=False)
    print(g.round(4).to_string())
    print(f"\n  RF 모델의 로트별 편향 표준편차 = {g['RF편향'].std():.4f} µm "
          f"(로트 간 실측 평균의 표준편차 = {g['실측평균'].std():.4f} µm)")
    print(f"  RF 모델의 로트 내 상관 평균 = {g['RF_로트내_r'].mean():.4f}")

    print("\n" + "=" * 84)
    print("순번을 이미 아는 상태에서 센서가 추가로 주는 것 (증분 예측력)")
    print("=" * 84)
    r_seq = res["① 순번만 (웨이퍼 장수 세기)"]
    for name in ("⑨ RF + 순번", "⑧ 전체 + 순번"):
        r = res[name]
        print(f"  {name:22s} CV R² {r_seq['R2']:.4f} → {r['R2']:.4f} "
              f"(ΔR² {r['R2']-r_seq['R2']:+.4f}),  "
              f"RMSE {r_seq['RMSE']:.4f} → {r['RMSE']:.4f} µm "
              f"({(r['RMSE']/r_seq['RMSE']-1)*100:+.1f} %)")

    out = d[["exp_key", "lot", "seq", tgt]].copy()
    for name, r in res.items():
        out[name] = r["pred"]
    out.to_csv(RESULTS / "phase2R_pm_predictions.csv", index=False)
    print(f"\n저장: {RESULTS/'phase2R_pm_predictions.csv'}")


if __name__ == "__main__":
    main()
