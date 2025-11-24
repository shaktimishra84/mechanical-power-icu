# mp_assistant_app.py
# Streamlit bedside MP calculator + best next setting suggestion
# Author: Dr Shakti’s ICU group (helper script)

import math
import numpy as np
import pandas as pd
import streamlit as st

# -----------------------------
# Helpers
# -----------------------------
def pbw_kg(height_cm: float, sex: str) -> float:
    if height_cm is None or np.isnan(height_cm):
        return np.nan
    sex = (sex or "").strip().lower()
    if sex in ["m", "male"]:
        return 50 + 0.91*(height_cm - 152.4)
    if sex in ["f", "female"]:
        return 45.5 + 0.91*(height_cm - 152.4)
    return np.nan

def coerce_float(x):
    try:
        if x is None: return np.nan
        if isinstance(x, str) and x.strip()=="":
            return np.nan
        return float(x)
    except Exception:
        return np.nan

def compute_pressures(mode: str,
                      vt_ml: float,
                      peep: float,
                      pplat: float,
                      pip: float,
                      delta_pinsp: float,
                      cstat_ml_per_cmH2O: float):
    mode = (mode or "").lower().strip()
    vt_L = vt_ml/1000.0 if vt_ml and np.isfinite(vt_ml) else np.nan
    peep = coerce_float(peep)
    pplat = coerce_float(pplat)
    pip   = coerce_float(pip)
    dP    = coerce_float(delta_pinsp)
    cstat = coerce_float(cstat_ml_per_cmH2O)

    # Estimate pplat and pip when missing, following your house rules:
    # VC: pplat ≈ VT/C + PEEP (if C given); if still missing, accept user pplat if provided.
    # PC: pplat ≈ PEEP + ΔPinsp if ΔPinsp given; pip ~ pplat + 5 unless provided.
    # Generic fallback for resistive gap: pip ≈ pplat + 5 if pip missing and pplat present.

    if mode in ["vc","volume control","volume-controlled","volume controlled"]:
        if (not np.isfinite(pplat)) and np.isfinite(vt_L) and np.isfinite(cstat) and np.isfinite(peep):
            # cstat may be in mL/cmH2O; convert to L/cmH2O
            cL = cstat/1000.0
            if cL>0:
                pplat = vt_L/cL + peep
        if (not np.isfinite(pip)) and np.isfinite(pplat):
            pip = pplat + 5.0

    elif mode in ["pc","pressure control","pressure-controlled","pressure controlled"]:
        if (not np.isfinite(dP)) and np.isfinite(pip) and np.isfinite(peep):
            dP = pip - peep
        if (not np.isfinite(pplat)) and np.isfinite(peep) and np.isfinite(dP):
            pplat = peep + dP
        if (not np.isfinite(pip)) and np.isfinite(pplat):
            pip = pplat + 5.0

    # Generic fallback if still missing pip and have pplat:
    if (not np.isfinite(pip)) and np.isfinite(pplat):
        pip = pplat + 5.0

    return pplat, pip

def mechanical_power(rr_bpm: float, vt_ml: float, peep: float, pplat: float, pip: float):
    # Preferred house formula (Gattinoni-style):
    # MP = 0.098 × RR × VT(L) × ( Ppeak − (Pplat − PEEP)/2 )
    rr = coerce_float(rr_bpm)
    vt_L = (coerce_float(vt_ml) or 0)/1000.0
    peep = coerce_float(peep)
    pplat = coerce_float(pplat)
    pip = coerce_float(pip)
    if not (np.isfinite(rr) and np.isfinite(vt_L) and np.isfinite(pip) and np.isfinite(pplat) and np.isfinite(peep)):
        return np.nan
    term = pip - (pplat - peep)/2.0
    return 0.098 * rr * vt_L * term

# Guardrails for bedside feasibility
GUARDS = dict(
    rr_min=8, rr_max=35,
    vt_min_mlkg=4.0, vt_max_mlkg=8.0,
    peep_min=5, peep_max=15,
    pmax=30.0  # cap for Pplat or PIP (whichever is relevant)
)

def within_vt_guard(vt_ml, pbw):
    if not (np.isfinite(vt_ml) and np.isfinite(pbw) and pbw>0): return False
    mlkg = vt_ml/pbw
    return (mlkg >= GUARDS["vt_min_mlkg"]) and (mlkg <= GUARDS["vt_max_mlkg"])

def cap_pressures(pplat, pip):
    # If either exceeds pmax, mark as unsafe
    pmax = GUARDS["pmax"]
    if np.isfinite(pplat) and pplat>pmax: return False
    if np.isfinite(pip)   and pip>pmax:   return False
    return True

def propose_candidates(mode, rr, vt_ml, peep, pplat, pip, dP, cstat_ml_per_cmH2O, pbw, allow_peep_down=True):
    """Enumerate one-step counterfactuals; return list of dicts with new settings and MP."""
    base_pplat, base_pip = compute_pressures(mode, vt_ml, peep, pplat, pip, dP, cstat_ml_per_cmH2O)
    base_mp = mechanical_power(rr, vt_ml, peep, base_pplat, base_pip)

    cands = []

    # helper to pack a candidate
    def add(label, rr_new, vt_new, peep_new, dP_new):
        pplat_new, pip_new = compute_pressures(mode, vt_new, peep_new, pplat, pip, dP_new, cstat_ml_per_cmH2O)
        mp_new = mechanical_power(rr_new, vt_new, peep_new, pplat_new, pip_new)
        if not np.isfinite(mp_new): 
            return
        # guardrails
        if rr_new < GUARDS["rr_min"] or rr_new > GUARDS["rr_max"]:
            return
        if not within_vt_guard(vt_new, pbw):
            return
        if not (GUARDS["peep_min"] <= peep_new <= GUARDS["peep_max"]):
            return
        if not cap_pressures(pplat_new, pip_new):
            return
        cands.append(dict(move=label,
                          rr=rr_new, vt_ml=vt_new, peep=peep_new, dP=dP_new,
                          mp=mp_new,
                          abs_drop=(base_mp-mp_new) if np.isfinite(base_mp) else np.nan,
                          rel_drop=((base_mp-mp_new)/base_mp) if (np.isfinite(base_mp) and base_mp>0) else np.nan))
    # Moves
    add("RR -2", rr-2, vt_ml, peep, dP)
    add("RR +2", rr+2, vt_ml, peep, dP)  # expected to worsen MP; included for transparency
    add("VT -50", rr, vt_ml-50, peep, dP)
    add("VT +50", rr, vt_ml+50, peep, dP)  # expected to worsen MP
    if allow_peep_down:
        add("PEEP -1", rr, vt_ml, peep-1, dP)
    # Pressure-targeted tweak (reduce ΔPinsp by 2) when in PC:
    if mode in ["pc","pressure control","pressure-controlled","pressure controlled"]:
        dP_new = coerce_float(dP)
        if np.isfinite(dP_new):
            add("ΔPinsp -2", rr, vt_ml, peep, dP_new-2)

    # Choose best reducer
    improving = [c for c in cands if np.isfinite(c["abs_drop"]) and c["abs_drop"]>0]
    best = None
    if improving:
        # tie-breaker: max absolute drop; then max relative drop; then prefer RR -2, VT -50, ΔPinsp -2, PEEP -1 in that order
        improving.sort(key=lambda x: (x["abs_drop"], x.get("rel_drop", 0.0),
                                      {"RR -2":4, "VT -50":3, "ΔPinsp -2":2, "PEEP -1":1, "RR +2":0, "VT +50":0}.get(x["move"], 0)),
                       reverse=True)
        best = improving[0]

    # To show the full table nicely:
    df = pd.DataFrame(cands)
    # Order columns
    if not df.empty:
        df = df[["move","mp","abs_drop","rel_drop","rr","vt_ml","peep","dP"]].sort_values(["abs_drop","rel_drop"], ascending=[False, False])
    return base_pplat, base_pip, base_mp, df, best

def greedy_multistep(mode, rr, vt_ml, peep, pplat, pip, dP, cstat_ml_per_cmH2O, pbw, allow_peep_down=True, max_steps=5):
    """Optional: repeatedly apply best one-step move until no more improvement or steps exhausted."""
    steps = []
    for _ in range(max_steps):
        _, _, base_mp, df, best = propose_candidates(mode, rr, vt_ml, peep, pplat, pip, dP, cstat_ml_per_cmH2O, pbw, allow_peep_down)
        if best is None or not np.isfinite(best["abs_drop"]) or best["abs_drop"]<=0:
            break
        steps.append(dict(step=len(steps)+1, move=best["move"], mp_after=best["mp"], abs_drop=best["abs_drop"], rel_drop=best["rel_drop"]))
        rr, vt_ml, peep, dP = best["rr"], best["vt_ml"], best["peep"], best["dP"]
        # update pplat/pip for next loop
        pplat, pip = compute_pressures(mode, vt_ml, peep, pplat, pip, dP, cstat_ml_per_cmH2O)
    return pd.DataFrame(steps), dict(rr=rr, vt_ml=vt_ml, peep=peep, dP=dP)

# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="ICU Mechanical Power Assistant", page_icon="🫁", layout="centered")

st.title("ICU Mechanical Power Assistant")
st.caption("Calculates mechanical power and suggests a guardrail-safe ventilator change to reduce it.")

with st.form("inputs"):
    colA, colB = st.columns(2)
    mode = colA.selectbox("Mode", ["VC", "PC"], index=0)
    sex  = colB.selectbox("Sex (for PBW)", ["Male","Female"], index=0)

    c1, c2, c3 = st.columns(3)
    height_cm = c1.number_input("Height (cm)", min_value=120.0, max_value=220.0, value=170.0, step=0.5)
    rr_bpm    = c2.number_input("Respiratory Rate (bpm)", min_value=4.0, max_value=60.0, value=18.0, step=1.0)
    vt_ml     = c3.number_input("Tidal Volume (mL)", min_value=100.0, max_value=1200.0, value=450.0, step=10.0)

    c4, c5, c6 = st.columns(3)
    peep       = c4.number_input("PEEP (cmH₂O)", min_value=0.0, max_value=24.0, value=8.0, step=1.0)
    pplat      = c5.number_input("Plateau Pressure (cmH₂O)", min_value=0.0, max_value=60.0, value=0.0, step=0.5)
    pip        = c6.number_input("PIP (cmH₂O)", min_value=0.0, max_value=60.0, value=0.0, step=0.5)

    c7, c8, c9 = st.columns(3)
    dP         = c7.number_input("ΔPinsp (PC only) (cmH₂O)", min_value=0.0, max_value=40.0, value=0.0, step=0.5)
    cstat_ml   = c8.number_input("Static compliance (mL/cmH₂O) (optional)", min_value=0.0, max_value=300.0, value=0.0, step=1.0)
    fio2_pct   = c9.number_input("FiO₂ (%) (optional, for PEEP decisions)", min_value=21.0, max_value=100.0, value=60.0, step=1.0)

    allow_peep = st.checkbox("Allow PEEP −1 suggestion when FiO₂ ≤60% or unknown", value=True)
    do_greedy  = st.checkbox("Also compute a short greedy sequence (≤5 steps)", value=False)

    submitted = st.form_submit_button("Compute")

if submitted:
    pbw = pbw_kg(height_cm, sex)
    st.write(f"PBW ≈ {pbw:.1f} kg  |  VT ≈ {vt_ml/pbw:.2f} mL/kg" if np.isfinite(pbw) and pbw>0 else "PBW not available")

    # Gate PEEP reductions by oxygenation, if selected
    allow_peep_down = allow_peep and (np.isnan(fio2_pct) or fio2_pct <= 60)

    pplat_use, pip_use = compute_pressures(mode, vt_ml, peep, pplat, pip, dP, cstat_ml)
    mp = mechanical_power(rr_bpm, vt_ml, peep, pplat_use, pip_use)

    st.subheader("Current setting")
    st.write(f"Pplat est/meas: {pplat_use:.1f} cmH₂O  |  PIP est/meas: {pip_use:.1f} cmH₂O")
    st.write(f"Mechanical Power: {mp:.2f} J/min" if np.isfinite(mp) else "Mechanical Power: not computable from given inputs")

    base_ok = cap_pressures(pplat_use, pip_use) and within_vt_guard(vt_ml, pbw) and (GUARDS["rr_min"]<=rr_bpm<=GUARDS["rr_max"]) and (GUARDS["peep_min"]<=peep<=GUARDS["peep_max"])
    if not base_ok:
        st.warning("Current settings are outside guardrails (VT/PBW 4–8 mL/kg, RR 8–35, PEEP 5–15, Pplat/PIP ≤30). Suggestions will still be computed, but may be restricted.")

    # One-step suggestion
    pplat_use, pip_use, base_mp, df_moves, best = propose_candidates(mode, rr_bpm, vt_ml, peep, pplat, pip, dP, cstat_ml, pbw, allow_peep_down=allow_peep_down)

    st.subheader("One-step counterfactuals")
    if df_moves is None or df_moves.empty:
        st.info("No safe one-step improvement found with the provided inputs and guardrails.")
    else:
        show = df_moves.copy()
        if "rel_drop" in show:
            show["rel_drop_%"] = (show["rel_drop"]*100).round(1)
            show = show.drop(columns=["rel_drop"])
        st.dataframe(show.style.format({"mp":"{:.2f}","abs_drop":"{:.2f}","rel_drop_%":"{:.1f}","rr":"{:.0f}","vt_ml":"{:.0f}","peep":"{:.0f}","dP":"{:.1f}"}), use_container_width=True)

    st.subheader("Best next move")
    if best is None:
        st.write("none")
    else:
        st.write(f"{best['move']} → MP {best['mp']:.2f} J/min  (↓ {best['abs_drop']:.2f} J/min; {best['rel_drop']*100:.1f}%)")
        st.write(f"Apply: RR {int(best['rr'])}, VT {int(best['vt_ml'])} mL, PEEP {int(best['peep'])} cmH₂O" + (f", ΔPinsp {best['dP']:.1f} cmH₂O" if np.isfinite(best.get("dP", np.nan)) else ""))

    # Optional greedy multi-step
    if do_greedy:
        steps_df, final_set = greedy_multistep(mode, rr_bpm, vt_ml, peep, pplat, pip, dP, cstat_ml, pbw, allow_peep_down=allow_peep_down, max_steps=5)
        st.subheader("Short greedy sequence")
        if steps_df.empty:
            st.write("No additional improving steps beyond the best next move.")
        else:
            out = steps_df.copy()
            out["rel_drop_%"] = (out["rel_drop"]*100).round(1)
            out = out.drop(columns=["rel_drop"])
            st.dataframe(out.style.format({"mp_after":"{:.2f}","abs_drop":"{:.2f}","rel_drop_%":"{:.1f}"}), use_container_width=True)
            st.write(f"Greedy target (apply in order): RR {int(final_set['rr'])}, VT {int(final_set['vt_ml'])} mL, PEEP {int(final_set['peep'])} cmH₂O" + (f", ΔPinsp {final_set['dP']:.1f} cmH₂O" if np.isfinite(final_set['dP']) else ""))

st.caption("Guardrails: VT 4–8 mL/kg PBW, RR 8–35 bpm, PEEP 5–15 cmH₂O, Pplat/PIP ≤30 cmH₂O. Use clinical judgement for oxygenation; consider PEEP ↓ only if safe.")
