"""Maximum-weight matching of bounded, already gated tracking candidates."""

from math import isfinite

import numpy as np
from numpy.typing import NDArray

# The existing geometric scorer is bounded below by -0.45. A valid same-origin
# typewriter expansion can have a negative score; it must still beat no match.
UNMATCHED_SCORE = -0.5


def _assignment(costs: NDArray[np.float64]) -> tuple[int, ...]:
    """Rectangular Hungarian / shortest augmenting paths, with rows <= columns.

    Row/column potentials maintain nonnegative reduced costs on the alternating tree.
    Each augmentation assigns one more row; dummy columns guarantee a finite path.
    Vectorized column relaxation uses existing NumPy, not a new native dependency.
    Stable column order and free-column preference resolve exact ties without epsilon
    perturbations that could change the maximum-weight objective.
    """
    rows, columns = costs.shape
    row_potential = np.zeros(rows + 1)
    column_potential = np.zeros(columns + 1)
    owner = np.zeros(columns + 1, dtype=np.intp)
    parent = np.zeros(columns + 1, dtype=np.intp)
    for row in range(1, rows + 1):
        owner[0] = row
        slack = np.full(columns, np.inf)
        visited = np.zeros(columns + 1, dtype=np.bool_)
        column = 0
        while True:
            visited[column] = True
            active = owner[column]
            reduced = costs[active - 1] - row_potential[active] - column_potential[1:]
            improved = ~visited[1:] & (reduced < slack)
            slack[improved] = reduced[improved]
            parent[1:][improved] = column
            available = np.where(visited[1:], np.inf, slack)
            next_column = int(np.argmin(available))
            delta = available[next_column]
            # Dense identical labels should take a free equal-cost column directly,
            # rather than walking an arbitrary chain through already assigned labels.
            free = np.flatnonzero((available == delta) & (owner[1:] == 0))
            if free.size:
                next_column = int(free[0])
            row_potential[owner[visited]] += delta
            column_potential[visited] -= delta
            slack[~visited[1:]] -= delta
            column = next_column + 1
            if owner[column] == 0:
                break
        while column:
            previous = int(parent[column])
            owner[column] = owner[previous]
            column = previous
    result = [-1] * rows
    for column in range(1, columns + 1):
        if owner[column]:
            result[int(owner[column]) - 1] = column - 1
    return tuple(result)


def assign_tracks(
    candidates: list[tuple[float, int, int]], observation_order: tuple[int, ...]
) -> tuple[tuple[int, int], ...]:
    """Return (track ID, observation index) pairs maximizing total assignment score.

    Caller bounds tracks/observations and supplies canonical observation order. Missing
    edges remain forbidden. Every track may choose a dummy at UNMATCHED_SCORE;
    maximizing cardinality must not force weak pairs over one strong identity match.
    Only connected competing components need an assignment matrix (at most 128x640
    under the live tracking policy); isolated pairs/stars use their exact best edge.
    """
    by_track: dict[int, dict[int, float]] = {}
    by_observation: dict[int, set[int]] = {}
    for score, track, observation in candidates:
        if score > UNMATCHED_SCORE and isfinite(score):
            edges = by_track.setdefault(track, {})
            edges[observation] = max(score, edges.get(observation, score))
            by_observation.setdefault(observation, set()).add(track)
    rank = {observation: i for i, observation in enumerate(observation_order)}
    remaining = set(by_track)
    matches = []
    while remaining:
        pending = [min(remaining)]
        tracks, observations = set(pending), set()
        remaining.difference_update(tracks)
        while pending:
            for observation in by_track[pending.pop()]:
                if observation in observations:
                    continue
                observations.add(observation)
                neighbors = by_observation[observation] & remaining
                remaining.difference_update(neighbors)
                tracks.update(neighbors)
                pending.extend(neighbors)
        ordered_tracks = sorted(tracks)
        ordered_observations = sorted(observations, key=rank.__getitem__)
        if min(len(tracks), len(observations)) == 1:
            _, track, observation = min(
                (
                    (-score, track, observation)
                    for track in ordered_tracks
                    for observation, score in by_track[track].items()
                ),
                key=lambda edge: (edge[0], edge[1], rank[edge[2]]),
            )
            matches.append((track, observation))
            continue
        positions = {observation: i for i, observation in enumerate(ordered_observations)}
        costs = np.full((len(tracks), len(observations) + len(tracks)), np.inf)
        for row, track in enumerate(ordered_tracks):
            for observation, score in by_track[track].items():
                costs[row, positions[observation]] = -score
            costs[row, len(observations) + row] = -UNMATCHED_SCORE
        for row, column in enumerate(_assignment(costs)):
            if column < len(observations):
                matches.append((ordered_tracks[row], ordered_observations[column]))
    return tuple(sorted(matches))
