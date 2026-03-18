from fastapi import FastAPI
from farewalk.api.routes import router

app = FastAPI(title="farewalk")

app.include_router(router)
