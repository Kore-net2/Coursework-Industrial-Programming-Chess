"""Desktop integration checks. Requires a working Tk installation.

Uses the application's own widgets and callbacks; no user input is injected.
"""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from chess_app.gui import ChessApp


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.app = ChessApp()
        self.app.withdraw()
        self.temp = tempfile.TemporaryDirectory()
        self.messages = []
        self.error_patch = patch("chess_app.gui.messagebox.showerror", side_effect=lambda *args, **kwargs: self.messages.append(args))
        self.error_patch.start()

    def tearDown(self):
        self.error_patch.stop()
        self.app.destroy()
        self.temp.cleanup()

    def wait(self):
        deadline = time.monotonic() + 20
        while self.app.busy and time.monotonic() < deadline:
            self.app.update()
            time.sleep(.01)
        self.app.update()
        self.assertFalse(self.app.busy, "GUI task failed to finish")

    def test_import_all_analyses_and_error_recovery(self):
        demo = Path(__file__).resolve().parents[1] / "demo" / "synthetic_demo.pgn.zst"
        self.app.raw_path.set(str(demo))
        self.app.output_path.set(str(Path(self.temp.name) / "imported.sqlite"))
        self.app.import_data()
        self.wait()
        self.assertEqual(len(self.app.player_names), 24)
        self.assertIn("720 games", self.app.stats_label.get())
        self.app.run_top()
        self.wait()
        self.assertEqual(len(self.app.top_table.get_children()), 10)
        self.app.run_openings()
        self.wait()
        self.assertIsNotNone(self.app.chart_canvas)
        self.assertEqual(len(self.app.last_figure.axes[0].patches), 8)
        self.app.search.set("Alice")
        self.assertEqual(self.app.selected_player.get(), "Alice")
        self.app.run_similar()
        self.wait()
        self.assertEqual(len(self.app.similar_table.get_children()), 10)
        self.app.metric_choice.set("Black openings")
        self.app.run_similar()
        self.wait()
        self.assertGreater(len(self.app.similar_table.get_children()), 0)
        self.assertEqual(self.messages, [])
        self.app.min_rating.set("invalid")
        self.app.guard(self.app.run_openings)
        self.assertEqual(len(self.messages), 1)
        self.app.min_rating.set("")
        self.app.run_openings()
        self.wait()
        self.assertIsNotNone(self.app.chart_canvas)
        # Reopening a dataset clears old results, rather than labelling them as new data.
        self.app.load_path(self.app.database)
        self.wait()
        self.assertEqual(self.app.top_table.get_children(), ())
        self.assertIsNone(self.app.last_figure)


if __name__ == "__main__":
    unittest.main()
