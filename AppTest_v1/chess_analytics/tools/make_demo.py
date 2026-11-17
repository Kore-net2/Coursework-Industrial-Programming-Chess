"""Generate reproducible SYNTHETIC metadata; this is not the coursework dataset."""
from datetime import datetime, timedelta
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chess_app.storage import preprocess
import zstandard


def main():
    root = Path(__file__).resolve().parents[1] / "demo"
    root.mkdir(exist_ok=True)
    rng = random.Random(20)
    names = ["Ada", "Alan", "Alice", "Anatoly", "Beth", "Bobby", "Boris", "Carol", "Dina", "Eva", "Garry", "Grace", "Hikaru", "Judit", "Levon", "Magnus", "Mikhail", "Nina", "Paul", "Sofia", "Vera", "Vishy", "Wesley", "Yifan"]
    openings = ["Sicilian Defense", "French Defense", "Queen's Gambit", "Italian Game", "Ruy Lopez", "Caro-Kann Defense", "English Opening", "King's Indian Defense"]
    ratings = {(name, tc): rng.randint(1100, 2300) for name in names for tc in ("60+0", "180+2", "600+0")}
    games = []
    for i in range(720):
        white, black = rng.sample(names, 2)
        tc = rng.choice(("60+0", "180+2", "600+0"))
        wp, bp = ratings[white, tc], ratings[black, tc]
        change = rng.choice((-12, -8, -4, 0, 4, 8, 12))
        ratings[white, tc] += change
        ratings[black, tc] -= change
        stamp = datetime(2026, 1, 1) + timedelta(minutes=i * 17)
        fields = dict(Event="SYNTHETIC demo rated game", White=white, Black=black,
                      WhiteElo=wp, BlackElo=bp, WhiteRatingDiff=change, BlackRatingDiff=-change,
                      Opening=rng.choices(openings, weights=(25, 18, 16, 12, 10, 9, 6, 4))[0] + ": Demo Variation",
                      TimeControl=tc, UTCDate=stamp.strftime("%Y.%m.%d"), UTCTime=stamp.strftime("%H:%M:%S"), Result="1/2-1/2")
        games.append("\n".join(f'[{key} "{value}"]' for key, value in fields.items()) + "\n\n1/2-1/2\n\n")
    rng.shuffle(games)
    raw = root / "synthetic_demo.pgn.zst"
    raw.write_bytes(zstandard.ZstdCompressor().compress("".join(games).encode()))
    print(preprocess(raw, root / "synthetic_demo.sqlite").describe())


if __name__ == "__main__":
    main()
