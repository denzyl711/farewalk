from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "farewalk"
    debug: bool = True

    default_network_type: str = "drive"

    default_search_radius_m: float = 1000.0
    default_half_angle_deg: float = 90.0
    default_local_circle_radius_m: float = 500.0
    default_arc_steps: int = 24
    default_road_point_spacing_m: float = 100.0
    default_candidate_merge_radius_m: float = 20.0

    default_search_budget: int = 100
    default_walk_penalty_lambda: float = 0.001
    default_max_leaf_size: int = 12
    default_pricing_provider: Literal["auto", "stub", "uber"] = "auto"

    uber_cookie: str = ""
    uber_product: str = "UBERX"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
