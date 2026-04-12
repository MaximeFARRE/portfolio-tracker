# DATA_QUALITY_GAPS

Date d'audit: 2026-04-12
Portee: audit cible des cas restants ou une donnee absente, incomplete ou non calculable peut encore etre affichee comme un vrai zero metier.

## Synthese

Le code a deja corrige plusieurs cas critiques: la vue ensemble affiche des alertes FX et couverture epargne, les projections standard signalent certaines bases incompletes, et la prevision avancee indique quand le patrimoine de depart vaut 0.

Les gaps restants ne justifient pas un gros refactor immediat. Le risque principal vient des totaux agreges: des donnees exclues a cause d'un prix/FX absent sont parfois additionnees comme si elles valaient 0, puis consommees par patrimoine, bourse, liquidites, famille et projection.

## Cas trouves

| ID | Priorite | Ecran / fichier | Variable ou KPI concerne | Type de donnee | Comportement actuel | Comportement attendu |
|---|---|---|---|---|---|---|
| DQ-01 | haute | Ecran Liquidites: `qt_ui/panels/liquidites_panel.py`; service: `services/liquidites.py` | `bank_cash_eur`, `bourse_cash_eur`, `total_eur` | FX compte bancaire/bourse absent | Le compte est ignore du total si la conversion FX retourne `None`; si tous les comptes concernes sont ignores, l'UI affiche `0.00 EUR` comme une vraie liquidite nulle. Le service loggue seulement l'exclusion. | Remonter un statut `incomplete` et la liste des comptes/devises ignores; l'UI doit afficher un badge du type `Donnees FX incompletes`, pas uniquement `0.00 EUR`. |
| DQ-02 | haute | Ecrans patrimoine / vue ensemble / famille / projection; service: `services/snapshots_compute.py` | `liquidites_total`, `bourse_cash`, `bourse_holdings`, `patrimoine_net`, `patrimoine_brut` | FX/prix weekly absent pendant rebuild snapshot | Les comptes/actifs non convertibles ou sans prix sont exclus du snapshot; le snapshot stocke ensuite des montants numeriques arrondis. Les ecrans consommateurs voient un vrai 0 ou une valeur sous-estimee sans flag persistant. | Stocker ou exposer une qualite de snapshot (`complete`, `partial_fx`, `partial_price`) et l'afficher dans les ecrans qui consomment les snapshots. |
| DQ-03 | haute | Bourse live globale et compte bourse: `qt_ui/panels/bourse_global_panel.py`, `qt_ui/panels/compte_bourse_panel.py`; service: `services/portfolio.py` | `last_price`, `value`, `pnl_latent`, `Valeur Actuelle`, `Holdings` | Prix live absent | `compute_positions_v1` remplace `last_price` manquant par `0.0`, donc la valeur et le PnL deviennent 0 pour la ligne. Un diagnostic ticker existe, mais les KPI agrégés utilisent quand meme ces valeurs. | Garder la ligne en `prix manquant` / `non valorisable` et exclure ou flagger explicitement la valorisation agrégée; l'UI ne doit pas laisser croire que la position vaut 0. |
| DQ-04 | haute | Bourse historique: `qt_ui/panels/bourse_global_panel.py`; service: `services/bourse_analytics.py::get_bourse_state_asof` | `total_val`, `fx_rate`, `value`, `Perf Globale` historique | FX historical absent | En mode historique, si le taux FX est absent, `fx_rate` retombe a `1.0`. Une devise non-EUR peut donc etre traitee comme EUR. Si le prix est absent, `px` devient `0.0`. | Ne pas fallback a `1.0` hors EUR; retourner `None`/statut incomplet et afficher un avertissement dans le mode historique. |
| DQ-05 | moyenne | Bourse globale: `qt_ui/panels/bourse_global_panel.py`; service: `services/bourse_analytics.py::get_bourse_performance_metrics` | `global_perf_pct`, `ytd_perf_pct`, `invested_eur` | Historique ou montant investi non calculable | `global_perf` et `ytd_perf` demarrent a `0.0`; si `invested_eur <= 0`, pas assez d'historique YTD, ou conversion investie ignoree, l'UI affiche `0.00 %` au lieu de `N/A`. | Retourner `None` pour les performances non calculables et afficher `—`/`N/A`, avec une raison courte (`investi manquant`, `historique insuffisant`). |
| DQ-06 | moyenne | Bourse globale: `qt_ui/panels/bourse_global_panel.py`; service: `services/bourse_analytics.py::compute_passive_income_history` | `Dividendes (all time)`, `Interets (all time)` | FX revenu passif absent | Les dividendes/interets non convertibles sont ignores; si tous les revenus concernes sont ignores, les KPI affichent `0 EUR`. | Remonter `income_fx_missing_count` ou une liste de devises ignorees; l'UI doit distinguer `aucun revenu` de `revenus non convertibles`. |
| DQ-07 | moyenne | Vue ensemble: `qt_ui/panels/vue_ensemble_panel.py`; service: `services/vue_ensemble_metrics.py` | Graphiques cashflow, `epargne_12m`, `capacite_epargne_avg`, `taux_epargne_avg` | Colonnes cashflow absentes / mois sans donnees | Les mois manquants sont volontairement reindexes a 0; la vue affiche une alerte si moins de 8 mois sur 12 ont revenus/depenses non nuls. Mais une colonne attendue absente dans la preparation graphique peut encore etre remplacee par 0. | Conserver le reindex calendrier, mais exposer un champ de couverture/colonnes manquantes depuis le service plutot qu'une detection UI heuristique. |
| DQ-08 | moyenne | Famille: `qt_ui/pages/famille_page.py`; service: `services/family_dashboard.py` | `Liquidites`, `Bourse`, `PE`, `Entreprises`, `Immobilier`, `% Expo Bourse`, treemap/area charts | Colonnes snapshot absentes ou personne sans snapshot a la semaine commune | Plusieurs helpers utilisent `get(..., 0.0)` ou remplacent une colonne absente par 0. Une personne sans snapshot est ignoree; une exposition bourse non calculable devient `0.0 %`. | Ajouter un statut `person_missing_snapshot` / `category_missing_column`; l'UI famille doit afficher un warning quand le tableau ou les charts excluent une personne/categorie faute de donnees. |
| DQ-09 | haute | Projection standard: `qt_ui/pages/goals_projection_page.py`; service: `services/projections.py` | `Patrimoine actuel`, `Revenus mensuels moyens`, `Depenses mensuelles moyennes`, `Epargne mensuelle`, `Objectif FIRE`, `Progression FIRE` | Snapshot ou cashflow absent | La page affiche deja un warning quand snapshot/revenus/depenses sont a 0. Mais la base de projection convertit les absences en 0 via `safe_float`, puis la simulation peut produire un objectif FIRE de 0 et une progression FIRE de 100% si les depenses sont absentes. | Bloquer ou degrader la simulation FIRE si les depenses sont non disponibles; `0 depenses` ne doit etre accepte comme vrai zero que si la couverture cashflow le prouve. |
| DQ-10 | haute | Prevision avancee: `qt_ui/panels/prevision_avancee_panel.py`; service: `services/prevision_base.py` | `current_net_worth`, `current_cash`, `current_equity`, `current_savings_per_year`, `fire_annual_expenses`, `current_passive_income_per_year`, `current_crypto` | Base prevision absente / champs non supportes | `prevision_base` initialise beaucoup de champs a `0.0` et utilise `or 0.0` pour les metriques absentes. L'UI signale seulement `Patrimoine non renseigné` si net worth = 0; crypto et revenus passifs sont explicitement forces a 0 avec warnings dans le modele, mais ces warnings ne sont pas visibles dans les KPI principaux. | Afficher les `warnings` de `PrevisionBase` de facon visible et distinguer `non supporte` / `non disponible` / `vrai zero`. |
| DQ-11 | faible | Objectifs / jalons: `qt_ui/pages/goals_projection_page.py` | `Montant actuel`, `Progression %`, jalons natifs | Objectif sans montant courant ou jalon indisponible | Les montants absents passent souvent par `safe_float(..., 0.0)`. La page affiche deja des messages d'indisponibilite pour les jalons, mais les lignes d'objectifs peuvent montrer une progression 0%. | Acceptable court terme; ameliorer seulement si les objectifs deviennent un flux produit critique. |
| DQ-12 | faible | Liquidites et certains charts: `qt_ui/panels/liquidites_panel.py`, `qt_ui/pages/famille_page.py`, `qt_ui/panels/vue_ensemble_panel.py` | Pie charts / charts d'allocation | Allocation vide ou toutes categories a 0 | Quand le DataFrame de chart est vide, certains builders retournent sans poser de figure explicite `vide`. Selon l'etat precedent du widget, cela peut laisser une ancienne figure ou un espace neutre plutot qu'un message `aucune donnee`. | Nettoyer les figures ou afficher un placeholder explicite quand le dataset est vide. Priorite faible car ce n'est pas un zero numerique KPI, mais c'est une ambiguite visuelle. |

## Cas deja partiellement couverts

- Vue ensemble: alerte FX manquants et alerte couverture epargne deja presentes dans `qt_ui/panels/vue_ensemble_panel.py`.
- Projection standard: warning deja affiche si aucun snapshot, aucun revenu mensuel ou aucune depense mensuelle.
- Prevision avancee: la carte `Patrimoine actuel` signale deja `Patrimoine non renseigné` quand la base vaut 0.
- Bourse: diagnostic ticker affiche deja les prix live/weekly absents, mais il ne protege pas encore les KPI agreges.

## Priorite d'action recommandee

1. Haute: DQ-01, DQ-02, DQ-03, DQ-04, DQ-09, DQ-10.
2. Moyenne: DQ-05, DQ-06, DQ-07, DQ-08.
3. Faible: DQ-11, DQ-12.

## Corrections mineures eventuelles

Aucune correction code appliquee pendant cet audit. Les corrections utiles demandent un petit contrat de qualite de donnees en sortie service (`quality_status`, `missing_fx`, `missing_prices`, `coverage_months`) plutot qu'un patch local isole. Un patch local uniquement UI risquerait de masquer une partie des cas sans corriger les totaux en amont.

## Tests

Aucun test execute pour cette mission: seule la documentation `DATA_QUALITY_GAPS.md` a ete ajoutee, sans modification de code.
