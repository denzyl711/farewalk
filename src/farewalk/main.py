from fastapi import FastAPI

from farewalk.api.routes import router
from farewalk.config import settings

app = FastAPI(title=settings.app_name)

app.include_router(router)