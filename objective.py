# objective.py
# Port of the digital-lung trial engine objective (digital-lung engine/digital_lung.py, E3-E4,
# protective selection from engine/run_trials.py E5.4).
#
# J = MP + w_dr * driving-pressure penalty + w_od * overdistension penalty
# Candidates must satisfy Pplat <= 30, driving pressure <= 15 cmH2O and VE >= 100 mL/kg PBW/min.
# The VE floor is added here; the pipeline's E5.4 selection does not have it.
#
# Uses the engine's population default parameters (BASE), not values fitted to the patient.

import math
from dataclasses import dataclass
from typing import List, Optional

BASE = dict(EL_spec=13.5, kappa=0.7, r=0.3, mu_c=5.0, g=15.0, sigma=5.0,
            eps_star=1.5, R_aw=10.0, IE=0.5)

# Pipeline grid (E5.4 search space). 10 mL/kg PBW is left out: it is above the 8 mL/kg rail used in mp_calc.py.
VT_GRID = [4, 6, 8]              # mL/kg PBW
PEEP_GRID = [5, 8, 10, 12, 15, 18, 20]
RR_GRID = [15, 20, 25]

PPLAT_MAX = 30.0
DP_MAX = 15.0
VE_KG_MIN = 100.0                # mL/kg PBW/min, the pipeline's matched minute ventilation (engine_spec_v1)
W_DR = 1.0                       # pipeline E5.4 weight pair (1, 1)
W_OD = 1.0


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def pbw_kg(sex: str, height_cm: float) -> float:
    h_in = float(height_cm) / 2.54
    if (sex or "").strip().lower().startswith("m"):
        return 50.0 + 2.3 * (h_in - 60.0)
    return 45.5 + 2.3 * (h_in - 60.0)


def frc(C: float, p: dict) -> float:
    return p["EL_spec"] * C / p["kappa"]


def fractions(peep: float, pplat: float, p: dict):
    hi_open = min(peep, pplat - p["g"])
    f_open = norm_cdf((hi_open - p["mu_c"]) / p["sigma"])
    f_cyc = max(norm_cdf((pplat - p["g"] - p["mu_c"]) / p["sigma"])
                - norm_cdf((peep - p["mu_c"]) / p["sigma"]), 0.0)
    return f_open, f_cyc


def mechanical_power(C: float, vt: float, rr: float, peep: float, p: dict = BASE) -> float:
    """J/min. vt in L, C in L/cmH2O, pressures in cmH2O, rr in /min."""
    K = (1 + p["IE"]) / (60 * p["IE"])
    return 0.098 * rr * (0.5 * vt ** 2 / C + rr * K * p["R_aw"] * vt ** 2 + peep * vt)


def penalties(C: float, vt: float, rr: float, peep: float, p: dict = BASE):
    """Returns (driving-pressure penalty, overdistension penalty, Pplat)."""
    pplat = peep + vt / C
    f_open, f_cyc = fractions(peep, pplat, p)
    F = frc(C, p)
    VR = p["r"] * F
    p_dr = 0.098 * rr * VR * f_cyc * (p["mu_c"] + p["g"])
    A = F + VR * f_open
    Vstar = p["eps_star"] * A
    Vpeep = C * peep
    Vei = Vpeep + vt
    EL = p["kappa"] / C
    if Vei > Vstar:
        p_od = 0.098 * rr * 0.5 * EL * (Vei ** 2 - max(Vpeep, Vstar) ** 2)
    else:
        p_od = 0.0
    return p_dr, p_od, pplat


@dataclass
class Setting:
    vt_kg: float
    peep: float
    rr: float
    mp: float
    p_dr: float
    p_od: float
    pplat: float
    dp: float
    ve_kg: float                 # minute ventilation, mL/kg PBW/min
    J: float
    feasible: bool


def evaluate(C_ml: float, pbw: float, vt_kg: float, peep: float, rr: float,
             w_dr: float = W_DR, w_od: float = W_OD, p: dict = BASE) -> Setting:
    """C_ml is static compliance in mL/cmH2O (as the engine's crs data)."""
    C = C_ml / 1000.0
    vt = vt_kg * pbw / 1000.0
    mp = mechanical_power(C, vt, rr, peep, p)
    p_dr, p_od, pplat = penalties(C, vt, rr, peep, p)
    dp = vt / C
    ve_kg = vt_kg * rr
    return Setting(vt_kg=vt_kg, peep=peep, rr=rr, mp=mp, p_dr=p_dr, p_od=p_od,
                   pplat=pplat, dp=dp, ve_kg=ve_kg, J=mp + w_dr * p_dr + w_od * p_od,
                   feasible=pplat <= PPLAT_MAX and dp <= DP_MAX and ve_kg >= VE_KG_MIN)


def search_grid(C_ml: float, pbw: float, w_dr: float = W_DR, w_od: float = W_OD,
                p: dict = BASE) -> List[Setting]:
    """All grid settings, sorted by J (feasible ones first)."""
    rows = [evaluate(C_ml, pbw, v, pe, r, w_dr, w_od, p)
            for v in VT_GRID for pe in PEEP_GRID for r in RR_GRID]
    return sorted(rows, key=lambda s: (not s.feasible, s.J))


def best_setting(C_ml: float, pbw: float, w_dr: float = W_DR, w_od: float = W_OD,
                 p: dict = BASE) -> Optional[Setting]:
    """Lowest-J feasible grid setting, or None if no grid setting is protective."""
    feasible = [s for s in search_grid(C_ml, pbw, w_dr, w_od, p) if s.feasible]
    return feasible[0] if feasible else None
