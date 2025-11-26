# app_mp.py
import streamlit as st
from mp_calc import (
    MPInputs,
    compute_mp,
    guardrail_messages,
    pbw_kg,
    CLINICIAN_GUIDE,   # remove this import if you don't want the guide at the bottom
)

st.set_page_config(page_title="Mechanical Power & Recruitability", page_icon="🫁", layout="centered")
st.title("Mechanical Power & Recruitability Tool")

# -----------------------------
# 1. MECHANICAL POWER CALCULATOR
# -----------------------------
st.header("Mechanical Power Calculator")

with st.form("mp_form"):
    mode = st.selectbox("Ventilator mode", ["VC", "PC", "PRVC"])

    c1, c2, c3 = st.columns(3)
    with c1:
        rr = st.number_input("RR (breaths/min)", min_value=1.0, max_value=80.0, value=18.0, step=1.0)
        peep = st.number_input("PEEP (cmH2O)", min_value=0.0, max_value=50.0, value=8.0, step=1.0)
    with c2:
        sex = st.selectbox("Sex (for PBW, optional)", ["", "Male", "Female"])
        height_cm = st.number_input("Height (cm, optional)", min_value=0.0, max_value=250.0, value=0.0, step=0.5)
    with c3:
        vt_ml = st.number_input("VT (mL)", min_value=0.0, max_value=2000.0, value=420.0, step=10.0)

    help_box = st.expander("Optional pressures (for more accurate MP)")

    if mode == "VC":
        pplat = help_box.number_input("Pplat (cmH2O)", min_value=0.0, max_value=100.0, value=26.0, step=0.5)
        ppeak = help_box.number_input("Ppeak (cmH2O)", min_value=0.0, max_value=100.0, value=31.0, step=0.5)
        cstat = help_box.number_input(
            "Cstat (L/cmH2O) if NO reliable Pplat", min_value=0.0, max_value=1.0, value=0.0, step=0.005
        )
        delta_pinsp = None
        pip = None
    else:
        pplat = None
        ppeak = None
        cstat = None
        delta_pinsp = help_box.number_input("ΔPinsp (cmH2O)", min_value=0.0, max_value=80.0, value=18.0, step=0.5)
        pip = help_box.number_input("PIP (cmH2O, optional)", min_value=0.0, max_value=80.0, value=0.0, step=0.5)

    submitted_mp = st.form_submit_button("Compute Mechanical Power")

if submitted_mp:
    inp = MPInputs(
        mode=mode,
        rr_bpm=rr,
        vt_ml=vt_ml,
        peep=peep,
        pplat=None if mode != "VC" else (pplat if pplat > 0 else None),
        ppeak=None if mode != "VC" else (ppeak if ppeak > 0 else None),
        cstat_L_per_cmH2O=None
        if mode != "VC" or (mode == "VC" and pplat > 0)
        else (cstat if cstat > 0 else None),
        delta_pinsp=None if mode == "VC" else (delta_pinsp if delta_pinsp > 0 else None),
        pip=None if mode == "VC" else (pip if pip > 0 else None),
        sex=sex if sex else None,
        height_cm=height_cm if height_cm > 0 else None,
    )

    # PBW and VT/kg information
    if inp.sex and inp.height_cm:
        pbw = pbw_kg(inp.sex, inp.height_cm)
        if pbw > 0:
            st.info(f"PBW ≈ {pbw:.1f} kg | VT ≈ {inp.vt_ml / pbw:.2f} mL/kg")

    try:
        mp, info = compute_mp(inp)
        st.success(f"Mechanical Power: {mp:.2f} J/min")

        with st.expander("Computation details"):
            st.json({k: (round(v, 4) if isinstance(v, float) else v) for k, v in info.items()})

        # Guardrail warnings only (no “advice”)
        warns = guardrail_messages(inp)
        if warns:
            st.warning(" ; ".join(warns))

    except Exception as e:
        st.error(f"Error computing mechanical power: {e}")


# -----------------------------
# 2. R/I RATIO AND RECRUITABILITY
# -----------------------------
st.header("Recruitment-to-Inflation (R/I) Ratio")

st.caption(
    "Optional: use Chen et al. R/I maneuver. "
    "R/I ≥ 0.5 → high recruitability; ~0.3–0.49 → intermediate; < 0.3 → low recruitability."
)

with st.form("ri_form"):
    c1, c2, c3 = st.columns(3)
    with c1:
        high_peep = st.number_input("High PEEP (cmH2O)", min_value=0.0, max_value=40.0, value=15.0, step=1.0)
        low_peep = st.number_input("Low PEEP (cmH2O)", min_value=0.0, max_value=40.0, value=5.0, step=1.0)
    with c2:
        vt_set = st.number_input("Set VT (mL)", min_value=0.0, max_value=2000.0, value=420.0, step=10.0)
        vt_exh_high = st.number_input("VT exhaled @ high PEEP (mL)", min_value=0.0, max_value=3000.0, value=420.0, step=10.0)
    with c3:
        vt_exh_high_to_low = st.number_input(
            "VT exhaled from high→low PEEP (mL, first breath)",
            min_value=0.0,
            max_value=3000.0,
            value=520.0,
            step=10.0,
        )
        pplat_low = st.number_input(
            "Pplat at low PEEP (cmH2O)",
            min_value=0.0,
            max_value=60.0,
            value=24.0,
            step=0.5,
        )

    submitted_ri = st.form_submit_button("Compute R/I ratio")

if submitted_ri:
    try:
        if high_peep <= low_peep:
            raise ValueError("High PEEP must be greater than low PEEP for R/I maneuver.")

        delta_peep = high_peep - low_peep

        # Volume recruited = extra exhaled volume when dropping from high to low PEEP
        v_recruited = vt_exh_high_to_low - vt_exh_high
        if v_recruited <= 0:
            raise ValueError("Recruited volume (VT_high→low - VT_high) is ≤ 0; check your inputs.")

        # Compliance of recruited lung (C_rec), mL/cmH2O
        c_rec = v_recruited / delta_peep

        # Compliance of whole respiratory system at low PEEP (C_rs_low), mL/cmH2O
        if pplat_low <= low_peep:
            raise ValueError("Pplat at low PEEP must be greater than low PEEP.")
        c_rs_low = vt_set / (pplat_low - low_peep)

        if c_rs_low <= 0:
            raise ValueError("Computed Crs at low PEEP is ≤ 0; check VT, Pplat, and PEEP.")

        ri = c_rec / c_rs_low

        st.success(f"R/I ratio: {ri:.2f}")

        # Simple classification
        if ri >= 0.5:
            st.info("Recruitability class: HIGH (good recruiter, R/I ≥ 0.5).")
        elif ri >= 0.3:
            st.info("Recruitability class: INTERMEDIATE (R/I 0.30–0.49).")
        else:
            st.info("Recruitability class: LOW (poor recruiter, R/I < 0.30).")

        with st.expander("Details"):
            st.write(f"ΔPEEP = {delta_peep:.1f} cmH2O")
            st.write(f"Recruited volume = {v_recruited:.1f} mL")
            st.write(f"C_recruited = {c_rec:.1f} mL/cmH2O")
            st.write(f"C_rs (low PEEP) = {c_rs_low:.1f} mL/cmH2O")

    except Exception as e:
        st.error(f"Error computing R/I: {e}")


# -----------------------------
# 3. OPTIONAL QUICK GUIDE
# -----------------------------
st.header("Clinician quick guide")
st.code(CLINICIAN_GUIDE, language="markdown")
