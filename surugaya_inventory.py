"""Track observed returns to sale separately from Suruga-ya catalog identities."""
import hashlib
import json
from datetime import datetime, timezone


def observe_inventory(previous, watch, matched_ids, present_ids, complete, *, limit=500):
    """Return a new snapshot and eligible IDs seen again after two complete absences.

    Search failures never call this function. Partial pages provide positive
    observations only. An initial or changed search scope seeds silently.
    """
    scope = {
        "keywords": sorted(set(watch.get("keywords") or [watch["keyword"]])),
        **{key: watch.get(key) for key in (
            "price_min", "price_max", "must_match", "must_not_match",
            "must_match_anywhere", "must_not_match_anywhere", "review_unconfirmed",
        )},
    }
    signature = hashlib.sha256(json.dumps(scope, sort_keys=True).encode("utf-8")).hexdigest()
    previous = previous if isinstance(previous, dict) else {}
    same_scope = previous.get("scope") == signature
    stored = previous.get("offers", {}) if same_scope else {}
    offers = {identity: dict(observation) for identity, observation in stored.items()
              if isinstance(observation, dict)
              and type(observation.get("missing")) is int
              and 0 <= observation["missing"] <= 2
              and isinstance(observation.get("last_seen"), str)}
    now = datetime.now(timezone.utc).isoformat()
    matched_ids, present_ids = set(matched_ids), set(present_ids) | set(matched_ids)
    returned = set()
    for identity, observation in offers.items():
        if identity in present_ids:
            if observation["missing"] >= 2 and identity in matched_ids:
                returned.add(identity)
            observation.update(missing=0, last_seen=now)
        elif complete:
            observation["missing"] = min(2, observation["missing"] + 1)
    for identity in matched_ids - offers.keys():
        offers[identity] = {"missing": 0, "last_seen": now}
    offers = dict(sorted(offers.items(), key=lambda row: row[1]["last_seen"])[-limit:])
    return {"scope": signature, "offers": offers}, returned
