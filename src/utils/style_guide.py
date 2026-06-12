"""
Centralized visual style definitions for BaSIM plots and tables.
Economist-inspired clean style with consistent fonts, colors, and formatting.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass

# Color palette
COLORS = {
    'primary': '#0D47A1',      # Deep blue
    'secondary': '#1976D2',    # Medium blue
    'accent': '#E53935',       # Red for critical
    'warning': '#FB8C00',      # Orange for warnings
    'success': '#43A047',      # Green for success
    'gray_dark': '#424242',    # Text
    'gray_medium': '#757575',  # Secondary text
    'gray_light': '#E0E0E0',   # Gridlines/Borders
    'background': '#FAFAFA',   # Light background
}

# Typography
FONT_FAMILY = 'DejaVu Sans'
TITLE_SIZE = 14
LABEL_SIZE = 11
TICK_SIZE = 10
LEGEND_SIZE = 10
TABLE_FONT_SIZE = 9

@dataclass
class TableStyle:
    header_bg: str = '#F2F2F2'
    header_fg: str = COLORS['gray_dark']
    row_alt_bg: str = '#FFFFFF'
    row_bg: str = '#FAFAFA'
    border: str = COLORS['gray_light']

TABLE_STYLE = TableStyle()


def apply_mpl_style():
    """Apply consistent matplotlib rcParams."""
    try:
        import matplotlib as mpl
        # Force non-interactive backend for safe image generation in threads
        with contextlib.suppress(Exception):
            mpl.use('Agg')
        mpl.rcParams.update({
            'figure.facecolor': COLORS['background'],
            'axes.facecolor': '#FFFFFF',
            'axes.edgecolor': COLORS['gray_light'],
            'axes.labelcolor': COLORS['gray_dark'],
            'axes.grid': True,
            'grid.color': COLORS['gray_light'],
            'grid.linestyle': '-',
            'grid.linewidth': 0.6,
            'font.family': FONT_FAMILY,
            'font.size': LABEL_SIZE,
            'axes.titlesize': TITLE_SIZE,
            'axes.labelsize': LABEL_SIZE,
            'xtick.color': COLORS['gray_dark'],
            'ytick.color': COLORS['gray_dark'],
            'xtick.labelsize': TICK_SIZE,
            'ytick.labelsize': TICK_SIZE,
            'legend.fontsize': LEGEND_SIZE,
            'savefig.dpi': 150,
            'savefig.bbox': 'tight',
        })
    except Exception:
        pass


def prettify_name(name: str) -> str:
    """Turn snake_case or identifiers into Title Case without underscores."""
    if not name:
        return ''
    name = name.replace('_', ' ').strip()
    # Special units or all-caps tokens keep case
    tokens = name.split()
    out = []
    for t in tokens:
        if t.isupper():
            out.append(t)
        else:
            out.append(t.capitalize())
    return ' '.join(out)


def render_table_png(rows, columns, out_png_path, title: str | None = None):
    """Render a styled table image using matplotlib.
    rows: list of lists matching columns length
    columns: list of column names
    out_png_path: path to write PNG
    """
    try:
        import matplotlib.pyplot as plt
        apply_mpl_style()
        n = len(rows)
        h = max(3.0, 0.35 * n + (0.5 if title else 0))
        fig, ax = plt.subplots(figsize=(10, h))
        fig.patch.set_facecolor(COLORS['background'])
        ax.axis('off')
        if title:
            ax.set_title(title, pad=12)
        # Build table
        table = ax.table(cellText=rows, colLabels=[prettify_name(c) for c in columns], loc='center', cellLoc='left')
        table.auto_set_font_size(False)
        table.set_fontsize(TABLE_FONT_SIZE)
        table.scale(1, 1.2)
        # Header style
        for key, cell in table.get_celld().items():
            r, c = key
            cell.set_edgecolor(TABLE_STYLE.border)
            if r == 0:
                cell.set_facecolor(TABLE_STYLE.header_bg)
                cell.set_text_props(weight='bold', color=TABLE_STYLE.header_fg)
            else:
                # Alternating row colors
                cell.set_facecolor(TABLE_STYLE.row_bg if r % 2 == 0 else TABLE_STYLE.row_alt_bg)
        fig.tight_layout()
        fig.savefig(out_png_path)
        plt.close(fig)
    except Exception:
        # Fallback ignored; no crash if plotting fails
        pass
