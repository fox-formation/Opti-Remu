import math
import pandas as pd
import numpy as np
import streamlit as st

# =========================
# Helpers (format / math)
# =========================
def fmt_eur(x: float) -> str:
    return f"{x:,.0f} €".replace(",", " ")

def fmt_num(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ")

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def piecewise_linear_rate(x: float, points):
    """
    points: list of (x_ratio, rate) with x_ratio increasing
    returns the interpolated rate for x ratio.
    if x below min -> rate at min
    if above max -> rate at max
    """
    if not points:
        return 0.0
    if x <= points[0][0]:
        return float(points[0][1])
    for i in range(len(points) - 1):
        x1, r1 = points[i]
        x2, r2 = points[i + 1]
        if x1 <= x <= x2:
            if x2 == x1:
                return float(r2)
            t = (x - x1) / (x2 - x1)
            return float(r1 + t * (r2 - r1))
    return float(points[-1][1])

def safe_div(a, b):
    return 0.0 if b == 0 else a / b

# =========================
# Social model (editable)
# =========================
def default_social_params(pass_annuel: float) -> pd.DataFrame:
    """
    Cotisations hors CSG/CRDS & FP (détail modifiable).
    Valeurs par défaut basées sur le tableau fourni (PASS paramétrable).
    """
    return pd.DataFrame(
        [
            # Maladie-maternité : taux effectif progressif selon % PASS (approx)
            {
                "Ligne": "Maladie - maternité (taux effectif progressif)",
                "Type": "progressif_effectif",
                "Actif": True,
                # points (ratio PASS -> taux)
                "x1": 0.20, "r1": 0.00,
                "x2": 0.40, "r2": 0.015,
                "x3": 0.60, "r3": 0.040,
                "x4": 1.10, "r4": 0.065,
                "x5": 2.00, "r5": 0.077,
                "x6": 3.00, "r6": 0.085,
                "x7": 9.99, "r7": 0.065,  # au-delà 300% PASS: 6,5%
                "plafond_mult": 999.0,
            },
            # Allocations familiales (taux progressif 0 -> 3,1% entre 110% et 140% PASS)
            {
                "Ligne": "Allocations familiales (progressif 0% -> 3,10%)",
                "Type": "alloc_fam",
                "Actif": True,
                "seuil0_mult": 1.10,   # <= 110% PASS
                "seuil1_mult": 1.40,   # >= 140% PASS
                "taux_max": 0.031,     # 3,10%
                "plafond_mult": 999.0,
            },
            # Indemnités journalières (0,50% dans la limite de 240 300€ = 5 PASS si PASS=48 060)
            {
                "Ligne": "Indemnités journalières (0,50% plafonné)",
                "Type": "plafonne",
                "Actif": True,
                "taux": 0.005,
                "plafond_mult": 5.0,
            },
            # Contribution divers plafonné 3 PASS (0,30% dans la limite de 144 180€ = 3 PASS)
            {
                "Ligne": "Contribution plafonnée (0,30% plafonné à 3 PASS)",
                "Type": "plafonne",
                "Actif": True,
                "taux": 0.003,
                "plafond_mult": 3.0,
            },
            # Retraite de base (17,15% jusqu'à 1 PASS + 0,72% au-delà)
            {
                "Ligne": "Retraite de base (17,15% <= 1 PASS ; 0,72% au-delà)",
                "Type": "retraite_base",
                "Actif": True,
                "taux_plafond": 0.1715,
                "taux_deplafond": 0.0072,
                "plafond_mult": 1.0,
            },
            # Retraite complémentaire (8,10% <= 1 PASS ; 9,10% entre 1 et 4 PASS) (approx)
            {
                "Ligne": "Retraite complémentaire (8,10% <=1 PASS ; 9,10% de 1 à 4 PASS)",
                "Type": "retraite_complementaire",
                "Actif": True,
                "taux_t1": 0.0810,
                "taux_t2": 0.0910,
                "t1_mult": 1.0,
                "t2_mult": 4.0,
            },
            # Invalidité-décès (1,30% <= 1 PASS) (approx)
            {
                "Ligne": "Invalidité - décès (1,30% plafonné à 1 PASS)",
                "Type": "plafonne",
                "Actif": True,
                "taux": 0.013,
                "plafond_mult": 1.0,
            },
        ]
    )


def calcul_is(resultat_imposable: float, taux_reduit: bool) -> float:
    """
    Calcul de l'IS :
    - 15 % jusqu'à 42 500 € si taux réduit
    - 25 % au-delà
    - sinon 25 % sur la totalité
    """
    resultat = max(0.0, float(resultat_imposable))

    if not taux_reduit:
        return resultat * 0.25

    plafond_reduit = 42500
    is_reduit = min(resultat, plafond_reduit) * 0.15
    is_normal = max(0.0, resultat - plafond_reduit) * 0.25

    return is_reduit + is_normal

def compute_cotisations_detail(assiette: float, pass_annuel: float, df_params: pd.DataFrame) -> pd.DataFrame:
    """
    Retourne un df détail par ligne avec base, taux(s) et montant.
    Modèle volontairement transparent et ajustable.
    """
    rows = []
    assiette = max(0.0, float(assiette))
    pass_annuel = max(1.0, float(pass_annuel))
    ratio = assiette / pass_annuel

    for _, p in df_params.iterrows():
        if not bool(p.get("Actif", True)):
            continue
        typ = p.get("Type", "")
        lib = p.get("Ligne", "Cotisation")
        montant = 0.0
        base = assiette
        info = ""

        if typ == "progressif_effectif":
            pts = [
                (float(p["x1"]), float(p["r1"])),
                (float(p["x2"]), float(p["r2"])),
                (float(p["x3"]), float(p["r3"])),
                (float(p["x4"]), float(p["r4"])),
                (float(p["x5"]), float(p["r5"])),
                (float(p["x6"]), float(p["r6"])),
                (float(p["x7"]), float(p["r7"])),
            ]
            taux_eff = piecewise_linear_rate(ratio, pts)
            montant = assiette * taux_eff
            info = f"taux effectif ≈ {taux_eff*100:.2f}% (selon {ratio:.2f} PASS)"
            rows.append({"Cotisation": lib, "Base (€)": base, "Taux / règle": info, "Montant (€)": montant})

        elif typ == "alloc_fam":
            s0 = float(p["seuil0_mult"])
            s1 = float(p["seuil1_mult"])
            tmax = float(p["taux_max"])
            if ratio <= s0:
                taux = 0.0
            elif ratio >= s1:
                taux = tmax
            else:
                # progressif linéaire entre s0 et s1
                taux = tmax * (ratio - s0) / (s1 - s0)
            montant = assiette * taux
            info = f"taux ≈ {taux*100:.2f}% (0% ≤{s0} PASS ; {tmax*100:.2f}% ≥{s1} PASS)"
            rows.append({"Cotisation": lib, "Base (€)": base, "Taux / règle": info, "Montant (€)": montant})

        elif typ == "plafonne":
            taux = float(p["taux"])
            plaf_mult = float(p["plafond_mult"])
            plafond = pass_annuel * plaf_mult
            base_plaf = min(assiette, plafond)
            montant = base_plaf * taux
            info = f"{taux*100:.2f}% sur min(assiette ; {plaf_mult:.2f} PASS)"
            rows.append({"Cotisation": lib, "Base (€)": base_plaf, "Taux / règle": info, "Montant (€)": montant})

        elif typ == "retraite_base":
            taux_plaf = float(p["taux_plafond"])
            taux_depl = float(p["taux_deplafond"])
            plaf_mult = float(p["plafond_mult"])
            plafond = pass_annuel * plaf_mult
            base1 = min(assiette, plafond)
            base2 = max(0.0, assiette - plafond)
            montant = base1 * taux_plaf + base2 * taux_depl
            info = f"{taux_plaf*100:.2f}% ≤ {plaf_mult:.2f} PASS ; {taux_depl*100:.2f}% au-delà"
            rows.append({"Cotisation": lib, "Base (€)": assiette, "Taux / règle": info, "Montant (€)": montant})

        elif typ == "retraite_complementaire":
            t1 = float(p["taux_t1"])
            t2 = float(p["taux_t2"])
            t1_mult = float(p["t1_mult"])
            t2_mult = float(p["t2_mult"])
            lim1 = pass_annuel * t1_mult
            lim2 = pass_annuel * t2_mult
            base_t1 = min(assiette, lim1)
            base_t2 = min(max(0.0, assiette - lim1), max(0.0, lim2 - lim1))
            montant = base_t1 * t1 + base_t2 * t2
            info = f"{t1*100:.2f}% ≤ {t1_mult:.2f} PASS ; {t2*100:.2f}% de {t1_mult:.2f} à {t2_mult:.2f} PASS"
            rows.append({"Cotisation": lib, "Base (€)": assiette, "Taux / règle": info, "Montant (€)": montant})

        else:
            # fallback: no-op
            rows.append({"Cotisation": lib, "Base (€)": base, "Taux / règle": "Type non géré", "Montant (€)": 0.0})

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["Cotisation", "Base (€)", "Taux / règle", "Montant (€)"])
    return df

# =========================
# Dividends model (transparent)
# =========================
def seuil_dividendes_ssi(capital: float, primes: float, cca: float, nb_gerants: int) -> float:
    base = max(0.0, capital) + max(0.0, primes) + max(0.0, cca)
    nb = max(1, int(nb_gerants))
    return 0.10 * base / nb

def compute_dividendes_net(div_brut: float, pfu_ir: float, pfu_ps: float,
                           seuil_ssi: float, apply_ssi_on_above: bool,
                           ssi_on_above_rate: float, ssi_on_above_add_to_ps: bool):
    """
    - PFU = pfu_ir + pfu_ps sur tout dividende (mode standard)
    - Si apply_ssi_on_above: part > seuil soumise à cotisations SSI (taux paramétrable)
      * si ssi_on_above_add_to_ps=False : on suppose SSI "remplace" les PS sur la part > seuil (paramétrable)
      * si True : SSI s'ajoute aux PS (vision prudente)
    """
    div_brut = max(0.0, float(div_brut))
    seuil = max(0.0, float(seuil_ssi))
    base = min(div_brut, seuil)
    above = max(0.0, div_brut - seuil)

    pfu_total = pfu_ir + pfu_ps
    pfu_base = base * pfu_total
    pfu_above = above * (pfu_ir + (pfu_ps if ssi_on_above_add_to_ps else 0.0))
    ssi = above * (ssi_on_above_rate if apply_ssi_on_above else 0.0)

    net = div_brut - pfu_base - pfu_above - ssi
    detail = {
        "Dividendes bruts": div_brut,
        "Seuil 10% (par gérant)": seuil,
        "Part <= seuil": base,
        "Part > seuil": above,
        "PFU sur part <= seuil": pfu_base,
        "PFU sur part > seuil": pfu_above,
        "Cotisations SSI sur part > seuil": ssi,
        "Dividendes nets": max(0.0, net),
    }
    return max(0.0, net), detail

def solve_dividendes_bruts_for_net(target_net: float, **kwargs) -> float:
    """
    Trouve div_brut qui donne target_net (approche monotone par dichotomie).
    """
    target_net = max(0.0, float(target_net))
    if target_net == 0:
        return 0.0

    lo, hi = 0.0, max(1.0, target_net / 0.3)  # initial guess
    for _ in range(30):
        net, _ = compute_dividendes_net(hi, **kwargs)
        if net >= target_net:
            break
        hi *= 2

    for _ in range(60):
        mid = (lo + hi) / 2
        net, _ = compute_dividendes_net(mid, **kwargs)
        if net >= target_net:
            hi = mid
        else:
            lo = mid
    return hi

# =========================
# App
# =========================
st.set_page_config(page_title="Opti-Remu", layout="wide")
st.title("Opti-Remu")
st.caption("Comparateur de scénarios (SARL – SSI) : calculs visibles, paramètres modifiables, détail masqué dépliable.")

st.divider()

# =========================
# SECTION 1 – Paramètres généraux
# =========================
st.header("1️⃣ Paramètres généraux")

col1, col2, col3 = st.columns(3)
with col1:
    objectif_mensuel = st.number_input(
        "Objectif de revenu net mensuel par gérant (€)",
        min_value=0,
        value=2000,
        step=100,
        format="%d",
    )
with col2:
    nb_gerants = st.number_input(
        "Nombre de gérants",
        min_value=1,
        value=2,
        step=1,
        format="%d",
    )
with col3:
    parts_fiscales = st.number_input(
        "Parts fiscales (info / future V2 IR)",
        min_value=1.0,
        value=1.0,
        step=0.5,
    )

objectif_annuel = float(objectif_mensuel) * 12.0
st.write("🎯 Objectif annuel net par gérant :", fmt_eur(objectif_annuel))

st.divider()

# =========================
# SECTION 2 – Société & paramètres
# =========================
st.header("2️⃣ Données société + paramètres réglementaires")

# ---------
# Ligne 1
# ---------
cA, cB, cC, cD, cE = st.columns(5)

with cA:
    resultat_avant_rem = st.number_input(
        "Résultat avant rémunération et avant IS (€)",
        min_value=0,
        value=100000,
        step=1000,
        format="%d",
    )

with cB:
    is_taux_reduit = st.checkbox(
        "Soumis au taux réduit d’IS (15 % jusqu’à 42 500 €)",
        value=True
    )

with cC:
    capital = st.number_input(
        "Capital social (€)",
        min_value=0,
        value=50000,
        step=1000,
        format="%d",
    )

with cD:
    primes_emission = st.number_input(
        "Primes d'émission (€)",
        min_value=0,
        value=0,
        step=1000,
        format="%d",
    )

with cE:
    cca_total = st.number_input(
        "Comptes courants d'associés (total €)",
        min_value=0,
        value=0,
        step=1000,
        format="%d",
    )

# ---------
# Ligne 2
# ---------
cF, cG, cH, cI = st.columns(4)

with cF:
    pass_annuel = st.number_input(
        "PASS (€) — modifiable (défaut 2026)",
        min_value=0,
        value=48060,
        step=100,
        format="%d",
    )

with cG:
    abattement_csg = st.number_input(
        "Abattement CSG / CRDS (%)",
        min_value=0.0,
        max_value=100.0,
        value=26.0,
        step=0.1,
    )

with cH:
    taux_csg = st.number_input(
        "Taux CSG / CRDS (%)",
        min_value=0.0,
        max_value=100.0,
        value=9.70,
        step=0.01,
    )

with cI:
    st.write("")  # colonne volontairement vide pour l'équilibre visuel

# ---------
# Ligne 3 – Assiette SSI (largeur étendue)
# ---------
cJ, cK = st.columns([3, 1])

with cJ:
    mode_assiette = st.selectbox(
        "Assiette SSI retenue (V1)",
        options=[
            "Assiette = rémunération + dividendes soumis SSI (part > seuil)",
            "Assiette = rémunération uniquement (dividendes hors SSI)",
        ],
        index=0,
        help=(
            "V1 : ce paramètre permet de choisir si la part des dividendes "
            "supérieure au seuil de 10 % est intégrée ou non à l’assiette SSI."
        ),
    )

with cK:
    st.write("")  # espace volontaire (respiration visuelle)

st.divider()



# =========================
# SECTION 3 – Dividendes (PFU + SSI au-dessus du seuil)
# =========================
st.header("3️⃣ Paramètres dividendes (PFU + SSI au-delà du seuil 10%)")

d1, d2, d3, d4 = st.columns(4)
with d1:
    pfu_ir = st.number_input("PFU - IR (%)", min_value=0.0, max_value=100.0, value=12.8, step=0.1) / 100
with d2:
    pfu_ps = st.number_input("PFU - prélèvements sociaux (%)", min_value=0.0, max_value=100.0, value=17.2, step=0.1) / 100
with d3:
    apply_ssi_on_div_above = st.checkbox("Appliquer SSI sur dividendes > seuil 10%", value=True)
with d4:
    ssi_on_div_above_rate = st.number_input("Taux SSI (dividendes > seuil) % (param)", min_value=0.0, max_value=100.0, value=45.0, step=0.5) / 100

ssi_add_to_ps = st.checkbox(
    "Sur la part > seuil : SSI s’ajoute aux prélèvements sociaux (prudence)",
    value=True,
    help="Selon interprétations, la part > seuil supporte des cotisations SSI et peut également supporter des PS. "
         "Laisse coché si tu veux une approche prudente (sur-estimation possible).",
)

seuil_ssi_div = seuil_dividendes_ssi(capital, primes_emission, cca_total, int(nb_gerants))
st.write("📌 Seuil dividendes (10% / gérant) :", fmt_eur(seuil_ssi_div))

st.divider()

# =========================
# SECTION 4 – FP (formation professionnelle)
# =========================
st.header("4️⃣ Contribution formation professionnelle (FP)")

fp1, fp2 = st.columns(2)
with fp1:
    fp_statut = st.selectbox(
        "Catégorie FP",
        options=[
            "Commerçant / libéral non réglementé (seul)",
            "Commerçant / libéral non réglementé + conjoint collaborateur",
            "Artisan",
            "Autre (taux libre)",
        ],
        index=0,
    )
with fp2:
    fp_taux_libre = st.number_input(
        "Taux FP (%) si 'Autre (taux libre)'",
        min_value=0.0,
        max_value=10.0,
        value=0.25,
        step=0.01,
    ) / 100

# par défaut, on reprend les taux/valeurs de ton tableau (PASS base 1 PASS)
if fp_statut == "Commerçant / libéral non réglementé (seul)":
    fp_rate = 0.0025
elif fp_statut == "Commerçant / libéral non réglementé + conjoint collaborateur":
    fp_rate = 0.0034
elif fp_statut == "Artisan":
    fp_rate = 0.0029
else:
    fp_rate = fp_taux_libre

fp_montant = float(pass_annuel) * fp_rate
st.write("FP (sur base 1 PASS) :", fmt_eur(fp_montant), f"— taux {fp_rate*100:.2f}%")

st.divider()

# =========================
# SECTION 5 – Paramètres SSI (détail modifiable, masqué)
# =========================
st.header("5️⃣ Paramètres SSI (cotisations hors CSG/CRDS & FP)")

if "ssi_params" not in st.session_state:
    st.session_state["ssi_params"] = default_social_params(float(pass_annuel))

# On propose un bouton de reset si PASS change trop
left, right = st.columns([1, 3])
with left:
    if st.button("↩️ Réinitialiser les taux SSI (par défaut)"):
        st.session_state["ssi_params"] = default_social_params(float(pass_annuel))
with right:
    st.caption("Les calculs détaillés sont masqués dans chaque scénario (dépliables). Ici tu modifies le modèle global.")

with st.expander("🔧 Tableau des paramètres SSI (modifiable)"):
    st.session_state["ssi_params"] = st.data_editor(
        st.session_state["ssi_params"],
        use_container_width=True,
        num_rows="fixed",
    )

st.divider()

# =========================
# SECTION 6 – Scénarios standards
# =========================
st.header("6️⃣ Comparatif – 5 scénarios standards")

st.caption(
    "V1 : IR non intégré. Objectif = net de trésorerie "
    "(rémunération nette + dividendes nets). "
    "Les montants sont calculés par gérant."
)

# -------------------------
# Définition des scénarios
# -------------------------
scenarios = [
    ("A", "100 % rémunération", 1.00),
    ("B", "Rémunération majoritaire (75/25)", 0.75),
    ("C", "Mix équilibré (50/50)", 0.50),
    ("D", "Dividendes majoritaires (25/75)", 0.25),
    ("E", "Dividendes maximisés (limite société)", None),
]

# -------------------------
# Calcul IS (commun à tous)
# -------------------------
is_brut = calcul_is(resultat_avant_rem, is_taux_reduit)
resultat_apres_is = resultat_avant_rem - is_brut

st.subheader("🧾 Impôt sur les sociétés")

st.write("Impôt sur les sociétés :", fmt_eur(is_brut))

if is_taux_reduit:
    st.write("Hypothèse IS : taux réduit appliqué (15 % jusqu’à 42 500 €)")
else:
    st.write("Hypothèse IS : taux normal 25 % sur la totalité")

st.write(
    "Résultat après IS (base distribuable V1) :",
    fmt_eur(resultat_apres_is)
)

st.divider()

# -------------------------
# Capacité maximale dividendes
# -------------------------
div_brut_max_par_gerant = max(0.0, resultat_apres_is) / max(1, int(nb_gerants))

div_net_max_par_gerant, _ = compute_dividendes_net(
    div_brut_max_par_gerant,
    pfu_ir=pfu_ir,
    pfu_ps=pfu_ps,
    seuil_ssi=seuil_ssi_div,
    apply_ssi_on_above=apply_ssi_on_above,
    ssi_on_above_rate=ssi_on_above_rate,
    ssi_on_above_add_to_ps=ssi_add_to_ps,
)

# -------------------------
# Boucle de calcul scénarios
# -------------------------
summary_rows = []
details_by_scenario = {}

for code, label, share_rem in scenarios:

    target_cash = objectif_annuel  # objectif net annuel par gérant

    # Répartition net rémunération / dividendes
    if share_rem is None:
        div_net_target = min(target_cash, div_net_max_par_gerant)
        rem_net_target = max(0.0, target_cash - div_net_target)
    else:
        rem_net_target = target_cash * share_rem
        div_net_target = target_cash - rem_net_target

    # Dividendes bruts nécessaires
    div_brut_needed = solve_dividendes_bruts_for_net(
        div_net_target,
        pfu_ir=pfu_ir,
        pfu_ps=pfu_ps,
        seuil_ssi=seuil_ssi_div,
        apply_ssi_on_above=apply_ssi_on_above,
        ssi_on_above_rate=ssi_on_above_rate,
        ssi_on_above_add_to_ps=ssi_add_to_ps,
    )

    div_net_calc, div_detail = compute_dividendes_net(
        div_brut_needed,
        pfu_ir=pfu_ir,
        pfu_ps=pfu_ps,
        seuil_ssi=seuil_ssi_div,
        apply_ssi_on_above=apply_ssi_on_above,
        ssi_on_above_rate=ssi_on_above_rate,
        ssi_on_above_add_to_ps=ssi_add_to_ps,
    )

    # Assiette SSI
    div_part_ssi = 0.0
    if apply_ssi_on_above:
        div_part_ssi = max(0.0, div_brut_needed - seuil_ssi_div)

    if mode_assiette.startswith("Assiette = rémunération +"):
        assiette_ssi = rem_net_target + div_part_ssi
    else:
        assiette_ssi = rem_net_target

    # Cotisations hors CSG / FP
    df_detail = compute_cotisations_detail(
        assiette=assiette_ssi,
        pass_annuel=float(pass_annuel),
        df_params=st.session_state["ssi_params"],
    )

    cot_hors_csg_fp = (
        float(df_detail["Montant (€)"].sum())
        if not df_detail.empty
        else 0.0
    )

    # FP
    fp = float(fp_montant)

    # CSG / CRDS
    base_csg = assiette_ssi * (1 - abattement_csg / 100)
    csg_crds = base_csg * (taux_csg / 100)

    total_cotisations = cot_hors_csg_fp + fp + csg_crds

    cout_societe_estime = (
        rem_net_target + total_cotisations
    )

    capacity_ok = div_brut_needed <= div_brut_max_par_gerant + 1e-6

    # Avantages / inconvénients
    avantages = []
    inconvenients = []

    if share_rem == 1.0:
        avantages.append("Protection sociale maximale")
        inconvenients.append("Coût social élevé")
    elif share_rem == 0.0:
        avantages.append("Charges sociales limitées")
        inconvenients.append("Protection sociale faible")
    else:
        avantages.append("Compromis rémunération / dividendes")
        inconvenients.append("Sensibilité au seuil de 10 %")

    if not capacity_ok:
        inconvenients.append("Dépassement de la capacité distribuable")

    details_by_scenario[code] = {
        "label": label,
        "assiette_ssi": assiette_ssi,
        "cot_hors_csg_fp": cot_hors_csg_fp,
        "fp": fp,
        "csg_crds": csg_crds,
        "total_cotisations": total_cotisations,
    }

    summary_rows.append(
        {
            "Scénario": f"{code} – {label}",
            "Rémunération nette": rem_net_target,
            "Dividendes nets": div_net_target,
            "Cotisations hors CSG/FP": cot_hors_csg_fp,
            "FP": fp,
            "CSG/CRDS": csg_crds,
            "Total cotisations": total_cotisations,
            "Coût société estimé": cout_societe_estime,
            "Capacité dividendes OK": "OUI" if capacity_ok else "NON",
        }
    )

# -------------------------
# Tableau de synthèse
# -------------------------
df_summary = pd.DataFrame(summary_rows)

st.dataframe(
    df_summary.style.format(
        {
            "Rémunération nette": lambda x: fmt_eur(x),
            "Dividendes nets": lambda x: fmt_eur(x),
            "Cotisations hors CSG/FP": lambda x: fmt_eur(x),
            "FP": lambda x: fmt_eur(x),
            "CSG/CRDS": lambda x: fmt_eur(x),
            "Total cotisations": lambda x: fmt_eur(x),
            "Coût société estimé": lambda x: fmt_eur(x),
        }
    ),
    use_container_width=True,
    hide_index=True,
)

st.divider()

# SECTION 7 – Fiches scénarios (détails masqués + commentaire)
# =========================
st.header("7️⃣ Détails par scénario (dépliables) + commentaire")

for code, label, _ in scenarios:
    d = details_by_scenario[code]

    with st.expander(f"📌 Scénario {code} – {label}", expanded=False):
        colx, coly, colz = st.columns(3)
        with colx:
            st.write("🎯 Objectif net annuel :", fmt_eur(objectif_annuel))
            st.write("👤 Rémunération nette :", fmt_eur(d["rem_net_target"]))
            st.write("💸 Dividendes nets :", fmt_eur(d["div_net_target"]))
        with coly:
            st.write("📌 Dividendes bruts calculés :", fmt_eur(d["div_brut_needed"]))
            st.write("✅ Capacité dividendes :", "OK" if d["capacity_ok"] else "DÉPASSEMENT")
            st.write("📎 Seuil 10% / gérant :", fmt_eur(seuil_ssi_div))
        with colz:
            st.write("🧾 Assiette SSI (V1) :", fmt_eur(d["assiette_ssi"]))
            st.write("🔻 Cotisations hors CSG/FP :", fmt_eur(d["cot_hors_csg_fp"]))
            st.write("🟣 FP :", fmt_eur(d["fp"]))
            st.write("🟠 CSG/CRDS :", fmt_eur(d["csg_crds"]))
            st.write("✅ Total cotisations :", fmt_eur(d["total_cotisations"]))

        st.markdown("### ✅ Avantages")
        for a in d["avantages"]:
            st.write("•", a)

        st.markdown("### ⚠️ Inconvénients")
        for inc in d["inconvenients"]:
            st.write("•", inc)

        # Détail dividendes
        with st.expander("🔍 Détail dividendes (PFU + SSI au-delà du seuil)", expanded=False):
            st.json({k: float(v) if isinstance(v, (int, float)) else v for k, v in d["div_detail"].items()})

        # Détail cotisations (masqué, dépliable) + possibilité de modifier les montants via paramètres globaux
        with st.expander("🔍 Détail cotisations SSI (hors CSG/CRDS & FP) — lignes", expanded=False):
            df_det = d["df_detail"].copy()
            if df_det.empty:
                st.info("Aucune ligne active (vérifie les paramètres SSI).")
            else:
                df_det["Base (€)"] = df_det["Base (€)"].astype(float)
                df_det["Montant (€)"] = df_det["Montant (€)"].astype(float)

                st.dataframe(
                    df_det.style.format(
                        {"Base (€)": lambda x: fmt_eur(x), "Montant (€)": lambda x: fmt_eur(x)}
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

                st.write("Total hors CSG/FP :", fmt_eur(float(df_det["Montant (€)"].sum())))

        # Commentaire libre
        st.markdown("### 📝 Commentaire (à compléter)")
        st.text_area(
            f"Commentaire pour le scénario {code}",
            key=f"comment_{code}",
            placeholder="Ex : scénario retenu car compromis coût/protection sociale ; attention au dépassement de capacité distribuable…",
            height=120,
        )

st.divider()
st.caption("V1 : modèle volontairement transparent et paramétrable. V2 possible : IS recalculé après rémunération, intégration IR, minima SSI, régularisations, ACRE…")
