"""
Trade Republic — import via pytr 0.4.x.

Flux authentification (2 étapes) :
  1. login  : pytr login -n PHONE -p PIN --store_credentials
              → TR envoie une notification push sur l'app.
              → Si premier appareil, pytr affiche un code 4 car. que l'app demande.
              → Les credentials sont sauvegardés localement par pytr.

  2. export : pytr export_transactions --outputdir DIR
              → Utilise les credentials sauvegardés, pas besoin du PIN.
              → Produit account_transactions.csv dans DIR.

  3. import : parse + insérer dans la table transactions.

Chaque personne peut avoir un numéro TR différent (colonne tr_phone dans people).
"""

import logging
import os
import queue
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

import pandas as pd
from services import import_aliases_service

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Utilitaires bas-niveau
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def strip_ansi(text: str) -> str:
    """Supprime tous les codes ANSI/VT100 (couleurs, gras, etc.) d'une chaîne."""
    return _ANSI_RE.sub('', text)


def _find_pytr_cmd() -> list[str]:
    """
    Résout la commande pour lancer pytr, quelle que soit la configuration
    (venv sans pytr, Python système, exécutable direct dans PATH).

    Ordre de recherche :
      1. sys.executable -m pytr  (Python courant, ex: venv si pytr y est installé)
      2. python / python3 dans PATH (Python système)
      3. Exécutable `pytr` direct dans PATH
    Retourne toujours une liste utilisable, même si pytr est introuvable
    (l'erreur sera remontée au lancement effectif du processus).
    """
    # 1. Python courant (venv ou système)
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytr", "--version"],
            capture_output=True, text=True, timeout=6,
        )
        if r.returncode == 0:
            return [sys.executable, "-m", "pytr"]
    except Exception:
        pass

    # 2. python / python3 dans PATH (cas courant : venv sans pytr)
    for name in ("python", "python3"):
        py = shutil.which(name)
        if py and py != sys.executable:
            try:
                r = subprocess.run(
                    [py, "-m", "pytr", "--version"],
                    capture_output=True, text=True, timeout=6,
                )
                if r.returncode == 0:
                    return [py, "-m", "pytr"]
            except Exception:
                pass

    # 3. Exécutable pytr direct
    pytr_exe = shutil.which("pytr")
    if pytr_exe:
        return [pytr_exe]

    # Fallback (génèrera une erreur explicite au lancement)
    return [sys.executable, "-m", "pytr"]


# ---------------------------------------------------------------------------
# Gestion des credentials pytr
# ---------------------------------------------------------------------------

def get_pytr_credentials_path() -> Path:
    """Retourne le chemin du fichier de credentials pytr (~/.pytr/credentials)."""
    return Path.home() / ".pytr" / "credentials"


def pytr_has_credentials() -> bool:
    """Retourne True si des credentials pytr existent localement."""
    return get_pytr_credentials_path().exists()


def clear_pytr_credentials() -> bool:
    """Supprime le fichier de credentials pytr. Retourne True si supprimé."""
    cred_path = get_pytr_credentials_path()
    if cred_path.exists():
        cred_path.unlink()
        _logger.info("Credentials pytr supprimés : %s", cred_path)
        return True
    return False


# ---------------------------------------------------------------------------
# Mapping types Trade Republic → types internes
# ---------------------------------------------------------------------------

_TR_TYPE_MAP: dict[str, str | None] = {
    # Dépôts
    "paymentinbound": "DEPOT",
    "paymentinboundsepadirectdebit": "DEPOT",
    "paymentinboundbonus": "DEPOT",
    "paymentinboundgratuity": "DEPOT",
    "benefitstemplateexecution": "DEPOT",
    "dépôt": "DEPOT",
    "depot": "DEPOT",
    "deposit": "DEPOT",
    # Retraits
    "paymentoutbound": "RETRAIT",
    "paymentoutboundsepadirectdebit": "RETRAIT",
    "retrait": "RETRAIT",
    "withdrawal": "RETRAIT",
    # Trades  (sens déterminé par le signe du montant)
    "trade": None,
    "achat": "ACHAT",
    "vente": "VENTE",
    "buy": "ACHAT",
    "sell": "VENTE",
    "savingsplanexecuted": "ACHAT",
    "savingsplaninvestment": "ACHAT",
    "roundupinvestment": "ACHAT",
    # Revenus
    "dividendincome": "DIVIDENDE",
    "dividende": "DIVIDENDE",
    "dividendes": "DIVIDENDE",
    "dividend": "DIVIDENDE",
    "interest": "INTERETS",
    "intérêts": "INTERETS",
    "interets": "INTERETS",
    "vatexemptinterest": "INTERETS",
    "interests": "INTERETS",
    # Frais / divers
    "roundup": "FRAIS",
    "card": "DEPENSE",
    "cardsuccessful": "DEPENSE",
}


def _map_tr_type(tr_type: str, amount: float) -> str:
    mapped = _TR_TYPE_MAP.get(tr_type.strip().lower())
    if mapped is None:
        return "ACHAT" if amount <= 0 else "VENTE"
    return mapped


# ---------------------------------------------------------------------------
# Lecture / écriture du numéro TR par personne
# ---------------------------------------------------------------------------

def get_tr_phone(conn, person_id: int) -> str:
    """Retourne le numéro TR stocké pour cette personne (ou chaîne vide)."""
    try:
        row = conn.execute(
            "SELECT tr_phone FROM people WHERE id = ?", (person_id,)
        ).fetchone()
        if row:
            val = row[0] if not hasattr(row, "keys") else row["tr_phone"]
            return val or ""
    except Exception:
        pass
    return ""


def save_tr_phone(conn, person_id: int, phone: str) -> None:
    """Sauvegarde le numéro TR pour cette personne."""
    conn.execute(
        "UPDATE people SET tr_phone = ? WHERE id = ?",
        (phone.strip(), person_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Vérification installation
# ---------------------------------------------------------------------------

def check_pytr_installed() -> tuple[bool, str]:
    cmd = _find_pytr_cmd()
    try:
        result = subprocess.run(
            cmd + ["--version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            ver = strip_ansi((result.stdout or result.stderr or "").strip())
            return True, ver
    except Exception as e:
        return False, str(e)
    return False, "pytr non installé — lancez : pip install pytr"


# ---------------------------------------------------------------------------
# Processus interactif (lecture ligne par ligne)
# ---------------------------------------------------------------------------

class PytrProcess:
    """
    Lance un processus pytr et lit stdout/stderr caractère par caractère.
    Nécessaire car pytr émet des prompts sans saut de ligne (ex: "Reset device? (y)")
    via input() — un lecteur ligne-par-ligne resterait bloqué indéfiniment.

    PYTHONUNBUFFERED=1 force pytr à flusher immédiatement même quand stdout
    est un pipe (non-tty), ce qui garantit la réception des prompts.

    Thread-safe via une queue de lignes.
    """

    def __init__(self, args: list[str], waf_token: str = ""):
        extra = ["--waf-token", waf_token] if waf_token else []
        self._args = _find_pytr_cmd() + args + extra
        self._proc: subprocess.Popen | None = None
        self._line_queue: queue.Queue[str | None] = queue.Queue()
        self._threads: list[threading.Thread] = []
        self.returncode: int | None = None

    def start(self) -> None:
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        self._proc = subprocess.Popen(
            self._args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        t = threading.Thread(target=self._reader, daemon=True)
        t.start()
        self._threads.append(t)

    def _reader(self) -> None:
        """
        Lit caractère par caractère pour détecter les prompts sans newline.
        Envoie chaque ligne complète (ou chaque prompt partiel) dans la queue.
        """
        assert self._proc and self._proc.stdout
        buf = ""
        while True:
            ch = self._proc.stdout.read(1)
            if not ch:          # EOF → processus terminé
                break
            if ch == "\n":
                self._line_queue.put(buf.rstrip("\r"))
                buf = ""
            else:
                buf += ch
        if buf:                 # Ligne partielle restante (prompt sans newline)
            self._line_queue.put(buf)
        self._proc.wait()
        self.returncode = self._proc.returncode
        self._line_queue.put(None)  # sentinelle de fin

    def send_input(self, text: str) -> None:
        """Envoie une ligne sur stdin du processus (ex: le code 4 caractères)."""
        if self._proc and self._proc.stdin:
            try:
                self._proc.stdin.write(text + "\n")
                self._proc.stdin.flush()
            except Exception:
                pass

    def next_line(self, timeout: float = 0.1) -> str | None:
        """
        Retourne la prochaine ligne disponible ou None si timeout/fin.
        None = fin de processus.
        """
        try:
            return self._line_queue.get(timeout=timeout)
        except queue.Empty:
            return ""  # chaîne vide = pas encore de ligne (différent de None = fin)

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def terminate(self) -> None:
        if self._proc and self.is_running():
            self._proc.terminate()


# ---------------------------------------------------------------------------
# Lancement pytr en mode non-interactif (export uniquement)
# ---------------------------------------------------------------------------

def run_pytr_export(
    output_dir: str,
    phone: str = "",
    pin: str = "",
    waf_token: str = "",
) -> tuple[int, str]:
    """
    Lance pytr export_transactions (web login) avec les credentials sauvegardés.
    Retourne (returncode, output_text).
    """
    os.makedirs(output_dir, exist_ok=True)

    args = _find_pytr_cmd() + ["export_transactions",
            "--outputdir", output_dir, "--sort"]

    if phone:
        args += ["-n", phone]
    if pin:
        args += ["-p", pin]
    if phone:
        args += ["--store_credentials"]
    if waf_token:
        args += ["--waf-token", waf_token]

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=180,
        )
        out = (result.stdout or "") + (result.stderr or "")
        if pin and len(pin) >= 4:
            out = out.replace(pin, "****")
        return result.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return -1, "Timeout: l'export a pris trop de temps (>180s)."
    except Exception as e:
        err = str(e)
        if pin and len(pin) >= 4:
            err = err.replace(pin, "****")
        return -1, err


# ---------------------------------------------------------------------------
# Détection du CSV exporté
# ---------------------------------------------------------------------------

def find_tr_csv(output_dir: str) -> str | None:
    candidates = ["account_transactions.csv", "transactions.csv"]
    for name in candidates:
        p = Path(output_dir) / name
        if p.exists():
            return str(p)
    for p in Path(output_dir).glob("*.csv"):
        return str(p)
    return None


# ---------------------------------------------------------------------------
# Parser CSV
# ---------------------------------------------------------------------------

def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalise les noms de colonnes du CSV pytr.
    Gère les variantes FR/DE/EN et les colonnes *2 (isin2, parts2).
    """
    # 1. Nettoyage brut : minuscules + séparateurs → _
    cols_clean = [
        c.strip().lower()
         .replace(" ", "_")
         .replace("/", "_")
         .replace("-", "_")
         .replace(".", "_")
        for c in df.columns
    ]
    df.columns = cols_clean

    # 2. Table de mapping : nom_brut → nom_cible
    #    Les colonnes *2 (isin2, parts2) sont des fallbacks :
    #    elles ne remplacent la cible que si la cible n'est pas déjà présente.
    MAPPING: dict[str, str] = {
        # date
        "date": "date", "datetime": "date", "timestamp": "date",
        "time": "date", "datum": "date",
        # title / description
        "title": "title", "name": "title", "description": "title",
        "asset": "title", "instrument": "title",
        "note": "title", "notes": "title",
        "bezeichnung": "title", "libellé": "title", "libelle": "title",
        # amount
        "amount": "amount", "montant": "amount", "value": "amount",
        "total": "amount", "valeur": "amount",   # pytr FR
        "betrag": "amount", "wert": "amount",    # pytr DE
        # shares (quantité de titres)
        "shares": "shares", "quantity": "shares", "qty": "shares",
        "units": "shares", "anzahl": "shares",
        "parts": "shares",                       # pytr FR
        "stück": "shares",
        # isin
        "isin": "isin",
        # ticker/symbol brut (quand présent dans le CSV TR)
        "ticker": "symbol",
        "symbol": "symbol",
        # type
        "type": "type", "transaction_type": "type", "event_type": "type",
        "status": "type", "typ": "type",
        # price
        "price": "price", "unit_price": "price", "kurs": "price",
        "prix": "price", "cours": "price",
        # fees (frais + taxes fusionnés dans une seule colonne)
        "fees": "fees", "frais": "fees",
        "gebühren": "fees", "commission": "fees",
        "impôts___taxes": "fees",   # pytr FR après nettoyage
        "impots___taxes": "fees",
        "impôts_taxes": "fees",
        "taxes": "fees",
    }

    # Colonnes *2 = fallback (n'écrasent pas si la cible existe déjà)
    FALLBACK: dict[str, str] = {
        "isin2": "isin",
        "parts2": "shares",
    }

    # 3. Construire le dict rename
    targets_used: set[str] = set()
    rename: dict[str, str] = {}

    # Passe principale
    for col in df.columns:
        if col in MAPPING:
            target = MAPPING[col]
            rename[col] = target
            targets_used.add(target)

    # Passe fallback
    for col in df.columns:
        if col in FALLBACK:
            target = FALLBACK[col]
            if target not in targets_used:
                rename[col] = target
                targets_used.add(target)

    return df.rename(columns=rename)


def _parse_amount(raw) -> float | None:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = s.replace("\u2212", "-").replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_tr_csv(filepath: str) -> pd.DataFrame:
    """Parse le CSV pytr et retourne un DataFrame normalisé."""
    df = pd.read_csv(filepath, sep=None, engine="python")
    df = _normalize_columns(df)

    if "date" not in df.columns:
        raise ValueError(
            f"Colonne 'date' introuvable. Colonnes disponibles : {list(df.columns)}"
        )
    if "amount" not in df.columns:
        raise ValueError(
            f"Colonne 'amount' introuvable. Colonnes disponibles : {list(df.columns)}"
        )
    return df


def _upsert_asset_meta_isin(conn, asset_id: int, isin: str | None) -> None:
    isin_u = (isin or "").strip().upper()
    if not asset_id or not isin_u:
        return
    conn.execute(
        """
        INSERT INTO asset_meta(asset_id, isin, status)
        VALUES (?, ?, 'OK')
        ON CONFLICT(asset_id) DO UPDATE SET
            isin = CASE
                     WHEN COALESCE(asset_meta.isin, '') = '' THEN excluded.isin
                     ELSE asset_meta.isin
                   END
        """,
        (int(asset_id), isin_u),
    )


def _find_asset_by_symbol(conn, symbol: str | None) -> dict | None:
    symbol_u = (symbol or "").strip().upper()
    if not symbol_u:
        return None
    row = conn.execute(
        "SELECT id AS asset_id, symbol, name FROM assets WHERE UPPER(symbol) = ? LIMIT 1",
        (symbol_u,),
    ).fetchone()
    if row is None:
        return None
    asset_id = int(row[0] if not hasattr(row, "keys") else row["asset_id"])
    sym = str(row[1] if not hasattr(row, "keys") else row["symbol"])
    name = str(row[2] if not hasattr(row, "keys") else row["name"])
    return {"asset_id": asset_id, "symbol": sym, "name": name}


def _get_or_create_asset_by_symbol(
    conn,
    symbol: str | None,
    title: str,
    *,
    isin: str | None = None,
) -> int | None:
    symbol_u = (symbol or "").strip().upper()
    if not symbol_u:
        return None

    existing = _find_asset_by_symbol(conn, symbol_u)
    if existing is not None:
        _upsert_asset_meta_isin(conn, int(existing["asset_id"]), isin)
        conn.commit()
        return int(existing["asset_id"])

    isin_u = (isin or "").strip().upper()
    # Heuristique simple: les symboles avec suffixe marché sont souvent ETF/actions cotées.
    asset_type = "etf" if "." in symbol_u else "action"
    if isin_u[:2] in ("IE", "LU", "FR", "DE", "NL", "BE"):
        asset_type = "etf"

    conn.execute(
        "INSERT INTO assets(symbol, name, asset_type, currency) VALUES (?, ?, ?, 'EUR')",
        (symbol_u, (title or symbol_u)[:128], asset_type),
    )
    row = conn.execute("SELECT id FROM assets WHERE symbol = ?", (symbol_u,)).fetchone()
    if row is None:
        return None
    asset_id = int(row[0] if not hasattr(row, "keys") else row["id"])
    _upsert_asset_meta_isin(conn, asset_id, isin_u)
    conn.commit()
    return asset_id


# ---------------------------------------------------------------------------
# Asset : get or create
# ---------------------------------------------------------------------------

def _get_or_create_asset(
    conn, isin: str, title: str, ticker: str | None = None
) -> int | None:
    """
    Retourne l'asset_id correspondant à cet ISIN (crée l'asset si besoin).

    Si `ticker` est fourni (résolu via isin_resolver), il est utilisé comme `symbol`
    dans la table assets (meilleure compatibilité yfinance pour les lookups de prix).
    Si l'asset existait déjà avec l'ISIN comme symbol, son symbol est mis à jour vers
    le ticker (migration transparente).
    """
    if not isin or (isinstance(isin, float) and pd.isna(isin)) or not isin.strip():
        return None

    isin = isin.strip().upper()
    effective_symbol = ticker.strip() if ticker else isin

    # 1. Cherche par symbol effectif (ticker ou ISIN)
    row = conn.execute("SELECT id FROM assets WHERE symbol = ?", (effective_symbol,)).fetchone()
    if row:
        asset_id = int(row[0] if not hasattr(row, "keys") else row["id"])
        _upsert_asset_meta_isin(conn, asset_id, isin)
        conn.commit()
        return asset_id

    # 2. Si on a un ticker, cherche un asset existant encore stocké avec l'ISIN comme symbol
    #    (import précédent avant la résolution des tickers) → on migre son symbol
    if ticker and ticker != isin:
        row = conn.execute("SELECT id FROM assets WHERE symbol = ?", (isin,)).fetchone()
        if row:
            asset_id = int(row[0] if not hasattr(row, "keys") else row["id"])
            conn.execute("UPDATE assets SET symbol = ? WHERE id = ?", (effective_symbol, asset_id))
            _upsert_asset_meta_isin(conn, asset_id, isin)
            conn.commit()
            return asset_id

    # 3. Création d'un nouvel asset
    asset_type = "etf" if isin[:2] in ("IE", "LU", "FR", "DE", "NL", "BE") else "action"
    conn.execute(
        "INSERT INTO assets(symbol, name, asset_type, currency) VALUES (?, ?, ?, 'EUR')",
        (effective_symbol, (title or effective_symbol)[:128], asset_type),
    )
    row = conn.execute("SELECT id FROM assets WHERE symbol = ?", (effective_symbol,)).fetchone()
    asset_id = int(row[0] if not hasattr(row, "keys") else row["id"])
    _upsert_asset_meta_isin(conn, asset_id, isin)
    conn.commit()
    return asset_id


# ---------------------------------------------------------------------------
# Extraction et prédiction Multi-Comptes
# ---------------------------------------------------------------------------

def extract_tr_tickers_with_predictions(conn, filepath: str, person_id: int) -> list[dict]:
    df = parse_tr_csv(filepath)
    unique_assets = {}
    if "isin" in df.columns:
        for _, r in df.iterrows():
            isin_raw = r.get("isin", "")
            if isinstance(isin_raw, float) and pd.isna(isin_raw):
                continue
            isin = str(isin_raw).strip().upper()
            if isin and isin not in unique_assets:
                unique_assets[isin] = str(r.get("title", "")).strip()

    from services import isin_resolver
    isins_list = list(unique_assets.keys())
    isin_ticker_map = isin_resolver.batch_resolve_isins(conn, isins_list) if isins_list else {}

    results = []
    processed_symbols = set()
    for isin, title in unique_assets.items():
        ticker = isin_ticker_map.get(isin)
        raw_symbol = ticker or isin
        if raw_symbol in processed_symbols:
            continue
        processed_symbols.add(raw_symbol)

        canonical = import_aliases_service.find_canonical_asset_for_import(
            conn,
            import_aliases_service.IMPORT_SOURCE_TRADE_REPUBLIC,
            raw_symbol=raw_symbol,
            raw_isin=isin,
        )

        if canonical:
            canonical_symbol = canonical["symbol"]
            canonical_asset_id = int(canonical["asset_id"])
            match_source = canonical.get("match_source", "alias")
        else:
            canonical_symbol = raw_symbol
            existing = _find_asset_by_symbol(conn, canonical_symbol)
            canonical_asset_id = int(existing["asset_id"]) if existing else None
            match_source = "fallback"

        predicted_account_id = None
        if canonical_asset_id:
            tx_row = conn.execute(
                "SELECT account_id FROM transactions WHERE asset_id = ? AND person_id = ? ORDER BY date DESC LIMIT 1",
                (canonical_asset_id, person_id)
            ).fetchone()
            if tx_row:
                predicted_account_id = int(tx_row[0] if not hasattr(tx_row, "keys") else tx_row["account_id"])

        results.append({
            "isin": isin,
            "raw_symbol": raw_symbol,
            "symbol": canonical_symbol,
            "canonical_symbol": canonical_symbol,
            "title": title,
            "predicted_account_id": predicted_account_id,
            "match_source": match_source,
        })
    return results

# ---------------------------------------------------------------------------
# Import principal
# ---------------------------------------------------------------------------

def import_tr_transactions(
    conn,
    filepath: str,
    person_id: int,
    account_id: int,
    dry_run: bool = True,
    ticker_account_map: dict[str, int] | None = None,
    canonical_symbol_map: dict[str, str] | None = None,
    import_batch_id: int | None = None,
) -> dict:
    """
    Parse et importe les transactions TR.
    dry_run=True  → preview sans écriture (résolution ISIN→ticker incluse).
    dry_run=False → insertion réelle + déduplication.

    Chaque entrée du preview contient :
      - "raw_symbol" : ticker brut issu de la résolution TR (ou ISIN fallback)
      - "symbol"  : ticker canonique retenu pour l'app
      - "isin"    : ISIN brut tel que fourni par pytr
      - "effective_account_id" : le compte final qui a été attribué (via map ou fallback)
    """
    df = parse_tr_csv(filepath)
    ticker_account_map_norm = {
        str(k or "").strip().upper(): int(v)
        for k, v in (ticker_account_map or {}).items()
        if str(k or "").strip() and v
    }
    canonical_symbol_map_norm = {
        str(k or "").strip().upper(): str(v or "").strip().upper()
        for k, v in (canonical_symbol_map or {}).items()
        if str(k or "").strip() and str(v or "").strip()
    }

    unique_isins: list[str] = []
    if "isin" in df.columns:
        for raw in df["isin"].dropna():
            s = str(raw).strip().upper()
            if s and s not in unique_isins:
                unique_isins.append(s)

    from services import isin_resolver
    isin_ticker_map: dict[str, str] = (
        isin_resolver.batch_resolve_isins(conn, unique_isins) if unique_isins else {}
    )

    preview: list[dict] = []
    rows_to_insert: list[tuple] = []
    rows_meta: list[dict] = []
    skipped = 0
    seen_in_batch: set[tuple] = set()

    for _, r in df.iterrows():
        date_raw = str(r.get("date", "")).strip()
        d = pd.to_datetime(date_raw, errors="coerce", utc=True)
        if pd.isna(d):
            skipped += 1
            continue
        date_str = d.strftime("%Y-%m-%d")

        amount = _parse_amount(r.get("amount"))
        if amount is None:
            skipped += 1
            continue

        tr_type = str(r.get("type", "trade")).strip() if "type" in df.columns else "trade"
        title = str(r.get("title", "")).strip() if "title" in df.columns else ""
        isin_raw = r.get("isin", "") if "isin" in df.columns else ""
        isin = (
            str(isin_raw).strip().upper()
            if isin_raw and not (isinstance(isin_raw, float) and pd.isna(isin_raw))
            else ""
        )

        shares_raw = r.get("shares") if "shares" in df.columns else None
        shares = None
        if shares_raw is not None and not (isinstance(shares_raw, float) and pd.isna(shares_raw)):
            try:
                shares = float(shares_raw)
            except (ValueError, TypeError):
                shares = None

        price_raw = r.get("price") if "price" in df.columns else None
        price_col = None
        if price_raw is not None and not (isinstance(price_raw, float) and pd.isna(price_raw)):
            try:
                price_col = float(str(price_raw).replace(",", ".").replace(" ", ""))
            except (ValueError, TypeError):
                price_col = None

        fees_raw = r.get("fees") if "fees" in df.columns else None
        fees_val = 0.0
        if fees_raw is not None and not (isinstance(fees_raw, float) and pd.isna(fees_raw)):
            try:
                fees_val = abs(float(str(fees_raw).replace(",", ".").replace(" ", "") or "0"))
            except (ValueError, TypeError):
                fees_val = 0.0

        tx_type = _map_tr_type(tr_type, amount)
        tx_amount = abs(amount)
        unit_price = price_col
        if not unit_price and shares and shares > 0 and tx_type in ("ACHAT", "VENTE"):
            unit_price = tx_amount / shares

        csv_raw_symbol = ""
        if "symbol" in df.columns:
            symbol_raw = r.get("symbol")
            if symbol_raw is not None and not (isinstance(symbol_raw, float) and pd.isna(symbol_raw)):
                csv_raw_symbol = str(symbol_raw).strip().upper()

        ticker = isin_ticker_map.get(isin) if isin else None
        raw_symbol = csv_raw_symbol or ticker or isin

        canonical_override_symbol = canonical_symbol_map_norm.get(raw_symbol, "")
        canonical_match = None
        match_source = "fallback"

        if canonical_override_symbol:
            canonical_match = _find_asset_by_symbol(conn, canonical_override_symbol)
            if canonical_match:
                match_source = "user_override_existing"
        else:
            # Priorité auto: ISIN existant -> alias mémorisé.
            canonical_match = import_aliases_service.find_canonical_asset_for_import(
                conn,
                import_aliases_service.IMPORT_SOURCE_TRADE_REPUBLIC,
                raw_symbol=raw_symbol,
                raw_isin=isin,
            )
            if canonical_match:
                match_source = str(canonical_match.get("match_source") or "alias")

        symbol = canonical_override_symbol or raw_symbol
        asset_id = None
        if canonical_match:
            asset_id = int(canonical_match["asset_id"])
            symbol = str(canonical_match.get("symbol") or symbol)

        effective_account_id = account_id
        map_lookup_symbol = raw_symbol or symbol
        if map_lookup_symbol and map_lookup_symbol in ticker_account_map_norm:
            effective_account_id = ticker_account_map_norm[map_lookup_symbol]
        elif symbol and symbol in ticker_account_map_norm:
            effective_account_id = ticker_account_map_norm[symbol]
        if effective_account_id != account_id:
            _logger.info(
                "ticker_account_map: %s redirige vers account_id=%s (defaut=%s)",
                map_lookup_symbol or symbol,
                effective_account_id,
                account_id,
            )

        mem_fingerprint = (
            date_raw,
            effective_account_id,
            tx_type,
            tx_amount,
            raw_symbol,
            isin,
            shares,
            fees_val,
        )
        if mem_fingerprint in seen_in_batch:
            _logger.info("Skipping duplicate trade in batch: %s", mem_fingerprint)
            skipped += 1
            continue
        seen_in_batch.add(mem_fingerprint)

        if asset_id:
            existing = conn.execute(
                """SELECT id FROM transactions
                   WHERE date = ? AND account_id = ? AND type = ?
                     AND ABS(amount - ?) < 0.01
                     AND asset_id = ?""",
                (date_str, effective_account_id, tx_type, tx_amount, asset_id),
            ).fetchone()
        elif isin:
            existing = conn.execute(
                """SELECT t.id FROM transactions t
                   LEFT JOIN assets a ON t.asset_id = a.id
                   LEFT JOIN asset_meta am ON a.id = am.asset_id
                   WHERE t.date = ? AND t.account_id = ? AND t.type = ?
                     AND ABS(t.amount - ?) < 0.01
                     AND (am.isin = ? OR a.symbol = ?)""",
                (date_str, effective_account_id, tx_type, tx_amount, isin, isin),
            ).fetchone()
        else:
            existing = conn.execute(
                """SELECT id FROM transactions
                   WHERE date = ? AND account_id = ? AND type = ?
                     AND ABS(amount - ?) < 0.01 AND asset_id IS NULL""",
                (date_str, effective_account_id, tx_type, tx_amount),
            ).fetchone()
        is_duplicate = existing is not None

        if not dry_run and asset_id is None:
            if canonical_override_symbol:
                asset_id = _get_or_create_asset_by_symbol(
                    conn, canonical_override_symbol, title, isin=isin
                )
                symbol = canonical_override_symbol
                if asset_id:
                    match_source = "user_override_new"
            elif isin:
                asset_id = _get_or_create_asset(conn, isin, title, ticker=ticker)
                symbol = ticker or isin

        preview.append({
            "date": date_str,
            "type": tx_type,
            "raw_symbol": raw_symbol,
            "symbol": symbol,
            "title": title,
            "isin": isin,
            "shares": shares,
            "price": round(unit_price, 4) if unit_price else None,
            "amount": round(tx_amount, 2),
            "fees": round(fees_val, 2),
            "tr_type": tr_type,
            "duplicate": is_duplicate,
            "match_source": match_source,
            "effective_account_id": effective_account_id,
        })

        if not is_duplicate:
            rows_to_insert.append((
                date_str, person_id, effective_account_id, tx_type,
                asset_id, shares, unit_price, fees_val, tx_amount,
                None,
                f"TR: {tr_type} | {title}" if title else f"TR: {tr_type}",
            ))
            rows_meta.append({
                "raw_symbol": raw_symbol,
                "isin": isin,
                "title": title,
                "ticker": ticker,
                "symbol": symbol,
                "asset_id": asset_id,
            })

    if not dry_run:
        for i, rd in enumerate(rows_to_insert):
            meta = rows_meta[i]
            aid = rd[4]

            if aid is None:
                if meta.get("symbol"):
                    # Si symbole canonique explicite, on privilégie une création/recherche par symbole.
                    if meta.get("isin"):
                        resolved_ticker = isin_ticker_map.get(str(meta["isin"]).upper()) or ""
                        if str(meta["symbol"]).upper() != str(resolved_ticker or meta["isin"]).upper():
                            aid = _get_or_create_asset_by_symbol(
                                conn, meta["symbol"], meta.get("title", ""), isin=meta.get("isin")
                            )
                        else:
                            aid = _get_or_create_asset(
                                conn,
                                str(meta["isin"]),
                                meta.get("title", ""),
                                ticker=resolved_ticker or None,
                            )
                    else:
                        aid = _get_or_create_asset_by_symbol(
                            conn, meta["symbol"], meta.get("title", "")
                        )
                elif meta.get("isin"):
                    resolved_ticker = isin_ticker_map.get(str(meta["isin"]).upper())
                    aid = _get_or_create_asset(
                        conn, str(meta["isin"]), meta.get("title", ""), ticker=resolved_ticker
                    )
                rows_to_insert[i] = rd[:4] + (aid,) + rd[5:]

            rows_meta[i]["asset_id"] = aid
            if aid:
                import_aliases_service.upsert_import_alias(
                    conn,
                    import_aliases_service.IMPORT_SOURCE_TRADE_REPUBLIC,
                    canonical_asset_id=int(aid),
                    raw_symbol=str(meta.get("raw_symbol") or ""),
                    raw_isin=str(meta.get("isin") or ""),
                )

        conn.executemany(
            """INSERT INTO transactions
               (date, person_id, account_id, type, asset_id, quantity, price, fees, amount, category, note, import_batch_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [r + (import_batch_id,) for r in rows_to_insert],
        )
        conn.commit()

    return {
        "preview": preview,
        "to_insert": len(rows_to_insert),
        "duplicates": sum(1 for r in preview if r["duplicate"]),
        "skipped": skipped,
        "total": len(preview) + skipped,
        "resolved_tickers": len(isin_ticker_map),
        "unresolved_isins": [i for i in unique_isins if i not in isin_ticker_map],
    }


# ---------------------------------------------------------------------------
# Correction des transactions mal classifiées lors d'anciens imports
# ---------------------------------------------------------------------------

def fix_misclassified_tr_transactions(conn, person_id: int) -> dict:
    """
    Corrige les transactions TR enregistrées avec le mauvais type suite à
    d'anciens imports (dépôts, intérêts, dividendes classés en VENTE).

    Stratégie : toute transaction de type VENTE sans asset_id est suspecte.
    On réassigne son type en lisant le champ `note` (ex: "TR: Dépôt | ...").

    Retourne le nombre de corrections par type.
    """
    import pandas as pd
    import re

    df = pd.read_sql_query(
        """SELECT id, type, asset_id, note
           FROM transactions
           WHERE person_id = ? AND type = 'VENTE' AND asset_id IS NULL""",
        conn,
        params=(int(person_id),),
    )

    if df is None or df.empty:
        return {"fixed_depot": 0, "fixed_interets": 0, "fixed_dividende": 0, "total": 0}

    note_lower = df["note"].fillna("").str.lower()

    # Détection par mots-clés (accents normalisés + variantes TR multilingues)
    mask_depot    = note_lower.str.contains(r"d[eé]p[oô]t|depot|deposit|einzahlung", regex=True)
    mask_interets = note_lower.str.contains(r"int[eé]r[eê]ts?|zinsen|interest", regex=True)
    mask_dividende = note_lower.str.contains(r"dividendes?|dividend|dividende", regex=True)

    results = {"fixed_depot": 0, "fixed_interets": 0, "fixed_dividende": 0}

    for new_type, mask, key in [
        ("DEPOT",     mask_depot,     "fixed_depot"),
        ("INTERETS",  mask_interets,  "fixed_interets"),
        ("DIVIDENDE", mask_dividende, "fixed_dividende"),
    ]:
        ids = df[mask]["id"].tolist()
        if ids:
            placeholders = ",".join(["?"] * len(ids))
            conn.execute(
                f"UPDATE transactions SET type = ? WHERE id IN ({placeholders})",
                [new_type] + ids,
            )
            results[key] = len(ids)

    conn.commit()
    results["total"] = sum(v for v in results.values())
    return results
