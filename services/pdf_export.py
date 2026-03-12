"""
services/pdf_export.py
Génère un bilan patrimonial en PDF (fpdf2 + matplotlib).
"""
from __future__ import annotations

import io
from datetime import date
from typing import Optional

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _try_import_fpdf():
    try:
        from fpdf import FPDF
        return FPDF
    except ImportError:
        return None


def _money(x: float) -> str:
    try:
        return f"{float(x):,.2f} EUR".replace(",", " ")
    except Exception:
        return "— EUR"


def _pie_image(labels: list, values: list) -> Optional[bytes]:
    """Génère un camembert matplotlib et le retourne en bytes PNG."""
    filtered = [(l, v) for l, v in zip(labels, values) if v > 0]
    if not filtered:
        return None
    fl, fv = zip(*filtered)
    fig, ax = plt.subplots(figsize=(4, 3))
    ax.pie(fv, labels=fl, autopct="%1.1f%%", startangle=90)
    ax.axis("equal")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=100)
    plt.close(fig)
    return buf.getvalue()


def _line_image(dates: list, values: list, label: str = "Patrimoine net") -> Optional[bytes]:
    """Génère une courbe matplotlib et la retourne en bytes PNG."""
    if not dates or not values:
        return None
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.plot(dates, values, linewidth=2, color="#1E3A8A")
    ax.set_ylabel("EUR")
    ax.set_title(label)
    ax.tick_params(axis="x", rotation=30)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=100)
    plt.close(fig)
    return buf.getvalue()


def generate_patrimoine_pdf(
    conn,
    person_id: int,
    person_name: str = "Personne",
    period_days: int = 90,
) -> bytes:
    """
    Génère le bilan patrimonial PDF pour une personne.
    Retourne les bytes du PDF.
    Nécessite fpdf2 (pip install fpdf2).
    """
    FPDF = _try_import_fpdf()
    if FPDF is None:
        raise ImportError("fpdf2 n'est pas installé. Fais : pip install fpdf2")

    today = date.today()

    # ─── Données ───────────────────────────────────────────────
    # Dernier snapshot weekly
    try:
        snap = conn.execute(
            "SELECT patrimoine_net, patrimoine_brut, liquidites_total, "
            "bourse_holdings, pe_value, ent_value, credits_remaining "
            "FROM patrimoine_snapshots_weekly WHERE person_id=? ORDER BY week_date DESC LIMIT 1",
            (int(person_id),),
        ).fetchone()
    except Exception:
        snap = None

    def _v(row, key, idx):
        if row is None:
            return 0.0
        try:
            return float(row[key] or 0)
        except Exception:
            try:
                return float(row[idx] or 0)
            except Exception:
                return 0.0

    pat_net = _v(snap, "patrimoine_net", 0)
    pat_brut = _v(snap, "patrimoine_brut", 1)
    liquidites = _v(snap, "liquidites_total", 2)
    bourse = _v(snap, "bourse_holdings", 3)
    pe = _v(snap, "pe_value", 4)
    ent = _v(snap, "ent_value", 5)
    credits = _v(snap, "credits_remaining", 6)

    # Snapshots weekly pour la courbe
    try:
        df_snap = pd.read_sql_query(
            f"SELECT week_date, patrimoine_net FROM patrimoine_snapshots_weekly "
            f"WHERE person_id=? AND week_date >= date('now', '-{period_days} days') "
            f"ORDER BY week_date ASC",
            conn,
            params=(int(person_id),),
        )
        df_snap["week_date"] = pd.to_datetime(df_snap["week_date"], errors="coerce")
        df_snap = df_snap.dropna(subset=["week_date"])
    except Exception:
        df_snap = pd.DataFrame()

    # ─── Construction PDF ───────────────────────────────────────
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)

    # En-tête
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "Bilan Patrimonial", ln=True, align="C")
    pdf.set_font("Helvetica", size=11)
    pdf.cell(0, 8, f"{person_name}  —  {today.strftime('%d/%m/%Y')}", ln=True, align="C")
    pdf.ln(6)

    # KPIs résumé
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "Résumé", ln=True)
    pdf.set_font("Helvetica", size=10)
    kpis = [
        ("Patrimoine net", _money(pat_net)),
        ("Patrimoine brut", _money(pat_brut)),
        ("Liquidités", _money(liquidites)),
        ("Bourse (valeurs)", _money(bourse)),
        ("Private Equity", _money(pe)),
        ("Entreprises", _money(ent)),
        ("Crédits restants", _money(credits)),
    ]
    col_w = 90
    for label, val in kpis:
        pdf.cell(col_w, 7, label + " :", border=0)
        pdf.cell(col_w, 7, val, border=0, ln=True)
    pdf.ln(4)

    # Graphique répartition (camembert)
    labels = ["Liquidités", "Bourse", "Private Equity", "Entreprises"]
    values = [liquidites, bourse, pe, ent]
    pie_bytes = _pie_image(labels, values)
    if pie_bytes:
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 9, "Répartition du patrimoine brut", ln=True)
        img_buf = io.BytesIO(pie_bytes)
        # fpdf2 accepte un BytesIO
        try:
            pdf.image(img_buf, x=30, w=150)
        except Exception:
            # Fallback : écrire dans un fichier temporaire
            import tempfile, os
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            tmp.write(pie_bytes)
            tmp.close()
            pdf.image(tmp.name, x=30, w=150)
            os.unlink(tmp.name)
        pdf.ln(4)

    # Graphique évolution
    if not df_snap.empty and len(df_snap) >= 2:
        dates_list = df_snap["week_date"].tolist()
        vals_list = df_snap["patrimoine_net"].astype(float).tolist()
        line_bytes = _line_image(dates_list, vals_list)
        if line_bytes:
            pdf.set_font("Helvetica", "B", 13)
            pdf.cell(0, 9, f"Évolution ({period_days} derniers jours)", ln=True)
            img_buf2 = io.BytesIO(line_bytes)
            try:
                pdf.image(img_buf2, x=10, w=190)
            except Exception:
                import tempfile, os
                tmp2 = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                tmp2.write(line_bytes)
                tmp2.close()
                pdf.image(tmp2.name, x=10, w=190)
                os.unlink(tmp2.name)

    return bytes(pdf.output())
