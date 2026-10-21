"""Local, conservative comparison of saved daily-review snapshots."""


def comparable_previous(runs: list[dict], current: dict) -> dict | None:
    target = current.get("target") or current["config"]["requested_date"]
    cfg = current["config"]
    candidates = []
    for run in runs:
        day = run.get("target") or run["config"].get("requested_date")
        other = run["config"]
        if (day and day < target and set(other.get("boards", ())) == set(cfg.get("boards", ()))
                and other.get("exclude_st", True) == cfg.get("exclude_st", True)
                and other.get("exclude_new", True) == cfg.get("exclude_new", True)
                and other.get("source", "tencent") == cfg.get("source", "tencent")):
            candidates.append(run)
    return max(candidates, key=lambda r:(r.get("target") or r["config"]["requested_date"],
                                          r.get("created_at", "")), default=None)


def _verified(result):
    return result and result.get("outcome") in ("match", "no_match") and not (
        result.get("outcome") == "no_match" and result.get("cache_mode") == "batch")


def compare_reviews(previous_results: list[dict], current_results: list[dict]) -> dict[str, list[dict]]:
    old = {r["code"]:r for r in previous_results}
    new = {r["code"]:r for r in current_results}
    groups = {key:[] for key in ("new", "continued", "exited", "uncertain")}
    for code in sorted(old.keys() | new.keys()):
        before, after = old.get(code), new.get(code)
        if not (_verified(before) and _verified(after)):
            group = "uncertain"
        elif before["outcome"] == "no_match" and after["outcome"] == "match":
            group = "new"
        elif before["outcome"] == "match" and after["outcome"] == "match":
            group = "continued"
        elif before["outcome"] == "match" and after["outcome"] == "no_match":
            group = "exited"
        else:
            continue
        groups[group].append(after or before)
    return groups
