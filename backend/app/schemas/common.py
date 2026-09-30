from pydantic import BaseModel, ConfigDict


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(Schema):
    id: int
    login: str
    name: str
