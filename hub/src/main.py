from fastapi import FastAPI
from registration.router import router as reg_router

app = FastAPI()

app.include_router(reg_router)
