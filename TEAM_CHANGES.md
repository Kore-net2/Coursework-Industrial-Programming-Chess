# Changes for the team — 17 November 2026

## What changed

- `chess_app/storage.py` now imports a file, a list of files, or all `.pgn` / `.pgn.zst` files directly inside a folder into one SQLite database. Folder order is deterministic and duplicate resolved paths are skipped. A failed or cancelled batch preserves the previous output, including when a later archive is corrupt. The output cannot alias an input file. Error examples identify the source filename and record. Source paths are recorded in metadata. Schema version 1 and existing databases remain compatible.
- `cw2.py` accepts multiple paths after `--raw-data`, while preserving the required single-file command. File, permission, encoding and dependency messages use a shared formatter.
- `chess_app/gui.py` supports selecting several files or a folder. Black-opening similarity offers players with black games. The player search explains its 300-result limit. Errors use the same messages as CLI, and users can continue after a failed operation.
- `chess_app/analysis.py` selects the ten closest candidates with a bounded heap instead of building and sorting a second full candidate list. The profile dictionary still occupies memory proportional to the number of players. Ranking and alphabetical tie-breaking remain the same. Ineligible-profile errors are metric-independent. Negative rating bounds are rejected.
- SQLite work during import supports cancellation through a progress handler, including index construction. The final cancellation check protects output replacement.
- Closing the GUI cancels its scheduled polling callback, preventing callbacks against a destroyed window.
- Regression tests cover batch imports, overlapping file/folder selections, a corrupt later archive, empty inputs, CLI paths containing spaces, negative ratings, bounded similarity ordering, generic metric eligibility, invalid encoding, cancellation and GUI recovery.

## Commands

```powershell
python cw2.py --raw-data=dataset_folder --outfile=games.sqlite
python cw2.py --raw-data "part 1.pgn.zst" "part 2.pgn.zst" --outfile=games.sqlite
python -m unittest discover -s tests -v
```

## Delivery and remaining coursework work

Validation on Windows with Python 3.14 and the pinned direct dependencies completed with 23 passing tests, including two Tkinter integration tests. Synthetic demonstration data was regenerated locally for the GUI checks. The upstream python-chess dependency emits a Python 3.14 deprecation warning; it did not fail the tests.

The root source tree is the maintained application. `AppTest_v1` is an earlier packaged snapshot; its bundled executables do not include these changes. Rebuild the final Windows package from the root using `build_windows.ps1` before distribution, and test that package.

These changes address implementation gaps. A full supplied-dataset benchmark, the coursework report, the narrated video, CW1 feedback discussion and each participant's actual contribution still need completion by the team. No full-mark claim is made. The report should explain assumptions including skipped invalid metadata, alphabetical favourite-opening ties, timestamp ties resolved by input order, and percentage-point distances.

This update was produced with OpenAI Codex assistance. Record this assistance and any reused generated material in the coursework attribution according to the assignment requirements. Team members should review and understand the changes and record their own contributions accurately.
