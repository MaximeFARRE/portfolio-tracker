# ARCHITECTURE_SOURCES_DE_VERITE.md

> Référence SSOT (Single Source of Truth)
> Dernière mise à jour : 2026-04-07

Ce document définit les fonctions **officielles** à consommer pour les KPI et payloads métier.
Objectif : éviter les chemins concurrents et garantir un chiffre unique pour un même indicateur.

---

## 1) Règle globale

Architecture obligatoire :

```text
UI -> Services -> Repository / DB
```

Conséquences :
- Un panel/page Qt ne recalcule pas un KPI métier déjà fourni par un service.
- Un panel/page Qt ne lit pas directement plusieurs sources DB pour reconstruire un résultat métier.
- Toute logique de fallback métier vit dans les services.

---

## 2) KPI -> Source officielle

| KPI / Payload | Source officielle | Statut |
|---|---|---|
| Historique patrimoine personne | `services.snapshots.get_person_weekly_series` | OK |
| Historique patrimoine famille | `services.family_snapshots.get_family_weekly_series` | OK |
| KPI vue d'ensemble personne | `services.vue_ensemble_metrics.get_vue_ensemble_metrics` | OK |
| Positions bourse live (personne) | `services.bourse_analytics.get_live_bourse_positions` | OK |
| Positions bourse live (compte) | `services.bourse_analytics.get_live_bourse_positions_for_account` | OK |
| Capital investi bourse | `services.bourse_analytics.compute_invested_amount_eur_asof` | OK |
| Série bourse hebdo | `services.bourse_analytics.get_bourse_weekly_series` | OK |
| Perf bourse (perf/CAGR/12m) | `services.bourse_analytics.get_bourse_performance_metrics` | OK |
| Revenus passifs bourse | `services.bourse_analytics.compute_passive_income_history` | OK |
| Cashflow mensuel (scope) | `services.cashflow.get_cashflow_for_scope` | OK |
| Série mensuelle d'épargne personne | `services.cashflow.get_person_monthly_savings_series` | OK |
| KPIs d'épargne (12m/streak/capacité) | `services.cashflow.compute_savings_metrics` | OK |
| Taux d'épargne panel dédié | `services.cashflow.compute_savings_metrics` | OK |
| Synthèse liquidités personne | `services.liquidites.get_liquidites_summary` | OK |
| CRD à date | `services.credits.get_crd_a_date` | OK |
| Coût réel mensuel crédit | `services.credits.cout_reel_mois_credit_via_bankin` | OK |
| Projections patrimoine | `services.projections.run_projection` | OK |
| Base de projection | `services.projections.get_projection_base_for_scope` | OK |
| Milestones natives | `services.native_milestones.build_native_milestones_for_scope` | OK |

Notes de transition :
- `services.portfolio.compute_positions_v2_fx` reste un moteur interne utilisé via `bourse_analytics`.
- `services.revenus_repository.compute_taux_epargne_mensuel` est un chemin legacy (compatibilité), à ne plus brancher directement dans l'UI.

---

## 3) Écrans -> Services à consommer

### 3.1 Pages

| Écran | Service(s) métier attendu(s) | Statut |
|---|---|---|
| `qt_ui/pages/famille_page.py` | `family_snapshots`, `family_dashboard`, `diagnostics_global`, `cashflow` | Majoritairement aligné |
| `qt_ui/pages/personnes_page.py` | orchestration panels + `repositories` pour structure UI | Aligné UI |
| `qt_ui/pages/goals_projection_page.py` | `projections`, `native_milestones`, repositories de scénarios/presets | En cours côté domaine dédié |
| `qt_ui/pages/import_page.py` | `imports`, `tr_import`, `import_history`, `credits` | Aligné |
| `qt_ui/pages/settings_page.py` | services config/backups/presets | Aligné |

### 3.2 Panels

| Panel | Point(s) d'entrée métier | Statut |
|---|---|---|
| `qt_ui/panels/vue_ensemble_panel.py` | `vue_ensemble_metrics.get_vue_ensemble_metrics` | Propre |
| `qt_ui/panels/bourse_global_panel.py` | `bourse_analytics.get_live_bourse_positions` + APIs bourse analytics | Propre |
| `qt_ui/panels/compte_bourse_panel.py` | `bourse_analytics.get_live_bourse_positions_for_account` | Propre |
| `qt_ui/panels/taux_epargne_panel.py` | `cashflow.compute_savings_metrics` | Propre |
| `qt_ui/panels/liquidites_panel.py` | `liquidites.get_liquidites_summary` | Propre |
| `qt_ui/panels/credits_overview_panel.py` | `credits.*` | Quasi propre (reste une agrégation locale intermédiaire) |
| `qt_ui/panels/depenses_panel.py` | `depenses_repository` | Propre |
| `qt_ui/panels/revenus_panel.py` | `revenus_repository` | Propre |

---

## 4) Politique de fallback (en production)

### 4.1 Marché / FX
- Prix live absent : log warning côté service bourse, position conservée avec fallback métier prévu (ne pas crasher l'UI).
- FX hebdo introuvable (`convert_weekly`) : log erreur explicite et annulation de la valorisation concernée (0.0) pour éviter une valorisation fausse.

### 4.2 Snapshots
- Série vide/manquante : service retourne DataFrame vide typé, l'UI affiche un état vide explicite.
- Dates invalides : coercition + filtrage avec log warning.

### 4.3 Cashflow
- Revenus/dépenses absents : retours vides ou KPI à 0.0 avec log info/warning côté service.
- Mois incomplets : outer merge + `fillna(0.0)` dans le service.

### 4.4 Crédits
- `payer_account_id` absent : `cout_reel_mois_credit_via_bankin` retourne `0.0` avec warning (comportement attendu).
- Amortissement absent : services crédits retournent un résultat vide sûr, sans casser l'affichage.

---

## 5) Chemins interdits côté UI

- Import direct de `services.portfolio` dans les panels.
- Appel de fonctions privées de service (préfixe `_`) depuis l'UI.
- Recalcul local de KPI bourse/cashflow/liquidités déjà disponibles via service public.
- Agrégation DataFrame métier complexe dans les panels quand un service existe déjà.

---

## 6) Priorités restantes (post mise à jour)

1. Finir le reliquat d'agrégation métier dans `qt_ui/panels/credits_overview_panel.py` en exposant un payload structuré dédié dans `services/credits.py`.
2. Stabiliser définitivement le chemin legacy `revenus_repository.compute_taux_epargne_mensuel` pour éviter tout risque de boucle d'implémentation pendant la transition.
3. Continuer le nettoyage par domaine (un bloc UI + service associé à la fois).

---

## 7) Convention de décision

Si deux implémentations existent, la priorité est :
1. Fonction publique explicitement listée dans ce document.
2. À défaut, service métier du domaine.
3. Jamais la logique recopiée dans l'UI.
