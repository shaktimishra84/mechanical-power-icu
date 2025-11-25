# app_mp.py
import streamlit as st
from mp_calc import (
    MPInputs, compute_mp, guardrail_messages, pbw_kg,
    load_priors, rank_moves, greedy_plan, CLINICIAN_GUIDE,
    DEFAULT_RR_MIN, DEFAULT_RR_MAX, DEFAULT_PEEP_MIN, DEFAULT_PEEP_MAX
)

st.set_page_config(page_title="Mechanical Power Assistant", page_icon="🫁", layout="centered")
st.title("Mechanical Power Assistant")

with st.sidebar:
    st.subheader("Settings")
    use_priors = st.checkbox("Use eICU/MIMIC priors for tie-breaks", value=True)
    greedy_steps = st.slider("Greedy steps (0–3)", 0, 3, 2)
    priors_path = st.text_input("priors.json path", "priors.json")
    priors = load_priors(priors_path) if use_priors else None

    st.markdown("Guardrails (warnings only):")
    rr_min = st.number_input("RR min", value=DEFAULT_RR_MIN, step=1)
    rr_max = st.number_input("RR max", value=DEFAULT_RR_MAX, step=1)
    peep_min = st.number_input("PEEP min", value=DEFAULT_PEEP_MIN, step=1)
    peep_max = st.number_input("PEEP max", value=DEFAULT_PEEP_MAX, step=1)
    st.caption("Pplat/PIP >30 cmH2O will be flagged, not blocked.")

st.header("Calculator")

with st.form("mp_form"):
    mode = st.selectbox("Ventilator mode", ["VC", "PC", "PRVC"])

    c1, c2, c3 = st.columns(3)
    with c1:
        rr = st.number_input("RR (breaths/min)", min_value=1.0, max_value=80.0, value=18.0, step=1.0)
        peep = st.number_input("PEEP (cmH2O)", min_value=0.0, max_value=50.0, value=8.0, step=1.0)
    with c2:
        sex = st.selectbox("Sex (optional for PBW)", ["", "Male", "Female"])
        height_cm = st.number_input("Height (cm, optional)", min_value=0.0, max_value=250.0, value=0.0, step=0.5)
    with c3:
        vt_ml = st.number_input("VT (mL)", min_value=0.0, max_value=2000.0, value=420.0, step=10.0)

    help_box = st.expander("Optional pressures / aids")
    if mode == "VC":
        pplat = help_box.number_input("Pplat (cmH2O)", min_value=0.0, max_value=100.0, value=26.0, step=0.5)
        ppeak = help_box.number_input("Ppeak (cmH2O)", min_value=0.0, max_value=100.0, value=31.0, step=0.5)
        cstat = help_box.number_input("Cstat (L/cmH2O) if no Pplat", min_value=0.0, max_value=1.0, value=0.0, step=0.005)
        delta_pinsp = None; pip = None
    else:
        pplat = None; ppeak = None; cstat = None
        delta_pinsp = help_box.number_input("ΔPinsp (cmH2O)", min_value=0.0, max_value=80.0, value=18.0, step=0.5)
        pip = help_box.number_input("PIP (cmH2O, optional)", min_value=0.0, max_value=80.0, value=0.0, step=0.5)

    submitted = st.form_submit_button("Compute MP and suggest next move")

if submitted:
    inp = MPInputs(
        mode=mode, rr_bpm=rr, vt_ml=vt_ml, peep=peep,
        pplat=None if mode != "VC" else (pplat if pplat > 0 else None),
        ppeak=None if mode != "VC" else (ppeak if ppeak > 0 else None),
        cstat_L_per_cmH2O=None if mode != "VC" or (mode=="VC" and pplat>0) else (cstat if cstat>0 else None),
        delta_pinsp=None if mode == "VC" else (delta_pinsp if delta_pinsp > 0 else None),
        pip=None if mode == "VC" else (pip if pip > 0 else None),
        sex=sex if sex else None,
        height_cm=height_cm if height_cm > 0 else None
    )

    # PBW/VT per kg
    if inp.sex and inp.height_cm:
        pbw = pbw_kg(inp.sex, inp.height_cm)
        if pbw > 0:
            st.info(f"PBW ≈ {pbw:.1f} kg | VT ≈ {inp.vt_ml/pbw:.2f} mL/kg")

    try:
        mp, info = compute_mp(inp)
        st.success(f"Mechanical Power: {mp:.2f} J/min")
        with st.expander("Computation details"):
            st.json({k: (round(v, 4) if isinstance(v, float) else v) for k, v in info.items()})

        # rails as warnings
        warns = guardrail_messages(inp)
        # override min/max with sidebar values for RR/PEEP notes
        if not (rr_min <= inp.rr_bpm <= rr_max):
            warns.append(f"RR {inp.rr_bpm:g} bpm (outside {rr_min}–{rr_max}).")
        if not (peep_min <= inp.peep <= peep_max):
            warns.append(f"PEEP {inp.peep:g} cmH2O (outside {peep_min}–{peep_max}).")
        if warns:
            st.warning(" ; ".join(warns))

        st.subheader("Next best move")
        ranked = rank_moves(inp, priors=priors)
        if ranked:
            best = ranked[0]
            st.write(f"{best['move']} → MP {best['new_mp']:.2f} J/min (Δ {best['abs_drop']:.2f} J/min)")
            if best.get("prior_abs_drop") is not None:
                st.caption(f"Observed average drop for this move (database prior): ≈ {best['prior_abs_drop']:.2f} J/min")

            if greedy_steps > 0:
                plan = greedy_plan(inp, priors=priors, steps=greedy_steps)
                if plan:
                    st.markdown("Short greedy plan:")
                    for i, step in enumerate(plan, 1):
                        st.write(f"{i}) {step['move']} → MP {step['new_mp']:.2f} (Δ {step['abs_drop']:.2f})")
                else:
                    st.caption("No additional improving steps found.")
        else:
            st.info("No safe one-step improvement found with current inputs.")

    except Exception as e:
        st.error(str(e))

st.header("Clinician quick guide")
st.code(CLINICIAN_GUIDE, language="markdown")
