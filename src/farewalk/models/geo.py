from dataclasses import dataclass


@dataclass(frozen=True)
class LatLng:
    lat: float
    lng: float
