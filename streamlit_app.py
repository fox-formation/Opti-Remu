# ============================================================
# OPTI-REMU — VERSION CABINET / GESTION DE PATRIMOINE
# ============================================================

from __future__ import annotations
import streamlit as st
import pandas as pd

# ============================================================
# HELPERS
# ============================================================
def eur(x: float) -> str:
    return f"{x:,.0f} €".replace(",", " ")

def safe_div(a: float, b: float) -> float:
    return 0.0 if b == 0 else a / b

# ============================================================
# PHASE 1 — INITIALISATION CENTRALE
# ============================================================
def default_ssi_table() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Cotisation": "Maladie – maternité", "Taux": 0.065},
            {"Cotisation": "Allocations familiales", "Taux": 0.031},
            {"Cotisation": "Retraite de base", "Taux": 0.1715},
            {"Cotisation": "Retraite complémentaire", "Taux": 0.081},
            {"Cotisation": "Invalidité – décès", "Taux": 0.013},
        ]
    )

def init_state():
    defaults = {
        # Gérants
        "nb_gerants": 2,
        "obj_mensuels": [2000.0, 2000.0],
        "gerant_filtre": "Tous",

        # Société
        "resultat": 100000.0,
        "capital": 50000.0,
        "primes": 0.0,
        "cca": 0.0,
        "is_taux_reduit": True,
        "cotisations_deductibles_is": True,

        # Dividendes
        "mode_div": "PFU",
        "pfu_ir": 0.128,
        "pfu_ps": 0.172,
        "taux_ir_div": 0.11,
        "apply_ssi_on_above": True,
        "ssi_on_above_rate": 0.45,
        "apply_ps_on_above": True,

        # SSI / CSG / FP
        "pass_annuel": 48060.0,
        "abattement_csg": 26.0,
        "taux_csg": 9.7,
        "fp_montant": 0.0,

        # SSI table
        "ssi_table": default_ssi_table(),

        # Scénarios (MODIFIABLES)
        "scenarios": {
            "A – 100 % rémunération": {"rem": 100, "div": 0},
            "B – 75 % rémunération / 25 % dividendes": {"rem": 75, "div": 25},
            "C – 50 % / 50 %": {"rem": 50, "div": 50},
            "D – 25 % / 75 %": {"rem": 25, "div": 75},
            "E – 100 % dividendes": {"rem": 0, "div": 100},
        },
    }

    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    nb = st.session_state["nb_gerants"]
    objs = st.session_state["obj_mensuels"]
    if len(objs) < nb:
        objs += [objs[-1]] * (nb - len(objs))
    st.session_state["obj_mensuels"] = objs[:nb]

# ============================================================
# PHASE 2 — UI
# ============================================================
def ui():
    st.title("Opti-Remu — Optimisation rémunération & dividendes")
    st.caption("Approche expert fiscalité & gestion de patrimoine")

    tabs = st.tabs(["🧑 Gérants", "🏢 Société", "📊 Dividendes", "🧮 SSI & CSG", "🧠 Scénarios", "📈 Résultats"])

    # ---------------- GÉRANTS ----------------
    with tabs[0]:
        st.session_state["nb_gerants"] = st.number_input(
            "Nombre de gérants",
            min_value=1,
            max_value=5,
            step=1,
            help="Nombre de gérants majoritaires",
        )

        for i in range(st.session_state["nb_gerants"]):
            st.session_state["obj_mensuels"][i] = st.number_input(
                f"Gérant {i+1} — Objectif net mensuel",
                value=st.session_state["obj_mensuels"][i],
                step=100.0,
                help="Net annuel cible en poche",
            )

    # ---------------- SOCIÉTÉ ----------------
    with tabs[1]:
        st.number_input("Résultat avant rémunération", key="resultat", step=1000.0)
        st.number_input("Capital social", key="capital", step=1000.0)
        st.number_input("Primes d’émission", key="primes", step=1000.0)
        st.number_input("CCA", key="cca", step=1000.0)

        st.checkbox("Taux réduit IS", key="is_taux_reduit")
        st.checkbox("Cotisations déductibles IS", key="cotisations_deductibles_is")

    # ---------------- DIVIDENDES ----------------
    with tabs[2]:
        st.radio("Fiscalité des dividendes", ["PFU", "IR"], key="mode_div", horizontal=True)
        st.number_input("IR PFU", key="pfu_ir", step=0.01)
        st.number_input("PS", key="pfu_ps", step=0.01)
        st.number_input("Taux IR (option IR)", key="taux_ir_div", step=0.01)

        st.checkbox("SSI sur dividendes > 10 %", key="apply_ssi_on_above")
        st.number_input("Taux SSI sur > 10 %", key="ssi_on_above_rate", step=0.05)
        st.checkbox("PS maintenus sur > 10 % (prudence)", key="apply_ps_on_above")

    # ---------------- SSI & CSG ----------------
    with tabs[3]:
        st.number_input("PASS", key="pass_annuel", step=100.0)
        st.number_input("Abattement CSG (%)", key="abattement_csg", step=0.1)
        st.number_input("CSG / CRDS (%)", key="taux_csg", step=0.1)
        st.number_input("FP / CFP (montant annuel)", key="fp_montant", step=50.0)

        with st.expander("Détail SSI (modifiable)"):
            st.session_state["ssi_table"] = st.data_editor(
                st.session_state["ssi_table"],
                use_container_width=True,
                hide_index=True,
            )

    # ---------------- SCÉNARIOS ----------------
    with tabs[4]:
        st.caption("Scénarios patrimoniaux — modifiables")
        for name, s in st.session_state["scenarios"].items():
            c1, c2 = st.columns(2)
            with c1:
                s["rem"] = st.number_input(f"{name} — % rémunération", value=s["rem"], step=5)
            with c2:
                s["div"] = st.number_input(f"{name} — % dividendes", value=s["div"], step=5)

# ============================================================
# PHASE 3 — MOTEUR (SIMPLIFIÉ & STABLE)
# ============================================================
def calcul_is(base: float, taux_reduit: bool) -> float:
    if base <= 0:
        return 0.0
    if not taux_reduit:
        return base * 0.25
    return min(base, 42500) * 0.15 + max(0, base - 42500) * 0.25

# ============================================================
# PHASE 4 — RÉSULTATS & TABLEAU PATRIMONIAL
# ============================================================
def results():
    st.subheader("📊 Tableau synthétique — Analyse patrimoniale")

    seuil_ssi = 0.10 * (st.session_state["capital"] + st.session_state["primes"] + st.session_state["cca"]) / max(
        1, st.session_state["nb_gerants"]
    )

    rows = []

    for scen, s in st.session_state["scenarios"].items():
        total_net = sum(st.session_state["obj_mensuels"]) * 12
        part_rem = total_net * s["rem"] / 100
        part_div = total_net * s["div"] / 100

        ssi_div = max(0.0, part_div - seuil_ssi) * st.session_state["ssi_on_above_rate"] if st.session_state["apply_ssi_on_above"] else 0.0
        ps_div = part_div * st.session_state["pfu_ps"]
        ir_div = part_div * (st.session_state["pfu_ir"] if st.session_state["mode_div"] == "PFU" else st.session_state["taux_ir_div"])

        cotisations = part_rem * st.session_state["ssi_table"]["Taux"].sum() + ssi_div
        impots_perso = ir_div + ps_div

        base_is_j = st.session_state["resultat"] - part_rem - (cotisations if st.session_state["cotisations_deductibles_is"] else 0)
        is_j = calcul_is(base_is_j, st.session_state["is_taux_reduit"])

        base_is_e = base_is_j - impots_perso
        is_e = calcul_is(base_is_e, st.session_state["is_taux_reduit"])

        rows.append(
            {
                "Scénario": scen,
                "Rémunération nette": eur(part_rem),
                "Dividendes nets": eur(part_div),
                "Cotisations sociales": eur(cotisations),
                "Impôts personnels": eur(impots_perso),
                "IS juridique": eur(is_j),
                "IS économique": eur(is_e),
                "Total prélèvements (juridique)": eur(cotisations + impots_perso + is_j),
                "Total prélèvements (éco)": eur(cotisations + impots_perso + is_e),
            }
        )

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

# ============================================================
# MAIN
# ============================================================
st.set_page_config(layout="wide")
init_state()
ui()
results()
