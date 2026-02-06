# streamlit_app.py — Opti-Remu V2 (REFactor complet + IR abattement 10% + conseil auto)
# ============================================================
# OBJECTIFS (cabinet / audit-proof)
# - Architecture stable : init_state -> UI -> config dérivée -> moteur pur -> restitution
# - Valeurs par défaut visibles et modifiables (PASS, CSG, SSI, PFU, barème IR, scénarios)
# - IS fiscal = colonne "IS" (ex-IS juridique). IS économique non affiché.
# - Tableau synthétique multi-scénarios (approche fiscalité & gestion de patrimoine)
# - Colonne "TOTAL" grisée
# - Ajout "Dividendes bruts"
# - IR sur rémunération = barème progressif + abattement 10% (CGI art. 83)
# - Commentaire de conseil : pré-rempli automatiquement mais modifiable (table + fiches)
# ============================================================

from __future__ import annotations

import pandas as pd
import streamlit as st
from typing import Dict, Any, Tuple, List


# ============================================================
# Helpers (purs)
# ============================================================
def fmt_eur(x: float) -> str:
    return f"{float(x):,.0f} €".replace(",", " ")


def safe_div(a: float, b: float) -> float:
    return 0.0 if b == 0 else a / b


def piecewise_linear_rate(x: float, points: List[Tuple[float, float]]) -> float:
    """points: list of (x_ratio, rate) in increasing x_ratio"""
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


# ============================================================
# IS (France) — IS fiscal (ex "IS juridique")
# ============================================================
def calcul_is(resultat_imposable: float, taux_reduit: bool) -> float:
    """
    IS fiscal :
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


# ============================================================
# Seuil 10% dividendes SSI (par gérant)
# ============================================================
def seuil_dividendes_ssi(capital: float, primes: float, cca: float, nb_gerants: int) -> float:
    base = max(0.0, float(capital)) + max(0.0, float(primes)) + max(0.0, float(cca))
    nb = max(1, int(nb_gerants))
    return 0.10 * base / nb


# ============================================================
# IR sur rémunération — barème progressif + abattement 10% (CGI art. 83)
# ============================================================
def calcul_ir_remuneration_detail(remuneration_nette_annuelle: float, tranche1_revalo: bool) -> Dict[str, Any]:
    """
    IR (traitements et salaires) — version cabinet / explicable.

    Règles appliquées :
    - Abattement forfaitaire 10% (CGI art. 83) : on applique 10% sans plafond (hypothèse simplificatrice)
    - Barème progressif (CGI art. 197) sur revenu net imposable
    - Hypothèses : 1 part, pas de quotient familial, pas de décote, pas de réductions/crédits.

    Retour :
    - dict avec IR total + détail par tranches (audit-proof).
    """
    rem = max(0.0, float(remuneration_nette_annuelle))

    # Abattement 10% (CGI art. 83)
    abattement_10 = rem * 0.10
    revenu_imposable = max(0.0, rem - abattement_10)

    # Tranche 1 (revalo optionnelle)
    t1_max = 11612.0 if tranche1_revalo else 11497.0

    tranches = [
        (0.0, t1_max, 0.00),
        (t1_max, 29315.0, 0.11),
        (29315.0, 83823.0, 0.30),
        (83823.0, 180294.0, 0.41),
        (180294.0, float("inf"), 0.45),
    ]

    ir_total = 0.0
    detail_tranches: List[Dict[str, Any]] = []

    for bas, haut, taux in tranches:
        if revenu_imposable > bas:
            base = min(revenu_imposable, haut) - bas
            impot = base * taux
            ir_total += impot
            detail_tranches.append(
                {
                    "Tranche": f"{int(taux*100)} %",
                    "Base taxable": float(base),
                    "Taux": float(taux),
                    "Impôt tranche": float(impot),
                    "Règle": "Barème progressif IR (CGI art. 197)",
                }
            )

    return {
        "Rémunération nette annuelle": float(rem),
        "Abattement 10% (CGI art. 83)": float(abattement_10),
        "Revenu net imposable IR": float(revenu_imposable),
        "IR total": float(ir_total),
        "Détail par tranche": detail_tranches,
        "Règle globale": "Traitements et salaires : abattement forfaitaire 10% (CGI art. 83) + barème progressif (CGI art. 197)",
    }


# ============================================================
# Conseil automatique (pré-rempli, modifiable)
# ============================================================
def conseil_automatique(rem_pct: float, div_pct: float) -> str:
    """
    Commentaire de conseil (CGP / cabinet) : pré-rempli et éditable.
    Logique volontairement simple, lisible, non prétentieuse.
    """
    rem_pct = float(rem_pct)
    div_pct = float(div_pct)

    if rem_pct >= 75.0:
        return (
            "Orientation rémunération : protection sociale renforcée (assiette SSI plus élevée) "
            "mais coût global souvent supérieur via les cotisations. "
            "Pertinent si l'objectif prioritaire est la couverture sociale et la régularité."
        )
    if div_pct >= 75.0:
        return (
            "Orientation dividendes : réduction des cotisations (hors SSI sur part > 10% si activée) "
            "mais hausse de la fiscalité personnelle sur dividendes. "
            "Intéressant en logique patrimoniale / trésorerie, sous réserve du seuil 10% SSI."
        )
    return (
        "Mix équilibré : compromis entre charges sociales et fiscalité. "
        "Souvent une option robuste pour lisser le coût global tout en conservant une protection sociale correcte."
    )


# ============================================================
# Dividendes — V2 (PFU vs IR + seuil 10% SSI)
# ============================================================
def compute_dividendes_net_v2(
    div_brut: float,
    mode_div: str,                # "PFU" or "IR"
    taux_ir_div: float,           # taux IR approché utilisé si mode_div="IR"
    pfu_ir: float,                # 0.128 (utilisé si PFU)
    pfu_ps: float,                # 0.172
    seuil_ssi: float,
    apply_ssi_on_above: bool,
    ssi_on_above_rate: float,
    apply_ps_on_above: bool,      # PS sur > seuil (prudence)
    apply_ir_on_above: bool,      # IR sur part > seuil ? (option avancée)
) -> Tuple[float, Dict[str, Any]]:
    """
    Découpage :
    - part <= seuil : pas SSI ; taxation selon mode (PFU OU IR abattement 40%) + PS 17,2%
    - part > seuil : SSI si activé ; PS 17,2% option prudente ; IR optionnel (apply_ir_on_above)
    """
    div_brut = max(0.0, float(div_brut))
    seuil = max(0.0, float(seuil_ssi))

    leq = min(div_brut, seuil)
    above = max(0.0, div_brut - seuil)

    # <= seuil
    if mode_div == "PFU":
        ir_leq = leq * pfu_ir
        ps_leq = leq * pfu_ps
        base_ir_leq = leq
        lib_ir = f"PFU IR {pfu_ir*100:.1f}%"
        regle_leq = "PFU : 12,8% (IR) + 17,2% (PS)"
    else:
        # IR barème approximé par taux moyen sur base 60% (abattement 40%)
        base_ir_leq = leq * 0.60
        ir_leq = base_ir_leq * taux_ir_div
        ps_leq = leq * pfu_ps
        lib_ir = f"IR (base 60%) @ {taux_ir_div*100:.1f}%"
        regle_leq = "Option IR : base = dividendes * 60% (abattement 40%) ; IR ≈ taux moyen paramétré ; PS 17,2%"

    # > seuil
    ssi_above = above * (ssi_on_above_rate if apply_ssi_on_above else 0.0)
    ps_above = above * (pfu_ps if apply_ps_on_above else 0.0)

    if apply_ir_on_above:
        if mode_div == "PFU":
            ir_above = above * pfu_ir
            base_ir_above = above
            regle_ir_above = "Option : PFU IR appliqué aussi sur la part > seuil"
        else:
            base_ir_above = above * 0.60
            ir_above = base_ir_above * taux_ir_div
            regle_ir_above = "Option : IR (base 60%) appliqué aussi sur la part > seuil"
    else:
        base_ir_above = 0.0
        ir_above = 0.0
        regle_ir_above = "IR sur part > seuil non appliqué (option désactivée)"

    ir_total = ir_leq + ir_above
    ps_total = ps_leq + ps_above
    impots_total = ir_total + ps_total

    net = div_brut - impots_total - ssi_above

    detail: Dict[str, Any] = {
        "Dividendes bruts": float(div_brut),
        "Seuil 10% (par gérant)": float(seuil),
        "Part <= seuil": float(leq),
        "Part > seuil": float(above),

        "Règle part <= seuil": regle_leq,
        "Libellé IR (part <= seuil)": lib_ir,

        "IR sur <= seuil": float(ir_leq),
        "PS sur <= seuil": float(ps_leq),
        "Base IR <= seuil": float(base_ir_leq),

        "SSI sur > seuil": float(ssi_above),
        "Règle SSI > seuil": "Dividendes excédant 10% (capital+primes+CCA) / gérant — soumis SSI si option activée",
        "PS sur > seuil (prudence)": float(ps_above),
        "Règle PS > seuil": "Approche prudente : PS 17,2% conservés sur la part > seuil si option activée",

        "IR sur > seuil (option)": float(ir_above),
        "Base IR > seuil": float(base_ir_above),
        "Règle IR > seuil": regle_ir_above,

        "IR total": float(ir_total),
        "PS total": float(ps_total),
        "Impôts dividendes (IR/PFU+PS)": float(impots_total),
        "Dividendes nets": float(max(0.0, net)),
    }
    return max(0.0, net), detail


def solve_dividendes_bruts_for_net_v2(target_net: float, **kwargs) -> float:
    """Trouve div_brut tel que dividendes_nets ~= target_net (dichotomie monotone)."""
    target_net = max(0.0, float(target_net))
    if target_net == 0:
        return 0.0

    lo, hi = 0.0, max(1.0, target_net / 0.3)
    for _ in range(30):
        net, _ = compute_dividendes_net_v2(hi, **kwargs)
        if net >= target_net:
            break
        hi *= 2

    for _ in range(60):
        mid = (lo + hi) / 2
        net, _ = compute_dividendes_net_v2(mid, **kwargs)
        if net >= target_net:
            hi = mid
        else:
            lo = mid
    return hi


# ============================================================
# SSI (détail modifiable) — modèle initial
# ============================================================
def default_social_params() -> pd.DataFrame:
    """
    Cotisations hors CSG/CRDS & FP (détail modifiable).
    Modèle transparent : ajustable cabinet.
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
                "x7": 9.99, "r7": 0.065,
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
            rows.append(
                {
                    "Cotisation": lib,
                    "Base (€)": assiette,
                    "Règle / taux": f"taux effectif ≈ {taux_eff*100:.2f}%",
                    "Montant (€)": montant,
                }
            )

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
            rows.append(
                {
                    "Cotisation": lib,
                    "Base (€)": assiette,
                    "Règle / taux": f"taux ≈ {taux*100:.2f}%",
                    "Montant (€)": montant,
                }
            )

        elif typ == "plafonne":
            taux = float(p["taux"])
            plaf_mult = float(p["plafond_mult"])
            plafond = pass_annuel * plaf_mult
            base_plaf = min(assiette, plafond)
            montant = base_plaf * taux
            rows.append(
                {
                    "Cotisation": lib,
                    "Base (€)": base_plaf,
                    "Règle / taux": f"{taux*100:.2f}% sur min(assiette ; {plaf_mult:.2f} PASS)",
                    "Montant (€)": montant,
                }
            )

        elif typ == "retraite_base":
            taux_plaf = float(p["taux_plafond"])
            taux_depl = float(p["taux_deplafond"])
            plaf_mult = float(p["plafond_mult"])
            plafond = pass_annuel * plaf_mult
            base1 = min(assiette, plafond)
            base2 = max(0.0, assiette - plafond)
            montant = base1 * taux_plaf + base2 * taux_depl
            rows.append(
                {
                    "Cotisation": lib,
                    "Base (€)": assiette,
                    "Règle / taux": f"{taux_plaf*100:.2f}% <= {plaf_mult:.2f} PASS + {taux_depl*100:.2f}% au-delà",
                    "Montant (€)": montant,
                }
            )

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
            rows.append(
                {
                    "Cotisation": lib,
                    "Base (€)": assiette,
                    "Règle / taux": f"{t1*100:.2f}% <= {t1_mult:.2f} PASS ; {t2*100:.2f}% de {t1_mult:.2f} à {t2_mult:.2f} PASS",
                    "Montant (€)": montant,
                }
            )

        else:
            rows.append({"Cotisation": lib, "Base (€)": assiette, "Règle / taux": "Type non géré", "Montant (€)": 0.0})

    return pd.DataFrame(rows)


# ============================================================
# PHASE 1 — Initialisation centrale (Streamlit state)
# ============================================================
def init_state() -> None:
    defaults: Dict[str, Any] = {
        # Gérants
        "nb_gerants": 2,
        "gerant_filtre": "Tous",
        "obj_mensuels": [2000.0, 2000.0],

        # Société
        "resultat_avant_rem": 100000.0,
        "capital": 50000.0,
        "primes_emission": 0.0,
        "cca_total": 0.0,
        "is_taux_reduit": True,
        "cotisations_deductibles_is": True,

        # Assiette SSI (mode)
        "mode_assiette": "Assiette = rémunération + dividendes soumis SSI (part > seuil)",

        # Dividendes
        "mode_div": "PFU",         # PFU / IR
        "pfu_ir": 0.128,
        "pfu_ps": 0.172,
        "taux_ir_div": 0.11,       # taux moyen (si option IR dividendes)
        "apply_ssi_on_above": True,
        "ssi_on_above_rate": 0.45,
        "apply_ps_on_above": True,
        "apply_ir_on_above": False,

        # FP / CSG
        "pass_annuel": 48060.0,
        "abattement_csg_pct": 26.0,
        "taux_csg_pct": 9.7,
        "fp_montant": 0.0,

        # IR barème rémunération
        "revalo_tranche1": False,

        # SSI paramètres (table modifiable)
        "ssi_params": default_social_params(),

        # Scénarios (table modifiable)
        "scenarios_df": pd.DataFrame(
            [
                {"Code": "A", "Libellé": "100 % rémunération", "Rem_%": 100.0, "Div_%": 0.0},
                {"Code": "B", "Libellé": "75 % rémunération / 25 % dividendes", "Rem_%": 75.0, "Div_%": 25.0},
                {"Code": "C", "Libellé": "50 % / 50 %", "Rem_%": 50.0, "Div_%": 50.0},
                {"Code": "D", "Libellé": "25 % / 75 %", "Rem_%": 25.0, "Div_%": 75.0},
                {"Code": "E", "Libellé": "100 % dividendes", "Rem_%": 0.0, "Div_%": 100.0},
            ]
        ),

        # Commentaires (pré-remplis mais modifiables)
        # clé = f"{code}::G{idx}" (ex : "C::G1")
        "commentaires": {},

        # UI
        "show_details": False,
    }

    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # Normalisation objectifs : longueur = nb_gerants
    nb = int(st.session_state["nb_gerants"])
    obj = list(st.session_state["obj_mensuels"])
    if len(obj) < nb:
        obj = obj + [obj[-1] if obj else 0.0] * (nb - len(obj))
    elif len(obj) > nb:
        obj = obj[:nb]
    st.session_state["obj_mensuels"] = obj


# ============================================================
# PHASE 3 — Variables dérivées (UNE SEULE FOIS)
# ============================================================
def build_config() -> Dict[str, Any]:
    nb = int(st.session_state["nb_gerants"])
    gerant_filtre = st.session_state["gerant_filtre"]

    gerant_index = None
    if gerant_filtre != "Tous":
        try:
            gerant_index = int(gerant_filtre.split()[-1]) - 1
        except Exception:
            gerant_index = None

    objectifs_annuels = [float(x) * 12.0 for x in st.session_state["obj_mensuels"]]

    seuil_ssi_div = seuil_dividendes_ssi(
        capital=float(st.session_state["capital"]),
        primes=float(st.session_state["primes_emission"]),
        cca=float(st.session_state["cca_total"]),
        nb_gerants=nb,
    )

    return {
        "nb_gerants": nb,
        "gerant_index": gerant_index,
        "objectifs_annuels": objectifs_annuels,
        "seuil_ssi_div": seuil_ssi_div,
    }


# ============================================================
# PHASE 4 — Moteur pur : calcule tous scénarios
# ============================================================
def compute_all_scenarios(cfg: Dict[str, Any]) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    nb = cfg["nb_gerants"]
    objectifs_annuels = cfg["objectifs_annuels"]
    seuil_ssi_div = cfg["seuil_ssi_div"]

    resultat_avant_rem = float(st.session_state["resultat_avant_rem"])
    is_taux_reduit = bool(st.session_state["is_taux_reduit"])
    cotisations_deductibles_is = bool(st.session_state["cotisations_deductibles_is"])

    mode_assiette = st.session_state["mode_assiette"]

    # Dividendes params
    mode_div = st.session_state["mode_div"]
    taux_ir_div = float(st.session_state["taux_ir_div"])
    pfu_ir = float(st.session_state["pfu_ir"])
    pfu_ps = float(st.session_state["pfu_ps"])
    apply_ssi_on_above = bool(st.session_state["apply_ssi_on_above"])
    ssi_on_above_rate = float(st.session_state["ssi_on_above_rate"])
    apply_ps_on_above = bool(st.session_state["apply_ps_on_above"])
    apply_ir_on_above = bool(st.session_state["apply_ir_on_above"])

    # SSI params
    pass_annuel = float(st.session_state["pass_annuel"])
    df_ssi_params = st.session_state["ssi_params"]

    # FP / CSG
    fp_montant = float(st.session_state["fp_montant"])
    abatt_csg = float(st.session_state["abattement_csg_pct"]) / 100.0
    taux_csg = float(st.session_state["taux_csg_pct"]) / 100.0

    # IR barème rémunération
    revalo_tr1 = bool(st.session_state["revalo_tranche1"])

    scenarios_df: pd.DataFrame = st.session_state["scenarios_df"].copy()
    for col in ["Rem_%", "Div_%"]:
        scenarios_df[col] = pd.to_numeric(scenarios_df[col], errors="coerce").fillna(0.0)

    details_by_code: Dict[str, Any] = {}
    synth_rows: List[Dict[str, Any]] = []

    for _, srow in scenarios_df.iterrows():
        code = str(srow.get("Code", "")).strip() or "?"
        label = str(srow.get("Libellé", "")).strip()
        rem_pct = float(srow["Rem_%"])
        div_pct = float(srow["Div_%"])

        # Normalisation souple : si somme != 100, on normalise
        tot = rem_pct + div_pct
        if tot <= 0:
            rem_share = 0.0
            div_share = 0.0
        else:
            rem_share = rem_pct / tot
            div_share = div_pct / tot

        gerants: List[Dict[str, Any]] = []
        total_rem_net = 0.0
        total_cot = 0.0
        total_ir_rem = 0.0
        total_impots_div = 0.0
        total_div_brut = 0.0
        total_div_net = 0.0
        poids_eco: List[float] = []

        for i in range(nb):
            target_cash = float(objectifs_annuels[i])

            # Répartition : on vise des nets (proxy)
            rem_net_target = target_cash * rem_share
            div_net_target = target_cash * div_share

            # Dividendes bruts nécessaires
            div_brut_needed = solve_dividendes_bruts_for_net_v2(
                div_net_target,
                mode_div=mode_div,
                taux_ir_div=taux_ir_div,
                pfu_ir=pfu_ir,
                pfu_ps=pfu_ps,
                seuil_ssi=seuil_ssi_div,
                apply_ssi_on_above=apply_ssi_on_above,
                ssi_on_above_rate=ssi_on_above_rate,
                apply_ps_on_above=apply_ps_on_above,
                apply_ir_on_above=apply_ir_on_above,
            )

            div_net_calc, div_detail = compute_dividendes_net_v2(
                div_brut_needed,
                mode_div=mode_div,
                taux_ir_div=taux_ir_div,
                pfu_ir=pfu_ir,
                pfu_ps=pfu_ps,
                seuil_ssi=seuil_ssi_div,
                apply_ssi_on_above=apply_ssi_on_above,
                ssi_on_above_rate=ssi_on_above_rate,
                apply_ps_on_above=apply_ps_on_above,
                apply_ir_on_above=apply_ir_on_above,
            )

            impots_div_i = float(div_detail["Impôts dividendes (IR/PFU+PS)"])

            # Part dividendes SSI (part > seuil)
            div_part_ssi = max(0.0, float(div_detail["Part > seuil"])) if apply_ssi_on_above else 0.0

            # Assiette SSI proxy
            if mode_assiette.startswith("Assiette = rémunération +"):
                assiette_ssi = rem_net_target + div_part_ssi
            else:
                assiette_ssi = rem_net_target

            # Cotisations SSI hors CSG/FP
            df_ssi_detail = compute_cotisations_detail(
                assiette=assiette_ssi,
                pass_annuel=pass_annuel,
                df_params=df_ssi_params,
            )
            cot_hors_csg_fp = float(df_ssi_detail["Montant (€)"].sum()) if not df_ssi_detail.empty else 0.0

            # CSG/CRDS
            base_csg = max(0.0, assiette_ssi) * (1.0 - abatt_csg)
            csg_crds = base_csg * taux_csg

            # FP/CFP (montant direct)
            fp = float(fp_montant)

            cotisations_total_i = cot_hors_csg_fp + csg_crds + fp

            # ✅ IR rémunération (barème + abattement 10% + détail)
            ir_detail = calcul_ir_remuneration_detail(rem_net_target, tranche1_revalo=revalo_tr1)
            ir_rem_i = float(ir_detail["IR total"])

            # Totaux
            total_rem_net += rem_net_target
            total_ir_rem += ir_rem_i
            total_div_brut += div_brut_needed
            total_div_net += div_net_calc
            total_cot += cotisations_total_i
            total_impots_div += impots_div_i

            # Poids pour ventilation IS (prorata net cash perçu)
            poids_i = rem_net_target + div_net_calc
            poids_eco.append(poids_i)

            gerants.append(
                {
                    "idx": i + 1,
                    "target_cash": target_cash,
                    "rem_net": rem_net_target,
                    "ir_rem": ir_rem_i,
                    "ir_detail": ir_detail,
                    "div_net": div_net_calc,
                    "div_brut": div_brut_needed,
                    "div_detail": div_detail,
                    "assiette_ssi": assiette_ssi,
                    "cot_hors_csg_fp": cot_hors_csg_fp,
                    "csg_crds": csg_crds,
                    "fp": fp,
                    "cotisations_total": cotisations_total_i,
                    "impots_div": impots_div_i,
                    "df_ssi_detail": df_ssi_detail,
                }
            )

        # IS fiscal : base = résultat - rémunérations - (cotisations si déductibles)
        base_is = resultat_avant_rem - total_rem_net - (total_cot if cotisations_deductibles_is else 0.0)
        base_is = max(0.0, base_is)
        is_societe = calcul_is(base_is, is_taux_reduit)

        # Ventilation IS par gérant au prorata du net cash perçu
        total_poids = sum(poids_eco) or 1.0
        is_par_gerant = [is_societe * safe_div(p, total_poids) for p in poids_eco]

        # Conseil auto (par scénario, utilisé pour pré-remplir les commentaires gérants)
        conseil_auto = conseil_automatique(rem_pct=rem_pct, div_pct=div_pct)

        details_by_code[code] = {
            "code": code,
            "label": label,
            "rem_pct": rem_pct,
            "div_pct": div_pct,
            "rem_share": rem_share,
            "div_share": div_share,
            "conseil_auto": conseil_auto,
            "gerants": gerants,
            "total_rem_net": total_rem_net,
            "total_div_brut": total_div_brut,
            "total_div_net": total_div_net,
            "total_ir_rem": total_ir_rem,
            "total_cot": total_cot,
            "total_impots_div": total_impots_div,
            "base_is": base_is,
            "is_societe": is_societe,
            "is_par_gerant": is_par_gerant,
        }

        # Synthèse (moyenne par gérant) — utile en “Tous”
        avg = lambda x: x / max(1, nb)
        synth_rows.append(
            {
                "Code": code,
                "Scénario": f"{code} – {label}",
                "Rémunération nette": avg(total_rem_net),
                "IR rémunération": avg(total_ir_rem),
                "Dividendes bruts": avg(total_div_brut),
                "Dividendes nets": avg(total_div_net),
                "Impôts dividendes": avg(total_impots_div),
                "Cotisations sociales": avg(total_cot),
                "IS": avg(is_societe),
                "TOTAL": avg(total_cot + total_ir_rem + total_impots_div + is_societe),
                "Commentaire": conseil_auto,
            }
        )

    df_synth = pd.DataFrame(synth_rows)
    return df_synth, details_by_code


# ============================================================
# PHASE 2 — UI (écritures st.session_state uniquement)
# ============================================================
def ui() -> None:
    st.set_page_config(page_title="Opti-Remu V2", layout="wide")
    st.title("Opti-Remu — V2 (IS, PFU/IR, seuil 10% SSI, IR barème + abattement 10%)")
    st.caption("Outil cabinet : comparaison multi-scénarios + fiches détaillées (audit-proof).")

    tab_gerants, tab_societe, tab_dividendes, tab_ssi, tab_ir, tab_scenarios, tab_resultats = st.tabs(
        ["🧑 Gérants", "🏢 Société", "📊 Dividendes", "🧮 SSI / CSG / FP", "🧾 IR rémunération", "🧠 Scénarios", "📈 Résultats"]
    )

    with tab_gerants:
        c1, c2 = st.columns([1, 1])
        with c1:
            st.session_state["nb_gerants"] = st.number_input(
                "Nombre de gérants",
                min_value=1,
                max_value=6,
                step=1,
                value=int(st.session_state["nb_gerants"]),
                help="Nombre de gérants majoritaires pris en compte dans la simulation.",
            )
        with c2:
            st.session_state["gerant_filtre"] = st.selectbox(
                "Filtre restitution",
                options=["Tous"] + [f"Gérant {i}" for i in range(1, int(st.session_state["nb_gerants"]) + 1)],
                index=0,
                help="Affiche la moyenne (Tous) ou un gérant en particulier.",
            )

        # Resync objectifs
        nb = int(st.session_state["nb_gerants"])
        obj = list(st.session_state["obj_mensuels"])
        if len(obj) < nb:
            obj += [obj[-1] if obj else 0.0] * (nb - len(obj))
        st.session_state["obj_mensuels"] = obj[:nb]

        st.divider()
        st.caption("Objectifs : net mensuel en poche (converti en net annuel = ×12).")
        cols = st.columns(min(3, nb))
        for i in range(nb):
            with cols[i % len(cols)]:
                st.session_state["obj_mensuels"][i] = st.number_input(
                    f"Gérant {i+1} — net mensuel",
                    min_value=0.0,
                    step=100.0,
                    value=float(st.session_state["obj_mensuels"][i]),
                    help="Objectif de revenu net mensuel en poche.",
                )

    with tab_societe:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.session_state["resultat_avant_rem"] = st.number_input(
                "Résultat avant rémunération",
                value=float(st.session_state["resultat_avant_rem"]),
                step=1000.0,
                help="Résultat comptable/fiscal avant rémunérations (base de simulation).",
            )
        with c2:
            st.session_state["capital"] = st.number_input(
                "Capital social",
                value=float(st.session_state["capital"]),
                step=1000.0,
                help="Capital social (sert au seuil 10% SSI dividendes).",
            )
        with c3:
            st.session_state["primes_emission"] = st.number_input(
                "Primes d’émission",
                value=float(st.session_state["primes_emission"]),
                step=1000.0,
                help="Primes d’émission (sert au seuil 10% SSI dividendes).",
            )
        with c4:
            st.session_state["cca_total"] = st.number_input(
                "CCA (total)",
                value=float(st.session_state["cca_total"]),
                step=1000.0,
                help="Comptes courants d’associés (sert au seuil 10% SSI dividendes).",
            )

        st.divider()
        c5, c6 = st.columns(2)
        with c5:
            st.session_state["is_taux_reduit"] = st.checkbox(
                "Taux réduit IS (15% jusqu’à 42 500 €)",
                value=bool(st.session_state["is_taux_reduit"]),
                help="Hypothèse : conditions d’éligibilité remplies (PME). Paramètre de simulation.",
            )
        with c6:
            st.session_state["cotisations_deductibles_is"] = st.checkbox(
                "Cotisations sociales déductibles de l’IS",
                value=bool(st.session_state["cotisations_deductibles_is"]),
                help="Si les cotisations sont supportées par la société, elles sont déductibles de la base IS.",
            )

        st.session_state["mode_assiette"] = st.selectbox(
            "Assiette SSI retenue (proxy)",
            options=[
                "Assiette = rémunération + dividendes soumis SSI (part > seuil)",
                "Assiette = rémunération uniquement (dividendes hors SSI)",
            ],
            index=0 if st.session_state["mode_assiette"].startswith("Assiette = rémunération +") else 1,
            help="Mode proxy : inclure ou non la part de dividendes > 10% dans l’assiette SSI.",
        )

    with tab_dividendes:
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            st.session_state["mode_div"] = st.radio(
                "Mode d’imposition des dividendes",
                ["PFU", "IR"],
                horizontal=True,
                index=0 if st.session_state["mode_div"] == "PFU" else 1,
                help="PFU = 12,8% + 17,2%. Option IR : base 60% (abattement 40%) avec taux moyen paramétrable.",
            )
        with c2:
            st.session_state["pfu_ir"] = st.number_input(
                "PFU – part IR",
                value=float(st.session_state["pfu_ir"]),
                step=0.001,
                format="%.4f",
                help="Par défaut : 0,128 (12,8%). Modifiable pour simulations.",
            )
        with c3:
            st.session_state["pfu_ps"] = st.number_input(
                "PFU – prélèvements sociaux",
                value=float(st.session_state["pfu_ps"]),
                step=0.001,
                format="%.4f",
                help="Par défaut : 0,172 (17,2%). Modifiable pour simulations.",
            )

        st.session_state["taux_ir_div"] = st.number_input(
            "Option IR – taux moyen sur base 60%",
            value=float(st.session_state["taux_ir_div"]),
            step=0.01,
            format="%.4f",
            help="Utilisé si mode dividendes = IR : IR ≈ (div * 60%) * taux.",
        )

        st.divider()
        c4, c5, c6 = st.columns(3)
        with c4:
            st.session_state["apply_ssi_on_above"] = st.checkbox(
                "SSI sur dividendes > 10%",
                value=bool(st.session_state["apply_ssi_on_above"]),
                help="Si activé : la part de dividendes > seuil 10% est soumise à un taux SSI (paramétré).",
            )
        with c5:
            st.session_state["ssi_on_above_rate"] = st.number_input(
                "Taux SSI sur part > 10%",
                value=float(st.session_state["ssi_on_above_rate"]),
                step=0.005,
                format="%.4f",
                help="Taux global SSI appliqué à la part de dividendes excédentaire (hypothèse cabinet).",
            )
        with c6:
            st.session_state["apply_ps_on_above"] = st.checkbox(
                "PS sur part > 10% (prudence)",
                value=bool(st.session_state["apply_ps_on_above"]),
                help="Approche prudente : conserve les prélèvements sociaux 17,2% sur la part > 10%.",
            )

        st.session_state["apply_ir_on_above"] = st.checkbox(
            "IR sur part > 10% (option avancée)",
            value=bool(st.session_state["apply_ir_on_above"]),
            help="Option avancée : applique aussi IR/PFU IR sur la part > seuil.",
        )

    with tab_ssi:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.session_state["pass_annuel"] = st.number_input(
                "PASS annuel",
                value=float(st.session_state["pass_annuel"]),
                step=100.0,
                help="Valeur par défaut issue du code initial : 48 060 €. Modifiable.",
            )
        with c2:
            st.session_state["abattement_csg_pct"] = st.number_input(
                "Abattement CSG (%)",
                value=float(st.session_state["abattement_csg_pct"]),
                step=0.1,
                help="Valeur par défaut code initial : 26,0%. Utilisée sur l’assiette SSI proxy.",
            )
        with c3:
            st.session_state["taux_csg_pct"] = st.number_input(
                "CSG/CRDS (%)",
                value=float(st.session_state["taux_csg_pct"]),
                step=0.1,
                help="Valeur par défaut code initial : 9,7%.",
            )
        with c4:
            st.session_state["fp_montant"] = st.number_input(
                "FP/CFP (montant annuel)",
                value=float(st.session_state["fp_montant"]),
                step=50.0,
                help="Montant annuel direct (pas de calcul implicite).",
            )

        with st.expander("🔧 Cotisations SSI détaillées (hors CSG/CRDS & FP) — modifiables", expanded=False):
            st.caption("Table pré-remplie avec le modèle initial. Éditable ligne par ligne (hypothèses cabinet).")
            st.session_state["ssi_params"] = st.data_editor(
                st.session_state["ssi_params"],
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
            )

    with tab_ir:
        st.checkbox(
            "Revalorisation +1% de la 1ère tranche (11 612 € au lieu de 11 497 €)",
            key="revalo_tranche1",
            value=bool(st.session_state["revalo_tranche1"]),
            help="Permet de basculer la borne de la 1ère tranche (0%) de 11 497 € à 11 612 €.",
        )
        st.info(
            "IR rémunération : abattement 10% (CGI art. 83) puis barème progressif (CGI art. 197). "
            "Hypothèses : 1 part, sans quotient familial, sans décote, sans réductions/crédits."
        )

    with tab_scenarios:
        st.caption("Scénarios par défaut modifiables. Si Rem_% + Div_% ≠ 100, le moteur normalise automatiquement.")
        st.session_state["scenarios_df"] = st.data_editor(
            st.session_state["scenarios_df"],
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            column_config={
                "Code": st.column_config.TextColumn(help="Identifiant court (A, B, C...)."),
                "Libellé": st.column_config.TextColumn(help="Nom du scénario (affiché dans les tableaux)."),
                "Rem_%": st.column_config.NumberColumn(format="%.1f", help="% de l'objectif net affecté à la rémunération (proxy)."),
                "Div_%": st.column_config.NumberColumn(format="%.1f", help="% de l'objectif net affecté aux dividendes (proxy)."),
            },
        )

    with tab_resultats:
        st.session_state["show_details"] = st.toggle(
            "Afficher les fiches détaillées ouvertes par défaut",
            value=bool(st.session_state["show_details"]),
            help="Si activé, les expanders de détail s’ouvrent automatiquement.",
        )


# ============================================================
# PHASE 5 — Restitution (tableau + fiches)
# ============================================================
def render_results(cfg: Dict[str, Any], df_synth: pd.DataFrame, details_by_code: Dict[str, Any]) -> None:
    st.header("📌 Tableau synthétique des résultats — multi-scénarios")

    # Rappel seuil 10%
    st.info(
        f"Seuil 10% SSI dividendes (par gérant) : **{fmt_eur(cfg['seuil_ssi_div'])}**  "
        f"(capital={fmt_eur(float(st.session_state['capital']))}, primes={fmt_eur(float(st.session_state['primes_emission']))}, CCA={fmt_eur(float(st.session_state['cca_total']))})"
    )

    gi = cfg["gerant_index"]
    nb = cfg["nb_gerants"]

    # Construit dataframe affiché selon filtre
    rows = []
    for _, r in df_synth.iterrows():
        code = r["Code"]
        det = details_by_code.get(code, {})
        if not det:
            continue

        if gi is None:
            rows.append(
                {
                    "Scénario": r["Scénario"],
                    "Rémunération nette": r["Rémunération nette"],
                    "IR rémunération": r["IR rémunération"],
                    "Dividendes bruts": r["Dividendes bruts"],
                    "Dividendes nets": r["Dividendes nets"],
                    "Impôts dividendes": r["Impôts dividendes"],
                    "Cotisations sociales": r["Cotisations sociales"],
                    "IS": r["IS"],
                    "TOTAL": r["TOTAL"],
                    "Commentaire": r.get("Commentaire", det.get("conseil_auto", "")),
                }
            )
        else:
            g = det["gerants"][gi]
            is_i = det["is_par_gerant"][gi]
            total_i = g["cotisations_total"] + g["ir_rem"] + g["impots_div"] + is_i
            rows.append(
                {
                    "Scénario": f"{det['code']} – {det['label']}",
                    "Rémunération nette": g["rem_net"],
                    "IR rémunération": g["ir_rem"],
                    "Dividendes bruts": g["div_brut"],
                    "Dividendes nets": g["div_net"],
                    "Impôts dividendes": g["impots_div"],
                    "Cotisations sociales": g["cotisations_total"],
                    "IS": is_i,
                    "TOTAL": total_i,
                    "Commentaire": det.get("conseil_auto", ""),
                }
            )

    df = pd.DataFrame(rows)

    # Mise en forme : TOTAL grisé (sans toucher à Commentaire)
    money_cols = [c for c in df.columns if c not in ("Scénario", "Commentaire")]
    styler = (
        df.style
        .format({c: (lambda x: fmt_eur(x)) for c in money_cols})
        .set_properties(subset=["TOTAL"], **{"background-color": "#F0F0F0", "font-weight": "bold"})
    )
    st.dataframe(styler, use_container_width=True, hide_index=True)

    st.divider()
    st.header("🔎 Fiches détaillées par scénario")

    default_open = bool(st.session_state["show_details"])

    for code, det in details_by_code.items():
        title = f"📌 Scénario {code} – {det['label']}  (Rem {det['rem_pct']:.0f}% / Div {det['div_pct']:.0f}%)"
        with st.expander(title, expanded=default_open):
            st.write("**Base IS (fiscale)** :", fmt_eur(det["base_is"]))
            st.write("**IS (société)** :", fmt_eur(det["is_societe"]))
            st.caption(
                "Règle IS : base = résultat – rémunérations – (cotisations si déductibles) ; taux 15% jusqu’à 42 500€ (option) puis 25%."
            )

            st.divider()
            st.subheader("💡 Conseil (pré-rempli, modifiable)")
            st.caption("Commentaire cabinet / CGP : pré-rempli automatiquement et modifiable pour le dossier.")
            st.write(det.get("conseil_auto", ""))

            st.divider()
            st.caption("Ventilation IS (E1) : prorata du net cash perçu (rémunération nette + dividendes nets).")

            if cfg["gerant_index"] is None:
                # Tous les gérants
                for g in det["gerants"]:
                    idx0 = g["idx"] - 1
                    st.subheader(f"Gérant {g['idx']}")

                    st.write("Objectif net annuel :", fmt_eur(g["target_cash"]))

                    st.write("Rémunération nette :", fmt_eur(g["rem_net"]))
                    st.caption("Règle : base IR = rémunération nette – abattement 10% (CGI art. 83), puis barème (CGI art. 197).")
                    st.write("IR rémunération :", fmt_eur(g["ir_rem"]))

                    st.write("Dividendes bruts :", fmt_eur(g["div_brut"]))
                    st.write("Dividendes nets :", fmt_eur(g["div_net"]))
                    st.write("Impôts dividendes (IR/PFU+PS) :", fmt_eur(g["impots_div"]))

                    st.write("Assiette SSI (proxy) :", fmt_eur(g["assiette_ssi"]))
                    st.caption("Règle : assiette SSI = rémunération + (dividendes > seuil si option activée) selon le mode retenu.")
                    st.write("Cotisations sociales (total) :", fmt_eur(g["cotisations_total"]))

                    st.write("IS ventilé (E1) :", fmt_eur(det["is_par_gerant"][idx0]))

                    total_i = g["cotisations_total"] + g["ir_rem"] + g["impots_div"] + det["is_par_gerant"][idx0]
                    st.write("✅ **TOTAL** :", fmt_eur(total_i))

                    with st.expander("🧾 Détail IR rémunération (abattement 10% + tranches)", expanded=False):
                        ir_det = g["ir_detail"]
                        st.write("Rémunération nette annuelle :", fmt_eur(ir_det["Rémunération nette annuelle"]))
                        st.write("Abattement 10% (CGI art. 83) :", fmt_eur(ir_det["Abattement 10% (CGI art. 83)"]))
                        st.write("Revenu net imposable IR :", fmt_eur(ir_det["Revenu net imposable IR"]))
                        st.write("IR total :", fmt_eur(ir_det["IR total"]))
                        st.caption(ir_det["Règle globale"])

                        df_ir = pd.DataFrame(ir_det["Détail par tranche"])
                        if df_ir.empty:
                            st.write("Aucun détail disponible.")
                        else:
                            st.dataframe(
                                df_ir.style.format(
                                    {
                                        "Base taxable": lambda x: fmt_eur(x),
                                        "Impôt tranche": lambda x: fmt_eur(x),
                                        "Taux": "{:.0%}".format,
                                    }
                                ),
                                use_container_width=True,
                                hide_index=True,
                            )

                    with st.expander("🔍 Détail dividendes (<=10% / >10%)", expanded=False):
                        st.json(g["div_detail"])

                    with st.expander("🔍 Détail SSI (hors CSG/CRDS & FP)", expanded=False):
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
                            st.write("CSG/CRDS :", fmt_eur(g["csg_crds"]))
                            st.write("FP/CFP :", fmt_eur(g["fp"]))

                    # Commentaire par gérant (pré-rempli, modifiable)
                    key = f"{code}::G{g['idx']}"
                    if key not in st.session_state["commentaires"] or not st.session_state["commentaires"][key]:
                        st.session_state["commentaires"][key] = det.get("conseil_auto", "")

                    st.session_state["commentaires"][key] = st.text_area(
                        f"Commentaire – scénario {code} – gérant {g['idx']}",
                        value=st.session_state["commentaires"][key],
                        height=90,
                        help="Commentaire de conseil : pré-rempli automatiquement, modifiable pour adaptation au dossier client.",
                    )

                    st.divider()
            else:
                # Gérant filtré
                gi = cfg["gerant_index"]
                g = det["gerants"][gi]
                st.subheader(f"👤 {st.session_state['gerant_filtre']}")

                st.write("Objectif net annuel :", fmt_eur(g["target_cash"]))

                st.write("Rémunération nette :", fmt_eur(g["rem_net"]))
                st.caption("Règle : base IR = rémunération nette – abattement 10% (CGI art. 83), puis barème (CGI art. 197).")
                st.write("IR rémunération :", fmt_eur(g["ir_rem"]))

                st.write("Dividendes bruts :", fmt_eur(g["div_brut"]))
                st.write("Dividendes nets :", fmt_eur(g["div_net"]))
                st.write("Impôts dividendes (IR/PFU+PS) :", fmt_eur(g["impots_div"]))

                st.write("Assiette SSI (proxy) :", fmt_eur(g["assiette_ssi"]))
                st.write("Cotisations sociales (total) :", fmt_eur(g["cotisations_total"]))

                st.write("IS ventilé (E1) :", fmt_eur(det["is_par_gerant"][gi]))
                total_i = g["cotisations_total"] + g["ir_rem"] + g["impots_div"] + det["is_par_gerant"][gi]
                st.write("✅ **TOTAL** :", fmt_eur(total_i))

                with st.expander("🧾 Détail IR rémunération (abattement 10% + tranches)", expanded=False):
                    ir_det = g["ir_detail"]
                    st.write("Rémunération nette annuelle :", fmt_eur(ir_det["Rémunération nette annuelle"]))
                    st.write("Abattement 10% (CGI art. 83) :", fmt_eur(ir_det["Abattement 10% (CGI art. 83)"]))
                    st.write("Revenu net imposable IR :", fmt_eur(ir_det["Revenu net imposable IR"]))
                    st.write("IR total :", fmt_eur(ir_det["IR total"]))
                    st.caption(ir_det["Règle globale"])

                    df_ir = pd.DataFrame(ir_det["Détail par tranche"])
                    if df_ir.empty:
                        st.write("Aucun détail disponible.")
                    else:
                        st.dataframe(
                            df_ir.style.format(
                                {
                                    "Base taxable": lambda x: fmt_eur(x),
                                    "Impôt tranche": lambda x: fmt_eur(x),
                                    "Taux": "{:.0%}".format,
                                }
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )

                with st.expander("🔍 Détail dividendes (<=10% / >10%)", expanded=False):
                    st.json(g["div_detail"])

                with st.expander("🔍 Détail SSI (hors CSG/CRDS & FP)", expanded=False):
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
                        st.write("CSG/CRDS :", fmt_eur(g["csg_crds"]))
                        st.write("FP/CFP :", fmt_eur(g["fp"]))

                # Commentaire par gérant (pré-rempli, modifiable)
                key = f"{code}::G{g['idx']}"
                if key not in st.session_state["commentaires"] or not st.session_state["commentaires"][key]:
                    st.session_state["commentaires"][key] = det.get("conseil_auto", "")

                st.session_state["commentaires"][key] = st.text_area(
                    f"Commentaire – scénario {code} – {st.session_state['gerant_filtre']}",
                    value=st.session_state["commentaires"][key],
                    height=110,
                    help="Commentaire de conseil : pré-rempli automatiquement, modifiable pour adaptation au dossier client.",
                )

    st.divider()
    st.caption(
        "IS = IS fiscal. TOTAL = cotisations + IR rémunération + impôts dividendes + IS (ventilé). "
        "IR rémunération : abattement 10% (CGI art. 83) + barème (CGI art. 197)."
    )


# ============================================================
# MAIN
# ============================================================
def main() -> None:
    init_state()
    ui()
    cfg = build_config()
    df_synth, details = compute_all_scenarios(cfg)
    render_results(cfg, df_synth, details)


if __name__ == "__main__":
    main()
