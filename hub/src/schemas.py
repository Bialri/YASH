from pydantic import BaseModel
from typing import Literal


class ResponseSchema(BaseModel):
    status: str
    results: object

class ErrorSchema(BaseModel):
    type: str
    message: str

class DeviceResponseSchema(BaseModel):
    name: str
    type: Literal["device", "sensor"]
    fields: list[str]