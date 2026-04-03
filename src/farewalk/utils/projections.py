from pyproj import CRS, Transformer


def utm_crs_for_latlng(lat: float, lng: float) -> CRS:
    """
    Determine the UTM CRS for a given latitude and longitude.

    UTM (Universal Transverse Mercator) divides the world into 60 zones,
    each 6 degrees wide. This function calculates the zone number based on
    the longitude and determines whether it's in the northern or southern
    hemisphere based on the latitude.

    Args:
        lat: Latitude in degrees (WGS84)
        lng: Longitude in degrees (WGS84)

    Returns:
        CRS object for the appropriate UTM zone
    """
    zone = int((lng + 180) // 6) + 1
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    return CRS.from_epsg(epsg)


def get_local_transformers(lat: float, lng: float) -> tuple[Transformer, Transformer]:
    """
    Create coordinate transformers for converting between WGS84 and local UTM coordinates.

    This function creates two transformers:
    - to_local: Transforms from WGS84 (EPSG:4326) to the local UTM CRS
    - to_wgs84: Transforms from the local UTM CRS back to WGS84 (EPSG:4326)

    Args:
        lat: Latitude in degrees (WGS84)
        lng: Longitude in degrees (WGS84)

    Returns:
        Tuple of (to_local, to_wgs84) transformers
    """
    local_crs = utm_crs_for_latlng(lat, lng)
    to_local = Transformer.from_crs("EPSG:4326", local_crs, always_xy=True)
    to_wgs84 = Transformer.from_crs(local_crs, "EPSG:4326", always_xy=True)
    return to_local, to_wgs84
