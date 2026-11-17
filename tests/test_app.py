"""Regression tests using synthetic, hand-checkable PGN metadata."""
import contextlib
import io
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

import zstandard

from chess_app.storage import AppError, Cancelled, classify_time_control, normalize_headers, open_database, preprocess
from chess_app.analysis import BlackOpeningMetric, TimeFormatMetric, popular_openings, similar_players, top_players
from cw2 import main


def headers(**changes):
    result = dict(Event="Rated Blitz game", White="Alice", Black="Bob", WhiteElo="1500", BlackElo="1600",
                  WhiteRatingDiff="10", BlackRatingDiff="-10", Opening="Sicilian Defense: Dragon Variation",
                  TimeControl="180+0", UTCDate="2026.01.01", UTCTime="12:00:00", Result="1-0")
    result.update(changes)
    return result


def pgn(**changes):
    return "\n".join(f'[{key} "{value}"]' for key, value in headers(**changes).items()) + "\n\n1. e4 c5 1-0\n\n"


class AnalyticsTests(unittest.TestCase):
    def test_batch_import_folder_and_duplicate_paths(self):
        self.raw.write_text(pgn(), encoding="utf-8")
        second = self.folder / "second.pgn.zst"
        second.write_bytes(zstandard.ZstdCompressor().compress(pgn(White="Carol").encode()))
        summary = preprocess([self.raw, self.folder, second], self.db)
        self.assertEqual((summary.read, summary.kept), (2, 2))
        with open_database(self.db) as con:
            self.assertEqual(con.execute("SELECT count(*) FROM games").fetchone()[0], 2)
            self.assertEqual(len(top_players(con, "blitz")), 3)

    def test_failure_in_later_archive_preserves_database(self):
        self.raw.write_text(pgn(), encoding="utf-8")
        bad = self.folder / "bad.pgn.zst"
        bad.write_bytes(zstandard.ZstdCompressor().compress(pgn().encode())[:-3])
        self.db.write_bytes(b"previous database")
        with self.assertRaisesRegex(AppError, "bad.pgn.zst"):
            preprocess([self.raw, bad], self.db)
        self.assertEqual(self.db.read_bytes(), b"previous database")
        self.assertEqual(list(self.folder.glob(".chess-import-*")), [])

    def test_empty_batch_and_empty_later_file(self):
        with self.assertRaises(AppError):
            preprocess([], self.db)
        with self.assertRaises(AppError):
            preprocess(self.folder, self.db)
        self.raw.write_text(pgn(), encoding="utf-8")
        empty = self.folder / "empty.pgn"
        empty.write_text("", encoding="utf-8")
        with self.assertRaisesRegex(AppError, "empty.pgn"):
            preprocess([self.raw, empty], self.db)
        self.assertFalse(self.db.exists())

    def test_cli_multiple_files_and_negative_rating(self):
        self.raw.write_text(pgn(), encoding="utf-8")
        second = self.folder / "second file.pgn"
        second.write_text(pgn(White="Carol"), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--raw-data", str(self.raw), str(second), f"--outfile={self.db}"]), 0)
        with open_database(self.db) as con:
            self.assertEqual(popular_openings(con)[0], 2)
            with self.assertRaisesRegex(AppError, "non-negative"):
                popular_openings(con, minimum=-1)

    def test_similarity_bounded_ranking_and_generic_ineligibility(self):
        self.prepare(pgn())
        class CustomMetric:
            def profiles(self, con):
                return {"Alice": 0, **{f"Player{i:02}": i % 3 for i in range(50)}}
            def distance(self, a, b):
                return abs(a - b)
            def describe(self, value):
                return str(value)
        with open_database(self.db) as con:
            _, rows = similar_players(con, "Alice", CustomMetric())
            self.assertEqual([r["Player"] for r in rows], [f"Player{i:02}" for i in range(0, 30, 3)])
            with self.assertRaisesRegex(AppError, "selected similarity metric"):
                similar_players(con, "Bob", CustomMetric())

    def test_permission_and_encoding_errors_preserve_destination(self):
        from chess_app.storage import error_message
        self.assertIn("Access denied", error_message(PermissionError(13, "denied", "input.pgn")))
        self.raw.write_bytes(b"\xff\xfe")
        self.db.write_bytes(b"previous")
        with self.assertRaisesRegex(AppError, "UTF-8"):
            preprocess(self.raw, self.db)
        self.assertEqual(self.db.read_bytes(), b"previous")

    def test_cancel_during_indexing_preserves_destination(self):
        self.raw.write_text(pgn(), encoding="utf-8")
        self.db.write_bytes(b"previous")
        event = threading.Event()
        def progress(message):
            if "indexes" in message:
                event.set()
        with self.assertRaises(Cancelled):
            preprocess(self.raw, self.db, progress, event)
        self.assertEqual(self.db.read_bytes(), b"previous")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.raw = self.folder / "sample.pgn"
        self.db = self.folder / "sample.sqlite"

    def prepare(self, text):
        self.raw.write_text(text, encoding="utf-8")
        return preprocess(self.raw, self.db)

    def test_time_boundaries(self):
        for seconds, expected in ((0, None), (29, None), (30, "bullet"), (179, "bullet"), (180, "blitz"), (479, "blitz"), (480, "rapid"), (1499, "rapid"), (1500, None)):
            with self.subTest(seconds=seconds):
                self.assertEqual(classify_time_control(f"{seconds}+0"), expected)
        self.assertEqual(classify_time_control("60+3"), "blitz")
        for value in ("bad", "-1+1", "3+-1", "1+2+3"):
            with self.assertRaises(ValueError):
                classify_time_control(value)

    def test_normalization(self):
        row = normalize_headers(headers(BlackElo="1601"))
        self.assertEqual(row[4:8], (1510, 1591, 1550.5, "Sicilian Defense"))
        self.assertEqual(row[-1], "2026-01-01T12:00:00+00:00")
        with self.assertRaises(ValueError):
            normalize_headers(headers(WhiteElo="?"))

    def test_compressed_multiple_frames(self):
        raw = self.folder / "sample.pgn.zst"
        compressor = zstandard.ZstdCompressor()
        raw.write_bytes(compressor.compress(pgn().encode()) + compressor.compress(pgn(White="Carol").encode()))
        self.assertEqual(preprocess(raw, self.db).kept, 2)

    def test_truncated_archive_preserves_destination(self):
        self.db.write_bytes(b"original")
        raw = self.folder / "bad.zst"
        raw.write_bytes(zstandard.ZstdCompressor().compress(pgn().encode())[:-3])
        with self.assertRaises(Exception):
            preprocess(raw, self.db)
        self.assertEqual(self.db.read_bytes(), b"original")
        self.assertEqual(list(self.folder.glob(".chess-import-*")), [])

    def test_invalid_records_and_excluded_controls(self):
        result = self.prepare(pgn() + pgn(WhiteElo="?") + pgn(TimeControl="1500+0") + pgn(UTCDate="2026.99.01"))
        self.assertEqual((result.read, result.kept, result.malformed, result.excluded), (4, 1, 2, 1))

    def test_empty_input_and_invalid_database(self):
        self.raw.write_text("", encoding="utf-8")
        with self.assertRaises(AppError):
            preprocess(self.raw, self.db)
        self.db.write_text("not sqlite", encoding="utf-8")
        with self.assertRaises(AppError), open_database(self.db):
            pass
        self.db.unlink()
        with contextlib.closing(sqlite3.connect(self.db)) as connection:
            connection.execute("CREATE TABLE anything (x)")
        with self.assertRaises(AppError), open_database(self.db):
            pass

    def test_cancellation_and_same_path(self):
        self.raw.write_text(pgn(), encoding="utf-8")
        event = threading.Event()
        event.set()
        with self.assertRaises(Cancelled):
            preprocess(self.raw, self.db, cancel=event)
        self.assertFalse(self.db.exists())
        with self.assertRaises(AppError):
            preprocess(self.raw, self.raw)

    def test_popularity_exact_one_percent_and_inclusive_filters(self):
        self.prepare(pgn() * 99 + pgn(Opening="French Defense") + pgn(TimeControl="60+0", Opening="Other"))
        with open_database(self.db) as con:
            total, rows = popular_openings(con, "blitz", 1550, 1550)
            self.assertEqual(total, 100)
            self.assertEqual([(r["Opening"], r["Percent"]) for r in rows], [("Sicilian Defense", 99), ("French Defense", 1)])
            total, rows = popular_openings(con)
            self.assertEqual(total, 101)
            self.assertEqual(len(rows), 1)
            self.assertEqual(popular_openings(con, minimum=2000), (0, []))
            with self.assertRaises(AppError):
                popular_openings(con, minimum=2000, maximum=1000)

    def test_improvement_uses_chronology_both_colours_and_control(self):
        # Latest is first in the file; Alice switches colours. Her gain is 65, not sum(deltas).
        self.prepare(pgn(White="Carol", Black="Alice", BlackElo="1560", BlackRatingDiff="5", UTCDate="2026.01.03")
                     + pgn() + pgn(White="Alice", WhiteElo="1510", WhiteRatingDiff="20", UTCDate="2026.01.02")
                     + pgn(White="Alice", WhiteElo="2500", TimeControl="60+0"))
        with open_database(self.db) as con:
            rows = top_players(con, "blitz")
            alice = next(row for row in rows if row["Player"] == "Alice")
            self.assertEqual(alice, dict(Player="Alice", Initial=1500, Final=1565, Change=65, Games=3))
            self.assertEqual(rows[0]["Player"], "Alice")

    def test_time_similarity_and_target_exclusion(self):
        self.prepare(pgn(White="Alice", Black="Bob", TimeControl="60+0")
                     + pgn(White="Alice", Black="Bob", TimeControl="180+0")
                     + pgn(White="Carol", Black="Dan", TimeControl="480+0"))
        with open_database(self.db) as con:
            target, rows = similar_players(con, "Alice", TimeFormatMetric())
            self.assertEqual(rows[0]["Player"], "Bob")
            self.assertEqual(rows[0]["Distance"], 0)
            self.assertAlmostEqual(rows[1]["Distance"], (50**2+50**2+100**2)**.5)
            self.assertNotIn("Alice", [row["Player"] for row in rows])
            with self.assertRaises(AppError):
                similar_players(con, "Unknown", TimeFormatMetric())

    def test_black_similarity_favourite_ties_and_white_only_player(self):
        self.prepare(pgn(Black="Bob", Opening="A") * 3 + pgn(Black="Bob", Opening="B")
                     + pgn(Black="Carol", Opening="A") + pgn(Black="Carol", Opening="B")
                     + pgn(Black="Dan", Opening="B"))
        with open_database(self.db) as con:
            _, rows = similar_players(con, "Bob", BlackOpeningMetric())
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["Player"], "Carol")
            self.assertEqual(rows[0]["Distance"], 25)
            with self.assertRaises(AppError):
                similar_players(con, "Alice", BlackOpeningMetric())

    def test_metric_is_extensible(self):
        self.prepare(pgn())
        class CustomMetric:
            def profiles(self, con): return {"Alice": 10, "Bob": 13}
            def distance(self, a, b): return abs(a-b)
            def describe(self, value): return str(value)
        with open_database(self.db) as con:
            _, rows = similar_players(con, "Alice", CustomMetric())
            self.assertEqual(rows[0]["Distance"], 3)

    def test_cli_validation(self):
        bad_args = [["--unknown"], ["--top10", "--datafile=x"],
                    ["--raw-data=x"], ["--popular-openings", "--datafile=x", "--time-control=classical"],
                    ["--players-similar-to=Alice", "--datafile=x"],
                    ["--popular-openings", "--datafile=x", "--min-rating=abc"],
                    ["--top10", "--datafile=x", "--time-control=blitz", "--black-openings"]]
        for args in bad_args:
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                main(args)
            self.assertEqual(exc.exception.code, 2)

    def test_cli_import_analysis_chart_and_runtime_error(self):
        self.raw.write_text(pgn(), encoding="utf-8")
        chart = self.folder / "chart.png"
        commands = [[f"--raw-data={self.raw}", f"--outfile={self.db}"],
                    [f"--datafile={self.db}", "--top10", "--time-control=blitz"],
                    [f"--datafile={self.db}", "--players-similar-to=Alice", "--time-formats"],
                    [f"--datafile={self.db}", "--players-similar-to=Bob", "--black-openings"],
                    [f"--datafile={self.db}", "--popular-openings", f"--save-chart={chart}"]]
        for args in commands:
            with self.subTest(args=args), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 0)
        self.assertTrue(chart.read_bytes().startswith(b"\x89PNG"))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--datafile=missing.sqlite", "--top10", "--time-control=blitz"]), 1)


if __name__ == "__main__":
    unittest.main()

