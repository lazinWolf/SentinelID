"""Optional investigation priority without changing detector scores or queue policy."""

import copy

from .pipeline import WorkloadQueue


class ExperimentQueue(WorkloadQueue):
    def rank_key(self, candidate):
        return (-candidate["priority_score"], candidate["available_time"], candidate["identity_id"])

    def offer(self, candidate):
        c = copy.deepcopy(candidate)
        if c["score"] != c["detector_score"]:
            raise ValueError("Legacy score must remain the detector score")
        old = self.pending.get(c["identity_id"])
        old_priority = old["priority_score"] if old else None
        priority_day = old["priority_day"] if old else c["day"]
        detector_day = old.get("detector_day", old["day"]) if old else c["day"]
        if old is None or c["detector_score"] > old["detector_score"]:
            detector_day = c["day"]
        decision_start = len(self.decisions)
        history_size = len(old["score_history"]) if old else 0
        super().offer(c)
        pending = self.pending.get(c["identity_id"])
        accepted = pending is not None and len(pending["score_history"]) > history_size
        if accepted:
            if old_priority is None or c["priority_score"] > old_priority:
                priority_day = c["day"]
                old_priority = c["priority_score"]
            pending["priority_score"] = old_priority
            pending["detector_score"] = pending["score"]
            pending["detector_day"] = detector_day
            pending["priority_day"] = priority_day
            if old:
                pending["priority_history"].append(
                    {"day": c["day"], "priority_score": c["priority_score"]}
                )
                pending["detector_history"].append(
                    {"day": c["day"], "detector_score": c["detector_score"]}
                )
            else:
                pending["priority_history"] = [
                    {"day": c["day"], "priority_score": c["priority_score"]}
                ]
                pending["detector_history"] = [
                    {"day": c["day"], "detector_score": c["detector_score"]}
                ]
        for decision in self.decisions[decision_start:]:
            decision.update(detector_score=c["detector_score"], priority_score=c["priority_score"])

    def decide(self, when):
        prior = copy.deepcopy(self.pending)
        start = len(self.decisions)
        cases = super().decide(when)
        for decision in self.decisions[start:]:
            candidate = prior[decision["identity_id"]]
            decision.update(
                {
                    k: candidate[k]
                    for k in ("detector_score", "priority_score", "detector_day", "priority_day")
                }
            )
        return cases
