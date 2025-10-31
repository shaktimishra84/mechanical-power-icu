import math, streamlit as st
st.set_page_config(page_title="Mechanical Power by Mode", page_icon="🫁", layout="centered")
st.title("Mechanical Power (mode-specific)")
st.caption("Passive patient assumption. Prefer measured plateau pressure when available.")
def pbw_kg(sex,h): 
    return None if not h or h<=0 else (45.5+0.91*(h-152.4) if sex=="Female" else 50+0.91*(h-152.4))
def nonneg(x): return max(0.0,x) if x is not None else None
def band(mp): return "low" if mp<12 else ("moderate" if mp<=17 else "high")
col0,col1=st.columns(2)
with col0: mode=st.selectbox("Ventilator mode",["Volume-controlled (VCV)","Pressure-controlled (PCV)","PRVC"])
with col1: rr=st.number_input("Respiratory rate (breaths/min)",4,60,20)
col2,col3,col4=st.columns(3)
with col2: vt_ml=st.number_input("Tidal volume VT (mL)",50.0,1200.0,420.0,step=10.0)
with col3: peep=st.number_input("PEEP (cmH₂O)",0.0,24.0,10.0)
with col4: sex=st.selectbox("Sex (for PBW)",["Male","Female"]); height_cm=st.number_input("Height (cm)",120.0,220.0,170.0,step=0.5)
pbw=pbw_kg(sex,height_cm);  vt_l=vt_ml/1000.0
if pbw: st.caption(f"Predicted body weight ≈ {pbw:.1f} kg")
mp=None; dp=None; used=None; notes=[]
if mode=="Volume-controlled (VCV)":
    st.subheader("VCV inputs"); c1,c2,c3=st.columns(3)
    with c1: ppeak=st.number_input("Peak airway pressure Ppeak (cmH₂O)",0.0,80.0,25.0)
    with c2: have_pplat=st.checkbox("I have plateau pressure (Pplat)",True)
    with c3: pplat=st.number_input("Plateau pressure Pplat (cmH₂O)",0.0,80.0,22.0) if have_pplat else None
    insp_flow=None
    if not have_pplat:
        st.markdown("No Pplat → surrogate formula needs inspiratory flow.")
        d1,d2=st.columns(2)
        with d1: know_flow=st.checkbox("I know Inspiratory Flow (L/min)",True)
        if know_flow: insp_flow=st.number_input("Inspiratory Flow (L/min)",10.0,120.0,60.0,step=1.0)
        else:
            with d2: ti_s=st.number_input("Inspiratory time Ti (s)",0.2,5.0,1.0,step=0.1)
            insp_flow=vt_l/(ti_s/60.0)
    if st.button("Compute mechanical power",key="btn_vcv"):
        if have_pplat and pplat is not None:
            mp=0.098*rr*vt_l*(ppeak-0.5*(pplat-peep)); dp=pplat-peep
            used="VCV comprehensive: 0.098×RR×VT×[Ppeak − ½×(Pplat−PEEP)]"
            notes+=["Assumes constant flow & passive patient.","Use inspiratory hold to measure Pplat."]
        else:
            ve=rr*vt_l; mp=ve*(ppeak+peep+(insp_flow or 0)/6.0)/20.0
            used="VCV surrogate (no Pplat): VE×[Ppeak+PEEP+InspFlow/6]/20"
            notes+=["Surrogate without Pplat; accuracy depends on constant flow.","Measure Pplat when feasible."]
        mp=nonneg(mp)
elif mode=="Pressure-controlled (PCV)":
    st.subheader("PCV inputs"); c1,c2,c3=st.columns(3)
    with c1: dpinsp=st.number_input("ΔPinsp above PEEP (cmH₂O)",0.0,50.0,15.0,step=1.0)
    with c2: have_full=st.checkbox("I have R, C and Tinsp (comprehensive)",False)
    with c3: pplat_meas=st.text_input("Optional: measured Pplat (cmH₂O)","")
    if have_full:
        d1,d2,d3=st.columns(3)
        with d1: tinsp_s=st.number_input("Inspiratory time Tinsp (s)",0.2,5.0,1.0,step=0.1)
        with d2: R=st.number_input("Airway resistance R (cmH₂O·s/L)",2.0,50.0,10.0,step=0.5)
        with d3: C_ml=st.number_input("Compliance C (mL/cmH₂O)",5.0,150.0,40.0,step=1.0)
    if st.button("Compute mechanical power",key="btn_pcv"):
        if have_full:
            C_L=C_ml/1000.0; import math
            factor=1.0-math.exp(-(tinsp_s/(R*C_L)))
            mp=0.098*rr*vt_l*(peep+dpinsp*factor)
            used="PCV comprehensive: 0.098×RR×VT×[PEEP + ΔPinsp×(1−e^(−Tinsp/(R×C)))]"
            notes+=["Needs accurate R,C,Tinsp; passive patient.","If end-insp flow ~0, factor→1."]
        else:
            mp=0.098*rr*vt_l*(peep+dpinsp)
            used="PCV simplified: 0.098×RR×VT×[PEEP + ΔPinsp]"
            notes+=["Square-wave assumption; decelerating flow may lower true value.","Confirm with comprehensive inputs if possible."]
        mp=nonneg(mp)
        try:
            if pplat_meas.strip(): dp=float(pplat_meas)-peep
        except: dp=None
else:
    st.subheader("PRVC inputs"); c1,c2=st.columns(2)
    with c1: dpinsp=st.number_input("ΔPinsp above PEEP (cmH₂O)",0.0,50.0,12.0,step=1.0)
    with c2: st.caption("PRVC auto-adjusts ΔPinsp to hit target VT; recompute after changes.")
    if st.button("Compute mechanical power",key="btn_prvc"):
        mp=0.098*rr*vt_l*(peep+dpinsp); mp=nonneg(mp)
        used="PRVC (treated as PCV simplified): 0.098×RR×VT×[PEEP + ΔPinsp]"
        notes+=["Assumes passive patient.","Recalculate after PRVC auto-adjusts ΔPinsp."]
if mp is not None:
    cA,cB,cC=st.columns(3)
    with cA:
        if dp is not None: st.metric("Driving pressure",f"{dp:.1f} cmH₂O")
    with cB: st.metric("Mechanical power",f"{mp:.1f} J/min")
    with cC:
        if pbw: st.metric("MP per kg PBW",f"{(mp/pbw):.2f} J/min/kg")
    st.write("Formula used: "+used); st.write("Precautions: "+" ".join(notes))
st.markdown("---"); st.caption("Bands: <12 low, 12–17 moderate, >17 high J/min. Interpret with gas exchange & mechanics.")
