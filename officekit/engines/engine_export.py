"""
OfficeKit - Universal Result Exporter Engine (officekit/engines/engine_export.py)
Transforms immutable calculation and conversion snapshots into:
- Markdown (.md) AI-Chat Context Pack (provenance, clean fenced tables, no prompt injection)
- Self-contained offline HTML (.html) with bundled responsive tokens, semantic tables, zero tracking
- Editable PowerPoint (.pptx) summary decks (title slide, executive metrics, tabular schedules, assumptions)
- Formatted CSV & Excel (.xlsx) with neutralized spreadsheet formula injection
- Canonical JSON (.json) result bundles
"""

import io
import json
import html
import datetime
from typing import Dict, Any, List, Optional
import pandas as pd

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
except ImportError:
    Presentation = None


class ExportEngine:
    """Universal immutable snapshot exporter across all OfficeKit tools."""

    BRAND_FOOTER = "Generated with OfficeKit · officekit.app"

    @classmethod
    def to_markdown(
        cls,
        title: str,
        inputs: Dict[str, Any],
        results: Dict[str, Any],
        table_records: Optional[List[Dict[str, Any]]] = None,
        assumptions: Optional[List[str]] = None,
        include_attribution: bool = True
    ) -> str:
        """Generates an AI-Chat Context Pack in clean Markdown."""
        now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        lines = [
            f"# {title}",
            "",
            "> **AI Context Note:** This document contains verified deterministic calculation outputs generated locally.",
            f"> **Generated:** {now_utc}",
            ""
        ]

        # Inputs section
        lines.append("## Inputs")
        for k, v in inputs.items():
            clean_k = k.replace("_", " ").title()
            lines.append(f"- **{clean_k}**: `{v}`")
        lines.append("")

        # Results summary
        lines.append("## Results Summary")
        for k, v in results.items():
            clean_k = k.replace("_", " ").title()
            lines.append(f"- **{clean_k}**: **{v}**")
        lines.append("")

        # Optional tabular data (e.g. amortization schedule or transaction statement)
        if table_records and len(table_records) > 0:
            lines.append("## Detailed Schedule / Data")
            cols = list(table_records[0].keys())
            header_row = "| " + " | ".join(c.replace("_", " ").title() for c in cols) + " |"
            sep_row = "| " + " | ".join("---" for _ in cols) + " |"
            lines.append(header_row)
            lines.append(sep_row)
            for row in table_records:
                row_str = "| " + " | ".join(str(row.get(c, "")).replace("|", "\\|") for c in cols) + " |"
                lines.append(row_str)
            lines.append("")

        # Assumptions
        if assumptions:
            lines.append("## Assumptions & Notes")
            for a in assumptions:
                lines.append(f"- {a}")
            lines.append("")

        if include_attribution:
            lines.append("---")
            lines.append(f"*{cls.BRAND_FOOTER}*")

        return "\n".join(lines)

    @classmethod
    def to_html(
        cls,
        title: str,
        inputs: Dict[str, Any],
        results: Dict[str, Any],
        table_records: Optional[List[Dict[str, Any]]] = None,
        assumptions: Optional[List[str]] = None,
        include_attribution: bool = True
    ) -> str:
        """Generates a standalone, styled, offline-first HTML report."""
        now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        inputs_html = "".join(
            f"<tr><th>{html.escape(k.replace('_', ' ').title())}</th><td>{html.escape(str(v))}</td></tr>"
            for k, v in inputs.items()
        )

        results_cards = "".join(
            f'<div class="card"><div class="label">{html.escape(k.replace("_", " ").title())}</div><div class="val">{html.escape(str(v))}</div></div>'
            for k, v in results.items()
        )

        table_html = ""
        if table_records and len(table_records) > 0:
            cols = list(table_records[0].keys())
            th_cells = "".join(f"<th>{html.escape(c.replace('_', ' ').title())}</th>" for c in cols)
            tr_rows = []
            for r in table_records:
                td_cells = "".join(f"<td>{html.escape(str(r.get(c, '')))}</td>" for c in cols)
                tr_rows.append(f"<tr>{td_cells}</tr>")
            table_html = f"""
            <h2>Detailed Breakdown</h2>
            <div class="table-container">
                <table>
                    <thead><tr>{th_cells}</tr></thead>
                    <tbody>{''.join(tr_rows)}</tbody>
                </table>
            </div>
            """

        assumptions_html = ""
        if assumptions:
            li_items = "".join(f"<li>{html.escape(a)}</li>" for a in assumptions)
            assumptions_html = f"<h2>Assumptions</h2><ul>{li_items}</ul>"

        attribution_html = f'<div class="footer">{html.escape(cls.BRAND_FOOTER)} · {now_utc}</div>' if include_attribution else ""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(title)} — OfficeKit Report</title>
<style>
  :root {{
    --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    --text: #1d2630;
    --bg: #ffffff;
    --card-bg: #f8fafc;
    --primary: #185c89;
    --border: #e2e8f0;
  }}
  body {{ font-family: var(--font); color: var(--text); background: var(--bg); margin: 0; padding: 32px; }}
  .header {{ border-bottom: 2px solid var(--primary); padding-bottom: 16px; margin-bottom: 24px; }}
  h1 {{ margin: 0 0 8px 0; color: var(--primary); font-size: 24px; }}
  .meta {{ color: #64748b; font-size: 13px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }}
  .card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }}
  .card .label {{ font-size: 12px; color: #64748b; margin-bottom: 4px; text-transform: uppercase; font-weight: 600; }}
  .card .val {{ font-size: 20px; font-weight: 700; color: var(--text); }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 13px; }}
  th, td {{ border: 1px solid var(--border); padding: 8px 12px; text-align: left; }}
  th {{ background: #f1f5f9; font-weight: 600; }}
  .table-container {{ overflow-x: auto; max-height: 400px; }}
  .footer {{ margin-top: 32px; border-top: 1px solid var(--border); padding-top: 12px; font-size: 12px; color: #94a3b8; text-align: center; }}
</style>
</head>
<body>
  <div class="header">
    <h1>{html.escape(title)}</h1>
    <div class="meta">OfficeKit Verified Snapshot · Generated: {now_utc}</div>
  </div>
  <div class="cards">{results_cards}</div>
  <h2>Inputs & Parameters</h2>
  <table style="max-width: 500px; margin-bottom: 24px;">{inputs_html}</table>
  {table_html}
  {assumptions_html}
  {attribution_html}
</body>
</html>"""

    @classmethod
    def to_pptx(
        cls,
        title: str,
        inputs: Dict[str, Any],
        results: Dict[str, Any],
        table_records: Optional[List[Dict[str, Any]]] = None,
        assumptions: Optional[List[str]] = None,
        include_attribution: bool = True
    ) -> bytes:
        """Generates a professional, editable multi-slide PowerPoint deck (.pptx)."""
        if not Presentation:
            raise RuntimeError("python-pptx is not installed")

        prs = Presentation()
        # Set 16:9 widescreen
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)

        # Slide 1: Title & Executive Summary
        blank_slide_layout = prs.slide_layouts[6] # Blank
        s1 = prs.slides.add_slide(blank_slide_layout)

        # Title box
        txBox = s1.shapes.add_textbox(Inches(1.0), Inches(0.8), Inches(11.33), Inches(1.2))
        tf = txBox.text_frame
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(36)
        p.font.bold = True
        p.font.color.rgb = RGBColor(24, 92, 137) # Utility Blue

        # Subtitle
        p2 = tf.add_paragraph()
        p2.text = f"OfficeKit Executive Report · Generated {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')}"
        p2.font.size = Pt(14)
        p2.font.color.rgb = RGBColor(100, 116, 139)

        # Key Metrics Summary Cards
        left_pos = Inches(1.0)
        card_w = Inches(3.4)
        for i, (k, v) in enumerate(list(results.items())[:3]):
            box = s1.shapes.add_textbox(left_pos + (i * Inches(3.8)), Inches(2.3), card_w, Inches(1.8))
            btf = box.text_frame
            bp1 = btf.paragraphs[0]
            bp1.text = k.replace("_", " ").title()
            bp1.font.size = Pt(14)
            bp1.font.color.rgb = RGBColor(100, 116, 139)

            bp2 = btf.add_paragraph()
            bp2.text = str(v)
            bp2.font.size = Pt(28)
            bp2.font.bold = True
            bp2.font.color.rgb = RGBColor(29, 38, 48)

        # Inputs column
        inpBox = s1.shapes.add_textbox(Inches(1.0), Inches(4.5), Inches(5.5), Inches(2.2))
        itf = inpBox.text_frame
        ip_head = itf.paragraphs[0]
        ip_head.text = "Key Inputs & Scope"
        ip_head.font.size = Pt(16)
        ip_head.font.bold = True
        for k, v in list(inputs.items())[:4]:
            ip = itf.add_paragraph()
            ip.text = f"• {k.replace('_', ' ').title()}: {v}"
            ip.font.size = Pt(13)

        # Assumptions column
        if assumptions:
            asBox = s1.shapes.add_textbox(Inches(6.8), Inches(4.5), Inches(5.5), Inches(2.2))
            atf = asBox.text_frame
            ap_head = atf.paragraphs[0]
            ap_head.text = "Assumptions & Notes"
            ap_head.font.size = Pt(16)
            ap_head.font.bold = True
            for a in assumptions[:4]:
                ap = atf.add_paragraph()
                ap.text = f"• {a}"
                ap.font.size = Pt(12)

        if include_attribution:
            footBox = s1.shapes.add_textbox(Inches(1.0), Inches(7.0), Inches(11.33), Inches(0.4))
            fp = footBox.text_frame.paragraphs[0]
            fp.text = cls.BRAND_FOOTER
            fp.font.size = Pt(10)
            fp.font.color.rgb = RGBColor(148, 163, 184)

        # Slide 2: Table Schedule (if data provided)
        if table_records and len(table_records) > 0:
            s2 = prs.slides.add_slide(blank_slide_layout)
            t_box = s2.shapes.add_textbox(Inches(1.0), Inches(0.6), Inches(11.33), Inches(0.8))
            tp = t_box.text_frame.paragraphs[0]
            tp.text = f"{title} — Detailed Breakdown"
            tp.font.size = Pt(24)
            tp.font.bold = True
            tp.font.color.rgb = RGBColor(24, 92, 137)

            cols = list(table_records[0].keys())[:8] # Up to 8 columns
            sample_rows = table_records[:15] # Top 15 rows for slide presentation
            num_rows = len(sample_rows) + 1
            num_cols = len(cols)

            table_shape = s2.shapes.add_table(num_rows, num_cols, Inches(1.0), Inches(1.6), Inches(11.33), Inches(5.0))
            table = table_shape.table

            for c_idx, c_name in enumerate(cols):
                cell = table.cell(0, c_idx)
                cell.text = c_name.replace("_", " ").title()
                for cp in cell.text_frame.paragraphs:
                    cp.font.size = Pt(11)
                    cp.font.bold = True

            for r_idx, row in enumerate(sample_rows):
                for c_idx, c_name in enumerate(cols):
                    cell = table.cell(r_idx + 1, c_idx)
                    cell.text = str(row.get(c_name, ""))
                    for cp in cell.text_frame.paragraphs:
                        cp.font.size = Pt(10)

        out = io.BytesIO()
        prs.save(out)
        return out.getvalue()

    @classmethod
    def to_csv_neutralized(cls, records: List[Dict[str, Any]]) -> str:
        """Exports tabular records to CSV with spreadsheet formula injection protection."""
        if not records:
            return ""
        df = pd.DataFrame(records)
        # Neutralize dangerous formula prefixes (=, +, -, @, \t, \r) across all columns
        for col in df.columns:
            df[col] = df[col].map(
                lambda v: f"'{v}" if isinstance(v, str) and len(v) > 0 and v[0] in ('=', '+', '-', '@', '\t', '\r') else v
            )
        return df.to_csv(index=False)
