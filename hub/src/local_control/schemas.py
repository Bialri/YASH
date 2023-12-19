from pydantic import BaseModel


class ChangingField(BaseModel):
    name: str
    value: int | float | bool | str