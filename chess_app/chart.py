"""Shared chart rendering for the CLI and GUI."""
import os
from pathlib import Path
import tempfile

# Keep rendering caches out of the project and support read-only installations.
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "f20sc-matplotlib"))


def opening_figure(total, rows, subtitle="All time controls", figure=None, font_family=None, colors=None):
    from matplotlib.figure import Figure
    if figure is None:
        figure = Figure(figsize=(max(9, len(rows) * .42), 6.2), dpi=100)
    colors = colors or {"background": "white", "text": "black", "accent": "#0078d7"}
    font_family = font_family or ("Segoe UI" if os.name == "nt" else "sans-serif")
    figure.set_facecolor(colors["background"])
    axis = figure.add_subplot(111)
    axis.set_facecolor(colors["background"])
    axis.set_title(f"Opening popularity — {subtitle}\n{total:,} matching games · openings used in at least 1%", loc="left", pad=16)
    axis.set_xlabel("Opening")
    axis.set_ylabel("Games (%)")
    if rows:
        axis.bar([r["Opening"] for r in rows], [r["Percent"] for r in rows], color=colors["accent"], width=.7)
        axis.tick_params(axis="x", labelrotation=55, labelsize=8)
        for label in axis.get_xticklabels():
            label.set_horizontalalignment("right")
        axis.set_ylim(bottom=0)
    else:
        axis.text(.5, .5, "No games match these filters." if total == 0 else "No opening reaches 1%.", transform=axis.transAxes, ha="center")
    axis.spines[["top", "right"]].set_visible(False)
    axis.grid(axis="y", alpha=.18)
    axis.set_axisbelow(True)
    from matplotlib.text import Text
    for text in figure.findobj(Text):
        text.set_fontfamily(font_family)
        text.set_color(colors["text"])
    axis.tick_params(colors=colors["text"])
    for spine in axis.spines.values():
        spine.set_color(colors["text"])
    figure.tight_layout()
    return figure
