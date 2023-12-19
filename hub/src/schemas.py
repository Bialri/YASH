from pydantic import BaseModel


class ResponseSchema(BaseModel):
    status: str
    results: object

class ErrorSchema(BaseModel):
    type: str
    message: str