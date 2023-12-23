from pydantic import BaseModel


class ConfirmSchema(BaseModel):
    status: bool
    message: object


class CommandSchema(BaseModel):
    command: str
    content: object
