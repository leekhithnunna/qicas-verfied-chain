"""Phase 2 quantum layer: per-workflow sub-problem solvers (NOT used by the default demo).

Every sub-solver: solve(sp: SubProblem, seed: int, **params) -> SubResult, with the evaluation
budget set beforehand via sp.set_budget(B) (exceeding it raises BudgetExceeded).
Honest labels (AGENTS.md rule 5): see LABEL. QAOA runs on a classical statevector simulator.
Dependencies: standard library + numpy only.
"""
from .exact import solve as exact
from .model import BudgetExceeded, SubProblem, SubResult
from .qaoa_xy import qaoa_complete, qaoa_complete_ideal, qaoa_ring, qaoa_ring_ideal
from .rand import solve as random_sampling
from .sa import solve as sa
from .sb import solve as sb_ballistic
from .sb import solve_discrete as sb_discrete
from .sqa import solve as sqa

SUBSOLVERS = {
    "exact": exact,
    "random": random_sampling,
    "sa": sa,
    "sqa": sqa,
    "sb_ballistic": sb_ballistic,
    "sb_discrete": sb_discrete,
    "qaoa_ring": qaoa_ring,
    "qaoa_complete": qaoa_complete,
    "qaoa_ring_ideal": qaoa_ring_ideal,
    "qaoa_complete_ideal": qaoa_complete_ideal,
}

_Q = "quantum algorithm, classically simulated"
LABEL = {
    "exact": "reference (brute force)",
    "random": "sanity baseline",
    "sa": "classical",
    "sqa": "quantum-inspired",
    "sb_ballistic": "quantum-inspired",
    "sb_discrete": "quantum-inspired",
    "qaoa_ring": _Q,
    "qaoa_complete": _Q,
    "qaoa_ring_ideal": _Q + " (ideal angles: optimistic upper bound)",
    "qaoa_complete_ideal": _Q + " (ideal angles: optimistic upper bound)",
}

__all__ = ["SUBSOLVERS", "LABEL", "SubProblem", "SubResult", "BudgetExceeded"]
