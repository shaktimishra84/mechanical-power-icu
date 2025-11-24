# mp_calc_app.py
# Streamlit mechanical power calculator for VC, PC, and PRVC
# Uses distinct closed-form formulas and safe fallbacks you can audit.

import math
import streamlit as st

K = 0.098  # conversion factor in J·min⁻¹ when pressures in cmH2O, VT in L, RR in bpm

# ---- helpers ----
def devine_pbw(sex: str, height_cm: float) -> float:
    if height_cm is None or height_cm <= 0:
        return float("nan")
    base = 50.0 if sex.lower().startswith("m") else 45.5
    return base + 0.91 * (height_cm - 152.4)

def to_float(x, default=None):
    try:
        v = float(x)
        if math.isfinite(v):
            return v
    except Exception:
        pass
    return default

def clamp(v, lo, hi):
    if v is None or not math.isfinite(v):
        return v
    return max(lo, min(hi, v))

# ---- formulas ----
def mp_vc(RR, VT_ml, PEEP, Pplat=None, PIP=None, Cstat_ml_per_cmH2O=None):
    """
    Volume-controlled (constant flow) approximation:
      MP ≈ 0.098 × RR × VT(L) × [Ppeak − 0.5 × (Pplat − PEEP)]
    Fallbacks:
      - If Pplat missing and Cstat given: Pplat = VT(L) / Cstat(L/cmH2O) + PEEP
      - If Pplat missing and only PIP given: assume resistive ~5 → Pplat = max(PIP − 5, PEEP)
      - If PIP missing but Pplat available: PIP = Pplat + 5 (resistive ~5)
    """
    VT_L = VT_ml / 1000.0
    Cstat_L = (Cstat_ml_per_cmH2O / 1000.0) if Cstat_ml_per_cmH2O else None

    # estimate Pplat if needed
    if Pplat is None:
        if Cstat_L and Cstat_L > 0:
            Pplat = VT_L / Cstat_L + PEEP
        elif PIP is not None:
            Pplat = max(PIP - 5.0, PEEP)  # heuristic
    # estimate PIP if needed
    if PIP is None and Pplat is not None:
        PIP = Pplat + 5.0

    # as a last resort, if still missing anything vital, return NaN
    if any(v is None or not math.isfinite(v) for v in (RR, VT_L, PEEP, Pplat, PIP)):
        return float("nan"), Pplat, PIP

    dP = max(Pplat - PEEP, 0.0)
    mp = K * RR * VT_L * (PIP - 0.5 * dP)
    return mp, Pplat, PIP

def mp_pc_prvc(RR, VT_ml, PEEP, Pplat=None, PIP=None, DeltaPinsp=None):
    """
    Pressure-controlled (and PRVC as pressure-regulated) approximation:
      In decelerating flow with negligible resistive peak,
      Pplat ≈ PIP, ΔP ≈ (Pplat − PEEP) ≈ (PIP − PEEP)
      MP ≈ 0.098 × RR × VT(L) × [PEEP + 0.5 × ΔP]
    Accept any of: (Pplat, PEEP) or (PIP, PEEP) or DeltaPinsp.
    """
    VT_L = VT_ml / 1000.0

    # derive ΔP
    dP = None
    if DeltaPinsp is not None and math.isfinite(DeltaPinsp):
        dP = max(DeltaPinsp, 0.0)
    elif Pplat is not None and math.isfinite(Pplat):
        dP = max(Pplat - PEEP, 0.0)
    elif PIP is not None and math.isfinite(PIP):
        dP = max(PIP - PEEP, 0.0)

    if any(v is None or not math.isfinite(v) for v in (RR, VT_L, PEEP)) or dP is None:
        return float("nan"), (Pplat if Pplat is not None else (PIP if PIP is not None else None)), (PIP if PIP is not None else Pplat)

    mp = K * RR * VT_L * (PEEP + 0.5 * dP)
    # pick a representative “plateau-like” and “peak-like” to show back
    used_pplat = Pplat if Pplat is not None else (PIP if PIP is not None else (PEEP + dP))
    used_pip   = PIP if PIP is not None else used_pplat
    return mp, used_pplat, used_pip

# ---- UI ----
st.set_page_config(page_title="Mechanical Power Calculator (VC / PC / PRVC)", layout="centered")

st.title("Mechanical Power Calculator")
st.caption("Mode-aware formulas with sensible ICU guardrails and pressure fallbacks.")

colA, colB = st.columns(2)
with colA:
    mode = st.selectbox("Ventilator mode", ["VC", "PC", "PRVC"])
with colB:
    rr = to_float(st.number_input("Respiratory rate (bpm)", min_value=1.0, max_value=80.0, value=18.0, step=1.0))

col1, col2, col3 = st.columns(3)
with col1:
    sex = st.selectbox("Sex (for PBW)", ["Male", "Female"])
with col2:
    height_cm = to_float(st.number_input("Height (cm)", min_value=100.0, max_value=220.0, value=170.0, step=1.0))
with col3:
    pbw = devine_pbw(sex, height_cm)
    st.metric("Predicted body weight (kg)", f"{pbw:.1f}" if math.isfinite(pbw) else "NA")

vt_mode = st.radio("VT input", ["VT per kg (mL/kg PBW)", "VT absolute (mL)"], horizontal=True)
if vt_mode == "VT per kg (mL/kg PBW)":
    vtkg = to_float(st.number_input("VT per kg (mL/kg)", min_value=3.0, max_value=12.0, value=6.0, step=0.2))
    vt_ml = vtkg * pbw if math.isfinite(pbw) else float("nan")
else:
    vt_ml = to_float(st.number_input("VT (mL)", min_value=50.0, max_value=1200.0, value=400.0, step=10.0))

colP1, colP2, colP3 = st.columns(3)
with colP1:
    peep = to_float(st.number_input("PEEP (cmH₂O)", min_value=0.0, max_value=30.0, value=10.0, step=1.0))
with colP2:
    pplat = st.text_input("Plateau (Pplat) cmH₂O [optional]", "")
    pplat = to_float(pplat, None)
with colP3:
    pip = st.text_input("Peak (PIP) cmH₂O [optional]", "")
    pip = to_float(pip, None)

extra = st.expander("Optional inputs and assumptions")
with extra:
    cstat_ml = st.text_input("Cstat (mL/cmH₂O) [optional, VC fallback]", "")
    cstat_ml = to_float(cstat_ml, None)
    dPinsp = st.text_input("ΔPinsp (cmH₂O) [optional, PC/PRVC]", "")
    dPinsp = to_float(dPinsp, None)
    st.write("Fallbacks used when needed:")
    st.write("• VC: Pplat = VT/Cstat + PEEP, else Pplat ≈ PIP − 5; PIP ≈ Pplat + 5")
    st.write("• PC/PRVC: ΔP ≈ PIP − PEEP or Pplat − PEEP")

# compute
mp = float("nan")
used_pplat, used_pip = None, None
if mode == "VC":
    mp, used_pplat, used_pip = mp_vc(rr, vt_ml, peep, Pplat=pplat, PIP=pip, Cstat_ml_per_cmH2O=cstat_ml)
else:
    mp, used_pplat, used_pip = mp_pc_prvc(rr, vt_ml, peep, Pplat=pplat, PIP=pip, DeltaPinsp=dPinsp)

# guardrails
pbw_ok = math.isfinite(pbw)
vtkg_calc = (vt_ml / pbw) if (pbw_ok and math.isfinite(vt_ml) and pbw > 0) else float("nan")
guard = {
    "VT/PBW 4–8 mL/kg": (4.0 <= vtkg_calc <= 8.0) if math.isfinite(vtkg_calc) else None,
    "RR 8–35 bpm": (8 <= rr <= 35) if math.isfinite(rr) else None,
    "PEEP 5–15 cmH₂O": (5 <= peep <= 15) if math.isfinite(peep) else None,
    "Plateau or PIP ≤30 cmH₂O": (max((used_pplat or 0), (used_pip or 0)) <= 30) if all(
        v is not None and math.isfinite(v) for v in (used_pplat, used_pip)
    ) else None,
}

st.markdown("---")
st.subheader("Results")
st.write(f"PBW ≈ {pbw:.1f} kg" if math.isfinite(pbw) else "PBW: NA")
st.write(f"VT ≈ {vtkg_calc:.2f} mL/kg PBW" if math.isfinite(vtkg_calc) else "VT/kg: NA")

if math.isfinite(mp):
    st.metric("Mechanical Power", f"{mp:.2f} J/min")
else:
    st.error("Insufficient inputs to compute MP for the selected mode. Provide Pplat or PIP (or ΔPinsp for PC/PRVC).")

# show pressures used
p_line = []
if used_pplat is not None and math.isfinite(used_pplat):
    p_line.append(f"Pplat used: {used_pplat:.1f}")
if used_pip is not None and math.isfinite(used_pip):
    p_line.append(f"PIP used: {used_pip:.1f}")
if p_line:
    st.caption(" | ".join(p_line))

st.markdown("#### Guardrails")
for k, ok in guard.items():
    if ok is None:
        st.write(f"• {k}: not assessed")
    else:
        st.write(f"• {k}: {'ok' if ok else 'outside'}")

st.markdown("---")
st.caption("VC formula: MP ≈ 0.098·RR·VT(L)·[Ppeak − 0.5·(Pplat−PEEP)]")
st.caption("PC/PRVC formula: MP ≈ 0.098·RR·VT(L)·[PEEP + 0.5·ΔP] with ΔP ≈ (Pplat−PEEP) or (PIP−PEEP)")      - If Pplat missing and Cstat given: Pplat = VT(L) / Cstat(L/cmH2O) + PEEP
      - If Pplat missing and only PIP given: assume resistive ~5 → Pplat = max(PIP − 5, PEEP)
      - If PIP missing but Pplat available: PIP = Pplat + 5 (resistive ~5)
    """
    VT_L = VT_ml / 1000.0
    Cstat_L = (Cstat_ml_per_cmH2O / 1000.0) if Cstat_ml_per_cmH2O else None

    # estimate Pplat if needed
    if Pplat is None:
        if Cstat_L and Cstat_L > 0:
            Pplat = VT_L / Cstat_L + PEEP
        elif PIP is not None:
            Pplat = max(PIP - 5.0, PEEP)  # heuristic
    # estimate PIP if needed
    if PIP is None and Pplat is not None:
        PIP = Pplat + 5.0

    # as a last resort, if still missing anything vital, return NaN
    if any(v is None or not math.isfinite(v) for v in (RR, VT_L, PEEP, Pplat, PIP)):
        return float("nan"), Pplat, PIP

    dP = max(Pplat - PEEP, 0.0)
    mp = K * RR * VT_L * (PIP - 0.5 * dP)
    return mp, Pplat, PIP

def mp_pc_prvc(RR, VT_ml, PEEP, Pplat=None, PIP=None, DeltaPinsp=None):
    """
    Pressure-controlled (and PRVC as pressure-regulated) approximation:
      In decelerating flow with negligible resistive peak,
      Pplat ≈ PIP, ΔP ≈ (Pplat − PEEP) ≈ (PIP − PEEP)
      MP ≈ 0.098 × RR × VT(L) × [PEEP + 0.5 × ΔP]
    Accept any of: (Pplat, PEEP) or (PIP, PEEP) or DeltaPinsp.
    """
    VT_L = VT_ml / 1000.0

    # derive ΔP
    dP = None
    if DeltaPinsp is not None and math.isfinite(DeltaPinsp):
        dP = max(DeltaPinsp, 0.0)
    elif Pplat is not None and math.isfinite(Pplat):
        dP = max(Pplat - PEEP, 0.0)
    elif PIP is not None and math.isfinite(PIP):
        dP = max(PIP - PEEP, 0.0)

    if any(v is None or not math.isfinite(v) for v in (RR, VT_L, PEEP)) or dP is None:
        return float("nan"), (Pplat if Pplat is not None else (PIP if PIP is not None else None)), (PIP if PIP is not None else Pplat)

    mp = K * RR * VT_L * (PEEP + 0.5 * dP)
    # pick a representative “plateau-like” and “peak-like” to show back
    used_pplat = Pplat if Pplat is not None else (PIP if PIP is not None else (PEEP + dP))
    used_pip   = PIP if PIP is not None else used_pplat
    return mp, used_pplat, used_pip

# ---- UI ----
st.set_page_config(page_title="Mechanical Power Calculator (VC / PC / PRVC)", layout="centered")

st.title("Mechanical Power Calculator")
st.caption("Mode-aware formulas with sensible ICU guardrails and pressure fallbacks.")

colA, colB = st.columns(2)
with colA:
    mode = st.selectbox("Ventilator mode", ["VC", "PC", "PRVC"])
with colB:
    rr = to_float(st.number_input("Respiratory rate (bpm)", min_value=1.0, max_value=80.0, value=18.0, step=1.0))

col1, col2, col3 = st.columns(3)
with col1:
    sex = st.selectbox("Sex (for PBW)", ["Male", "Female"])
with col2:
    height_cm = to_float(st.number_input("Height (cm)", min_value=100.0, max_value=220.0, value=170.0, step=1.0))
with col3:
    pbw = devine_pbw(sex, height_cm)
    st.metric("Predicted body weight (kg)", f"{pbw:.1f}" if math.isfinite(pbw) else "NA")

vt_mode = st.radio("VT input", ["VT per kg (mL/kg PBW)", "VT absolute (mL)"], horizontal=True)
if vt_mode == "VT per kg (mL/kg PBW)":
    vtkg = to_float(st.number_input("VT per kg (mL/kg)", min_value=3.0, max_value=12.0, value=6.0, step=0.2))
    vt_ml = vtkg * pbw if math.isfinite(pbw) else float("nan")
else:
    vt_ml = to_float(st.number_input("VT (mL)", min_value=50.0, max_value=1200.0, value=400.0, step=10.0))

colP1, colP2, colP3 = st.columns(3)
with colP1:
    peep = to_float(st.number_input("PEEP (cmH₂O)", min_value=0.0, max_value=30.0, value=10.0, step=1.0))
with colP2:
    pplat = st.text_input("Plateau (Pplat) cmH₂O [optional]", "")
    pplat = to_float(pplat, None)
with colP3:
    pip = st.text_input("Peak (PIP) cmH₂O [optional]", "")
    pip = to_float(pip, None)

extra = st.expander("Optional inputs and assumptions")
with extra:
    cstat_ml = st.text_input("Cstat (mL/cmH₂O) [optional, VC fallback]", "")
    cstat_ml = to_float(cstat_ml, None)
    dPinsp = st.text_input("ΔPinsp (cmH₂O) [optional, PC/PRVC]", "")
    dPinsp = to_float(dPinsp, None)
    st.write("Fallbacks used when needed:")
    st.write("• VC: Pplat = VT/Cstat + PEEP, else Pplat ≈ PIP − 5; PIP ≈ Pplat + 5")
    st.write("• PC/PRVC: ΔP ≈ PIP − PEEP or Pplat − PEEP")

# compute
mp = float("nan")
used_pplat, used_pip = None, None
if mode == "VC":
    mp, used_pplat, used_pip = mp_vc(rr, vt_ml, peep, Pplat=pplat, PIP=pip, Cstat_ml_per_cmH2O=cstat_ml)
else:
    mp, used_pplat, used_pip = mp_pc_prvc(rr, vt_ml, peep, Pplat=pplat, PIP=pip, DeltaPinsp=dPinsp)

# guardrails
pbw_ok = math.isfinite(pbw)
vtkg_calc = (vt_ml / pbw) if (pbw_ok and math.isfinite(vt_ml) and pbw > 0) else float("nan")
guard = {
    "VT/PBW 4–8 mL/kg": (4.0 <= vtkg_calc <= 8.0) if math.isfinite(vtkg_calc) else None,
    "RR 8–35 bpm": (8 <= rr <= 35) if math.isfinite(rr) else None,
    "PEEP 5–15 cmH₂O": (5 <= peep <= 15) if math.isfinite(peep) else None,
    "Plateau or PIP ≤30 cmH₂O": (max((used_pplat or 0), (used_pip or 0)) <= 30) if all(
        v is not None and math.isfinite(v) for v in (used_pplat, used_pip)
    ) else None,
}

st.markdown("---")
st.subheader("Results")
st.write(f"PBW ≈ {pbw:.1f} kg" if math.isfinite(pbw) else "PBW: NA")
st.write(f"VT ≈ {vtkg_calc:.2f} mL/kg PBW" if math.isfinite(vtkg_calc) else "VT/kg: NA")

if math.isfinite(mp):
    st.metric("Mechanical Power", f"{mp:.2f} J/min")
else:
    st.error("Insufficient inputs to compute MP for the selected mode. Provide Pplat or PIP (or ΔPinsp for PC/PRVC).")

# show pressures used
p_line = []
if used_pplat is not None and math.isfinite(used_pplat):
    p_line.append(f"Pplat used: {used_pplat:.1f}")
if used_pip is not None and math.isfinite(used_pip):
    p_line.append(f"PIP used: {used_pip:.1f}")
if p_line:
    st.caption(" | ".join(p_line))

st.markdown("#### Guardrails")
for k, ok in guard.items():
    if ok is None:
        st.write(f"• {k}: not assessed")
    else:
        st.write(f"• {k}: {'ok' if ok else 'outside'}")

st.markdown("---")
st.caption("VC formula: MP ≈ 0.098·RR·VT(L)·[Ppeak − 0.5·(Pplat−PEEP)]")
st.caption("PC/PRVC formula: MP ≈ 0.098·RR·VT(L)·[PEEP + 0.5·ΔP] with ΔP ≈ (Pplat−PEEP) or (PIP−PEEP)")
