# Chess Analytics — F20SC application

Python 3 desktop and command-line application for the chess metadata tasks in Coursework 2. This package contains the application, tests and synthetic demonstration data. No coursework report or video is included.

## Быстрый запуск в Windows

1. Если используете готовую сборку, распакуйте весь архив и откройте `ChessAnalytics.exe` в папке `Windows`. Папка `_internal` должна оставаться рядом с EXE.
2. Нажмите **Open database** и выберите `demo/lichess_sample.sqlite` (реальная выборка из учебного датасета, 9 825 сохранённых партий) или `demo/synthetic_demo.sqlite` (искусственный пример на 720 партий).
3. Вкладки **Openings**, **Improvement**, **Similar players** запускают анализ. Для своего датасета используйте **Import data**, выберите `.pgn.zst` и путь для новой базы `.sqlite`, затем **Import and open dataset**.
4. Для поиска игрока введите часть имени в **Find player**, затем выберите точное имя в списке. Список показывает первые 300 совпадений; уточните поиск для остальных имён.

Интерфейс и сообщения приложения на английском языке. Расчёты не требуют подключения к интернету.

## Run from source

Python 3.10 or newer with Tk support is required. Tested with Python 3.12 on Windows. In this directory:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install --no-cache-dir -r requirements.txt
.venv\Scripts\python cw2.py
```

On Linux, install your distribution's `python3-tk` package if Tk is unavailable. A desktop session is required for GUI windows; `--save-chart` works without one.

## Required CLI commands

```powershell
python cw2.py --raw-data=games.pgn.zst --outfile=games.sqlite
python cw2.py --datafile=games.sqlite --popular-openings --time-control=blitz --min-rating=1200 --max-rating=1800
python cw2.py --datafile=games.sqlite --popular-openings
python cw2.py --datafile=games.sqlite --top10 --time-control=rapid
python cw2.py --datafile=games.sqlite --players-similar-to=Alice --time-formats
python cw2.py --datafile=games.sqlite --players-similar-to=Alice --black-openings
```

Use an actual dataset player name in place of Alice. Quote file paths or names containing spaces. With the Windows build, replace `python cw2.py` with `Windows\cw2.exe`. Invoking `cw2.py` or `cw2.exe` without arguments starts the GUI.

Opening popularity opens a bar chart. Optionally save it without a window:

```powershell
python cw2.py --datafile=demo/synthetic_demo.sqlite --popular-openings --save-chart=openings.png
```

Unknown options or invalid combinations return exit code 2. Runtime errors return 1; success returns 0. No traceback is shown to end users. GUI errors appear in dialogs and the application remains open.

## Data and calculation rules

- Supports plain UTF-8 PGN and Zstandard PGN, including concatenated Zstandard frames. Reads metadata with python-chess; does not replay moves. Truncated or corrupt compressed streams fail the import.
- Only estimated durations `initial + 40 * increment` in `[30,180)`, `[180,480)` and `[480,1500)` are kept, as bullet, blitz and rapid respectively. Unlimited/correspondence controls (`-` or `?`) are excluded.
- Ratings, rating changes, names, opening and UTC date/time must be present and valid. Invalid records are skipped with a count and up to five example reasons. Missing changes are never interpreted as zero. If nothing usable remains, import fails.
- Post-game rating = pre-game rating + rating difference. Game rating is the exact mean, including `.5` values. Opening variations after the first colon are removed.
- Rating filters include both endpoints. Opening percentages use **all** matching games as the denominator; only bars at or above 1% are displayed. Displayed bars need not total 100%.
- Improvement is last post-game minus first pre-game rating for the selected control, counting both colours. Input need not be sorted. Simultaneous timestamps are ordered by original record order. With fewer than ten players, all are returned; negative changes remain eligible.
- Time-format similarity uses percentages from 0 to 100 and Euclidean distance. Black-opening similarity only compares players with the same favourite opening and uses the absolute difference in percentages. A tied favourite is resolved alphabetically. Players without black games are ineligible for that metric. The target is excluded; equal distances sort by player name.
- Input files are not modified. Import builds a temporary database beside the destination and replaces the destination only on success. CLI `--outfile` authorizes replacement; the GUI asks before replacing an existing file. Cancellation or failure preserves the existing destination.
- Duplicate records are retained: no game identifier is required by the assignment. Input is assumed to be a rated Lichess export. Invalid movetext is outside the metadata analysis scope.

## Project structure

| File | Purpose |
|---|---|
| `cw2.py` | CLI parsing, validation, output and GUI entry point |
| `chess_app/storage.py` | Stream ingestion, normalization, atomic writes and read-only database access |
| `chess_app/analysis.py` | SQL analytics and interchangeable similarity metrics |
| `chess_app/chart.py` | Shared matplotlib chart |
| `chess_app/gui.py` | Tkinter UI with background work, cancellation and error dialogs |
| `tests/test_app.py` | Deterministic regression tests |
| `tools/make_demo.py` | Recreates the synthetic demo |

SQLite schema version 1 stores `games(id, white, black, white_pre, black_pre, white_post, black_post, game_rating, opening, time_control, played_at)`. Timestamps are UTC ISO 8601 text. `metadata` records the schema version and import summary. The `appearances` view exposes one row per player per game. Indexes support rating/control filtering and player chronology. Only databases created by this application are supported.

To add a metric, implement `profiles(connection)`, `distance(target, candidate)` and `describe(profile)` as documented by `SimilarityMetric`, then register it in `METRICS`. `similar_players` and its sorting logic need no changes. A new user-selectable metric also needs a CLI flag and GUI option.

Import does not load the whole archive into memory. Analytics execute in SQLite, while similarity profiles and the GUI player-name list are held in memory. Full-month Lichess archives have not been benchmarked; large datasets may need significant disk space and query time. No internet download is built into the application.

## Verification and rebuilding

Verified on Windows: 15 automated tests covering calculations, command-line validation, compressed imports, cancellation, atomic replacement, chart output, and GUI import/analysis/error recovery. Both built CLI analytics and PNG export were exercised.

An additional integration check read the first 10,000 game headers from the [course's small dataset](https://marko.doko.foo/F2%5B01%5DSC/CW2/datasets/): 9,825 were retained, 113 had excluded time controls and 62 had missing/invalid required metadata. All four analysis paths succeeded on that sample. The prepared subset is included as `demo/lichess_sample.sqlite`; this is not a test of every record in the complete dataset. Public Lichess game data is provided under CC0.

```powershell
python -m unittest discover -s tests -v
python tools/make_demo.py
```

To rebuild the Windows executables, use `build_windows.ps1` with Python installed. The build uses PyInstaller; distribute the entire resulting folder, including `_internal`. The application is not digitally signed.

## Sources and attribution

Implementation developed with assistance from **OpenAI Codex, 16 November 2026**. Review and understand the code and retain this acknowledgement when adapting it for coursework. The synthetic demo is generated locally and contains no actual player data.

- [python-chess PGN metadata skimming](https://python-chess.readthedocs.io/en/latest/pgn.html#skimming)
- [python-zstandard decompression APIs](https://python-zstandard.readthedocs.io/en/latest/decompressor.html)
- [Python sqlite3](https://docs.python.org/3/library/sqlite3.html)
- [Python tkinter](https://docs.python.org/3/library/tkinter.html)
- [matplotlib](https://matplotlib.org/stable/)

python-chess is licensed under GPL-3.0-or-later. If redistributing the bundled executable, retain third-party notices and comply with dependency licences, including availability of corresponding source. This package includes its application source; third-party projects retain their own licences.
