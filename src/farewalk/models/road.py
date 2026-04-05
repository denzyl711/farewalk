from dataclasses import dataclass


@dataclass(frozen=True)
class CandidatePoint:
    lat: float
    lng: float


@dataclass(frozen=True)
class ScoredCandidate:
    candidate: CandidatePoint
    price: float
    walk_distance_m: float
    score: float
