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

    remuneration_nette = st.number_input(
        "Rémunération nette annuelle souhaitée (€)",
        min_value=0,
        value=18000,
        step=500
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



st.divider()

# =========================
# SECTION 4 – Premiers calculs
# =========================
st.header("4️⃣ Premiers calculs")

# Objectif annuel par gérant
objectif_annuel = objectif_mensuel * 12

# Seuil des dividendes non soumis aux cotisations sociales
# Règle : 10 % du capital social / nombre de gérants
seuil_dividendes = (capital * 0.10) / nombre_gerants

st.write("🎯 Objectif annuel par gérant :", objectif_annuel, "€")
st.write("📌 Seuil annuel de dividendes non soumis aux cotisations sociales :", seuil_dividendes, "€")

# Lecture pédagogique
if objectif_annuel <= seuil_dividendes:
    st.success(
        "L’objectif annuel est inférieur ou égal au seuil des 10 %. "
        "➡️ Les dividendes peuvent suffire sans cotisations sociales."
    )
else:
    st.warning(
        "L’objectif annuel dépasse le seuil des 10 %. "
        "➡️ Une rémunération sera nécessaire pour compléter."
    )


st.divider()

# =========================
# SECTION 5 – Arbitrage dividendes / rémunération
# =========================
st.header("5️⃣ Arbitrage dividendes / rémunération")

# Dividendes utilisables sans cotisations sociales
dividendes_utilisables = min(objectif_annuel, seuil_dividendes)

# Reste à couvrir via rémunération
reste_a_couvrir = max(0, objectif_annuel - dividendes_utilisables)

st.write("💰 Dividendes mobilisables (sans cotisations sociales) :", dividendes_utilisables, "€")
st.write("📉 Reste à couvrir via rémunération :", reste_a_couvrir, "€")

if reste_a_couvrir == 0:
    st.success(
        "L’objectif annuel peut être atteint uniquement par dividendes "
        "sans cotisations sociales."
    )
else:
    st.info(
        "Les dividendes ne suffisent pas : "
        "une rémunération est nécessaire pour atteindre l’objectif."
    )

