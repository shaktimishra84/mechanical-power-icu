def compute_mp_basic(
    mode: str,
    rr_bpm: float,
    vt_ml: float,
    peep: float,
    pplat: float | None = None,
    ppeak: float | None = None,
    delta_pinsp: float | None = None,
) -> float:
    """
    Mechanical power (J/min) using:
    - VCV:  MP = 0.098 * RR * VT_L * (Ppeak - 0.5 * (Pplat - PEEP))
    - PCV/PRVC: MP = 0.098 * RR * VT_L * (ΔPinsp + PEEP)
    """

    VT_L = vt_ml / 1000.0

    mode = mode.upper()
    if mode == "VC":
        if pplat is None or ppeak is None:
            raise ValueError("VC mode requires both Pplat and Ppeak.")
        dp = pplat - peep
        mp = 0.098 * rr_bpm * VT_L * (ppeak - 0.5 * dp)

    elif mode in ("PC", "PRVC"):
        if delta_pinsp is None:
            raise ValueError("PC/PRVC mode requires ΔPinsp (inspiratory pressure above PEEP).")
        mp = 0.098 * rr_bpm * VT_L * (delta_pinsp + peep)

    else:
        raise ValueError(f"Unsupported mode: {mode}")

    return mp
