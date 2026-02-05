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
        min_value=1,
        value=2,
        step=1
    )

st.divider()

# =========================
# SECTION 2 – Informations société
# =========================
st.header("2️⃣ Données de la société")

col3, col4, col5 = st.columns(3)

with col3:
    resultat = st.number_input(
        "Résultat avant rémunération et avant IS (€)",
        min_value=0,
        value=100000,
        step=1000
    )

with col4:
    capital = st.number_input(
        "Capital social (€)",
        min_value=0,
        value=50000,
        step=1000
    )

with col5:
    taux_is = st.number_input(
        "Taux d’IS (%)",
        min_value=0.0,
        value=15.0,
        step=0.1
    )

st.divider()

# =========================
# SECTION 3 – Résumé (temporaire)
# =========================
st.header("3️⃣ Résumé (test)")

st.write("Objectif annuel par gérant :", objectif_mensuel * 12, "€")
st.write("Résultat société :", resultat, "€")
st.write("Capital social :", capital, "€")
st.write("Taux IS :", taux_is, "%")


