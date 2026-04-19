import math

import httpx

from farewalk.config import settings
from farewalk.models.geo import LatLng

_BASE_FARE = 3.50
_PRICE_PER_KM = 1.80


def stub_price_provider(pickup: LatLng, destination: LatLng) -> float:
    """Estimate fare based on straight-line distance pickup -> destination."""
    dlat = math.radians(destination.lat - pickup.lat)
    dlng = math.radians(destination.lng - pickup.lng)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(pickup.lat))
        * math.cos(math.radians(destination.lat))
        * math.sin(dlng / 2) ** 2
    )
    distance_km = 6371 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return _BASE_FARE + _PRICE_PER_KM * distance_km


# ---------------------------------------------------------------------------
# Uber GraphQL price provider (m.uber.com reverse-engineered API)
# ---------------------------------------------------------------------------

_UBER_GRAPHQL_URL = "https://m.uber.com/go/graphql"

_UBER_HEADERS = {
    "accept": "*/*",
    "content-type": "application/json",
    "origin": "https://m.uber.com",
    "x-csrf-token": "x",
    "x-uber-rv-session-type": "mobile_session",
    "user-agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 "
        "Mobile/15E148 Safari/604.1"
    ),
}

_PRODUCTS_QUERY = (
    "query Products("
    "$boostedVehicleId: String, "
    "$capacity: Int, "
    "$destinations: [InputCoordinate!]!, "
    "$includeRecommended: Boolean = false, "
    "$isRiderCurrentUser: Boolean, "
    "$payment: InputPayment, "
    "$paymentProfileUUID: String, "
    "$pickup: InputCoordinate!, "
    "$pickupFormattedTime: String, "
    "$profileType: String, "
    "$profileUUID: String, "
    "$returnByFormattedTime: String, "
    "$stuntID: String, "
    "$targetProductType: EnumRVWebCommonTargetProductType"
    ") {\n"
    "  products(\n"
    "    boostedVehicleId: $boostedVehicleId\n"
    "    capacity: $capacity\n"
    "    destinations: $destinations\n"
    "    includeRecommended: $includeRecommended\n"
    "    isRiderCurrentUser: $isRiderCurrentUser\n"
    "    payment: $payment\n"
    "    paymentProfileUUID: $paymentProfileUUID\n"
    "    pickup: $pickup\n"
    "    pickupFormattedTime: $pickupFormattedTime\n"
    "    profileType: $profileType\n"
    "    profileUUID: $profileUUID\n"
    "    returnByFormattedTime: $returnByFormattedTime\n"
    "    stuntID: $stuntID\n"
    "    targetProductType: $targetProductType\n"
    "  ) {\n"
    "    ...ProductsFragment\n"
    "    __typename\n"
    "  }\n"
    "}\n"
    "\n"
    "fragment ProductsFragment on RVWebCommonProductsResponse {\n"
    "  defaultVVID\n"
    "  productsUnavailableMessage\n"
    "  tiers {\n"
    "    ...TierFragment\n"
    "    __typename\n"
    "  }\n"
    "  __typename\n"
    "}\n"
    "\n"
    "fragment TierFragment on RVWebCommonProductTier {\n"
    "  products {\n"
    "    ...ProductFragment\n"
    "    __typename\n"
    "  }\n"
    "  title\n"
    "  __typename\n"
    "}\n"
    "\n"
    "fragment ProductFragment on RVWebCommonProduct {\n"
    "  displayName\n"
    "  fares {\n"
    "    fare\n"
    "    fareAmountE5\n"
    "    __typename\n"
    "  }\n"
    "  isAvailable\n"
    "  productClassificationTypeName\n"
    "  productUuid\n"
    "  __typename\n"
    "}\n"
)


def uber_price_provider(pickup: LatLng, destination: LatLng) -> float:
    payload = {
        "operationName": "Products",
        "variables": {
            "includeRecommended": False,
            "destinations": [
                {"latitude": destination.lat, "longitude": destination.lng},
            ],
            "payment": {"uberCashToggleOn": True},
            "pickup": {"latitude": pickup.lat, "longitude": pickup.lng},
        },
        "query": _PRODUCTS_QUERY,
    }

    response = httpx.post(
        _UBER_GRAPHQL_URL,
        json=payload,
        headers={**_UBER_HEADERS, "cookie": settings.uber_cookie},
        timeout=15.0,
    )
    response.raise_for_status()

    data = response.json()
    target = settings.uber_product

    for tier in data["data"]["products"]["tiers"]:
        for product in tier["products"]:
            if product["productClassificationTypeName"] == target:
                fare_e5 = product["fares"][0]["fareAmountE5"]
                return fare_e5 / 100_000

    raise ValueError(f"Product '{target}' not found in Uber response")
