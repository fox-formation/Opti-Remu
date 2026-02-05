# app.py — Opti-Remu (Streamlit)
# ============================================================
# Architecture (OBLIGATOIRE)
# 1) init_state() : toutes les variables "moteur" + UI ont des défauts ici
# 2) UI (tabs) : écrit UNIQUEMENT dans st.session_state (aucun calcul métier)
# 3) Variables dérivées : config dérivée calculée UNE SEULE FOIS
# 4) Moteur pur : fonctions pures, paramètres explicites, zéro Streamlit
# 5) Restitution : tableaux + expanders (audit-proof)
#
# ⚠️ Notes
# - Modèle volontairement paramétrable (cabinet) : vous ajustez les taux/assiettes.
# - IR ici = approximation par taux moyen (paramétrable) comme demandé.
# - SSI : table éditable "tranches" (hors CSG/FP), + modules CSG/FP séparés.
# - Dividendes : PFU par défaut ou IR barème (taux moyen) + abattement 40%.
# - Dividendes > 10% (capital + primes + CCA) : intégration SSI activable.
# - “IS juridique” ≠ “IS économique” : affichés séparément, jamais mélangés.
# ============================================================

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st


# -------------------------------
# PHASE 1 — INITIALISATION CENTRALE
# -------------------------------
def init_state() -> None:
    defaults: Dict[str, object] = {
        # --- Gérants
        "nb_gerants": 1,
        "selected_gerant": "Tous",
        # objectifs nets mensuels (par gérant)
        "obj_net_mensuels": [3500.0],
        # --- Société
        "resultat_avant_remu": 120000.0,  # résultat comptable/fiscal avant rémunérations
        "capital_social": 10000.0,
        "primes_emission": 0.0,
        "cca": 0.0,
        "option_is_reduit": True,
        "seuil_is_reduit": 42500.0,
        "taux_is_reduit": 0.15,
        "taux_is_normal": 0.25,
        # --- Dividendes
        "mode_dividendes": "PFU",  # "PFU" ou "IR"
        "taux_ir_remu": 0.20,  # taux moyen (approx) IR sur rémunération
        "taux_ir_div": 0.20,  # taux moyen (approx) IR sur dividendes si option IR
        "abattement_div_40": True,
        "apply_ssi_on_div_above": True,  # SSI sur dividendes > seuil 10%
        "apply_ps_on_div_above_prudent": True,  # PS sur > seuil, approche prudente
        "apply_ir_on_div_above": False,  # option IR sur > seuil (si vous voulez scinder)
        # --- Assiette SSI
        "mode_assiette_ssi": "Remu seule",  # "Remu seule" / "Remu + Div > seuil"
        # --- Cotisations SSI (hors CSG/FP) : table éditable
        # Chaque ligne = tranche sur assiette annuelle (borne inf incluse, borne sup exclue)
        "ssi_table": pd.DataFrame(
            [
                {"Libellé": "SSI - Tranche 1", "Borne_inf": 0.0, "Borne_sup": 45000.0, "Taux": 0.30},
                {"Libellé": "SSI - Tranche 2", "Borne_inf": 45000.0, "Borne_sup": 1e12, "Taux": 0.15},
            ]
        ),
        # --- CSG/CRDS (module séparé)
        "use_csg": True,
        "taux_csg_crds": 0.097,  # ordre de grandeur, ajustable
        "abattement_csg": 0.0175,  # abattement d'assiette (approx), ajustable
        # --- FP/CFP (module séparé)
        "use_fp": True,
        "pass_annuel": 46368.0,  # PASS annuel (modifiable)
        "taux_fp": 0.0025,  # CFP/FP (approx), ajustable
        # --- Hypothèses de charge sociale
        "cotis_payees_par_societe": True,  # si True : cotisations déductibles IS
        # --- Scénarios standard A→E (part "dividendes" dans le net cible)
        "scenario_splits": {
            "A - 100% rémunération": 0.00,
            "B - 75% remu / 25% div": 0.25,
            "C - 50% remu / 50% div": 0.50,
            "D - 25% remu / 75% div": 0.75,
            "E - 100% dividendes": 1.00,
        },
        # --- UI compact
        "show_details": False,
        "commentaires": {},  # commentaires libres par scénario et par gérant
    }

    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # normalisation : obj_net_mensuels longueur = nb_gerants
    nb = int(st.session_state["nb_gerants"])
    obj = list(st.session_state["obj_net_mensuels"])
    if len(obj) < nb:
        obj = obj + [obj[-1] if obj else 0.0] * (nb - len(obj))
    elif len(obj) > nb:
        obj = obj[:nb]
    st.session_state["obj_net_mensuels"] = obj


# -------------------------------
# PHASE 4 — MOTEUR PUR (zéro Streamlit)
# -------------------------------
ScenarioName = str


@dataclass(frozen=True)
class CompanyParams:
    resultat_avant_remu: float
    option_is_reduit: bool
    seuil_is_reduit: float
    taux_is_reduit: float
    taux_is_normal: float
    cotis_payees_par_societe: bool
    capital_social: float
    primes_emission: float
    cca: float


@dataclass(frozen=True)
class PersonalTaxParams:
    mode_dividendes: Literal["PFU", "IR"]
    taux_ir_remu: float
    taux_ir_div: float
    abattement_div_40: bool
    apply_ps_on_div_above_prudent: bool
    apply_ir_on_div_above: bool  # si vous voulez traiter différemment la part > seuil


@dataclass(frozen=True)
class SSIParams:
    mode_assiette_ssi: Literal["Remu seule", "Remu + Div > seuil"]
    apply_ssi_on_div_above: bool
    seuil_div_10pct: float
    ssi_table: pd.DataFrame  # colonnes: Libellé, Borne_inf, Borne_sup, Taux
    use_csg: bool
    taux_csg_crds: float
    abattement_csg: float
    use_fp: bool
    pass_annuel: float
    taux_fp: float


@dataclass(frozen=True)
class ManagerInput:
    name: str
    obj_net_annuel: float


@dataclass(frozen=True)
class ManagerScenarioResult:
    # Cibles / flux
    obj_net_annuel: float
    net_via_remu: float
    net_via_div: float
    # Rémunération
    remu_brute: float
    remu_ir: float
    # Dividendes
    div_bruts: float
    div_pfu_ir: float
    div_ps: float
    # SSI
    assiette_ssi: float
    cotis_ssi_hors_csg_fp: float
    csg_crds: float
    fp: float
    # Totaux perso
    impots_perso: float
    prelevements_perso: float  # impôts + PS + SSI perso (éco)
    # Allocation IS (ventilation “E1”)
    is_juridique_alloc: float
    is_economique_alloc: float


@dataclass(frozen=True)
class ScenarioTotals:
    scenario: ScenarioName
    # Agrégats société / groupe
    remu_total: float
    cotis_total_deductibles: float
    is_juridique: float
    is_economique: float
    # Agrégats perso
    cotisations_sociales_total: float
    impots_perso_total: float
    total_prelevements_juridique: float
    total_prelevements_economique: float
    # Détails par gérant
    per_manager: Dict[str, ManagerScenarioResult]


def _safe_float(x: object, default: float = 0.0) -> float:
    try:
        v = float(x)
        if np.isfinite(v):
            return v
        return default
    except Exception:
        return default


def compute_is_juridique(base_is: float, option_reduit: bool, seuil: float, t_reduit: float, t_normal: float) -> float:
    base = max(0.0, base_is)
    if not option_reduit:
        return base * t_normal
    seuil_eff = max(0.0, seuil)
    part15 = min(base, seuil_eff)
    part25 = max(0.0, base - seuil_eff)
    return part15 * t_reduit + part25 * t_normal


def compute_ssi_hors_csg_fp(assiette: float, ssi_table: pd.DataFrame) -> float:
    """
    Cotisations SSI hors CSG/FP, via un tableau de tranches éditable.
    Colonnes attendues: Borne_inf, Borne_sup, Taux
    """
    a = max(0.0, assiette)
    total = 0.0

    # robustesse colonnes
    for col in ["Borne_inf", "Borne_sup", "Taux"]:
        if col not in ssi_table.columns:
            return 0.0

    df = ssi_table.copy()
    df["Borne_inf"] = pd.to_numeric(df["Borne_inf"], errors="coerce").fillna(0.0)
    df["Borne_sup"] = pd.to_numeric(df["Borne_sup"], errors="coerce").fillna(0.0)
    df["Taux"] = pd.to_numeric(df["Taux"], errors="coerce").fillna(0.0)

    df = df.sort_values(["Borne_inf", "Borne_sup"]).reset_index(drop=True)

    for _, row in df.iterrows():
        bi = max(0.0, float(row["Borne_inf"]))
        bs = float(row["Borne_sup"])
        taux = max(0.0, float(row["Taux"]))

        if bs <= bi:
            continue

        tranche = max(0.0, min(a, bs) - bi)
        total += tranche * taux

    return total


def compute_csg_crds(assiette: float, taux: float, abattement: float) -> float:
    """
    Approximation: CSG/CRDS = assiette * (1 - abattement) * taux
    """
    a = max(0.0, assiette)
    abat = min(max(0.0, abattement), 0.5)
    t = max(0.0, taux)
    return a * (1.0 - abat) * t


def compute_fp(assiette: float, pass_annuel: float, taux_fp: float) -> float:
    """
    CFP/FP (approx) souvent plafonnée à 1 PASS.
    """
    a = max(0.0, assiette)
    cap = max(0.0, pass_annuel)
    base = min(a, cap) if cap > 0 else a
    return base * max(0.0, taux_fp)


def personal_tax_on_dividends(
    div_bruts: float,
    params: PersonalTaxParams,
    apply_ps: bool,
) -> Tuple[float, float]:
    """
    Retourne (IR/PFU sur dividendes, prélèvements sociaux).
    - PFU : 12,8% (impôt) + PS 17,2% (si apply_ps True)
    - IR : taux moyen * base après abattement 40% (si activé) ; PS idem si apply_ps True
    """
    d = max(0.0, div_bruts)
    ps = 0.0
    if apply_ps:
        ps = d * 0.172  # PS "standard" sur dividendes

    if params.mode_dividendes == "PFU":
        imp = d * 0.128
        return imp, ps

    # IR barème approximé
    base = d
    if params.abattement_div_40:
        base = d * 0.60
    imp = base * max(0.0, params.taux_ir_div)
    return imp, ps


def personal_tax_on_remuneration(remu_brute: float, taux_ir_remu: float) -> float:
    """
    IR sur rémunération : approximation taux moyen.
    """
    r = max(0.0, remu_brute)
    return r * max(0.0, taux_ir_remu)


def solve_remu_brute_for_net_target(
    net_target: float,
    ssi_params: SSIParams,
    tax_params: PersonalTaxParams,
    max_iter: int = 60,
) -> Tuple[float, float, float, float, float]:
    """
    Résout une rémunération brute annuelle (TNS) pour obtenir un net en poche annuel (approx)
    net ≈ remu_brute - SSI_total - IR_remu
    Où SSI_total = SSI_hors_csg_fp + CSG + FP (selon options)
    Retourne: (remu_brute, ssi_hors, csg, fp, ir_remu)
    """
    target = max(0.0, net_target)

    # méthode monotone par dichotomie
    lo = 0.0
    hi = max(1000.0, target * 3.0)  # borne haute initiale

    def net_from_brut(brut: float) -> Tuple[float, float, float, float, float]:
        assiette = brut
        ssi_h = compute_ssi_hors_csg_fp(assiette, ssi_params.ssi_table)
        csg = compute_csg_crds(assiette, ssi_params.taux_csg_crds, ssi_params.abattement_csg) if ssi_params.use_csg else 0.0
        fp = compute_fp(assiette, ssi_params.pass_annuel, ssi_params.taux_fp) if ssi_params.use_fp else 0.0
        ir = personal_tax_on_remuneration(brut, tax_params.taux_ir_remu)
        net = brut - (ssi_h + csg + fp) - ir
        return net, ssi_h, csg, fp, ir

    # élargit hi si nécessaire
    for _ in range(20):
        net_hi, *_ = net_from_brut(hi)
        if net_hi >= target:
            break
        hi *= 1.7

    best = (0.0, 0.0, 0.0, 0.0, 0.0)
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        net_mid, ssi_h, csg, fp, ir = net_from_brut(mid)
        best = (mid, ssi_h, csg, fp, ir)
        if abs(net_mid - target) <= 1e-2:
            break
        if net_mid < target:
            lo = mid
        else:
            hi = mid

    return best


def compute_scenario(
    managers: List[ManagerInput],
    company: CompanyParams,
    ssi: SSIParams,
    tax: PersonalTaxParams,
    scenario: ScenarioName,
    div_share_of_net: float,
) -> ScenarioTotals:
    """
    Scénario : chaque gérant vise son net annuel, réparti selon div_share_of_net (0..1)
    - Part net via dividendes = obj_net_annuel * div_share
    - Part net via rémunération = obj_net_annuel * (1 - div_share)
    """
    div_share = float(np.clip(div_share_of_net, 0.0, 1.0))
    per_manager: Dict[str, ManagerScenarioResult] = {}

    remu_total = 0.0
    cotis_total = 0.0  # cotisations (SSI+CSG+FP) qui impactent la société si prises en charge
    impots_perso_total = 0.0
    cotisations_sociales_total = 0.0

    # 1) Calcule d'abord les besoins "poche" par gérant (remu + div nets), puis remu brute et div bruts
    for m in managers:
        net_target = max(0.0, m.obj_net_annuel)
        net_div = net_target * div_share
        net_remu = net_target - net_div

        # --- Rémunération : on solve le brut pour obtenir net_remu
        remu_brute, ssi_h, csg, fp, ir_remu = solve_remu_brute_for_net_target(
            net_remu, ssi, tax
        )

        # --- Dividendes : on remonte du net au brut selon PFU/IR + PS
        # net_div = div_bruts - (PFU/IR) - PS - (SSI éventuelle sur > seuil si activée)
        # Comme la SSI sur > seuil dépend du brut, on résout aussi par dichotomie.

        seuil = max(0.0, ssi.seuil_div_10pct)
        apply_ssi_on_above = bool(ssi.apply_ssi_on_div_above and ssi.mode_assiette_ssi == "Remu + Div > seuil")
        apply_ps = bool(tax.apply_ps_on_div_above_prudent)

        def net_div_from_brut(div_brut: float) -> Tuple[float, float, float, float]:
            d = max(0.0, div_brut)
            imp_div, ps_div = personal_tax_on_dividends(d, tax, apply_ps=apply_ps)

            # SSI sur la part > seuil 10% (option)
            above = max(0.0, d - seuil) if apply_ssi_on_above else 0.0
            ssi_on_above_h = compute_ssi_hors_csg_fp(above, ssi.ssi_table) if apply_ssi_on_above else 0.0
            csg_on_above = compute_csg_crds(above, ssi.taux_csg_crds, ssi.abattement_csg) if (apply_ssi_on_above and ssi.use_csg) else 0.0
            fp_on_above = compute_fp(above, ssi.pass_annuel, ssi.taux_fp) if (apply_ssi_on_above and ssi.use_fp) else 0.0

            net = d - imp_div - ps_div - (ssi_on_above_h + csg_on_above + fp_on_above)
            return net, imp_div, ps_div, (ssi_on_above_h + csg_on_above + fp_on_above)

        if net_div <= 1e-9:
            div_bruts = 0.0
            imp_div = 0.0
            ps_div = 0.0
            ssi_div = 0.0
        else:
            lo = 0.0
            hi = max(1000.0, net_div * 2.0)
            for _ in range(25):
                net_hi, *_ = net_div_from_brut(hi)
                if net_hi >= net_div:
                    break
                hi *= 1.7
            div_bruts = 0.0
            imp_div = 0.0
            ps_div = 0.0
            ssi_div = 0.0
            for _ in range(70):
                mid = (lo + hi) / 2.0
                net_mid, imp_mid, ps_mid, ssi_mid = net_div_from_brut(mid)
                div_bruts, imp_div, ps_div, ssi_div = mid, imp_mid, ps_mid, ssi_mid
                if abs(net_mid - net_div) <= 1e-2:
                    break
                if net_mid < net_div:
                    lo = mid
                else:
                    hi = mid

        # Assiette SSI (pour reporting)
        assiette_ssi = remu_brute
        if ssi.mode_assiette_ssi == "Remu + Div > seuil" and apply_ssi_on_above:
            assiette_ssi += max(0.0, div_bruts - seuil)

        # Totaux perso
        impots_perso = ir_remu + imp_div
        prelevements_sociaux = (ssi_h + csg + fp) + ps_div + ssi_div

        per_manager[m.name] = ManagerScenarioResult(
            obj_net_annuel=net_target,
            net_via_remu=net_remu,
            net_via_div=net_div,
            remu_brute=remu_brute,
            remu_ir=ir_remu,
            div_bruts=div_bruts,
            div_pfu_ir=imp_div,
            div_ps=ps_div,
            assiette_ssi=assiette_ssi,
            cotis_ssi_hors_csg_fp=ssi_h + (ssi_div if apply_ssi_on_above else 0.0),  # reporting (mélange volontaire ici = cotis SSI)
            csg_crds=csg,
            fp=fp,
            impots_perso=impots_perso,
            prelevements_perso=impots_perso + prelevements_sociaux,
            is_juridique_alloc=0.0,   # rempli plus bas
            is_economique_alloc=0.0,  # rempli plus bas
        )

        remu_total += remu_brute
        cotis_total += (ssi_h + csg + fp) if company.cotis_payees_par_societe else 0.0
        impots_perso_total += impots_perso
        cotisations_sociales_total += prelevements_sociaux

    # 2) IS juridique (réel fiscal) : base = résultat - remu - cotis_deductibles
    base_is_juridique = company.resultat_avant_remu - remu_total - (cotis_total if company.cotis_payees_par_societe else 0.0)
    is_juridique = compute_is_juridique(
        base_is_juridique, company.option_is_reduit, company.seuil_is_reduit, company.taux_is_reduit, company.taux_is_normal
    )

    # 3) IS économique (pilotage cash) : résultat - remu - cotis - impôts perso
    # Ici on considère les impôts personnels comme une sortie économique "groupe"
    base_is_economique = company.resultat_avant_remu - remu_total - (cotis_total if company.cotis_payees_par_societe else 0.0) - impots_perso_total
    is_economique = compute_is_juridique(
        base_is_economique, company.option_is_reduit, company.seuil_is_reduit, company.taux_is_reduit, company.taux_is_normal
    )

    # 4) Ventilation E1 par gérant (pro-rata du net cible, à défaut d’une autre clé)
    total_obj = sum(max(0.0, m.obj_net_annuel) for m in managers) or 1.0
    for m in managers:
        w = max(0.0, m.obj_net_annuel) / total_obj
        r = per_manager[m.name]
        per_manager[m.name] = ManagerScenarioResult(
            **{**r.__dict__},
            is_juridique_alloc=is_juridique * w,
            is_economique_alloc=is_economique * w,
        )

    # 5) Totaux prélèvements
    # Juridique : IS juridique + impôts perso + cotisations sociales (SSI/CSG/FP + PS)
    total_prelev_juridique = is_juridique + impots_perso_total + cotisations_sociales_total
    # Economique : IS économique + impôts perso + cotisations sociales
    total_prelev_economique = is_economique + impots_perso_total + cotisations_sociales_total

    return ScenarioTotals(
        scenario=scenario,
        remu_total=remu_total,
        cotis_total_deductibles=(cotis_total if company.cotis_payees_par_societe else 0.0),
        is_juridique=is_juridique,
        is_economique=is_economique,
        cotisations_sociales_total=cotisations_sociales_total,
        impots_perso_total=impots_perso_total,
        total_prelevements_juridique=total_prelev_juridique,
        total_prelevements_economique=total_prelev_economique,
        per_manager=per_manager,
    )


# -------------------------------
# PHASE 3 — VARIABLES DÉRIVÉES (UNE SEULE FOIS)
# -------------------------------
def build_config_from_state() -> Tuple[List[ManagerInput], CompanyParams, SSIParams, PersonalTaxParams, Dict[ScenarioName, float]]:
    nb = int(st.session_state["nb_gerants"])
    obj_m = list(st.session_state["obj_net_mensuels"])
    managers = [
        ManagerInput(name=f"Gérant {i+1}", obj_net_annuel=max(0.0, float(obj_m[i])) * 12.0)
        for i in range(nb)
    ]

    capital = _safe_float(st.session_state["capital_social"])
    primes = _safe_float(st.session_state["primes_emission"])
    cca = _safe_float(st.session_state["cca"])
    seuil_10 = 0.10 * max(0.0, (capital + primes + cca))

    company = CompanyParams(
        resultat_avant_remu=_safe_float(st.session_state["resultat_avant_remu"]),
        option_is_reduit=bool(st.session_state["option_is_reduit"]),
        seuil_is_reduit=_safe_float(st.session_state["seuil_is_reduit"]),
        taux_is_reduit=_safe_float(st.session_state["taux_is_reduit"]),
        taux_is_normal=_safe_float(st.session_state["taux_is_normal"]),
        cotis_payees_par_societe=bool(st.session_state["cotis_payees_par_societe"]),
        capital_social=capital,
        primes_emission=primes,
        cca=cca,
    )

    tax = PersonalTaxParams(
        mode_dividendes=st.session_state["mode_dividendes"],
        taux_ir_remu=_safe_float(st.session_state["taux_ir_remu"]),
        taux_ir_div=_safe_float(st.session_state["taux_ir_div"]),
        abattement_div_40=bool(st.session_state["abattement_div_40"]),
        apply_ps_on_div_above_prudent=bool(st.session_state["apply_ps_on_div_above_prudent"]),
        apply_ir_on_div_above=bool(st.session_state["apply_ir_on_div_above"]),
    )

    ssi = SSIParams(
        mode_assiette_ssi=st.session_state["mode_assiette_ssi"],
        apply_ssi_on_div_above=bool(st.session_state["apply_ssi_on_div_above"]),
        seuil_div_10pct=seuil_10,
        ssi_table=st.session_state["ssi_table"],
        use_csg=bool(st.session_state["use_csg"]),
        taux_csg_crds=_safe_float(st.session_state["taux_csg_crds"]),
        abattement_csg=_safe_float(st.session_state["abattement_csg"]),
        use_fp=bool(st.session_state["use_fp"]),
        pass_annuel=_safe_float(st.session_state["pass_annuel"]),
        taux_fp=_safe_float(st.session_state["taux_fp"]),
    )

    scenarios = dict(st.session_state["scenario_splits"])
    return managers, company, ssi, tax, scenarios


# -------------------------------
# PHASE 2 — UI (tabs) : zéro calcul métier
# -------------------------------
def ui_tabs() -> None:
    st.title("Opti-Remu — Optimisation rémunération / dividendes (SARL gérant majoritaire)")

    tabs = st.tabs(["Gérants", "Société", "Dividendes & IR", "SSI (hors CSG/FP)", "CSG/FP", "Affichage"])

    with tabs[0]:
        st.subheader("Gérants")
        nb = st.number_input("Nombre de gérants", min_value=1, max_value=10, value=int(st.session_state["nb_gerants"]), step=1)
        st.session_state["nb_gerants"] = int(nb)
        init_state()  # resynchronise les objectifs

        cols = st.columns(2)
        with cols[0]:
            st.session_state["selected_gerant"] = st.selectbox(
                "Filtre restitution",
                options=["Tous"] + [f"Gérant {i+1}" for i in range(int(nb))],
                index=0 if st.session_state["selected_gerant"] == "Tous" else ["Tous"] + [f"Gérant {i+1}" for i in range(int(nb))].index(st.session_state["selected_gerant"]),
            )
        with cols[1]:
            st.session_state["cotis_payees_par_societe"] = st.toggle(
                "Cotisations SSI payées par la société (déductibles IS)",
                value=bool(st.session_state["cotis_payees_par_societe"]),
                help="Si activé : cotisations (SSI/CSG/FP) sont déductibles en IS juridique.",
            )

        st.caption("Objectif : net **annuel** = 12 × net mensuel (net en poche après taxes & prélèvements selon vos paramètres).")
        for i in range(int(nb)):
            st.session_state["obj_net_mensuels"][i] = st.number_input(
                f"Objectif net mensuel — Gérant {i+1} (€)",
                min_value=0.0,
                value=float(st.session_state["obj_net_mensuels"][i]),
                step=100.0,
            )

    with tabs[1]:
        st.subheader("Société")
        st.session_state["resultat_avant_remu"] = st.number_input(
            "Résultat avant rémunération (base de simulation) (€)",
            value=float(st.session_state["resultat_avant_remu"]),
            step=1000.0,
        )

        c1, c2, c3 = st.columns(3)
        with c1:
            st.session_state["capital_social"] = st.number_input("Capital social (€)", value=float(st.session_state["capital_social"]), step=1000.0)
        with c2:
            st.session_state["primes_emission"] = st.number_input("Primes d'émission (€)", value=float(st.session_state["primes_emission"]), step=1000.0)
        with c3:
            st.session_state["cca"] = st.number_input("CCA (comptes courants) (€)", value=float(st.session_state["cca"]), step=1000.0)

        st.session_state["option_is_reduit"] = st.toggle("Option taux réduit IS (15%)", value=bool(st.session_state["option_is_reduit"]))
        cc = st.columns(3)
        with cc[0]:
            st.session_state["seuil_is_reduit"] = st.number_input("Seuil IS réduit (€)", value=float(st.session_state["seuil_is_reduit"]), step=500.0)
        with cc[1]:
            st.session_state["taux_is_reduit"] = st.number_input("Taux IS réduit", value=float(st.session_state["taux_is_reduit"]), step=0.01, format="%.4f")
        with cc[2]:
            st.session_state["taux_is_normal"] = st.number_input("Taux IS normal", value=float(st.session_state["taux_is_normal"]), step=0.01, format="%.4f")

        st.session_state["mode_assiette_ssi"] = st.selectbox(
            "Mode assiette SSI",
            ["Remu seule", "Remu + Div > seuil"],
            index=0 if st.session_state["mode_assiette_ssi"] == "Remu seule" else 1,
            help="Active l'intégration des dividendes > 10% dans l'assiette SSI (si option correspondante).",
        )

    with tabs[2]:
        st.subheader("Dividendes & IR")
        st.session_state["mode_dividendes"] = st.radio(
            "Fiscalité dividendes",
            ["PFU", "IR"],
            index=0 if st.session_state["mode_dividendes"] == "PFU" else 1,
            horizontal=True,
        )

        c = st.columns(3)
        with c[0]:
            st.session_state["taux_ir_remu"] = st.number_input("Taux IR (approx) sur rémunération", value=float(st.session_state["taux_ir_remu"]), step=0.01, format="%.4f")
        with c[1]:
            st.session_state["taux_ir_div"] = st.number_input("Taux IR (approx) sur dividendes (si option IR)", value=float(st.session_state["taux_ir_div"]), step=0.01, format="%.4f")
        with c[2]:
            st.session_state["abattement_div_40"] = st.toggle("Abattement 40% (si option IR)", value=bool(st.session_state["abattement_div_40"]))

        st.session_state["apply_ssi_on_div_above"] = st.toggle(
            "Intégrer dividendes > 10% dans l'assiette SSI (activable)",
            value=bool(st.session_state["apply_ssi_on_div_above"]),
            help="Appliqué uniquement si le mode assiette SSI = 'Remu + Div > seuil'.",
        )

        st.session_state["apply_ps_on_div_above_prudent"] = st.toggle(
            "Prélèvements sociaux sur dividendes (approche prudente)",
            value=bool(st.session_state["apply_ps_on_div_above_prudent"]),
        )

        st.session_state["apply_ir_on_div_above"] = st.toggle(
            "Option IR sur la part > seuil (option avancée)",
            value=bool(st.session_state["apply_ir_on_div_above"]),
            help="Ici conservée pour extension; le moteur applique actuellement un traitement homogène du dividende.",
        )

    with tabs[3]:
        st.subheader("Cotisations SSI (hors CSG/FP)")
        st.caption("Table éditable : tranches annuelles sur assiette. Ajustez selon votre référentiel cabinet.")
        st.session_state["ssi_table"] = st.data_editor(
            st.session_state["ssi_table"],
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            column_config={
                "Libellé": st.column_config.TextColumn(required=False),
                "Borne_inf": st.column_config.NumberColumn(format="%.0f", required=True),
                "Borne_sup": st.column_config.NumberColumn(format="%.0f", required=True),
                "Taux": st.column_config.NumberColumn(format="%.4f", required=True),
            },
        )

        with st.expander("Détails (rappel)"):
            st.write(
                "- Ce module couvre les cotisations SSI **hors** CSG/CRDS et FP/CFP (qui sont paramétrées séparément).\n"
                "- La déductibilité IS dépend du paramètre “Cotisations payées par la société”.\n"
                "- En pratique, l’assiette et les règles peuvent être plus fines (minima, plafonds, régularisations)."
            )

    with tabs[4]:
        st.subheader("CSG/FP (modules séparés)")
        c1, c2 = st.columns(2)
        with c1:
            st.session_state["use_csg"] = st.toggle("Appliquer CSG/CRDS", value=bool(st.session_state["use_csg"]))
            st.session_state["taux_csg_crds"] = st.number_input("Taux CSG/CRDS", value=float(st.session_state["taux_csg_crds"]), step=0.001, format="%.4f")
            st.session_state["abattement_csg"] = st.number_input("Abattement CSG (assiette)", value=float(st.session_state["abattement_csg"]), step=0.001, format="%.4f")
        with c2:
            st.session_state["use_fp"] = st.toggle("Appliquer FP/CFP", value=bool(st.session_state["use_fp"]))
            st.session_state["pass_annuel"] = st.number_input("PASS annuel (€)", value=float(st.session_state["pass_annuel"]), step=100.0)
            st.session_state["taux_fp"] = st.number_input("Taux FP/CFP", value=float(st.session_state["taux_fp"]), step=0.0001, format="%.4f")

    with tabs[5]:
        st.subheader("Affichage")
        st.session_state["show_details"] = st.toggle("Afficher les détails (expanders) par défaut", value=bool(st.session_state["show_details"]))


# -------------------------------
# PHASE 5 — RESTITUTION
# -------------------------------
def money(x: float) -> str:
    return f"{x:,.0f} €".replace(",", " ")


def render_results(totals: List[ScenarioTotals], managers: List[ManagerInput], ssi: SSIParams, company: CompanyParams) -> None:
    # Synthèse seuil 10%
    st.info(
        f"Seuil 10% SSI dividendes (capital + primes + CCA) = {money(ssi.seuil_div_10pct)} "
        f"(capital={money(company.capital_social)}, primes={money(company.primes_emission)}, CCA={money(company.cca)})"
    )

    # Tableau comparatif final (par scénario)
    rows = []
    for t in totals:
        rows.append(
            {
                "Scénario": t.scenario,
                "Rémunérations (total)": t.remu_total,
                "Cotisations sociales (total)": t.cotisations_sociales_total,
                "Impôts personnels (total)": t.impots_perso_total,
                "IS juridique": t.is_juridique,
                "IS économique": t.is_economique,
                "Total prélèvements (juridique)": t.total_prelevements_juridique,
                "Total prélèvements (économique)": t.total_prelevements_economique,
            }
        )

    df = pd.DataFrame(rows)
    df_show = df.copy()
    for col in df_show.columns:
        if col != "Scénario":
            df_show[col] = df_show[col].apply(lambda v: money(float(v)))
    st.subheader("Tableau comparatif final (A → E)")
    st.dataframe(df_show, use_container_width=True, hide_index=True)

    # Filtres / détails
    filt = st.session_state["selected_gerant"]
    st.subheader("Fiches détaillées (audit-proof)")

    for t in totals:
        default_open = bool(st.session_state["show_details"])
        with st.expander(f"{t.scenario}", expanded=default_open):
            # bloc synthèse scénario
            c = st.columns(4)
            c[0].metric("IS juridique", money(t.is_juridique))
            c[1].metric("IS économique", money(t.is_economique))
            c[2].metric("Impôts personnels", money(t.impots_perso_total))
            c[3].metric("Cotisations sociales", money(t.cotisations_sociales_total))

            # par gérant
            per = t.per_manager
            names = list(per.keys()) if filt == "Tous" else [filt]
            detail_rows = []
            for name in names:
                r = per[name]
                detail_rows.append(
                    {
                        "Gérant": name,
                        "Objectif net annuel": r.obj_net_annuel,
                        "Net via rémunération": r.net_via_remu,
                        "Net via dividendes": r.net_via_div,
                        "Rémunération brute": r.remu_brute,
                        "IR rémunération": r.remu_ir,
                        "Dividendes bruts": r.div_bruts,
                        "PFU/IR dividendes": r.div_pfu_ir,
                        "PS dividendes": r.div_ps,
                        "Assiette SSI (reporting)": r.assiette_ssi,
                        "CSG/CRDS": r.csg_crds,
                        "FP/CFP": r.fp,
                        "IS juridique (alloc E1)": r.is_juridique_alloc,
                        "IS économique (alloc E1)": r.is_economique_alloc,
                    }
                )
            ddf = pd.DataFrame(detail_rows)
            ddf_show = ddf.copy()
            for col in ddf_show.columns:
                if col not in ["Gérant"]:
                    ddf_show[col] = ddf_show[col].apply(lambda v: money(float(v)))
            st.dataframe(ddf_show, use_container_width=True, hide_index=True)

            # commentaire libre
            st.caption("Commentaire libre (par scénario, par gérant) — stocké en session")
            for name in names:
                key = f"{t.scenario}::{name}"
                if key not in st.session_state["commentaires"]:
                    st.session_state["commentaires"][key] = ""
                st.session_state["commentaires"][key] = st.text_area(
                    f"Commentaire — {name}",
                    value=st.session_state["commentaires"][key],
                    key=f"comment_{key}",
                    height=80,
                )


# -------------------------------
# MAIN
# -------------------------------
def main() -> None:
    init_state()
    ui_tabs()

    managers, company, ssi, tax, scenarios = build_config_from_state()

    # Calculs (moteur pur) — une fois
    totals: List[ScenarioTotals] = []
    for scen_name, div_share in scenarios.items():
        totals.append(
            compute_scenario(
                managers=managers,
                company=company,
                ssi=ssi,
                tax=tax,
                scenario=scen_name,
                div_share_of_net=float(div_share),
            )
        )

    # Restitution
    render_results(totals, managers, ssi, company)

    with st.expander("Avertissements & périmètre (à conserver en production)"):
        st.write(
            "- Ce simulateur est un outil de **pilotage** : les paramètres SSI/CSG/FP et IR sont **approximatifs** et doivent être calibrés cabinet.\n"
            "- La réalité SSI inclut des mécanismes (minima, plafonds, régularisations N/N+1, exonérations, etc.).\n"
            "- La fiscalité des dividendes et leur assujettissement SSI dépendent de la situation exacte (statut, capital, CCA, règles applicables).\n"
            "- “IS économique” inclut ici les impôts personnels dans une vision cash globale ; ce n’est pas l’IS fiscal."
        )


if __name__ == "__main__":
    st.set_page_config(page_title="Opti-Remu", layout="wide")
    main()
