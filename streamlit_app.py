# streamlit_app.py
import pandas as pd
import streamlit as st

# =========================
# Helpers
# =========================
def fmt_eur(x: float) -> str:
    return f"{float(x):,.0f} €".replace(",", " ")

def safe_div(a: float, b: float) -> float:
    return 0.0 if b == 0 else a / b

def piecewise_linear_rate(x: float, points):
    """
    points: list of (x_ratio, rate) in increasing x_ratio
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

# =========================
# IS
# =========================
def calcul_is(resultat_imposable: float, taux_reduit: bool) -> float:
    """
    - Si taux réduit : 15% jusqu'à 42 500 €, puis 25%
    - Sinon : 25% sur la totalité
    """
    resultat = max(0.0, float(resultat_imposable))
    if not taux_reduit:
        return resultat * 0.25

    plafond_reduit = 42500.0
    is_reduit = min(resultat, plafond_reduit) * 0.15
    is_normal = max(0.0, resultat - plafond_reduit) * 0.25
    return is_reduit + is_normal

# =========================
# Seuil 10% dividendes SSI (par gérant)
# =========================
def seuil_dividendes_ssi(capital: float, primes: float, cca: float, nb_gerants: int) -> float:
    base = max(0.0, float(capital)) + max(0.0, float(primes)) + max(0.0, float(cca))
    nb = max(1, int(nb_gerants))
    return 0.10 * base / nb

# =========================
# Dividendes (Option B2 prudente)
# =========================
def compute_dividendes_net(
    div_brut: float,
    pfu_ir: float,
    pfu_ps: float,
    seuil_ssi: float,
    apply_ssi_on_above: bool,
    ssi_on_above_rate: float,
    ssi_on_above_add_to_ps: bool,
    apply_ir_on_above: bool = False,  # B2 : IR PFU sur > seuil désactivé par défaut
):
    """
    Option B2 (prudente) :
    - <= seuil : PFU IR + PFU PS
    - > seuil : SSI + (éventuellement PS si ssi_on_above_add_to_ps)
      (IR PFU sur > seuil désactivé par défaut pour éviter triple peine)
    """
    div_brut = max(0.0, float(div_brut))
    seuil = max(0.0, float(seuil_ssi))

    part_leq = min(div_brut, seuil)
    part_above = max(0.0, div_brut - seuil)

    # PFU sur <= seuil
    pfu_leq = part_leq * (pfu_ir + pfu_ps)

    # PFU sur > seuil (B2 prudente : PS éventuellement, IR éventuellement)
    pfu_above = part_above * ((pfu_ir if apply_ir_on_above else 0.0) + (pfu_ps if ssi_on_above_add_to_ps else 0.0))

    # SSI sur > seuil
    ssi = part_above * (ssi_on_above_rate if apply_ssi_on_above else 0.0)

    net = div_brut - pfu_leq - pfu_above - ssi

    detail = {
        "Dividendes bruts": div_brut,
        "Seuil 10% (par gérant)": seuil,
        "Dividendes <= seuil": part_leq,
        "Dividendes > seuil": part_above,
        "PFU (<= seuil)": pfu_leq,
        "PFU (> seuil)": pfu_above,
        "PFU total": pfu_leq + pfu_above,
        "SSI sur > seuil": ssi,
        "Dividendes nets": max(0.0, net),
    }
    return max(0.0, net), detail

def solve_dividendes_bruts_for_net(target_net: float, **kwargs) -> float:
    """
    Trouve div_brut tel que dividendes_nets ~= target_net (dichotomie).
    """
    target_net = max(0.0, float(target_net))
    if target_net == 0:
        return 0.0

    lo, hi = 0.0, max(1.0, target_net / 0.3)
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
# SSI (détail masqué + paramètres modifiables)
# =========================
def default_social_params() -> pd.DataFrame:
    """
    Cotisations hors CSG/CRDS & FP (détail modifiable).
    Modèle transparent et ajustable (approx progressive).
    """
    return pd.DataFrame(
        [
            {
                "Ligne": "Maladie - maternité (taux effectif progressif)",
                "Type": "progressif_effectif",
                "Actif": True,
                "x1": 0.20, "r1": 0.00,
                "x2": 0.40, "r2": 0.015,
                "x3": 0.60, "r3": 0.040,
                "x4": 1.10, "r4": 0.065,
                "x5": 2.00, "r5": 0.077,
                "x6": 3.00, "r6": 0.085,
                "x7": 9.99, "r7": 0.065,  # au-delà : 6,5%
                "plafond_mult": 999.0,
            },
            {
                "Ligne": "Allocations familiales (progressif 0% -> 3,10%)",
                "Type": "alloc_fam",
                "Actif": True,
                "seuil0_mult": 1.10,
                "seuil1_mult": 1.40,
                "taux_max": 0.031,
                "plafond_mult": 999.0,
            },
            {
                "Ligne": "Indemnités journalières (0,50% plafonné à 5 PASS)",
                "Type": "plafonne",
                "Actif": True,
                "taux": 0.005,
                "plafond_mult": 5.0,
            },
            {
                "Ligne": "Contribution plafonnée (0,30% plafonné à 3 PASS)",
                "Type": "plafonne",
                "Actif": True,
                "taux": 0.003,
                "plafond_mult": 3.0,
            },
            {
                "Ligne": "Retraite de base (17,15% <= 1 PASS ; 0,72% au-delà)",
                "Type": "retraite_base",
                "Actif": True,
                "taux_plafond": 0.1715,
                "taux_deplafond": 0.0072,
                "plafond_mult": 1.0,
            },
            {
                "Ligne": "Retraite complémentaire (8,10% <=1 PASS ; 9,10% de 1 à 4 PASS)",
                "Type": "retraite_complementaire",
                "Actif": True,
                "taux_t1": 0.0810,
                "taux_t2": 0.0910,
                "t1_mult": 1.0,
                "t2_mult": 4.0,
            },
            {
                "Ligne": "Invalidité - décès (1,30% plafonné à 1 PASS)",
                "Type": "plafonne",
                "Actif": True,
                "taux": 0.013,
                "plafond_mult": 1.0,
            },
        ]
    )

def compute_cotisations_detail(assiette: float, pass_annuel: float, df_params: pd.DataFrame) -> pd.DataFrame:
    """
    Retourne un tableau détaillé (hors CSG/CRDS & FP).
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
            rows.append({"Cotisation": lib, "Base (€)": assiette, "Règle / taux": f"taux eff. ≈ {taux_eff*100:.2f}%", "Montant (€)": montant})

        elif typ == "alloc_fam":
            s0 = float(p["seuil0_mult"])
            s1 = float(p["seuil1_mult"])
            tmax = float(p["taux_max"])
            if ratio <= s0:
                taux = 0.0
            elif ratio >= s1:
                taux = tmax
            else:
                taux = tmax * (ratio - s0) / (s1 - s0)
            montant = assiette * taux
            rows.append({"Cotisation": lib, "Base (€)": assiette, "Règle / taux": f"taux ≈ {taux*100:.2f}%", "Montant (€)": montant})

        elif typ == "plafonne":
            taux = float(p["taux"])
            plaf_mult = float(p["plafond_mult"])
            plafond = pass_annuel * plaf_mult
            base_plaf = min(assiette, plafond)
            montant = base_plaf * taux
            rows.append({"Cotisation": lib, "Base (€)": base_plaf, "Règle / taux": f"{taux*100:.2f}% sur min(assiette ; {plaf_mult:.2f} PASS)", "Montant (€)": montant})

        elif typ == "retraite_base":
            taux_plaf = float(p["taux_plafond"])
            taux_depl = float(p["taux_deplafond"])
            plaf_mult = float(p["plafond_mult"])
            plafond = pass_annuel * plaf_mult
            base1 = min(assiette, plafond)
            base2 = max(0.0, assiette - plafond)
            montant = base1 * taux_plaf + base2 * taux_depl
            rows.append({"Cotisation": lib, "Base (€)": assiette, "Règle / taux": f"{taux_plaf*100:.2f}% <= {plaf_mult:.2f} PASS + {taux_depl*100:.2f}% au-delà", "Montant (€)": montant})

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
            rows.append({"Cotisation": lib, "Base (€)": assiette, "Règle / taux": f"{t1*100:.2f}% <= {t1_mult:.2f} PASS ; {t2*100:.2f}% de {t1_mult:.2f} à {t2_mult:.2f} PASS", "Montant (€)": montant})

        else:
            rows.append({"Cotisation": lib, "Base (€)": assiette, "Règle / taux": "Type non géré", "Montant (€)": 0.0})

    return pd.DataFrame(rows)

# =========================
# APP
# =========================
st.set_page_config(page_title="Opti-Remu", layout="wide")
st.title("Opti-Remu — Comparateur multi-gérants (SARL / SSI)")
st.caption("Outil d’aide à la décision : scénarios, calculs visibles, paramètres modifiables. Affichage par gérant + filtre.")

st.divider()

# =========================
# SECTION 1 – Paramètres gérants (par gérant)
# =========================
st.header("1️⃣ Paramètres des gérants (par gérant)")

colA, colB = st.columns(2)

with colA:
    nb_gerants = st.number_input(
        "Nombre de gérants",
        min_value=1,
        value=2,
        step=1,
        format="%d",
    )

with colB:
    gerant_filtre = st.selectbox(
        "Filtrer l’affichage",
        options=["Tous"] + [f"Gérant {i}" for i in range(1, int(nb_gerants) + 1)],
        index=0,
        help="Le tableau comparatif final et les fiches détaillées s’affichent pour le gérant sélectionné (ou tous).",
    )

st.divider()

st.subheader("🎯 Objectifs de rémunération nette (par gérant)")
objectifs_mensuels = []
for i in range(1, int(nb_gerants) + 1):
    objectifs_mensuels.append(
        st.number_input(
            f"Rémunération nette mensuelle souhaitée – Gérant {i} (€)",
            min_value=0,
            value=2000,
            step=100,
            format="%d",
        )
    )
objectifs_annuels = [float(x) * 12.0 for x in objectifs_mensuels]

if gerant_filtre == "Tous":
    gerant_index = None
else:
    gerant_index = int(gerant_filtre.split()[-1]) - 1

st.write("Objectifs annuels :", ", ".join([fmt_eur(x) for x in objectifs_annuels]))

st.divider()

# =========================
# SECTION 2 – Société & paramètres (3 lignes, assiette large)
# =========================
st.header("2️⃣ Données société + paramètres réglementaires")

# Ligne 1
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
        value=True,
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

# Ligne 2
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
    st.write("")

# Ligne 3 (assiette SSI large)
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
    st.write("")

st.divider()

# =========================
# SECTION 3 – Paramètres dividendes (PFU + SSI > seuil)
# =========================
st.header("3️⃣ Paramètres dividendes (Option B2 prudente)")

dA, dB = st.columns(2)
with dA:
    pfu_ir = st.number_input(
        "PFU – Impôt sur le revenu (%)",
        min_value=0.0, max_value=100.0, value=12.8, step=0.1
    ) / 100.0
with dB:
    pfu_ps = st.number_input(
        "PFU – Prélèvements sociaux (%)",
        min_value=0.0, max_value=100.0, value=17.2, step=0.1
    ) / 100.0

dC, dD = st.columns(2)
with dC:
    apply_ssi_on_above = st.checkbox(
        "Soumettre aux cotisations SSI la part des dividendes > seuil de 10 %",
        value=True,
    )
with dD:
    ssi_on_above_rate = st.number_input(
        "Taux SSI sur dividendes > seuil (%)",
        min_value=0.0, max_value=100.0, value=45.0, step=0.5
    ) / 100.0

ssi_add_to_ps = st.checkbox(
    "Sur la part > seuil : les cotisations SSI s’ajoutent aux prélèvements sociaux (prudence)",
    value=True,
    help=(
        "Si coché : la part des dividendes > seuil supporte SSI + PS (17,2%).\n"
        "Si décoché : sur la part > seuil, on applique SSI mais pas les PS."
    ),
)

seuil_ssi_div = seuil_dividendes_ssi(
    capital=capital,
    primes=primes_emission,
    cca=cca_total,
    nb_gerants=int(nb_gerants),
)
st.write("📌 Seuil dividendes (10 % par gérant) :", fmt_eur(seuil_ssi_div))

st.divider()

# =========================
# SECTION 4 – FP
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
        min_value=0.0, max_value=10.0, value=0.25, step=0.01
    ) / 100.0

if fp_statut == "Commerçant / libéral non réglementé (seul)":
    fp_rate = 0.0025
elif fp_statut == "Commerçant / libéral non réglementé + conjoint collaborateur":
    fp_rate = 0.0034
elif fp_statut == "Artisan":
    fp_rate = 0.0029
else:
    fp_rate = fp_taux_libre

fp_montant = float(pass_annuel) * fp_rate
st.write("FP (par gérant, sur base 1 PASS) :", fmt_eur(fp_montant), f"— taux {fp_rate*100:.2f}%")

st.divider()

# =========================
# SECTION 5 – Paramètres SSI (table modifiable)
# =========================
st.header("5️⃣ Paramètres SSI (hors CSG/CRDS & FP)")

if "ssi_params" not in st.session_state:
    st.session_state["ssi_params"] = default_social_params()

cR1, cR2 = st.columns([1, 3])
with cR1:
    if st.button("↩️ Réinitialiser les taux SSI (défaut)"):
        st.session_state["ssi_params"] = default_social_params()
with cR2:
    st.caption("Tableau technique modifiable (détail masqué dans les fiches).")

with st.expander("🔧 Tableau SSI (modifiable)", expanded=False):
    st.session_state["ssi_params"] = st.data_editor(
        st.session_state["ssi_params"],
        use_container_width=True,
        num_rows="fixed",
    )

st.divider()

# =========================
# SECTION 6 – Moteur : 5 scénarios + IS par scénario + IS ventilé E1
# =========================
st.header("6️⃣ Comparatif final — 5 scénarios standards (par gérant + IS ventilé E1)")

st.caption(
    "IS recalculé par scénario selon ta règle : "
    "Résultat initial – total rémunérations – total cotisations sociales – total PFU."
)

scenarios = [
    ("A", "100 % rémunération", 1.00),
    ("B", "Rémunération majoritaire (75/25)", 0.75),
    ("C", "Mix équilibré (50/50)", 0.50),
    ("D", "Dividendes majoritaires (25/75)", 0.25),
    ("E", "Dividendes maximisés (limite économique)", None),
]

details_by_scenario = {}
table_final_rows = []

# Capacités approximatives (V1 prudente) : on borne par le résultat initial / gérant
div_brut_max_societe_approx = max(0.0, float(resultat_avant_rem))
div_brut_max_par_gerant_approx = div_brut_max_societe_approx / max(1, int(nb_gerants))

for code, label, share_rem in scenarios:

    gerants = []
    total_rem = 0.0
    total_cot = 0.0
    total_pfu = 0.0
    poids_eco = []  # pour E1 : net cash perçu (rem + div net)

    for i in range(int(nb_gerants)):
        target_cash = objectifs_annuels[i]

        # Répartition net salaire / net dividendes
        if share_rem is None:
            div_net_max_guess, _ = compute_dividendes_net(
                div_brut_max_par_gerant_approx,
                pfu_ir=pfu_ir,
                pfu_ps=pfu_ps,
                seuil_ssi=seuil_ssi_div,
                apply_ssi_on_above=apply_ssi_on_above,
                ssi_on_above_rate=ssi_on_above_rate,
                ssi_on_above_add_to_ps=ssi_add_to_ps,
                apply_ir_on_above=False,
            )
            div_net_target = min(target_cash, div_net_max_guess)
            rem_net_target = max(0.0, target_cash - div_net_target)
        else:
            rem_net_target = target_cash * float(share_rem)
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
            apply_ir_on_above=False,
        )

        div_net_calc, div_detail = compute_dividendes_net(
            div_brut_needed,
            pfu_ir=pfu_ir,
            pfu_ps=pfu_ps,
            seuil_ssi=seuil_ssi_div,
            apply_ssi_on_above=apply_ssi_on_above,
            ssi_on_above_rate=ssi_on_above_rate,
            ssi_on_above_add_to_ps=ssi_add_to_ps,
            apply_ir_on_above=False,
        )

        # PFU total (B2 prudente)
        pfu_total_i = float(div_detail["PFU total"])

        # Dividendes > seuil (potentiellement SSI)
        div_part_ssi = 0.0
        if apply_ssi_on_above:
            div_part_ssi = max(0.0, float(div_detail["Dividendes > seuil"]))

        # Assiette SSI selon choix
        if mode_assiette.startswith("Assiette = rémunération +"):
            assiette_ssi = rem_net_target + div_part_ssi
        else:
            assiette_ssi = rem_net_target

        # Cotisations hors CSG/FP (détail)
        df_ssi_detail = compute_cotisations_detail(
            assiette=assiette_ssi,
            pass_annuel=float(pass_annuel),
            df_params=st.session_state["ssi_params"],
        )
        cot_hors_csg_fp = float(df_ssi_detail["Montant (€)"].sum()) if not df_ssi_detail.empty else 0.0

        # FP
        fp = float(fp_montant)

        # CSG/CRDS
        base_csg = max(0.0, assiette_ssi) * (1.0 - float(abattement_csg) / 100.0)
        csg_crds = base_csg * (float(taux_csg) / 100.0)

        cotisations_total_i = cot_hors_csg_fp + fp + csg_crds

        # Agrégats société
        total_rem += rem_net_target
        total_cot += cotisations_total_i
        total_pfu += pfu_total_i

        # Poids économique (E1)
        poids_i = rem_net_target + div_net_calc
        poids_eco.append(poids_i)

        gerants.append(
            {
                "idx": i + 1,
                "target_cash": target_cash,
                "rem_net": rem_net_target,
                "div_net": div_net_calc,
                "div_brut": div_brut_needed,
                "div_detail": div_detail,
                "assiette_ssi": assiette_ssi,
                "cot_hors_csg_fp": cot_hors_csg_fp,
                "fp": fp,
                "csg_crds": csg_crds,
                "cotisations_total": cotisations_total_i,
                "pfu_total": pfu_total_i,
                "df_ssi_detail": df_ssi_detail,
            }
        )

    # ✅ IS par scénario selon ta formule (incluant PFU)
    resultat_base_is = max(0.0, float(resultat_avant_rem) - total_rem - total_cot - total_pfu)
    is_societe = calcul_is(resultat_base_is, bool(is_taux_reduit))

    # Ventilation IS (E1) au prorata du poids économique
    total_poids = sum(poids_eco)
    is_par_gerant = []
    for i in range(int(nb_gerants)):
        part = safe_div(poids_eco[i], total_poids)
        is_par_gerant.append(is_societe * part)

    details_by_scenario[code] = {
        "label": label,
        "gerants": gerants,
        "total_rem": total_rem,
        "total_cot": total_cot,
        "total_pfu": total_pfu,
        "resultat_base_is": resultat_base_is,
        "is_societe": is_societe,
        "is_par_gerant": is_par_gerant,
        "total_impots_charges_societe": total_cot + total_pfu + is_societe,
    }

    # Ligne tableau final (PAR GÉRANT filtré)
    if gerant_index is None:
        cot_moy = total_cot / max(1, int(nb_gerants))
        pfu_moy = total_pfu / max(1, int(nb_gerants))
        is_moy = is_societe / max(1, int(nb_gerants))
        total_moy = cot_moy + pfu_moy + is_moy

        table_final_rows.append(
            {
                "Scénario": f"{code} – {label}",
                "Total cotisations sociales": cot_moy,
                "IS à payer (ventilé)": is_moy,
                "Total PFU": pfu_moy,
                "TOTAL impôts & charges": total_moy,
            }
        )
    else:
        g = details_by_scenario[code]["gerants"][gerant_index]
        is_i = details_by_scenario[code]["is_par_gerant"][gerant_index]
        total_i = g["cotisations_total"] + g["pfu_total"] + is_i

        table_final_rows.append(
            {
                "Scénario": f"{code} – {label}",
                "Total cotisations sociales": g["cotisations_total"],
                "IS à payer (ventilé)": is_i,
                "Total PFU": g["pfu_total"],
                "TOTAL impôts & charges": total_i,
            }
        )

st.subheader("📌 Tableau comparatif final (par gérant filtré)")
df_final = pd.DataFrame(table_final_rows)

st.dataframe(
    df_final.style.format(
        {
            "Total cotisations sociales": lambda x: fmt_eur(x),
            "IS à payer (ventilé)": lambda x: fmt_eur(x),
            "Total PFU": lambda x: fmt_eur(x),
            "TOTAL impôts & charges": lambda x: fmt_eur(x),
        }
    ),
    use_container_width=True,
    hide_index=True,
)

st.caption(
    "IS (par scénario) = calculé sur : Résultat initial – rémunérations – cotisations – PFU. "
    "IS ventilé (E1) = au prorata du net cash perçu (rémunération nette + dividendes nets)."
)

st.divider()

# =========================
# SECTION 7 – Fiches détaillées filtrables par gérant
# =========================
st.header("7️⃣ Fiches détaillées par scénario (filtrables) + commentaire")

for code, label, _ in scenarios:
    s = details_by_scenario[code]

    with st.expander(f"📌 Scénario {code} – {label}", expanded=False):

        st.write("Résultat base IS (après rem – cotisations – PFU) :", fmt_eur(s["resultat_base_is"]))
        st.write("IS société :", fmt_eur(s["is_societe"]))

        if gerant_index is None:
            st.info("Affichage : Tous les gérants (détails par gérant ci-dessous).")

            for g in s["gerants"]:
                idx0 = g["idx"] - 1
                st.subheader(f"Gérant {g['idx']}")

                st.write("Objectif net annuel :", fmt_eur(g["target_cash"]))
                st.write("Rémunération nette :", fmt_eur(g["rem_net"]))
                st.write("Dividendes nets :", fmt_eur(g["div_net"]))
                st.write("Dividendes bruts :", fmt_eur(g["div_brut"]))

                st.divider()

                st.write("Cotisations sociales (total) :", fmt_eur(g["cotisations_total"]))
                st.write("PFU total :", fmt_eur(g["pfu_total"]))
                st.write("IS ventilé (E1) :", fmt_eur(s["is_par_gerant"][idx0]))
                st.write("✅ TOTAL impôts & charges :", fmt_eur(g["cotisations_total"] + g["pfu_total"] + s["is_par_gerant"][idx0]))

                with st.expander("🔍 Détail dividendes (<=10% / >10%)", expanded=False):
                    st.json(g["div_detail"])

                with st.expander("🔍 Détail SSI (hors CSG/CRDS & FP) — lignes", expanded=False):
                    df_det = g["df_ssi_detail"]
                    if df_det is None or df_det.empty:
                        st.write("Aucun détail disponible.")
                    else:
                        st.dataframe(
                            df_det.style.format(
                                {"Base (€)": lambda x: fmt_eur(x), "Montant (€)": lambda x: fmt_eur(x)}
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )
                        st.write("Total hors CSG/CRDS & FP :", fmt_eur(float(df_det["Montant (€)"].sum())))

                st.text_area(
                    f"Commentaire – scénario {code} – gérant {g['idx']}",
                    key=f"comment_{code}_g{g['idx']}",
                    height=100,
                )

                st.divider()

        else:
            g = s["gerants"][gerant_index]
            is_i = s["is_par_gerant"][gerant_index]

            st.subheader(f"👤 {gerant_filtre}")

            st.write("Objectif net annuel :", fmt_eur(g["target_cash"]))
            st.write("Rémunération nette :", fmt_eur(g["rem_net"]))
            st.write("Dividendes nets :", fmt_eur(g["div_net"]))
            st.write("Dividendes bruts :", fmt_eur(g["div_brut"]))

            st.divider()

            st.write("Cotisations sociales (total) :", fmt_eur(g["cotisations_total"]))
            st.write("PFU total :", fmt_eur(g["pfu_total"]))
            st.write("IS ventilé (E1) :", fmt_eur(is_i))
            st.write("✅ TOTAL impôts & charges :", fmt_eur(g["cotisations_total"] + g["pfu_total"] + is_i))

            with st.expander("🔍 Détail dividendes (<=10% / >10%)", expanded=False):
                st.json(g["div_detail"])

            with st.expander("🔍 Détail SSI (hors CSG/CRDS & FP) — lignes", expanded=False):
                df_det = g["df_ssi_detail"]
                if df_det is None or df_det.empty:
                    st.write("Aucun détail disponible.")
                else:
                    st.dataframe(
                        df_det.style.format(
                            {"Base (€)": lambda x: fmt_eur(x), "Montant (€)": lambda x: fmt_eur(x)}
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )
                    st.write("Total hors CSG/CRDS & FP :", fmt_eur(float(df_det["Montant (€)"].sum())))

            st.text_area(
                f"Commentaire – scénario {code} – {gerant_filtre}",
                key=f"comment_{code}_{gerant_filtre}",
                height=140,
            )

st.divider()
st.caption("Fin V1. Prochaine évolution possible : intégration IR (barème), minima SSI, régularisations N+1, IS sur base fiscale stricte (sans PFU), etc.")
