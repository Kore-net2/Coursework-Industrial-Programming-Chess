"""Streaming PGN ingestion and versioned SQLite storage.

Sources: https://python-chess.readthedocs.io/en/latest/pgn.html#skimming
https://python-zstandard.readthedocs.io/en/latest/decompressor.html
Implementation assistance: OpenAI Codex (2026-11-16).
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import io
import os
from pathlib import Path
import sqlite3
import tempfile

TIME_CONTROLS = ("bullet", "blitz", "rapid")
SCHEMA_VERSION = "1"
GAME_COLUMNS = ("id", "white", "black", "white_pre", "black_pre", "white_post",
                "black_post", "game_rating", "opening", "time_control", "played_at")
SCHEMA = """
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE games (
 id INTEGER PRIMARY KEY,
 white TEXT NOT NULL CHECK(length(white)>0),
 black TEXT NOT NULL CHECK(length(black)>0),
 white_pre INTEGER NOT NULL CHECK(white_pre>=0),
 black_pre INTEGER NOT NULL CHECK(black_pre>=0),
 white_post INTEGER NOT NULL CHECK(white_post>=0),
 black_post INTEGER NOT NULL CHECK(black_post>=0),
 game_rating REAL NOT NULL CHECK(game_rating=(white_pre+black_pre)/2.0),
 opening TEXT NOT NULL CHECK(length(opening)>0),
 time_control TEXT NOT NULL CHECK(time_control IN ('bullet','blitz','rapid')),
 played_at TEXT NOT NULL
);
CREATE VIEW appearances AS
 SELECT id AS game_id, white AS player, white_pre AS pre_rating,
 white_post AS post_rating, time_control, played_at FROM games
 UNION ALL
 SELECT id, black, black_pre, black_post, time_control, played_at FROM games;
"""


class AppError(Exception):
    """An actionable error suitable for CLI output or a GUI message box."""


class Cancelled(AppError):
    pass


@dataclass
class ImportSummary:
    read: int = 0
    kept: int = 0
    excluded: int = 0
    malformed: int = 0
    examples: list[str] = field(default_factory=list)

    def describe(self):
        text = (f"Read: {self.read:,} | Saved: {self.kept:,} | "
                f"Outside time controls: {self.excluded:,} | Invalid: {self.malformed:,}")
        if self.examples:
            text += "\nFirst invalid records:\n" + "\n".join(self.examples)
        return text


def classify_time_control(value):
    try:
        initial, increment = (int(part) for part in value.split("+"))
        if initial < 0 or increment < 0:
            raise ValueError
    except (ValueError, AttributeError):
        # Correspondence and unlimited games are outside the required categories.
        if value in ("-", "?"):
            return None
        raise ValueError("TimeControl must be non-negative seconds+increment")
    duration = initial + 40 * increment
    for name, lower, upper in (("bullet", 30, 180), ("blitz", 180, 480), ("rapid", 480, 1500)):
        if lower <= duration < upper:
            return name
    return None


def normalize_headers(headers):
    """Return a database row, or None for an excluded time control.

    Missing ratings/deltas are invalid, never silently treated as zero.
    """
    tc = classify_time_control(headers["TimeControl"])
    if tc is None:
        return None
    white, black = headers["White"].strip(), headers["Black"].strip()
    opening = headers["Opening"].split(":", 1)[0].strip()
    if any(not value or value == "?" for value in (white, black, opening)):
        raise ValueError("Player names and opening must be known and non-empty")
    wp, bp = int(headers["WhiteElo"]), int(headers["BlackElo"])
    wa = wp + int(headers["WhiteRatingDiff"])
    ba = bp + int(headers["BlackRatingDiff"])
    if min(wp, bp, wa, ba) < 0:
        raise ValueError("Ratings cannot be negative")
    stamp = datetime.strptime(headers["UTCDate"] + " " + headers["UTCTime"],
                              "%Y.%m.%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return (white, black, wp, bp, wa, ba, (wp + bp) / 2,
            opening, tc, stamp.isoformat(timespec="seconds"))


@contextmanager
def pgn_text(path):
    """Read plain PGN or Zstandard PGN without loading the archive into memory."""
    if path.suffix.lower() == ".zst":
        import zstandard
        with path.open("rb") as source:
            with io.BufferedReader(VerifiedZstdReader(source)) as reader:
                with io.TextIOWrapper(reader, encoding="utf-8-sig", errors="strict") as text:
                    yield text
    else:
        with path.open("r", encoding="utf-8-sig") as text:
            yield text


class VerifiedZstdReader(io.RawIOBase):
    """Incremental decompression that also rejects truncated Zstandard frames.

    Concatenated frames are supported. Checking decompressor.eof avoids silently
    accepting a truncated archive, which a simple stream_reader can do.
    """
    def __init__(self, source):
        super().__init__()
        import zstandard
        self.source = source
        self.factory = zstandard.ZstdDecompressor()
        self.decoder = self.factory.decompressobj()
        self.buffer = b""
        self.pending = b""
        self.finished = False

    def readable(self):
        return True

    def readinto(self, target):
        if not len(target):
            return 0
        while not self.buffer and not self.finished:
            data = self.pending or self.source.read(8192)
            self.pending = b""
            if not data:
                if not self.decoder.eof:
                    raise AppError("Incomplete or empty Zstandard archive. Download the file again.")
                self.finished = True
                break
            if self.decoder.eof:
                self.decoder = self.factory.decompressobj()
            self.buffer = self.decoder.decompress(data)
            if self.decoder.eof:
                self.pending = self.decoder.unused_data
        size = min(len(target), len(self.buffer))
        target[:size] = self.buffer[:size]
        self.buffer = self.buffer[size:]
        return size


def preprocess(raw_path, output_path, progress=None, cancel=None):
    """Atomically create a database; a failed import never replaces the destination.

    The caller owns overwrite confirmation in interactive mode. In CLI mode,
    --outfile explicitly selects the destination to replace after success.
    """
    import chess.pgn
    source, destination = Path(raw_path).resolve(), Path(output_path).resolve()
    if source == destination:
        raise AppError("Input and output must be different files.")
    if not source.is_file():
        raise AppError(f"Input file does not exist: {source}")
    if not destination.parent.is_dir():
        raise AppError(f"Output folder does not exist: {destination.parent}")
    descriptor, temporary = tempfile.mkstemp(prefix=".chess-import-", suffix=".sqlite", dir=destination.parent)
    os.close(descriptor)
    summary = ImportSummary()
    connection = None
    try:
        connection = sqlite3.connect(temporary)
        connection.executescript(SCHEMA)
        connection.execute("INSERT INTO metadata VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
        with pgn_text(source) as text:
            while True:
                if cancel and cancel.is_set():
                    raise Cancelled("Import cancelled. The destination was not changed.")
                headers = chess.pgn.read_headers(text)
                if headers is None:
                    break
                summary.read += 1
                try:
                    row = normalize_headers(headers)
                    if row is None:
                        summary.excluded += 1
                    else:
                        connection.execute("INSERT INTO games VALUES (NULL,?,?,?,?,?,?,?,?,?,?)", row)
                        summary.kept += 1
                except (ValueError, KeyError) as exc:
                    summary.malformed += 1
                    if len(summary.examples) < 5:
                        summary.examples.append(f"Record {summary.read}: {exc}")
                if summary.read % 2000 == 0:
                    connection.commit()
                    if progress:
                        progress(summary.describe())
        if summary.kept == 0:
            raise AppError("No usable bullet, blitz or rapid games found.\n" + summary.describe())
        if progress:
            progress("Building database indexes...")
        connection.executescript("""
            CREATE INDEX games_filter ON games(time_control, game_rating);
            CREATE INDEX games_white ON games(white, time_control, played_at, id);
            CREATE INDEX games_black ON games(black, time_control, played_at, id);
            CREATE INDEX games_opening ON games(opening);
        """)
        for key, value in (("source_name", source.name), ("import_summary", summary.describe())):
            connection.execute("INSERT INTO metadata VALUES (?,?)", (key, value))
        connection.commit()
        connection.close()
        connection = None
        if cancel and cancel.is_set():
            raise Cancelled("Import cancelled. The destination was not changed.")
        os.replace(temporary, destination)
        return summary
    finally:
        if connection is not None:
            connection.close()
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def open_database(filename):
    path = Path(filename).resolve()
    if not path.is_file():
        raise AppError(f"Data file does not exist: {path}")
    connection = None
    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        version = connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        columns = tuple(row[1] for row in connection.execute("PRAGMA table_info(games)"))
        if version is None or version[0] != SCHEMA_VERSION or columns != GAME_COLUMNS:
            raise AppError("Unsupported data format. Preprocess the original PGN with this application.")
        yield connection
    except sqlite3.Error as exc:
        raise AppError(f"Cannot read this database: {exc}. Select a preprocessed .sqlite file.") from exc
    finally:
        if connection is not None:
            connection.close()
