from pydantic import BaseModel, field_validator, ValidationInfo
from typing import Literal


class Field(BaseModel):
    name: str
    value: int | float | str | bool
    min: int | float | None = None
    max: int | float | None = None
    value: int | float | str | bool
    type: Literal["int", "float", "str", "bool"]

    @field_validator('type')
    @classmethod
    def check_numeric_restriction(cls, field_value, info: ValidationInfo):
        print('Im here')
        print(info.data)
        print(field_value)
        if eval(field_value) is int or eval(field_value) is float:
            min = info.data.get('min', None)
            max = info.data.get('max', None)
            if max is not None and min is not None:
                return field_value
            else:
                raise ValueError(f"Range should be defined for numeric field {info.field_name}")
        return field_value


class ResponseDetails(BaseModel):
    address: str
    port: str


class DeviceSpecification(BaseModel):
    name: str
    type: Literal["device", "sensor"]
    fields: list[Field]
    response_details: ResponseDetails

class ErrorForm(BaseModel):
    status: str
    type: str
    detail: str


class Confirm(BaseModel):
    status: bool
