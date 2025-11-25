# mp_calc.py
# Mechanical Power calculator + “next best move” suggester
# VC and PC/PRVC use the simplified Gattinoni forms you approved.

from dataclasses import dataclass
from typing import Optional, Tuple, Dict, List
import json
import math

K = 0.098  # J·min⁻¹ when pressures in cmH2O, VT in L, RR in bpm

# default rails (you can loosen/tighten in app)
DEFAULT_VT_MIN = 4.0   # mL/kg PBW
DEFAULT_VT_MAX = 8.0   # mL/kg PBW
DEFAULT_RR_MIN = 8
DEFAULT_RR_MAX = 35
DEFAULT_PEEP_MIN = 5
DEFAULT_PEEP_MAX = 40   # you asked to allow up to 40
PEAK_LIMIT_NOTE = 30    # warn only; does not block

def pbw_kg(sex: str, height_cm: float) -> float:
    sex = (sex or "").strip().lower()
    h_in = float(height_cm) / 2.54
    if sex.startswith("m"):
        return 50.0 + 2.3 * (h_in - 60.0)
    else:
        return 45.5 + 2.3 * (h_in - 60.0)

@dataclass
class MPInputs:
    mode: str                    # "VC" or "PC" or "PRVC"
    rr_bpm: float
    vt_ml: float
    peep: float

    # VC pressures
    pplat: Optional[float] = None
    ppeak: Optional[float] = None
    cstat_L_per_cmH2O: Optional[float] = None

    # PC/PRVC pressures
    delta_pinsp: Optional[float] = None  # Pinsp above PEEP
    pip: Optional[float] = None

    # optional for rails
    sex: Optional[str] = None
    height_cm: Optional[float] = None

def vc_mp_simplified(rr_bpm: float, vt_ml: float, peep: float,
                     pplat: Optional[float] = None,
                     ppeak: Optional[float] = None,
                     cstat_L_per_cmH2O: Optional[float] = None) -> Tuple[float, Dict]:
    """
    MP ≈ 0.098 × RR × VT(L) × [ Ppeak − 0.5 × (Pplat − PEEP) ]
    Fallbacks:
      - if Pplat missing but Cstat present: Pplat ≈ VT(L)/Cstat + PEEP
      - if Ppeak missing: Ppeak ≈ Pplat + 5
    """
    vt_L = vt_ml / 1000.0
    est = {}
    if pplat is None and cstat_L_per_cmH2O not in (None, 0):
        pplat = vt_L / float(cstat_L_per_cmH2O) + peep
        est["pplat_from_cstat"] = round(pplat, 2)
    if pplat is None:
        raise ValueError("VC requires Pplat (or Cstat to estimate it).")
    if ppeak is None:
        ppeak = pplat + 5.0
        est["ppeak_from_pplat_plus5"] = round(ppeak, 2)
    term = (ppeak - 0.5 * (pplat - peep))
    mp = K * rr_bpm * vt_L * term
    return float(mp), {"vt_L": vt_L, "term": term, **est}

def pc_mp_simplified(rr_bpm: float, vt_ml: float, peep: float,
                     delta_pinsp: Optional[float] = None,
                     pip: Optional[float] = None) -> Tuple[float, Dict]:
    """
    MP ≈ 0.098 × RR × VT(L) × (PEEP + ΔPinsp)
    Fallback: if ΔPinsp missing but PIP present, ΔPinsp = PIP − PEEP
    """
    vt_L = vt_ml / 1000.0
    est = {}
    if delta_pinsp is None and pip is not None:
        delta_pinsp = float(pip) - peep
        est["delta_pinsp_from_pip"] = round(delta_pinsp, 2)
    if delta_pinsp is None:
        raise ValueError("PC/PRVC requires ΔPinsp (or PIP to derive it).")
    term = peep + float(delta_pinsp)
    mp = K * rr_bpm * vt_L * term
    return float(mp), {"vt_L": vt_L, "term": term, **est}

def compute_mp(inp: MPInputs) -> Tuple[float, Dict]:
    mode = (inp.mode or "").strip().upper()
    if mode == "VC":
        return vc_mp_simplified(inp.rr_bpm, inp.vt_ml, inp.peep,
                                inp.pplat, inp.ppeak, inp.cstat_L_per_cmH2O)
    elif mode in ("PC", "PRVC"):
        return pc_mp_simplified(inp.rr_bpm, inp.vt_ml, inp.peep,
                                inp.delta_pinsp, inp.pip)
    else:
        raise ValueError("mode must be 'VC', 'PC', or 'PRVC'")

def guardrail_messages(inp: MPInputs) -> List[str]:
    msgs = []
    if inp.sex and inp.height_cm:
        pbw = pbw_kg(inp.sex, inp.height_cm)
        if pbw > 0:
            vtkg = inp.vt_ml / pbw
            if not (DEFAULT_VT_MIN <= vtkg <= DEFAULT_VT_MAX):
                msgs.append(f"VT/PBW ≈ {vtkg:.2f} mL/kg (outside {DEFAULT_VT_MIN:.0f}–{DEFAULT_VT_MAX:.0f}).")
    if not (DEFAULT_RR_MIN <= inp.rr_bpm <= DEFAULT_RR_MAX):
        msgs.append(f"RR {inp.rr_bpm:g} bpm (outside {DEFAULT_RR_MIN}–{DEFAULT_RR_MAX}).")
    if not (DEFAULT_PEEP_MIN <= inp.peep <= DEFAULT_PEEP_MAX):
        msgs.append(f"PEEP {inp.peep:g} cmH2O (outside {DEFAULT_PEEP_MIN}–{DEFAULT_PEEP_MAX}).")

    mode = (inp.mode or "").strip().upper()
    if mode == "VC" and inp.pplat is not None and inp.pplat > PEAK_LIMIT_NOTE:
        msgs.append(f"Pplat {inp.pplat:g} > {PEAK_LIMIT_NOTE} cmH2O.")
    if mode in ("PC", "PRVC") and inp.pip is not None and inp.pip > PEAK_LIMIT_NOTE:
        msgs.append(f"PIP {inp.pip:g} > {PEAK_LIMIT_NOTE} cmH2O.")
    return msgs

# ---- Next-best move logic ----

Move = Dict[str, float]  # {"rr_bpm": new_rr, "vt_ml": new_vt, "peep": new_peep, "delta_pinsp": new_delta, ...}

def load_priors(path: str) -> Optional[Dict]:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None

def candidate_moves(inp: MPInputs) -> List[str]:
    mode = (inp.mode or "").upper()
    moves = []
    # always consider RR -2 if within rails
    if inp.rr_bpm - 2 >= DEFAULT_RR_MIN:
        moves.append("RR -2")
    # PEEP -1 if within rails
    if inp.peep - 1 >= DEFAULT_PEEP_MIN:
        moves.append("PEEP -1")
    if mode == "VC":
        # VT -50 if not driving VT/PBW below min (if PBW known)
        ok = True
        if inp.sex and inp.height_cm:
            pbw = pbw_kg(inp.sex, inp.height_cm)
            if pbw > 0 and (inp.vt_ml - 50) / pbw < DEFAULT_VT_MIN:
                ok = False
        if inp.vt_ml - 50 <= 150:  # crude absolute floor
            ok = False
        if ok:
            moves.append("VT -50")
    else:
        # ΔPinsp -2 if we can compute ΔPinsp
        dpin = inp.delta_pinsp
        if dpin is None and inp.pip is not None:
            dpin = float(inp.pip) - inp.peep
        if dpin is not None and dpin - 2 >= 0:
            moves.append("ΔPinsp -2")
    return moves

def apply_move(inp: MPInputs, move: str) -> Tuple[float, Dict]:
    # produce a shallow copy of inputs with one change
    j = MPInputs(**vars(inp))
    if move == "RR -2":
        j.rr_bpm = max(DEFAULT_RR_MIN, inp.rr_bpm - 2)
    elif move == "PEEP -1":
        j.peep = max(DEFAULT_PEEP_MIN, inp.peep - 1)
    elif move == "VT -50":
        j.vt_ml = max(0.0, inp.vt_ml - 50.0)
    elif move == "ΔPinsp -2":
        if j.delta_pinsp is not None:
            j.delta_pinsp = max(0.0, j.delta_pinsp - 2.0)
        elif j.pip is not None:
            j.pip = max(j.peep, j.pip - 2.0)  # lower PIP by 2
        else:
            raise ValueError("Cannot apply ΔPinsp -2 without ΔPinsp or PIP.")
    else:
        raise ValueError("Unknown move")
    new_mp, _ = compute_mp(j)
    return new_mp, vars(j)

def rank_moves(inp: MPInputs, priors: Optional[Dict]=None) -> List[Dict]:
    base_mp, _ = compute_mp(inp)
    out = []
    for m in candidate_moves(inp):
        try:
            new_mp, _state = apply_move(inp, m)
            delta = base_mp - new_mp
            prior = None
            if priors:
                mode = (inp.mode or "").upper()
                if mode in priors and m in priors[mode]:
                    prior = float(priors[mode][m]["mean_abs_drop"])
            score = (delta if not math.isnan(delta) else -1e9)
            # tiny tie-break: add 1e-3 * prior (safe; does nothing if priors absent)
            if prior is not None:
                score += 1e-3 * prior
            out.append({
                "move": m,
                "base_mp": base_mp,
                "new_mp": new_mp,
                "abs_drop": delta,
                "prior_abs_drop": prior
            })
        except Exception:
            # ignore moves we cannot evaluate due to missing pressures
            continue
    out.sort(key=lambda r: r["abs_drop"], reverse=True)
    return out

def greedy_plan(inp: MPInputs, priors: Optional[Dict]=None, steps: int=3) -> List[Dict]:
    plan = []
    cur = MPInputs(**vars(inp))
    for _ in range(steps):
        ranked = rank_moves(cur, priors)
        if not ranked:
            break
        best = ranked[0]
        if best["abs_drop"] <= 0:
            break
        # commit the best move to state
        if best["move"] == "RR -2":
            cur.rr_bpm = max(DEFAULT_RR_MIN, cur.rr_bpm - 2)
        elif best["move"] == "PEEP -1":
            cur.peep = max(DEFAULT_PEEP_MIN, cur.peep - 1)
        elif best["move"] == "VT -50":
            cur.vt_ml = max(0.0, cur.vt_ml - 50.0)
        elif best["move"] == "ΔPinsp -2":
            if cur.delta_pinsp is not None:
                cur.delta_pinsp = max(0.0, cur.delta_pinsp - 2.0)
            elif cur.pip is not None:
                cur.pip = max(cur.peep, cur.pip - 2.0)
            else:
                break
        plan.append(best)
    return plan

CLINICIAN_GUIDE = """
Clinician quick guide — variables and where to read them on the ventilator
Units: RR breaths/min; VT mL; pressures cmH2O; Cstat L/cmH2O; height cm.

RR (total) — actual total frequency (machine + patient). Labels: fTotal, Total RR.
VT (exhaled) — VTe / Vt exp / VTE. Prefer exhaled VT.
PEEP — set PEEP.
Pplat — plateau during insp hold (VC/PRVC). If absent but Cstat known: Pplat ≈ VT(L)/Cstat + PEEP.
Ppeak / PIP — peak airway pressure. VC fallback: Ppeak ≈ Pplat + 5.
ΔPinsp — inspiratory pressure above PEEP (PC/PRVC). If not shown: ΔPinsp = PIP − PEEP.
Cstat — static compliance. If not displayed: Cstat ≈ VTe(L) / (Pplat − PEEP).
PBW — for VT/PBW rails (ARDSNet).

Brand map: Servo (f tot, VTe, Ppeak, Pplat); Dräger (f total, Vt exp, Pmax, Pplat); Hamilton (fTotal, VTE, Ppeak, Pplat); PB 840/980 (Total RR, Vte, Ppeak, Pplat).
"""
