from pydantic import BaseModel
from typing import Literal


class Field(BaseModel):
    name: str
    type: Literal["int", "float", "str", "bool"]


class DeviceSpecification(BaseModel):
    name: str
    type: Literal["device", "sensor"]
    fields: list[Field]


class ErrorForm(BaseModel):
    status: str
    type: str
    detail: str


class Confirm(BaseModel):
    status: bool
