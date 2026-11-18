"""Predict the predeclared CPU comparisons from one seed's slow-side trace."""

from hashlib import sha256

from backward_slice import UnsupportedProgram, backward_slice


ARM_IDS = ("hit_growth", "work_symptom", "work_scoped", "work_conventional",
           "hits_scoped", "hits_conventional", "work_scoped_symbolic")


def arm(symptom, candidates, ranking, *, status=None, alert=None):
    return {"alert": alert, "symptom_id": symptom, "candidates": candidates,
            "ranking": ranking, "status": status or ("ranked" if ranking else "no_symptom")}


def eligible_fit(fit, counts):
    growth = fit["growth"]
    quality = fit.get("r2_exp" if growth == "EXP" else "r2_poly", 0)
    if not any(counts) or growth not in {"EXP", "POLY"} or quality < 0.85:
        # Retain the numeric fields for diagnostics and remove eligibility for growth comparisons.
        return dict(fit, growth="UNAVAILABLE")
    return fit


def predict_seed(pipeline, normalized, profile, seed):
    nodes = profile["nodes"]
    digest = sha256(normalized.encode()).hexdigest()
    if digest != profile["normalized_sha256"]:
        raise ValueError("Baseline and profiler must use the same normalized source")
    ids = [node["id"] for node in nodes]
    original_fits = profile["fits"][str(seed)]
    clean = [row for row in profile["runs"][str(seed)] if row["status"] == "CLEAN_COMPLETION"]
    if set(ids) != set(original_fits) or any(set(row["nodes"]) != set(ids) for row in clean):
        raise ValueError("Fit and counter nodes must match the canonical map")
    sizes = [row["n"] for row in clean]
    if len(sizes) < 4 or sizes != sorted(set(sizes)) or sizes[-1] < 8 * sizes[0]:
        raise ValueError("Expected at least four distinct ascending clean sizes spanning eightfold")
    fits = {nid: {channel: eligible_fit(original_fits[nid][channel], [row["nodes"][nid][key] for row in clean])
                  for channel, key in (("fit_hits", "cnt"), ("fit_work", "work"))}
            for nid in ids}

    def hit_priority(nid):
        fit = fits[nid]["fit_hits"]
        exp = fit["growth"] == "EXP"
        return exp, fit["beta"] if exp else fit["alpha"]

    hit_order = sorted((nid for nid in ids if fits[nid]["fit_hits"]["growth"] in {"POLY", "EXP"}),
                       key=hit_priority, reverse=True)
    arms = {"hit_growth": arm(None, hit_order, hit_order, status="no_eligible_fit" if not hit_order else None)}
    conventional = {}
    for channel in ("work", "hits"):
        channel_fits = fits if channel == "work" else {
            nid: {"fit_hits": fit["fit_hits"], "fit_work": fit["fit_hits"]} for nid, fit in fits.items()
        }
        if not any(fit["fit_work"]["growth"] != "UNAVAILABLE" for fit in channel_fits.values()):
            unavailable = arm(None, [], [], status="no_eligible_fit")
            arms[f"{channel}_scoped"] = arms[f"{channel}_conventional"] = unavailable
            if channel == "work":
                arms["work_symptom"] = arms["work_scoped_symbolic"] = unavailable
            continue
        tiers = pipeline.evaluate_four_slicing_tiers(nodes, channel_fits)
        symptom, scoped = tiers["primary_symptom"], tiers["c_pruned"]
        dynamics = dict(tiers, c_slice=scoped, r_search=1 - len(scoped) / len(nodes) if nodes else 0)
        skeleton = pipeline.format_eapg_skeleton(nodes, channel_fits, dynamics)

        def rank(candidates, *, loop_def_use=False):
            if not candidates:
                return arm(symptom, [], [], alert=bool(symptom), status="empty_slice" if symptom else "no_symptom")
            record = {"skeleton": skeleton, "slicing": dict(tiers, c_pruned=candidates)}
            ranked = pipeline.rank_candidates_by_role_priority(
                record, use_loop_def_use=loop_def_use, macro_nodes=nodes,
            )
            if sorted(ranked) != sorted(candidates):
                return arm(symptom, candidates, [], alert=True, status="invalid_ranking")
            return arm(symptom, candidates, ranked, alert=True)

        arms[f"{channel}_scoped"] = rank(scoped)
        if symptom and symptom not in conventional:
            try:
                candidates = backward_slice(pipeline, normalized, nodes, symptom)
            except UnsupportedProgram:
                conventional[symptom] = None
            else:
                if (symptom not in candidates or len(candidates) != len(set(candidates))
                        or not set(candidates) <= set(ids)):
                    raise ValueError("Conventional slice must contain the symptom and use canonical IDs")
                conventional[symptom] = [nid for nid in ids if nid in candidates]
        candidates = conventional.get(symptom, [])
        arms[f"{channel}_conventional"] = (
            arm(symptom, [], [], alert=True, status="unsupported_baseline")
            if candidates is None else rank(candidates)
        )
        if channel == "work":
            singleton = [symptom] if symptom else []
            arms["work_symptom"] = arm(symptom, singleton, singleton, alert=bool(symptom))
            arms["work_scoped_symbolic"] = rank(scoped, loop_def_use=True)
    return {"seed": seed, "normalized_source_sha256": digest, "profile_status": "complete", "arms": arms}
