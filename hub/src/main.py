from fastapi import FastAPI
from registration.router import router as reg_router
from local_control.router import router as local_control_router

app = FastAPI()

app.include_router(reg_router)
app.include_router(local_control_router)
