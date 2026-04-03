from dataclasses import dataclass


@dataclass(frozen=True)
class CandidatePoint:
    lat: float
    lng: float
