from decimal import Decimal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    identifier: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class CompleteProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    age: int = Field(ge=13, le=120)
    position: str = Field(min_length=1, max_length=120)


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ChangePasswordIn(BaseModel):
    oldPassword: str = Field(min_length=1, max_length=128)
    newPassword: str = Field(min_length=8, max_length=128)


class ProfileUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    age: int | None = Field(default=None, ge=13, le=120)
    position: str | None = Field(default=None, max_length=120)
    email: EmailStr | None = None


class CategoryCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=60)
    allocated: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class CategoryUpdateIn(BaseModel):
    allocated: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class QRDecodeIn(BaseModel):
    qrRawString: str = Field(min_length=1, max_length=4096)


class TransferIn(BaseModel):
    recipient: str = Field(min_length=1, max_length=200)
    amount: Decimal = Field(max_digits=12, decimal_places=2)
    note: str = Field(default="", max_length=140)
    pin: str = Field(min_length=4, max_length=128)
    draftId: str | None = None


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class PinIn(BaseModel):
    pin: str = Field(pattern=r"^\d{4,6}$")
    currentPin: str | None = None


class ResponseModel(BaseModel):
    model_config = ConfigDict(extra="allow")

