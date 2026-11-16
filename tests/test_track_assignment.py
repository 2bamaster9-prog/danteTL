"""Assignment optimality against exhaustive small-graph search, not another solver."""

from itertools import product
from random import Random

import pytest

from dantejp.ocr.track_assignment import UNMATCHED_SCORE, assign_tracks


def objective(edges, matches):
    scores = {(track, observation): score for score, track, observation in edges}
    tracks = {track for _, track, _ in edges}
    return sum(scores[pair] for pair in matches) + (len(tracks) - len(matches)) * UNMATCHED_SCORE


def exhaustive(edges):
    tracks = sorted({track for _, track, _ in edges})
    choices = [
        [None, *(observation for _, key, observation in edges if key == track)] for track in tracks
    ]
    best = len(tracks) * UNMATCHED_SCORE
    for selected in product(*choices):
        present = [value for value in selected if value is not None]
        if len(present) != len(set(present)):
            continue
        pairs = tuple((t, o) for t, o in zip(tracks, selected, strict=True) if o is not None)
        best = max(best, objective(edges, pairs))
    return best


def test_competing_pairs_beat_greedy_without_forcing_maximum_cardinality():
    edges = [(2.5, 1, 0), (2.0, 1, 1), (1.5, 2, 0)]
    assert assign_tracks(edges, (0, 1)) == ((1, 1), (2, 0))
    # An incompatible pair must never be invented to make a square assignment full.
    # Keeping the strong match is better than forcing both weak alternatives.
    edges = [(5.0, 1, 0), (0.1, 1, 1), (0.1, 2, 0)]
    assert assign_tracks(edges, (0, 1)) == ((1, 0),)
    # Same-origin growth can be negative under the existing geometric score.
    assert assign_tracks([(-0.44, 3, 2)], (2,)) == ((3, 2),)
    assert assign_tracks([], ()) == ()


def test_components_rectangular_graphs_and_unmatched_choices_match_exhaustive_optimum():
    random = Random(713)
    for _ in range(150):
        tracks, observations = random.randrange(1, 5), random.randrange(1, 6)
        edges = [
            (random.randrange(-4, 41) / 8, track, observation)
            for track in range(tracks)
            for observation in range(observations)
            if random.random() < 0.65
        ]
        result = assign_tracks(edges, tuple(range(observations)))
        assert len({t for t, _ in result}) == len(result)
        assert len({o for _, o in result}) == len(result)
        assert all(any((t, o) == (key, index) for _, key, index in edges) for t, o in result)
        assert objective(edges, result) == pytest.approx(exhaustive(edges))


def test_ties_and_edge_order_respect_canonical_observation_order():
    random = Random(19)
    edges = [(1.0, track, observation) for track in range(4) for observation in range(6)]
    expected = assign_tracks(edges, tuple(range(6)))
    assert expected == tuple((i, i) for i in range(4))
    for _ in range(20):
        raw_indices = random.sample(range(6), 6)
        permuted = [(score, track, raw_indices[index]) for score, track, index in edges]
        random.shuffle(permuted)
        result = assign_tracks(permuted, tuple(raw_indices))
        assert tuple((track, raw_indices.index(index)) for track, index in result) == expected


def test_full_policy_capacity_handles_dense_ties_and_many_independent_components():
    dense = [(1.0, track, observation) for track in range(128) for observation in range(512)]
    assert assign_tracks(dense, tuple(range(512))) == tuple((i, i) for i in range(128))
    separate = [(1.0, track, track * 4 + index) for track in range(128) for index in range(4)]
    assert assign_tracks(separate, tuple(range(512))) == tuple((i, i * 4) for i in range(128))
