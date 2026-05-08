from pydantic import BaseModel, Field


class NameUpdateRequest(BaseModel):
    new_name: str = Field(min_length=1, max_length=128)


class UserView(BaseModel):
    id: int
    user_id: str
    name: str
    schedule_srelay: str
    card_code: str


class ApiResponse(BaseModel):
    ok: bool
    message: str


class ManagerUpsertRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: str = Field(pattern="^(full|limited)$")
