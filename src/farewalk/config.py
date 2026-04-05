from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "farewalk"
    debug: bool = True

    default_network_type: str = "drive"

    default_search_radius_m: float = 500.0
    default_half_angle_deg: float = 60.0
    default_local_circle_radius_m: float = 100.0
    default_arc_steps: int = 24
    default_road_point_spacing_m: float = 35.0

    default_search_budget: int = 15
    default_walk_penalty_lambda: float = 0.5
    default_max_leaf_size: int = 6

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
