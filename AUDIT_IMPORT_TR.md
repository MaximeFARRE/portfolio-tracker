# Audit — Import Trade Republic

> Fichiers analysés : `qt_ui/pages/import_page.py` · `services/tr_import.py` · `services/isin_resolver.py` · `db/schema.sql`

---

## Résumé exécutif

Le système d'import TR fonctionne dans les grandes lignes mais présente **5 bugs bloquants**, **6 problèmes de qualité de données** et **5 manques d'ergonomie**. Classement par priorité ci-dessous.

---

## 🔴 Bugs bloquants (à corriger en priorité)

### B1 — `_confirm_import()` tourne dans le thread principal (freeze UI)

**Fichier :** `import_page.py` — fonction `_confirm_import()`

```python
# Problème : s'exécute dans l'UI thread
result = import_tr_transactions(
    self._conn, filepath, pid, account_id, dry_run=False
)
```

Le `dry_run=False` fait : résolution des assets manquants + `conn.executemany()` sur potentiellement des centaines de lignes. Sur un gros historique (500+ transactions), l'UI se fige plusieurs secondes.

**Fix** : créer un `_ImportThread(QThread)` identique à `_PreviewThread`, avec signaux `done` / `error`, et désactiver le bouton pendant l'import (comme pour le preview).

---

### B2 — Déduplication trop lâche → faux doublons ou doublons non détectés

**Fichier :** `tr_import.py` — ligne ~491

```python
existing = conn.execute(
    """SELECT id FROM transactions
       WHERE date = ? AND account_id = ? AND type = ? AND ABS(amount - ?) < 0.01""",
    (date_str, account_id, tx_type, tx_amount),
).fetchone()
```

**Cas 1 — Faux doublon :** Si tu as acheté EUNL **et** IWDA le même jour pour le même montant (ex: 500 €), seul le premier sera importé. Le deuxième sera silencieusement ignoré.

**Cas 2 — Doublon non détecté :** Si le montant diffère de 0.02 € à cause d'arrondis dans le CSV (ex: 499.99 vs 500.01), la transaction sera importée deux fois.

**Fix** : ajouter `asset_id` ou `note LIKE 'TR:%'` dans la clé de déduplication. Une clé plus fiable : `date + account_id + type + symbol + ABS(amount) < 0.01`.

---

### B3 — Sélecteur de compte exclut CRYPTO

**Fichier :** `import_page.py` — `_refresh_tr_accounts()`

```python
WHERE person_id = ? AND account_type IN ('PEA', 'CTO')
```

Trade Republic propose aussi un **compte crypto** (ou compte cash). Si l'utilisateur a un compte `CRYPTO`, il ne peut pas y importer ses transactions TR.

**Fix** : étendre le filtre → `account_type IN ('PEA', 'CTO', 'CRYPTO')`.

---

### B4 — `asset_type` deviné par les 2 premiers caractères ISIN → données incorrectes

**Fichier :** `tr_import.py` — `_get_or_create_asset()`

```python
asset_type = "etf" if isin[:2] in ("IE", "LU", "FR", "DE", "NL", "BE") else "action"
```

- Une **action française** (ISIN `FR...`) sera taggée `etf` ✗
- Un **ETF américain** (ISIN `US...`) sera taggé `action` ✗

**Fix** : s'appuyer sur les données retournées par yfinance (champ `quoteType`) déjà disponible dans `_via_yfinance()`, ou utiliser la colonne `title` (qui contient souvent "ETF" ou "UCITS").

---

### B5 — Devise des assets hardcodée à EUR

**Fichier :** `tr_import.py` — `_get_or_create_asset()`

```python
INSERT INTO assets(symbol, name, asset_type, currency) VALUES (?, ?, ?, 'EUR')
```

Les actifs cotés en USD (actions US, ETF US comme `SPY`, `QQQ`) seront créés avec `currency = EUR`. Résultat : les calculs de valorisation appliqueront le taux de change EUR/EUR = 1 au lieu de EUR/USD.

**Fix** : récupérer la devise depuis yfinance (champ `currency` dans `yf.Ticker(symbol).info`), ou passer la devise depuis le CSV si disponible.

---

## 🟠 Problèmes de qualité de données

### Q1 — Type `card` / `cardSuccessful` importé dans le mauvais compte

**Fichier :** `tr_import.py` — `_TR_TYPE_MAP`

```python
"card": "DEPENSE",
"cardSuccessful": "DEPENSE",
```

Ces transactions correspondent à la **carte TR** (débit depuis le cash account). Elles n'ont rien à voir avec un compte PEA ou CTO. Les importer dans le compte bourse pollue les données.

**Fix** : filtrer ces types avant l'import (les ignorer ou les diriger vers un compte BANQUE TR dédié).

---

### Q2 — ISINs non résolus : le symbol ISIN brut est utilisé comme ticker

**Fichier :** `tr_import.py` — ligne ~488

```python
ticker = isin_ticker_map.get(isin) if isin else None
symbol = ticker or isin  # ticker si résolu, ISIN sinon
```

Si l'ISIN n'est pas résolu, l'asset est créé avec l'ISIN comme `symbol` (ex: `IE00B5BMR087`). Plus tard, le système de pricing essaiera de récupérer des prix via yfinance avec cet ISIN → **échec silencieux**, l'actif n'aura jamais de prix.

**Fix** : marquer les assets non résolus avec `status = 'NOT_FOUND'` dans `asset_meta`, et les lister dans le diagnostic pour action manuelle.

---

### Q3 — Cache ISIN "not_found" permanent → re-résolution impossible

**Fichier :** `isin_resolver.py` — `batch_resolve_isins()`

```python
_set_cached(conn, isin, "", "not_found")
```

Un ISIN non trouvé lors du premier import ne sera **jamais** re-tenté, même si tu améliores le code ou si l'API devient disponible. Il est bloqué avec `ticker = ""` en cache.

**Fix** : ajouter un champ `resolved_at` (déjà présent) et ignorer le cache si l'entrée a plus de N jours (ex: 7 jours). Ajouter un bouton "Vider le cache ISIN" dans l'UI.

---

### Q4 — Frais et taxes fusionnés dans la colonne `fees`

**Fichier :** `tr_import.py` — `_normalize_columns()`

```python
"impôts___taxes": "fees",
"taxes": "fees",
```

Trade Republic exporte parfois séparément les frais de courtage et les impôts/taxes (ex: flat tax). Fusionner les deux dans `fees` empêche toute analyse fiscale ultérieure (calcul de PFU, IFU).

**Fix** : conserver une colonne séparée `taxes` dans la table `transactions`, ou au minimum stocker les taxes dans le champ `note` pour la traçabilité.

---

### Q5 — `unit_price` calculé comme `tx_amount / shares` pour les non-trades

**Fichier :** `tr_import.py` — lignes ~483-485

```python
if not unit_price and shares and shares > 0 and tx_type in ("ACHAT", "VENTE"):
    unit_price = tx_amount / shares
```

Le calcul est conditionné à `tx_type in ("ACHAT", "VENTE")`, ce qui est correct. Mais `tx_amount = abs(amount)` est utilisé, alors que Trade Republic peut exprimer le montant **en devise locale** (GBX, USD) converti en EUR. Le prix calculé sera en EUR, pas dans la devise native de l'actif.

---

### Q6 — Le `note` perd le titre de l'actif si vide

**Fichier :** `tr_import.py` — lignes ~520-522

```python
f"TR: {tr_type} | {title}" if title else f"TR: {tr_type}",
```

Pour les dépôts/retraits sans titre (`title = ""`), on n'a que `"TR: paymentInbound"`. Ce n'est pas très lisible.

**Fix** : ajouter le ticker résolu dans la note pour les trades → `f"TR: {tr_type} | {symbol} | {title}"`.

---

## 🟡 Manques d'ergonomie (UX)

### E1 — Pas de bouton "Vider le cache ISIN" dans l'UI

Si un ticker est mal résolu (ex: `EUNL.DE` au lieu de `EUNL.AS`), il n'y a aucun moyen de le corriger depuis l'interface. Il faut modifier la DB manuellement.

**Fix** : ajouter dans le panel TR un bouton "🔄 Vider cache ISIN" qui appelle `isin_resolver.clear_cache(conn)` et un champ texte pour vider un ISIN spécifique.

---

### E2 — Pas de feedback sur la progression de la résolution ISIN

Pendant le preview, le message est `"⏳ Résolution des tickers en cours…"` mais si le fichier contient 20 ISINs non cachés, chaque appel yfinance peut prendre 1-2 secondes → 20-40 secondes de wait sans progression.

**Fix** : émettre un signal de progression depuis `_PreviewThread` → afficher `"X/Y ISINs résolus…"` en temps réel.

---

### E3 — Aucun moyen de voir les ISINs non résolus après l'import

Le résumé post-preview affiche `"X ISIN(s) non résolus"` mais la liste complète n'est visible que dans les logs. Après fermeture de la fenêtre, cette info est perdue.

**Fix** : afficher dans le résumé un tableau cliquable des ISINs non résolus avec un champ de saisie manuelle du ticker.

---

### E4 — L'étape 2 (Export) s'active seulement après un login réussi

Si les credentials pytr sont déjà sauvegardés (login fait une fois), l'utilisateur doit quand même re-login pour activer le bouton "Exporter".

**Fix** : au chargement du panel, vérifier si des credentials pytr existent déjà et activer le bouton "Exporter" directement si c'est le cas.

---

### E5 — Le PIN est visible dans `PytrProcess` args (logs système)

**Fichier :** `import_page.py` — `_do_login()`

```python
proc = PytrProcess(["login", "-n", phone, "-p", pin, "--store_credentials"])
```

Le PIN TR apparaît en clair dans la liste de processus système (`ps aux`, gestionnaire de tâches). C'est un risque de sécurité sur une machine partagée.

**Fix** : pytr accepte de lire le PIN depuis stdin. Lancer le processus sans `-p pin`, puis envoyer le PIN via `proc.send_input(pin)` quand pytr le demande.

---

## Synthèse prioritaire

| # | Problème | Priorité | Effort |
|---|---|---|---|
| B1 | `_confirm_import` bloque l'UI | 🔴 Critique | Faible |
| B2 | Déduplication faux doublons / manqués | 🔴 Critique | Moyen |
| B3 | CRYPTO exclu du sélecteur de compte | 🔴 Critique | Très faible |
| B4 | `asset_type` incorrect (ETF/action) | 🔴 Critique | Moyen |
| B5 | Devise assets hardcodée EUR | 🔴 Critique | Moyen |
| Q1 | Transactions carte TR dans mauvais compte | 🟠 Important | Faible |
| Q2 | ISIN non résolu → symbol invalide en DB | 🟠 Important | Moyen |
| Q3 | Cache ISIN "not_found" permanent | 🟠 Important | Faible |
| Q4 | Frais + taxes fusionnés | 🟠 Important | Moyen |
| Q5 | Prix calculé en EUR au lieu de devise native | 🟠 Important | Moyen |
| Q6 | Note peu lisible sans titre | 🟡 Mineur | Très faible |
| E1 | Pas de bouton "Vider cache ISIN" | 🟡 Ergonomie | Faible |
| E2 | Pas de progression résolution ISIN | 🟡 Ergonomie | Moyen |
| E3 | Liste ISINs non résolus perdue après preview | 🟡 Ergonomie | Faible |
| E4 | Re-login inutile si credentials existants | 🟡 Ergonomie | Faible |
| E5 | PIN visible en clair dans les processus | 🟡 Sécurité | Faible |

---

## Ordre de correction recommandé

1. **B3** (2 lignes de code — impact immédiat, 0 risque)
2. **B1** (créer `_ImportThread`, copie de `_PreviewThread`)
3. **Q1** (filtrer `card` / `cardSuccessful` avant l'insert)
4. **Q3 + E1** (reset cache ISIN : 1 bouton + expiration par date)
5. **B2** (renforcer la clé de déduplication avec `symbol`)
6. **E4** (vérifier credentials pytr au chargement)
7. **B4 + B5** (corriger `asset_type` et `currency` via yfinance)
8. **E2 + E3** (progression + tableau ISINs non résolus)
9. **E5** (PIN via stdin)
10. **Q4** (séparation frais/taxes)
