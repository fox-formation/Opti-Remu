import streamlit as st

# Configuration générale de la page
st.set_page_config(
    page_title="Opti-Remu",
    layout="wide"
)

# Titre principal
st.title("Opti-Remu")
st.subheader("Outil d’optimisation de la rémunération des dirigeants (SARL – SSI)")

st.divider()

# =========================
# SECTION 1 – Paramètres généraux
# =========================
st.header("1️⃣ Paramètres généraux")

col1, col2 = st.columns(2)

with col1:
    objectif_mensuel = st.number_input(
        "Objectif de revenu net mensuel (€)",
        min_value=0,
        value=2000,
        step=100
    )

with col2:
    nombre_gerants = st.number_input(
        "Nombre de gérants",
        mi

