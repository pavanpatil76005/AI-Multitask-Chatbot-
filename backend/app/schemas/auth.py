from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class EmailRequest(BaseModel):
    email: EmailStr = Field(max_length=255)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class RegisterRequest(EmailRequest):
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=1024)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class LoginRequest(EmailRequest):
    password: str = Field(min_length=1, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)
