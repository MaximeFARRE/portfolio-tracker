# -*- mode: python ; coding: utf-8 -*-
"""
Spec PyInstaller — Patrimoine Desktop
PyQt6 + QWebEngineView nécessite un dossier (pas un exe unique).
Le dossier final est : dist/Patrimoine/
L'exécutable est    : dist/Patrimoine/Patrimoine.exe
"""

from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None

# ── Collecte complète de PyQt6 (binaires + données + imports cachés) ──────────
qt6_datas, qt6_binaries, qt6_hiddenimports = collect_all("PyQt6")

# ── Données propres au projet ──────────────────────────────────────────────────
project_datas = [
    ("db",       "db"),
    ("services", "services"),
    ("core",     "core"),
    ("models",   "models"),
    ("utils",    "utils"),
    ("qt_ui",    "qt_ui"),
]

# ── Imports cachés ─────────────────────────────────────────────────────────────
hidden = qt6_hiddenimports + [
    # modules du projet
    "services.db",
    "services.repositories",
    "services.credits",
    "services.snapshots",
    "services.family_snapshots",
    "services.bourse_analytics",
    "services.pricing",
    "services.fx",
    "services.private_equity",
    "services.depenses_repository",
    "services.revenus_repository",
    "services.imports",
    "services.tr_import",
    "services.isin_resolver",
    "services.calculations",
    "core.db_connection",
    "models.enums",
    "utils.cache",
    "utils.validators",
    "utils.formatters",
    # dépendances tierces
    "yfinance",
    "requests",
    "pandas",
    "pandas._libs.tslibs.np_datetime",
    "pandas._libs.tslibs.nattype",
    "pandas._libs.skiplist",
    "plotly",
    "plotly.graph_objects",
    "sqlite3",
    "pyarrow",
    "multitasking",
    "beautifulsoup4",
    "bs4",
    "lxml",
    "lxml.etree",
    "numpy",
]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=qt6_binaries,
    datas=project_datas + qt6_datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "IPython", "jupyter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,       # obligatoire pour COLLECT (WebEngine)
    name="Patrimoine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                   # UPX désactivé (incompatible avec Qt6 sur Windows)
    console=False,               # pas de fenêtre console noire
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Patrimoine",
)
