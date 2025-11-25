# mp_calc.py
# Mechanical Power calculator (VC simplified and PC/PRVC simplified)
# Uses the two formulas you approved.

"""
Clinician quick guide — variables and where to read them on the ventilator
Units expected: RR = breaths/min; VT = mL (code converts to L); pressures = cmH2O; Cstat = L/cmH2O; height = cm.

RR (total respiratory rate)
• Meaning: breaths per minute actually delivered (machine + patient-triggered).
• Where on vent: “fTotal”, “f tot”, “Total RR”.
• Tip: if patient is stable and not auto-cycling, RR set ≈ total; otherwise use total.

VT (tidal volume, exhaled) [vt_ml]
• Meaning: the volume leaving the lungs each breath.
• Where on vent: “VTe”, “Vt exp”, “VTE”.
• Tip: prefer exhaled VT; in VC you may use VT set only if VTe not shown or large leak makes VTe unreliable.

PEEP [peep]
• Meaning: end-expiratory positive pressure (set).
• Where on vent: “PEEP”.

Pplat (plateau pressure) [pplat]
• Meaning: alveolar pressure during an inspiratory hold (no flow) in VC/PRVC.
• Where on vent: “Pplat” after performing inspiratory pause/hold 0.3–0.5 s.
• Not available in pure PC; if missing and Cstat is known, this file can estimate it from VT/Cstat.

Ppeak / PIP [ppeak / pip]
• Meaning: peak airway pressure reached during inspiration.
• Where on vent: “Ppeak”, “Pmax”, “PIP”.
• In VC, if Ppeak is missing but Pplat present, code uses Ppeak ≈ Pplat + 5 cmH2O.
• In PC/PRVC, displayed PIP = PEEP + ΔPinsp.

ΔPinsp (pressure above PEEP) [delta_pinsp]
• Meaning: inspiratory pressure set above PEEP in PC/PRVC.
• Where on vent: “PC above PEEP”, “Pinsp”, “ΔP control”.
• If not shown, use ΔPinsp = PIP − PEEP.

Cstat (static compliance) [cstat_L_per_cmH2O]
• Meaning: ΔV/ΔP with no flow (static). Helpful when Pplat is unavailable.
• Where on vent: “Cstat”, “Compliance”.
• If not displayed: Cstat ≈ VTe(L) / (Pplat − PEEP).

PBW, sex, height [sex, height_cm]
• Used to compute predicted body weight and VT/PBW for guardrails (target 4–8 mL/kg).

Data entry tips
• Enter values averaged over the last 1–2 minutes at steady state.
• PRVC behaves like PC for these formulas: use ΔPinsp (or PIP − PEEP).
• If there is a major leak, prefer VC: VT set + measured Pplat; avoid inferring Pplat from Ppeak.
• Guardrails in this app: VT/PBW 4–8 mL/kg, RR 8–35, PEEP 5–15, Pplat/PIP ≤30.

Brand label quick map
• Servo-i/u: RR “f tot”; VT “VTe”; Ppeak “Ppeak”; Pplat via insp hold; ΔPinsp “PC above PEEP”.
• Dräger Evita/Infinity: RR “f total”; VT “Vt exp”; Ppeak “Pmax”; Pplat via insp hold; ΔPinsp “Pinsp”.
• Hamilton G5/C3: RR “fTotal”; VT “VTE”; Ppeak “Ppeak”; Pplat via insp hold; ΔPinsp “Pinsp/ΔP control”.
• Puritan Bennett 840/980: RR “Total RR”; VT “Vte”; Ppeak “Ppeak”; Pplat via insp hold; ΔPinsp “PC above PEEP”.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

K = 0.098  # conversion constant in J·min⁻¹ when pressures in cmH2O, VT in L, RR in bpm

def pbw_kg(sex: str, height_cm: float) -> float:
    """Predicted body weight (ARDSNet)."""
    sex = (sex or "").strip().lower()
    h_in = float(height_cm) / 2.54
    if sex.startswith("m"):
        return 50.0 + 2.3 * (h_in - 60.0)
    else:
        return 45.5 + 2.3 * (h_in - 60.0)

def safe_float(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default

@dataclass
class MPInputs:
    mode: str                    # "VC" or "PC" or "PRVC"
    rr_bpm: float                # breaths/min (total)
    vt_ml: float                 # mL (will be converted to L)
    peep: float                  # cmH2O

    # Optional pressures (provide what you have)
    pplat: Optional[float] = None        # cmH2O (VC)
    ppeak: Optional[float] = None        # cmH2O (VC)
    delta_pinsp: Optional[float] = None  # cmH2O (PC/PRVC) = Pinsp above PEEP
    pip: Optional[float] = None          # cmH2O (PC/PRVC) peak insp (≈ PEEP + ΔPinsp)

    # Optional aids
    cstat_L_per_cmH2O: Optional[float] = None  # if Pplat missing in VC, ΔP ≈ VT(L)/Cstat
    sex: Optional[str] = None
    height_cm: Optional[float] = None

def vc_mp_simplified(rr_bpm: float, vt_ml: float, peep: float,
                     pplat: Optional[float] = None,
                     ppeak: Optional[float] = None,
                     cstat_L_per_cmH2O: Optional[float] = None) -> Tuple[float, dict]:
    """
    VC simplified:
      MP ≈ 0.098 × RR × VT(L) × [ Ppeak − 0.5 × (Pplat − PEEP) ]
    Fallbacks:
      - If Pplat missing but Cstat present: Pplat ≈ VT(L)/Cstat + PEEP
      - If Ppeak missing but Pplat present: Ppeak ≈ Pplat + 5
    """
    vt_L = vt_ml / 1000.0
    rr = rr_bpm
    peep = peep

    est = {}
    # Estimate Pplat if needed
    if pplat is None and cstat_L_per_cmH2O not in (None, 0):
        pplat = vt_L / float(cstat_L_per_cmH2O) + peep
        est["pplat_from_cstat"] = round(pplat, 2)

    # If still missing Pplat, formula becomes unreliable
    if pplat is None:
        raise ValueError("VC formula needs Pplat (or Cstat to estimate it).")

    # Estimate Ppeak if needed
    if ppeak is None:
        ppeak = pplat + 5.0
        est["ppeak_from_pplat_plus5"] = round(ppeak, 2)

    term = (ppeak - 0.5 * (pplat - peep))
    mp = K * rr * vt_L * term
    return float(mp), {"vt_L": vt_L, "term": term, **est}

def pc_mp_simplified(rr_bpm: float, vt_ml: float, peep: float,
                     delta_pinsp: Optional[float] = None,
                     pip: Optional[float] = None) -> Tuple[float, dict]:
    """
    PC/PRVC simplified:
      MP ≈ 0.098 × RR × VT(L) × (PEEP + ΔPinsp)
    Fallback:
      - If ΔPinsp missing but PIP present: ΔPinsp = PIP − PEEP
    """
    vt_L = vt_ml / 1000.0
    rr = rr_bpm
    peep = peep

    est = {}
    if delta_pinsp is None and pip is not None:
        delta_pinsp = float(pip) - peep
        est["delta_pinsp_from_pip"] = round(delta_pinsp, 2)

    if delta_pinsp is None:
        raise ValueError("PC/PRVC formula needs ΔPinsp (or PIP to derive it).")

    term = peep + float(delta_pinsp)
    mp = K * rr * vt_L * term
    return float(mp), {"vt_L": vt_L, "term": term, **est}

def compute_mp(inp: MPInputs) -> Tuple[float, dict]:
    """Dispatcher that uses the right simplified formula based on mode."""
    mode = (inp.mode or "").strip().upper()
    if mode == "VC":
        return vc_mp_simplified(
            rr_bpm=inp.rr_bpm,
            vt_ml=inp.vt_ml,
            peep=inp.peep,
            pplat=inp.pplat,
            ppeak=inp.ppeak,
            cstat_L_per_cmH2O=inp.cstat_L_per_cmH2O
        )
    elif mode in ("PC", "PRVC"):
        return pc_mp_simplified(
            rr_bpm=inp.rr_bpm,
            vt_ml=inp.vt_ml,
            peep=inp.peep,
            delta_pinsp=inp.delta_pinsp,
            pip=inp.pip
        )
    else:
        raise ValueError("mode must be one of: 'VC', 'PC', 'PRVC'")

def guardrail_messages(inp: MPInputs) -> list:
    """
    Simple safety rails:
      VT/PBW 4–8 mL/kg (if sex+height known),
      RR 8–35 bpm,
      PEEP 5–15 cmH2O,
      Pplat ≤30 (VC when available),
      PIP ≤30 (PC/PRVC when available).
    """
    msgs = []
    if inp.sex and inp.height_cm:
        pbw = pbw_kg(inp.sex, inp.height_cm)
        vtkg = inp.vt_ml / pbw if pbw > 0 else None
        if vtkg is not None and not (4.0 <= vtkg <= 8.0):
            msgs.append(f"VT/PBW ≈ {vtkg:.2f} mL/kg (outside 4–8).")

    if not (8 <= inp.rr_bpm <= 35):
        msgs.append(f"RR {inp.rr_bpm:g} bpm (outside 8–35).")

    if not (5 <= inp.peep <= 15):
        msgs.append(f"PEEP {inp.peep:g} cmH2O (outside 5–15).")

    mode = (inp.mode or "").strip().upper()
    if mode == "VC" and inp.pplat is not None and inp.pplat > 30:
        msgs.append(f"Pplat {inp.pplat:g} > 30 cmH2O.")
    if mode in ("PC", "PRVC") and inp.pip is not None and inp.pip > 30:
        msgs.append(f"PIP {inp.pip:g} > 30 cmH2O.")

    return msgs

if __name__ == "__main__":
    # Example quick test (edit these values):
    example = MPInputs(mode="VC", rr_bpm=18, vt_ml=420, peep=8, pplat=26, ppeak=31)
    mp, info = compute_mp(example)
    print(f"MP = {mp:.2f} J/min | details: {info}")
    warnings = guardrail_messages(example)
    if warnings:
        print("Guardrails:", "; ".join(warnings))
