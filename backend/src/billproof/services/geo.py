import math

EARTH_RADIUS_MILES = 3958.8


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """docs/05: a tested Haversine query is acceptable for SQLite/offline fixtures."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1, math.sqrt(a)))


ZIP_CENTROIDS = {
    # Coarse, rounded centroids only (docs/05: round/cache to ZIP centroid,
    # never require or persist an exact street address).
    "24060": (37.2001, -80.4181),  # Blacksburg
    "24073": (37.1259, -80.4292),  # Christiansburg
}


def zip_to_centroid(zip_code: str) -> tuple[float, float] | None:
    return ZIP_CENTROIDS.get(zip_code)
