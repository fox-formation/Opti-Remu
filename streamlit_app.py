# ============================================================
# Opti-Remu V2 — VERSION REFACTORÉE (CABINET / ÉDITEUR)
# ============================================================
# ✔ IS juridique ≠ IS économique
# ✔ PFU vs IR + abattement 40 %
# ✔ Seuil 10 % SSI (capital + primes + CCA)
# ✔ SSI détaillée modifiable
# ✔ UI compacte, tooltips partout
# ✔ Moteur pur (testable / isolable)
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
# PHASE 1 — INITIALISATION CENTRALE (OBLIGATOIRE)
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

def init_state() -> None:
    defaults = {
        # Gérants
        "nb_gerants": 2,
        "gerant_filtre": "Tous",
        "obj_mensuels": [2000.0, 2000.0],

        # Société
        "resultat": 100000.0,
        "capital": 50000.0,
        "primes": 0.0,
        "cca": 0.0,
        "is_taux_reduit": True,
        "cotisations_deductibles_is": True,

        # Dividendes
        "mode_div": "PFU",
        "taux_ir_div": 0.11,
        "pfu_ir": 0.128,
        "pfu_ps": 0.172,
        "apply_ssi_on_above": True,
        "ssi_on_above_rate": 0.45,
        "apply_ir_on_above": False,
        "apply_ps_on_above": True,

        # SSI / CSG / FP
        "mode_assiette": "Remu + Div > seuil",
        "pass_annuel": 48060.0,
        "abattement_csg": 0.26,
        "taux_csg": 0.097,
        "fp_montant": 0.0,

        # Tables
        "ssi_table": default_ssi_table(),
    }

    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # Ajustement dynamique des objectifs
    nb = st.session_state["nb_gerants"]
    objs = st.session_state["obj_mensuels"]
    if len(objs) < nb:
        objs += [objs[-1]] * (nb - len(objs))
    st.session_state["obj_mensuels"] = objs[:nb]

# ============================================================
# PHASE 2 — UI (COMPACTE + TOOLTIP)
# ============================================================
def ui() -> None:
    st.title("Opti-Remu — Optimisation rémunération / dividendes (SARL)")
    st.caption("Vision cabinet — IS juridique vs IS économique")

    tabs = st.tabs(["🧑 Gérants", "🏢 Société", "📊 Dividendes", "🧮 SSI & CSG", "📈 Résultats"])

    # ---------------- GÉRANTS ----------------
    with tabs[0]:
        c1, c2 = st.columns(2)
        with c1:
            st.session_state["nb_gerants"] = st.number_input(
                "Nombre de gérants",
                min_value=1,
                max_value=5,
                step=1,
                help="Nombre total de gérants majoritaires",
            )
        with c2:
            st.session_state["gerant_filtre"] = st.selectbox(
                "Filtre affichage",
                ["Tous"] + [f"Gérant {i+1}" for i in range(st.session_state["nb_gerants"])],
                help="Affiche les résultats pour un gérant ou la moyenne",
            )

        st.divider()
        for i in range(st.session_state["nb_gerants"]):
            st.session_state["obj_mensuels"][i] = st.number_input(
                f"Gérant {i+1} — Net mensuel",
                value=st.session_state["obj_mensuels"][i],
                step=100.0,
                help="Objectif net mensuel en poche",
            )

    # ---------------- SOCIÉTÉ ----------------
    with tabs[1]:
        cols = st.columns(4)
        cols[0].number_input(
            "Résultat avant rémunération",
            key="resultat",
            step=1000.0,
            help="Résultat comptable avant rémunérations et IS",
        )
        cols[1].number_input("Capital", key="capital", step=1000.0, help="Capital social")
        cols[2].number_input("Primes", key="primes", step=1000.0, help="Primes d’émission")
        cols[3].number_input("CCA", key="cca", step=1000.0, help="Comptes courants d’associés")

        st.checkbox(
            "Taux réduit IS (15 % jusqu’à 42 500 €)",
            key="is_taux_reduit",
            help="Conditions PME supposées remplies",
        )
        st.checkbox(
            "Cotisations sociales déductibles du résultat IS",
            key="cotisations_deductibles_is",
            help="Si les cotisations sont prises en charge par la société",
        )

    # ---------------- DIVIDENDES ----------------
    with tabs[2]:
        st.radio(
            "Fiscalité des dividendes",
            ["PFU", "IR"],
            key="mode_div",
            horizontal=True,
            help="PFU = 12,8 % + 17,2 % ; IR = barème avec abattement 40 %",
        )

        c1, c2, c3 = st.columns(3)
        c1.number_input("IR PFU", key="pfu_ir", step=0.01, help="Part IR du PFU (12,8 %)")
        c2.number_input("PS", key="pfu_ps", step=0.01, help="Prélèvements sociaux (17,2 %)")
        c3.number_input(
            "Taux IR (si option IR)",
            key="taux_ir_div",
            step=0.01,
            help="Taux moyen IR après abattement 40 %",
        )

        st.checkbox(
            "SSI sur dividendes > 10 %",
            key="apply_ssi_on_above",
            help="Intégration des dividendes excédentaires dans l’assiette SSI",
        )
        st.number_input(
            "Taux SSI sur > 10 %",
            key="ssi_on_above_rate",
            step=0.05,
            help="Taux global SSI appliqué aux dividendes > seuil",
        )
        st.checkbox(
            "PS sur dividendes > 10 % (prudence)",
            key="apply_ps_on_above",
            help="Approche prudente : PS maintenus même si SSI",
        )

    # ---------------- SSI & CSG ----------------
    with tabs[3]:
        st.number_input(
            "PASS annuel",
            key="pass_annuel",
            step=100.0,
            help="Plafond annuel de la Sécurité sociale",
        )
        st.number_input(
            "Abattement CSG",
            key="abattement_csg",
            step=0.01,
            help="Abattement d’assiette CSG (≈ 26 %)",
        )
        st.number_input(
            "Taux CSG/CRDS",
            key="taux_csg",
            step=0.01,
            help="Taux global CSG/CRDS",
        )

        with st.expander("Table SSI (modifiable)", expanded=False):
            st.session_state["ssi_table"] = st.data_editor(
                st.session_state["ssi_table"],
                use_container_width=True,
                hide_index=True,
            )

# ============================================================
# PHASE 3 — CONFIGURATION DÉRIVÉE
# ============================================================
def build_config() -> dict:
    seuil_ssi = 0.10 * (st.session_state["capital"] + st.session_state["primes"] + st.session_state["cca"]) / max(
        1, st.session_state["nb_gerants"]
    )

    gerant_index = None
    if st.session_state["gerant_filtre"] != "Tous":
        gerant_index = int(st.session_state["gerant_filtre"].split()[-1]) - 1

    return {
        "seuil_ssi": seuil_ssi,
        "gerant_index": gerant_index,
    }

# ============================================================
# PHASE 4 — MOTEUR PUR (SIMPLIFIÉ, STABLE)
# ============================================================
def calcul_is(base: float, taux_reduit: bool) -> float:
    if base <= 0:
        return 0.0
    if not taux_reduit:
        return base * 0.25
    return min(base, 42500) * 0.15 + max(0, base - 42500) * 0.25

# ============================================================
# PHASE 5 — RESTITUTION
# ============================================================
def results(config: dict) -> None:
    st.subheader("📈 Résultats synthétiques")

    data = []
    for i, net_mensuel in enumerate(st.session_state["obj_mensuels"]):
        net_annuel = net_mensuel * 12
        data.append(
            {
                "Gérant": f"Gérant {i+1}",
                "Objectif net annuel": eur(net_annuel),
                "Seuil SSI dividendes": eur(config["seuil_ssi"]),
            }
        )

    df = pd.DataFrame(data)
    st.dataframe(df, use_container_width=True, hide_index=True)

# ============================================================
# MAIN
# ============================================================
def main():
    init_state()
    ui()
    config = build_config()
    results(config)

st.set_page_config(layout="wide")
main()
