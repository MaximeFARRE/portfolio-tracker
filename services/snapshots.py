"""
Façade de compatibilité pour les snapshots hebdomadaires personne.

API publique inchangée : les fonctions historiques restent importables depuis
`services.snapshots`, mais l'implémentation est découpée en sous-modules.
"""

from services.snapshots_helpers import (
    _now_paris_iso,
    _today_paris_date,
    _list_weeks,
    _collect_person_market_sync_inputs,
    _sync_person_market_data_for_weeks,
    _get_last_snapshot_week_ts,
    _snapshot_row_to_dict,
)
from services.snapshots_compute import (
    _SENS_FLUX_MAP,
    _sum_cash_native,
    _bank_cash_asof_eur,
    _bourse_cash_and_holdings_eur_asof,
    _pe_cash_asof_eur,
    _pe_value_asof_eur,
    _enterprise_value_asof_eur,
    _immobilier_value_asof_eur,
    _credits_remaining_asof,
    upsert_weekly_snapshot,
    compute_weekly_snapshot_person,
)
from services.snapshots_rebuild import (
    rebuild_snapshots_person,
    rebuild_snapshots_person_missing_only,
    rebuild_snapshots_person_from_last,
    rebuild_snapshots_person_backdated_aware,
    has_new_transactions_since_person_watermark,
    get_first_transaction_date,
    rebuild_snapshots_person_full_history,
    _ensure_rebuild_watermarks,
    _get_person_watermark,
    _set_person_watermark,
)
from services.snapshots_read import (
    PERSON_WEEKLY_COLUMNS,
    get_person_weekly_series,
    get_latest_person_snapshot,
    get_latest_snapshot_notes,
    get_person_snapshot_at_week,
)

__all__ = [
    "PERSON_WEEKLY_COLUMNS",
    "compute_weekly_snapshot_person",
    "get_latest_person_snapshot",
    "get_latest_snapshot_notes",
    "get_person_snapshot_at_week",
    "get_person_weekly_series",
    "rebuild_snapshots_person",
    "rebuild_snapshots_person_backdated_aware",
    "rebuild_snapshots_person_from_last",
    "rebuild_snapshots_person_missing_only",
    "rebuild_snapshots_person_full_history",
    "get_first_transaction_date",
    "has_new_transactions_since_person_watermark",
    "upsert_weekly_snapshot",
    "_bank_cash_asof_eur",
    "_bourse_cash_and_holdings_eur_asof",
    "_collect_person_market_sync_inputs",
    "_credits_remaining_asof",
    "_enterprise_value_asof_eur",
    "_ensure_rebuild_watermarks",
    "_get_last_snapshot_week_ts",
    "_get_person_watermark",
    "_immobilier_value_asof_eur",
    "_list_weeks",
    "_now_paris_iso",
    "_pe_cash_asof_eur",
    "_pe_value_asof_eur",
    "_SENS_FLUX_MAP",
    "_set_person_watermark",
    "_snapshot_row_to_dict",
    "_sum_cash_native",
    "_sync_person_market_data_for_weeks",
    "_today_paris_date",
]
