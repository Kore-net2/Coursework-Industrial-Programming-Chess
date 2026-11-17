#!/usr/bin/env python3
"""Coursework CLI entry point. With no arguments, launch the desktop GUI.

"""
import argparse
from pathlib import Path
import sys

from chess_app.storage import AppError, TIME_CONTROLS, open_database, preprocess, error_message
from chess_app.analysis import METRICS, popular_openings, similar_players, top_players


def parser():
    result = argparse.ArgumentParser(description="Analyse Lichess chess metadata. Run without arguments to open the GUI.", allow_abbrev=False)
    mode = result.add_mutually_exclusive_group(required=True)
    mode.add_argument("--raw-data", metavar="PATH", nargs="+", help="Import PGN files or folders into one database")
    mode.add_argument("--popular-openings", action="store_true")
    mode.add_argument("--top10", action="store_true")
    mode.add_argument("--players-similar-to", metavar="NAME")
    result.add_argument("--outfile", metavar="FILE", help="Output SQLite database (import only)")
    result.add_argument("--datafile", metavar="FILE", help="Previously prepared SQLite database")
    result.add_argument("--time-control", choices=TIME_CONTROLS)
    result.add_argument("--min-rating", type=int)
    result.add_argument("--max-rating", type=int)
    metric = result.add_mutually_exclusive_group()
    metric.add_argument("--time-formats", action="store_true")
    metric.add_argument("--black-openings", action="store_true")
    result.add_argument("--save-chart", metavar="PNG", help="Save opening chart instead of opening a window")
    return result


def validate_args(p, args):
    if args.raw_data is not None:
        if not args.outfile:
            p.error("--raw-data requires --outfile")
        if any(value is not None for value in (args.datafile, args.time_control, args.min_rating, args.max_rating, args.save_chart)) or args.time_formats or args.black_openings:
            p.error("Import accepts only --raw-data and --outfile")
    else:
        if not args.datafile:
            p.error("Analysis requires --datafile")
        if args.outfile is not None:
            p.error("--outfile is only valid for import")
        if not args.popular_openings and any(value is not None for value in (args.min_rating, args.max_rating, args.save_chart)):
            p.error("Rating limits and --save-chart are only valid with --popular-openings")
        if args.top10 and args.time_control is None:
            p.error("--top10 requires --time-control")
        if args.players_similar_to is not None:
            if not (args.time_formats or args.black_openings):
                p.error("Similarity requires --time-formats or --black-openings")
            if args.time_control is not None:
                p.error("Similarity uses all retained time controls; omit --time-control")
        elif args.time_formats or args.black_openings:
            p.error("Similarity metrics require --players-similar-to")


def print_table(rows):
    if not rows:
        print("No matching results.")
        return
    headings = list(rows[0])
    formatted = [[f"{value:.4f}" if isinstance(value, float) else str(value) for value in row.values()] for row in rows]
    widths = [max(len(head), max(len(row[i]) for row in formatted)) for i, head in enumerate(headings)]
    for row in [headings, ["-" * width for width in widths], *formatted]:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        from chess_app.runtime import configure_tk
        configure_tk()
        if not argv:
            from chess_app.gui import launch
            launch()
            return 0
        p = parser()
        args = p.parse_args(argv)
        validate_args(p, args)
        if args.raw_data is not None:
            print(preprocess(args.raw_data, args.outfile).describe())
            print(f"Saved: {Path(args.outfile).resolve()}")
            return 0
        with open_database(args.datafile) as connection:
            if args.popular_openings:
                total, rows = popular_openings(connection, args.time_control, args.min_rating, args.max_rating)
                print(f"Matching games: {total:,}")
                print_table(rows)
                from chess_app.chart import opening_figure
                subtitle = f"{args.time_control or 'All time controls'} | rating {args.min_rating if args.min_rating is not None else '-inf'} to {args.max_rating if args.max_rating is not None else 'inf'}"
                if args.save_chart:
                    figure = opening_figure(total, rows, subtitle)
                    figure.savefig(args.save_chart, dpi=180, bbox_inches="tight")
                    print(f"Chart saved: {args.save_chart}")
                else:
                    import matplotlib.pyplot as plt
                    opening_figure(total, rows, subtitle, plt.figure(figsize=(max(9, len(rows) * .42), 6.2)))
                    plt.show()
            elif args.top10:
                print_table(top_players(connection, args.time_control))
            else:
                metric = METRICS["time-formats" if args.time_formats else "black-openings"]
                target, rows = similar_players(connection, args.players_similar_to, metric)
                print(f"Target: {args.players_similar_to} | {target}\nDistance is measured in percentage points.")
                print_table(rows)
        return 0
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {error_message(exc)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

