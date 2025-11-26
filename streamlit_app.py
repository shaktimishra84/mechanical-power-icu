# app_mp_recruit.py
import streamlit as st

MP_K = 0.098  # conversion constant for J/min


def pbw_kg(sex: str, height_cm: float) -> float:
    """Predicted body weight (ARDSNet)."""
    sex = sex.lower()
    if sex.startswith("m"):
        return 50.0 + 0.91 * (height_cm - 152.4)
    else:
        return 45.5 + 0.91 * (height_cm - 152.4)


def compute_mp_vc(rr: float, vt_ml: float, peep: float,
                  pplat: float, ppeak: float | None = None) -> tuple[float, float]:
    """
    Mechanical power for volume-controlled / PRVC ventilation
    using Gattinoni-style formula:

    MP = 0.098 × RR × VT(L) × [ Ppeak – 0.5 × (Pplat – PEEP) ]
    Returns: (MP, driving_pressure)
    """
    vt_L = vt_ml / 1000.0
    if vt_L <= 0 or rr <= 0:
        raise ValueError("RR and VT must be > 0.")

    if ppeak is None or ppeak <= 0:
        # simple approximation if peak not provided
        ppeak = pplat + 5.0

    delta_p = pplat - peep
    mp = MP_K * rr * vt_L * (ppeak - 0.5 * delta_p)
    return mp, delta_p


def compute_mp_pc(rr: float, vt_ml: float, peep: float,
                  delta_pinsp: float) -> tuple[float, float]:
    """
    Mechanical power for pressure-controlled ventilation.
    Simplified formula:

    MP ≈ 0.098 × RR × VT(L) × (PEEP + ΔPinsp / 2)

    Returns: (MP, driving_pressure = ΔPinsp)
    """
    vt_L = vt_ml / 1000.0
    if vt_L <= 0 or rr <= 0:
        raise ValueError("RR and VT must be > 0.")
    if delta_pinsp <= 0:
        raise ValueError("ΔPinsp must be > 0.")

    mp = MP_K * rr * vt_L * (peep + delta_pinsp / 2.0)
    return mp, delta_pinsp


def compute_ri_ratio(
    p_high: float,
    p_low: float,
    vt_set: float,
    vt_high: float,
    vt_high2low: float,
    pplat_low: float,
) -> float:
    """
    Recruitment-to-Inflation (R/I) ratio as per Chen et al.

    v_rec = VT_exhaled (high→low PEEP) – VT_exhaled @ high PEEP
    C_rec = v_rec / (P_high – P_low)
    C_rs  = VT_set / (Pplat_low – P_low)
    R/I   = C_rec / C_rs
    """
    if p_high <= p_low:
        raise ValueError("High PEEP must be greater than low PEEP.")
    if pplat_low <= p_low:
        raise ValueError("Plateau at low PEEP must be greater than low PEEP.")
    if vt_set <= 0:
        raise ValueError("Set VT must be > 0.")

    v_rec = vt_high2low - vt_high
    if v_rec <= 0:
        # no recruitable volume detected; treat as zero recruitability
        return 0.0

    c_rec = v_rec / (p_high - p_low)
    c_rs = vt_set / (pplat_low - p_low)
    if c_rs <= 0:
        raise ValueError("Computed respiratory system compliance ≤ 0, check inputs.")

    ri = c_rec / c_rs
    return ri


# -------------------- Streamlit UI --------------------

st.set_page_config(
    page_title="Mechanical Power and Recruitability",
    page_icon="🫁",
    layout="centered",
)

st.title("Mechanical Power and Recruitability Tool")

st.markdown("### 1. Mechanical power calculator")

with st.form("mp_form"):
    mode = st.selectbox("Ventilator mode", ["VC / PRVC", "PC"])

    c1, c2, c3 = st.columns(3)

    with c1:
        rr = st.number_input(
            "Respiratory rate (breaths/min)",
            min_value=1.0,
            max_value=80.0,
            value=18.0,
            step=1.0,
        )
        peep = st.number_input(
            "PEEP (cmH₂O)",
            min_value=0.0,
            max_value=40.0,
            value=8.0,
            step=1.0,
        )
    with c2:
        vt_ml = st.number_input(
            "Tidal volume (mL)",
            min_value=0.0,
            max_value=2000.0,
            value=420.0,
            step=10.0,
        )
        sex = st.selectbox("Sex for PBW (optional)", ["", "Male", "Female"])
    with c3:
        height_cm = st.number_input(
            "Height (cm, optional)",
            min_value=0.0,
            max_value=250.0,
            value=0.0,
            step=0.5,
        )

    if mode == "VC / PRVC":
        st.markdown("Tidal-volume or PRVC-type volume controlled ventilation")

        pplat = st.number_input(
            "Plateau pressure, Pplat (cmH₂O)",
            min_value=0.0,
            max_value=80.0,
            value=25.0,
            step=0.5,
        )
        ppeak = st.number_input(
            "Peak pressure, Ppeak (cmH₂O) (0 = approximate as Pplat + 5)",
            min_value=0.0,
            max_value=80.0,
            value=30.0,
            step=0.5,
        )
        delta_pinsp = None

    else:
        st.markdown("Pressure-controlled ventilation")

        delta_pinsp = st.number_input(
            "Inspiratory pressure above PEEP, ΔPinsp (cmH₂O)",
            min_value=0.0,
            max_value=60.0,
            value=16.0,
            step=0.5,
        )
        pplat = None
        ppeak = None

    submitted_mp = st.form_submit_button("Compute mechanical power")

if submitted_mp:
    # PBW and VT/kg info
    if sex and height_cm > 0:
        try:
            pbw = pbw_kg(sex, height_cm)
            if pbw > 0:
                st.info(f"Predicted body weight ≈ {pbw:.1f} kg | VT ≈ {vt_ml / pbw:.2f} mL/kg PBW")
        except Exception as e:
            st.warning(f"PBW could not be calculated: {e}")

    try:
        if mode == "VC / PRVC":
            mp, delta_p = compute_mp_vc(
                rr=rr,
                vt_ml=vt_ml,
                peep=peep,
                pplat=pplat,
                ppeak=ppeak if ppeak > 0 else None,
            )
        else:
            mp, delta_p = compute_mp_pc(
                rr=rr,
                vt_ml=vt_ml,
                peep=peep,
                delta_pinsp=delta_pinsp,
            )

        st.success(f"Mechanical power ≈ {mp:.2f} J/min")
        st.write(f"Driving pressure (ΔP) ≈ {delta_p:.1f} cmH₂O")

        # Simple safety flags (warnings only)
        warns = []
        if mp > 17:
            warns.append(f"Mechanical power > 17 J/min (≈ high-risk range in observational data).")
        if delta_p > 15:
            warns.append("Driving pressure > 15 cmH₂O.")
        if peep > 15:
            warns.append("PEEP > 15 cmH₂O.")
        if mode == "VC / PRVC" and pplat is not None and pplat > 30:
            warns.append("Plateau pressure > 30 cmH₂O.")

        if warns:
            st.warning(" | ".join(warns))

    except Exception as e:
        st.error(f"Could not compute mechanical power: {e}")


st.markdown("---")
st.markdown("### 2. R/I ratio and recruitability (binary)")

with st.form("ri_form"):
    st.markdown("Inputs from the R/I maneuver (Chen et al.)")

    c1, c2, c3 = st.columns(3)

    with c1:
        p_high = st.number_input(
            "High PEEP (cmH₂O)",
            min_value=0.0,
            max_value=40.0,
            value=15.0,
            step=1.0,
        )
        p_low = st.number_input(
            "Low PEEP (cmH₂O)",
            min_value=0.0,
            max_value=40.0,
            value=5.0,
            step=1.0,
        )
    with c2:
        vt_set = st.number_input(
            "Set VT (mL)",
            min_value=0.0,
            max_value=2000.0,
            value=400.0,
            step=10.0,
        )
        vt_high = st.number_input(
            "VT exhaled @ high PEEP (mL)",
            min_value=0.0,
            max_value=3000.0,
            value=400.0,
            step=10.0,
        )
    with c3:
        vt_high2low = st.number_input(
            "VT exhaled on drop high→low PEEP (mL)",
            min_value=0.0,
            max_value=3000.0,
            value=550.0,
            step=10.0,
        )
        pplat_low = st.number_input(
            "Plateau pressure at low PEEP (cmH₂O)",
            min_value=0.0,
            max_value=80.0,
            value=22.0,
            step=0.5,
        )

    submitted_ri = st.form_submit_button("Compute R/I ratio and classify")

if submitted_ri:
    try:
        ri = compute_ri_ratio(
            p_high=p_high,
            p_low=p_low,
            vt_set=vt_set,
            vt_high=vt_high,
            vt_high2low=vt_high2low,
            pplat_low=pplat_low,
        )

        st.success(f"R/I ratio ≈ {ri:.2f}")

        # Binary classification only
        if ri >= 0.5:
            st.info("Recruitability class: HIGH (good recruiter, R/I ≥ 0.5).")
        else:
            st.info("Recruitability class: LOW (poor recruiter, R/I < 0.5).")

    except Exception as e:
        st.error(f"Could not compute R/I ratio: {e}")
