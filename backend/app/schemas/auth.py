from app.schemas.common import Schema


class LoginIn(Schema):
    login: str
    password: str
