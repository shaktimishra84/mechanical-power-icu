import streamlit as st
from dataclasses import dataclass

# -----------------------------
# Core formulas (locked)
# -----------------------------

# Volume control (VCV):
# MP = 0.098 × RR × VT(L) × [Ppeak − 0.5 × (Pplat − PEEP)]
#
# Pressure control / PRVC:
# MP = 0.098 × RR × VT(L) × (ΔPinsp + PEEP)


@dataclass
class MPInputs:
    mode: str          # "VC", "PC", or "PRVC"
    rr_bpm: float
    vt_ml: float
    peep: float
    pplat: float | None = None      # VC only
    ppeak: float | None = None      # VC only
    delta_pinsp: float | None = None  # PC/PRVC only


def compute_mp(inputs: MPInputs) -> float:
    """
    Compute mechanical power (J/min) using mode-specific formulas.
    """
    mode = inputs.mode.upper()
    vt_l = inputs.vt_ml / 1000.0

    if vt_l <= 0 or inputs.rr_bpm <= 0:
        raise ValueError("VT and RR must be > 0.")

    if mode == "VC":
        if inputs.pplat is None or inputs.ppeak is None:
            raise ValueError("VC mode requires both Pplat and Ppeak.")
        dp = inputs.pplat - inputs.peep
        mp = 0.098 * inputs.rr_bpm * vt_l * (inputs.ppeak - 0.5 * dp)

    elif mode in ("PC", "PRVC"):
        if inputs.delta_pinsp is None:
            raise ValueError("PC/PRVC mode requires ΔPinsp (inspiratory pressure above PEEP).")
        mp = 0.098 * inputs.rr_bpm * vt_l * (inputs.delta_pinsp + inputs.peep)

    else:
        raise ValueError(f"Unsupported mode: {mode}")

    return mp


# -----------------------------
# Recruitability classification
# -----------------------------

def classify_recruitability(mp_low: float, peep_low: float,
                            mp_high: float, peep_high: float) -> dict:
    """
    Simple heuristic:
      - Requires peep_high > peep_low.
      - Compute % change in MP from low-PEEP to high-PEEP.
      - If MP does not increase (ΔMP ≤ 0%): "High recruiter"
      - If MP rises modestly (0–15%): "Intermediate / probable recruiter"
      - If MP rises >15%: "Low recruiter / poor recruitability"
    """
    if peep_high <= peep_low:
        return {
            "label": "Invalid",
            "detail": "High PEEP must be greater than low PEEP for classification.",
            "delta_mp": mp_high - mp_low,
            "delta_pct": None,
        }

    if mp_low <= 0:
        return {
            "label": "Invalid",
            "detail": "MP at low PEEP must be > 0.",
            "delta_mp": mp_high - mp_low,
            "delta_pct": None,
        }

    delta_mp = mp_high - mp_low
    delta_pct = (delta_mp / mp_low) * 100.0

    if delta_pct <= 0:
        label = "High recruitability"
        detail = "MP did not increase with higher PEEP (or decreased), suggesting recruitable lung."
    elif delta_pct <= 15:
        label = "Intermediate / probable recruiter"
        detail = "MP increased modestly with higher PEEP, compatible with partial recruitability."
    else:
        label = "Low recruitability"
        detail = "MP rose substantially with higher PEEP, suggesting poor recruitability / overdistension risk."

    return {
        "label": label,
        "detail": detail,
        "delta_mp": delta_mp,
        "delta_pct": delta_pct,
    }


# -----------------------------
# Streamlit UI
# -----------------------------

st.set_page_config(page_title="Mechanical Power & Recruitability", page_icon="🫁", layout="centered")
st.title("Mechanical Power & Recruitability Tool")

tab1, tab2 = st.tabs(["Mechanical Power (single setting)", "Recruitability (two PEEP levels)"])

# -------- Tab 1: Single setting MP --------
with tab1:
    st.subheader("Single setting mechanical power")

    with st.form("single_mp"):
        mode = st.selectbox("Ventilator mode", ["VC", "PC", "PRVC"])

        c1, c2, c3 = st.columns(3)
        with c1:
            rr = st.number_input("RR (breaths/min)", min_value=1.0, max_value=80.0, value=18.0, step=1.0)
        with c2:
            vt_ml = st.number_input("Tidal volume VT (mL)", min_value=10.0, max_value=2000.0, value=420.0, step=10.0)
        with c3:
            peep = st.number_input("PEEP (cmH2O)", min_value=0.0, max_value=40.0, value=8.0, step=1.0)

        if mode == "VC":
            c4, c5 = st.columns(2)
            with c4:
                pplat = st.number_input("Plateau pressure Pplat (cmH2O)", min_value=0.0, max_value=80.0, value=26.0, step=0.5)
            with c5:
                ppeak = st.number_input("Peak pressure Ppeak (cmH2O)", min_value=0.0, max_value=80.0, value=31.0, step=0.5)
            delta_pinsp = None
        else:
            pplat = None
            ppeak = None
            delta_pinsp = st.number_input("ΔPinsp (cmH2O above PEEP)", min_value=0.0, max_value=80.0, value=18.0, step=0.5)

        submitted = st.form_submit_button("Compute MP")

    if submitted:
        try:
            inp = MPInputs(
                mode=mode,
                rr_bpm=rr,
                vt_ml=vt_ml,
                peep=peep,
                pplat=pplat,
                ppeak=ppeak,
                delta_pinsp=delta_pinsp,
            )
            mp = compute_mp(inp)
            st.success(f"Mechanical Power ≈ {mp:.2f} J/min")

        except Exception as e:
            st.error(f"Error: {e}")

# -------- Tab 2: Recruitability --------
with tab2:
    st.subheader("Recruitability classification (low vs high PEEP)")

    st.caption("Enter two ventilator settings: one at lower PEEP, one at higher PEEP. "
               "The app will compute mechanical power for each and classify recruitability based on the MP change.")

    with st.form("recruit_form"):
        mode_r = st.selectbox("Ventilator mode", ["VC", "PC", "PRVC"], key="mode_r")

        st.markdown("Lower PEEP setting")
        c1, c2, c3 = st.columns(3)
        with c1:
            rr_low = st.number_input("RR low (breaths/min)", min_value=1.0, max_value=80.0, value=18.0, step=1.0)
        with c2:
            vt_low = st.number_input("VT low (mL)", min_value=10.0, max_value=2000.0, value=420.0, step=10.0)
        with c3:
            peep_low = st.number_input("PEEP low (cmH2O)", min_value=0.0, max_value=40.0, value=8.0, step=1.0)

        if mode_r == "VC":
            c4, c5 = st.columns(2)
            with c4:
                pplat_low = st.number_input("Pplat low (cmH2O)", min_value=0.0, max_value=80.0, value=26.0, step=0.5)
            with c5:
                ppeak_low = st.number_input("Ppeak low (cmH2O)", min_value=0.0, max_value=80.0, value=31.0, step=0.5)
            delta_low = None
        else:
            pplat_low = None
            ppeak_low = None
            delta_low = st.number_input("ΔPinsp low (cmH2O)", min_value=0.0, max_value=80.0, value=18.0, step=0.5)

        st.markdown("---")
        st.markdown("Higher PEEP setting")
        c6, c7, c8 = st.columns(3)
        with c6:
            rr_high = st.number_input("RR high (breaths/min)", min_value=1.0, max_value=80.0, value=18.0, step=1.0)
        with c7:
            vt_high = st.number_input("VT high (mL)", min_value=10.0, max_value=2000.0, value=420.0, step=10.0)
        with c8:
            peep_high = st.number_input("PEEP high (cmH2O)", min_value=0.0, max_value=40.0, value=12.0, step=1.0)

        if mode_r == "VC":
            c9, c10 = st.columns(2)
            with c9:
                pplat_high = st.number_input("Pplat high (cmH2O)", min_value=0.0, max_value=80.0, value=28.0, step=0.5)
            with c10:
                ppeak_high = st.number_input("Ppeak high (cmH2O)", min_value=0.0, max_value=80.0, value=33.0, step=0.5)
            delta_high = None
        else:
            pplat_high = None
            ppeak_high = None
            delta_high = st.number_input("ΔPinsp high (cmH2O)", min_value=0.0, max_value=80.0, value=20.0, step=0.5)

        sub_r = st.form_submit_button("Compute MP and classify")

    if sub_r:
        try:
            # Low PEEP MP
            inp_low = MPInputs(
                mode=mode_r,
                rr_bpm=rr_low,
                vt_ml=vt_low,
                peep=peep_low,
                pplat=pplat_low,
                ppeak=ppeak_low,
                delta_pinsp=delta_low,
            )
            mp_low = compute_mp(inp_low)

            # High PEEP MP
            inp_high = MPInputs(
                mode=mode_r,
                rr_bpm=rr_high,
                vt_ml=vt_high,
                peep=peep_high,
                pplat=pplat_high,
                ppeak=ppeak_high,
                delta_pinsp=delta_high,
            )
            mp_high = compute_mp(inp_high)

            st.write(f"MP at low PEEP ({peep_low:.0f}): {mp_low:.2f} J/min")
            st.write(f"MP at high PEEP ({peep_high:.0f}): {mp_high:.2f} J/min")

            result = classify_recruitability(mp_low, peep_low, mp_high, peep_high)

            if result["label"] == "Invalid":
                st.error(result["detail"])
            else:
                st.success(f"Recruitability: {result['label']}")
                st.write(result["detail"])
                st.caption(
                    f"ΔMP = {result['delta_mp']:.2f} J/min "
                    f"({result['delta_pct']:.1f}% change from low to high PEEP)"
                )

        except Exception as e:
            st.error(f"Error: {e}")
