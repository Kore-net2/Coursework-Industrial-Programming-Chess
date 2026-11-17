"""SQL analytics and interchangeable player-similarity strategies.

"""
from dataclasses import dataclass
from math import dist
from heapq import nsmallest
from typing import Protocol
from .storage import AppError, TIME_CONTROLS


def validate_control(control, required=False):
    if control is None and not required:
        return
    if control not in TIME_CONTROLS:
        raise AppError("Choose bullet, blitz or rapid.")


def players(connection):
    return [r[0] for r in connection.execute("SELECT white FROM games UNION SELECT black FROM games ORDER BY 1")]


def overview(connection):
    row = connection.execute("SELECT count(*), min(played_at), max(played_at), count(DISTINCT opening) FROM games").fetchone()
    return {"games": row[0], "first": row[1], "last": row[2], "openings": row[3]}


def popular_openings(connection, control=None, minimum=None, maximum=None):
    validate_control(control)
    for value in (minimum, maximum):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            raise AppError("Rating limits must be non-negative integers.")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise AppError("Minimum rating must not exceed maximum rating.")
    clauses, values = [], []
    for column, operator, value in (("time_control", "=", control), ("game_rating", ">=", minimum), ("game_rating", "<=", maximum)):
        if value is not None:
            clauses.append(f"{column} {operator} ?")
            values.append(value)
    condition = " WHERE " + " AND ".join(clauses) if clauses else ""
    counts = list(connection.execute("SELECT opening, count(*) AS n FROM games" + condition + " GROUP BY opening ORDER BY n DESC, opening", values))
    total = sum(row[1] for row in counts)
    return total, [{"Opening": name, "Games": n, "Percent": 100.0 * n / total}
                   for name, n in counts if n * 100 >= total]


def top_players(connection, control):
    validate_control(control, required=True)
    rows = connection.execute("""
        WITH ranked AS (
          SELECT player, pre_rating, post_rating,
            row_number() OVER (PARTITION BY player ORDER BY played_at, game_id) AS first_rank,
            row_number() OVER (PARTITION BY player ORDER BY played_at DESC, game_id DESC) AS last_rank
          FROM appearances WHERE time_control=?
        ), totals AS (
          SELECT player, max(CASE WHEN first_rank=1 THEN pre_rating END) AS initial,
            max(CASE WHEN last_rank=1 THEN post_rating END) AS final, count(*) AS games
          FROM ranked GROUP BY player
        )
        SELECT player, initial, final, final-initial AS gain, games FROM totals
        ORDER BY gain DESC, player LIMIT 10
    """, (control,))
    return [dict(zip(("Player", "Initial", "Final", "Change", "Games"), row)) for row in rows]


@dataclass(frozen=True)
class TimeProfile:
    percentages: tuple[float, float, float]


@dataclass(frozen=True)
class OpeningProfile:
    opening: str
    percentage: float


class SimilarityMetric(Protocol):
    """Add a strategy without changing similar_players or its sorting logic.

    None distance excludes an ineligible candidate; distances use percentage points.
    """
    def profiles(self, connection) -> dict: ...
    def distance(self, target, candidate) -> float | None: ...
    def describe(self, profile) -> str: ...


class TimeFormatMetric:
    def profiles(self, connection):
        counts = {}
        for name, control, count in connection.execute("SELECT player, time_control, count(*) FROM appearances GROUP BY player, time_control"):
            counts.setdefault(name, [0, 0, 0])[TIME_CONTROLS.index(control)] = count
        return {name: TimeProfile(tuple(100 * n / sum(nums) for n in nums)) for name, nums in counts.items()}

    def distance(self, target, candidate):
        return dist(target.percentages, candidate.percentages)

    def describe(self, profile):
        return " / ".join(f"{name}: {value:.2f}%" for name, value in zip(TIME_CONTROLS, profile.percentages))


class BlackOpeningMetric:
    def profiles(self, connection):
        # Stable policy for tied favourites: choose the alphabetically first opening.
        rows = connection.execute("""
            WITH counts AS (SELECT black AS player, opening, count(*) AS n FROM games GROUP BY black, opening),
            ranked AS (SELECT player, opening, n, sum(n) OVER (PARTITION BY player) AS total,
              row_number() OVER (PARTITION BY player ORDER BY n DESC, opening) AS position FROM counts)
            SELECT player, opening, 100.0*n/total FROM ranked WHERE position=1
        """)
        return {name: OpeningProfile(opening, percentage) for name, opening, percentage in rows}

    def distance(self, target, candidate):
        return abs(target.percentage - candidate.percentage) if target.opening == candidate.opening else None

    def describe(self, profile):
        return f"{profile.opening}: {profile.percentage:.2f}%"


METRICS = {"time-formats": TimeFormatMetric(), "black-openings": BlackOpeningMetric()}


def similar_players(connection, name, metric: SimilarityMetric):
    exists = connection.execute("SELECT 1 FROM games WHERE white=? OR black=? LIMIT 1", (name, name)).fetchone()
    if not exists:
        raise AppError(f"Unknown player: {name}")
    profiles = metric.profiles(connection)
    if name not in profiles:
        raise AppError(f"No eligible games for {name} under the selected similarity metric.")
    target = profiles[name]
    def candidates():
        for player, profile in profiles.items():
            if player != name:
                distance = metric.distance(target, profile)
                if distance is not None:
                    yield distance, player, profile
    closest = nsmallest(10, candidates(), key=lambda item: (item[0], item[1]))
    return metric.describe(target), [
        {"Player": player, "Distance": distance, "Profile": metric.describe(profile)}
        for distance, player, profile in closest]

