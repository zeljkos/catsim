"""GF(2) linear algebra for code construction: rank, kernel, coset checks.

Exists so code definitions can compute k and logical operators from their check
matrices with numpy alone, keeping the codes package a leaf.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

Matrix = npt.NDArray[np.uint8]


def row_reduce(matrix: Matrix) -> tuple[Matrix, list[int]]:
    """Bring a binary matrix to reduced row-echelon form over GF(2).

    Args:
        matrix: Any binary matrix (not modified).

    Returns:
        The reduced nonzero rows and the pivot column of each row.
    """
    m = (matrix.copy() % 2).astype(np.uint8)
    rank = 0
    pivots: list[int] = []
    for col in range(m.shape[1]):
        pivot = next((r for r in range(rank, m.shape[0]) if m[r, col]), None)
        if pivot is None:
            continue
        m[[rank, pivot]] = m[[pivot, rank]]
        for row in range(m.shape[0]):
            if row != rank and m[row, col]:
                m[row] ^= m[rank]
        pivots.append(col)
        rank += 1
    return m[:rank], pivots


def rank(matrix: Matrix) -> int:
    """GF(2) rank of a binary matrix."""
    return int(row_reduce(matrix)[0].shape[0])


def kernel_basis(matrix: Matrix) -> Matrix:
    """Basis of the right null space over GF(2), one vector per row.

    Args:
        matrix: Any binary matrix.

    Returns:
        A (nullity x columns) matrix whose rows span ``{v : matrix @ v = 0}``.
    """
    reduced, pivots = row_reduce(matrix)
    cols = matrix.shape[1]
    free = [c for c in range(cols) if c not in pivots]
    basis = np.zeros((len(free), cols), dtype=np.uint8)
    for i, f in enumerate(free):
        basis[i, f] = 1
        for row, p in enumerate(pivots):
            if reduced[row, f]:
                basis[i, p] = 1
    return basis


def in_rowspace(matrix: Matrix, vector: Matrix) -> bool:
    """True if ``vector`` lies in the GF(2) row space of ``matrix``."""
    return rank(np.vstack([matrix, vector])) == rank(matrix)


def coset_representatives(candidates: Matrix, subspace: Matrix) -> Matrix:
    """Select candidates independent of ``subspace`` (and each other) over GF(2).

    Used to pick logical operator representatives: kernel vectors that are not
    stabilizers, one per logical coset.

    Args:
        candidates: Row vectors to filter (e.g. a kernel basis).
        subspace: Row space to reduce against (e.g. stabilizer generators).

    Returns:
        The selected rows, in input order.
    """
    stack = subspace.copy()
    base = rank(stack)
    chosen: list[Matrix] = []
    for vector in candidates:
        stacked = np.vstack([stack, vector])
        r = rank(stacked)
        if r > base:
            chosen.append(vector)
            stack, base = stacked, r
    return (
        np.array(chosen, dtype=np.uint8) if chosen else np.zeros((0, candidates.shape[1]), np.uint8)
    )
