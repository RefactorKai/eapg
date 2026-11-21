"""Rank a slice against the canonical macro-nodes that were profiled, never a raw reparse."""

import copy
import inspect
from types import FunctionType


def _accepts_macro_nodes(rank):
    params = inspect.signature(rank).parameters.values()
    return any(p.name == "macro_nodes" or p.kind is p.VAR_KEYWORD for p in params)


def rank_canonical(pipeline, record, macro_nodes, *, use_loop_def_use=False):
    """Call the ranker so loop def-use analysis resolves IDs in the canonical node set.

    Candidate pipelines accept `macro_nodes` directly. The frozen ranker reparses
    `record["slow_code"]` without macro expansion, so expanded IDs such as `N4` can be
    missing; for it the frozen code runs unchanged with its reparse bound to `macro_nodes`.
    """
    rank = pipeline.rank_candidates_by_role_priority
    if _accepts_macro_nodes(rank):
        return rank(record, use_loop_def_use=use_loop_def_use, macro_nodes=macro_nodes)
    aliases = pipeline.loop_bound_aliases
    alias_globals = dict(aliases.__globals__,
                         extract_macro_nodes=lambda *_args: copy.deepcopy(macro_nodes),
                         normalize_synthetic_braces=lambda source: source)
    canonical_aliases = FunctionType(aliases.__code__, alias_globals, aliases.__name__,
                                     aliases.__defaults__, aliases.__closure__)
    canonical_rank = FunctionType(rank.__code__, dict(rank.__globals__, loop_bound_aliases=canonical_aliases),
                                  rank.__name__, rank.__defaults__, rank.__closure__)
    canonical_rank.__kwdefaults__ = rank.__kwdefaults__
    return canonical_rank(record, use_loop_def_use=use_loop_def_use)
