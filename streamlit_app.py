# app_mp.py
# Streamlit app that wraps mp_calc.py

import streamlit as st
from mp_calc import MPInputs, compute_mp, guardrail_messages, pbw_kg

st.set_page_config(page_title="Mechanical Power Calculator", page_icon="🫁", layout="centered")

st.title("Mechanical Power (MP) Calculator")
st.caption("Formulas used: VC simplified and PC/PRVC simplified as provided by you.")

with st.form("mp_form"):
    mode = st.selectbox("Ventilator mode", ["VC", "PC", "PRVC"])

    col1, col2, col3 = st.columns(3)
    with col1:
        rr = st.number_input("RR (breaths/min)", min_value=1.0, max_value=60.0, value=18.0, step=1.0)
        peep = st.number_input("PEEP (cmH₂O)", min_value=0.0, max_value=30.0, value=8.0, step=1.0)
    with col2:
        sex = st.selectbox("Sex (for PBW, optional)", ["", "Male", "Female"])
        height_cm = st.number_input("Height (cm, optional)", min_value=0.0, max_value=250.0, value=0.0, step=0.5)
    with col3:
        vt_ml = st.number_input("VT (mL)", min_value=0.0, max_value=1500.0, value=420.0, step=10.0)

    help_box = st.expander("Optional pressures / aids")
    with help_box:
        if mode == "VC":
            pplat = st.number_input("Pplat (cmH₂O)", min_value=0.0, max_value=80.0, value=26.0, step=0.5)
            ppeak = st.number_input("Ppeak (cmH₂O)", min_value=0.0, max_value=80.0, value=31.0, step=0.5)
            cstat = st.number_input("Cstat (L/cmH₂O) if no Pplat", min_value=0.0, max_value=1.0, value=0.0, step=0.005, help="Used only when Pplat is missing.")
            delta_pinsp = None
            pip = None
        else:
            pplat = None
            ppeak = None
            delta_pinsp = st.number_input("ΔPinsp (cmH₂O)", min_value=0.0, max_value=80.0, value=18.0, step=0.5, help="Inspiratory pressure above PEEP")
            pip = st.number_input("PIP (cmH₂O, optional)", min_value=0.0, max_value=80.0, value=0.0, step=0.5, help="If ΔPinsp unknown, ΔPinsp = PIP − PEEP")

    submitted = st.form_submit_button("Calculate")

if submitted:
    inp = MPInputs(
        mode=mode, rr_bpm=rr, vt_ml=vt_ml, peep=peep,
        pplat=None if mode != "VC" else (pplat if pplat > 0 else None),
        ppeak=None if mode != "VC" else (ppeak if ppeak > 0 else None),
        cstat_L_per_cmH2O=None if mode != "VC" or (mode=="VC" and pplat>0) else (cstat if cstat>0 else None),
        delta_pinsp=None if mode == "VC" else (delta_pinsp if delta_pinsp > 0 else None),
        pip=None if mode == "VC" else (pip if pip > 0 else None),
        sex=sex, height_cm=height_cm if height_cm > 0 else None
    )

    # Show PBW/VT per kg if available
    if inp.sex and inp.height_cm:
        pbw = pbw_kg(inp.sex, inp.height_cm)
        st.info(f"PBW ≈ {pbw:.1f} kg | VT ≈ {inp.vt_ml/pbw:.2f} mL/kg")

    try:
        mp, info = compute_mp(inp)
        st.success(f"Mechanical Power: {mp:.2f} J/min")
        with st.expander("Details / terms used"):
            st.json({k: (round(v, 4) if isinstance(v, float) else v) for k, v in info.items()})

        warns = guardrail_messages(inp)
        if warns:
            st.warning(" ; ".join(warns))

    except Exception as e:
        st.error(str(e))
