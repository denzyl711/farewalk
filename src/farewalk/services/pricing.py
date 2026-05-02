import math
from dataclasses import dataclass
from typing import Callable, Literal

import httpx

from farewalk.config import settings
from farewalk.models.geo import LatLng

_BASE_FARE = 3.50
_PRICE_PER_KM = 1.80
ProviderId = Literal["stub", "uber"]
RequestedProviderId = Literal["auto", "stub", "uber"]
PriceFunction = Callable[[LatLng, LatLng], float]


class PricingError(Exception):
    def __init__(self, message: str, provider_id: str):
        super().__init__(message)
        self.provider_id = provider_id


class PricingConfigurationError(PricingError):
    pass


class PricingTimeoutError(PricingError):
    pass


class PricingAuthError(PricingError):
    pass


class PricingUnavailableError(PricingError):
    pass


class PricingResponseError(PricingError):
    pass


@dataclass(frozen=True)
class RegisteredPricingProvider:
    provider_id: ProviderId
    quote: PriceFunction
    requires_cookie: bool = False

    def __call__(self, pickup: LatLng, destination: LatLng) -> float:
        return self.quote(pickup, destination)


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
    if not settings.uber_cookie:
        raise PricingConfigurationError("Uber pricing is not configured", "uber")

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

    try:
        response = httpx.post(
            _UBER_GRAPHQL_URL,
            json=payload,
            headers={**_UBER_HEADERS, "cookie": settings.uber_cookie},
            timeout=15.0,
        )
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise PricingTimeoutError("Uber pricing request timed out", "uber") from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {401, 403}:
            raise PricingAuthError("Uber pricing authentication failed", "uber") from exc
        raise PricingUnavailableError(
            f"Uber pricing request failed with status {exc.response.status_code}",
            "uber",
        ) from exc
    except httpx.HTTPError as exc:
        raise PricingUnavailableError("Uber pricing request failed", "uber") from exc

    try:
        data = response.json()
        tiers = data["data"]["products"]["tiers"]
    except (KeyError, TypeError, ValueError) as exc:
        raise PricingResponseError("Uber pricing response was malformed", "uber") from exc

    target = settings.uber_product

    try:
        for tier in tiers:
            for product in tier["products"]:
                if product["productClassificationTypeName"] == target:
                    fare_e5 = product["fares"][0]["fareAmountE5"]
                    return fare_e5 / 100_000
    except (KeyError, TypeError, IndexError) as exc:
        raise PricingResponseError("Uber pricing response was malformed", "uber") from exc

    raise PricingResponseError(f"Product '{target}' not found in Uber response", "uber")


_PROVIDERS: dict[ProviderId, RegisteredPricingProvider] = {
    "stub": RegisteredPricingProvider(
        provider_id="stub",
        quote=stub_price_provider,
    ),
    "uber": RegisteredPricingProvider(
        provider_id="uber",
        quote=uber_price_provider,
        requires_cookie=True,
    ),
}


def get_pricing_provider(provider_id: ProviderId) -> RegisteredPricingProvider:
    return _PROVIDERS[provider_id]


def default_pricing_provider_id() -> ProviderId:
    configured = settings.default_pricing_provider
    if configured == "auto":
        return "uber" if settings.uber_cookie else "stub"
    return configured


def resolve_pricing_provider(
    provider_id: RequestedProviderId | None = None,
) -> RegisteredPricingProvider:
    if provider_id in (None, "auto"):
        selected_id = default_pricing_provider_id()
    else:
        selected_id = provider_id
    provider = get_pricing_provider(selected_id)
    if provider.requires_cookie and not settings.uber_cookie:
        raise PricingConfigurationError("Uber pricing is not configured", provider.provider_id)
    return provider
