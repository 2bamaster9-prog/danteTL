"""Cutoff Levenshtein comparison for small OCR edits, without alignment heuristics."""


def within_edits(first: str, second: str, limit: int) -> bool:
    """Test unit-cost insertions/deletions/substitutions in a diagonal DP band.

    Trim equal ends, then keep only reachable cells within ``limit`` of the diagonal.
    No full distance matrix or edit script is built. Work is O(limit * string length),
    with O(limit) DP storage; Unicode code points are compared, not encoded bytes.
    """
    if limit < 0:
        raise ValueError("The edit limit must be nonnegative.")
    if abs(len(first) - len(second)) > limit:
        return False
    if first == second:
        return True
    start = 0
    end_first, end_second = len(first), len(second)
    while start < min(end_first, end_second) and first[start] == second[start]:
        start += 1
    while (
        end_first > start and end_second > start and first[end_first - 1] == second[end_second - 1]
    ):
        end_first -= 1
        end_second -= 1
    height, width = end_first - start, end_second - start
    if min(height, width) == 0:
        return max(height, width) <= limit
    previous = {column: column for column in range(min(width, limit) + 1)}
    outside = limit + 1
    for row in range(1, height + 1):
        current: dict[int, int] = {}
        for column in range(max(0, row - limit), min(width, row + limit) + 1):
            distance = (
                min(
                    previous.get(column, outside) + 1,
                    current.get(column - 1, outside) + 1,
                    previous.get(column - 1, outside)
                    + (first[start + row - 1] != second[start + column - 1]),
                )
                if column
                else row
            )
            if distance <= limit:
                current[column] = distance
        if not current:
            return False
        previous = current
    return previous.get(width, outside) <= limit
