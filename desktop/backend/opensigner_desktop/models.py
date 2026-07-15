"""Request/response shapes. Placement is fractional (0..1) with a top-left
origin, so one placement applies cleanly to pages of different sizes; the
signer converts it to PDF points per file."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class Placement(BaseModel):
    page: int = -1  # -1 = last page (resolved per file)
    fx: float = 0.68  # left, fraction of page width
    fy: float = 0.86  # top, fraction of page height
    fw: float = 0.29  # width fraction
    fh: float = 0.10  # height fraction


class AppearanceProfile(BaseModel):
    id: str
    name: str
    style: Literal["handwritten", "text", "image"] = "handwritten"
    font: str = "great-vibes"
    # base64 (data: URL ok) of an uploaded signature image; used when style="image".
    image: Optional[str] = None
    show_name: bool = True
    show_date: bool = True
    show_reason: bool = False
    show_location: bool = False


class SignRequest(BaseModel):
    files: list[str]
    identity_id: str
    profile: AppearanceProfile
    standard: str = "B-B"
    reason: Optional[str] = None
    location: Optional[str] = None
    suffix: str = "_signed"
    placement: Placement = Field(default_factory=Placement)
    # Token PIN entered in-app; None falls back to the host's own dialog.
    pin: Optional[str] = None


class Settings(BaseModel):
    last_folder: Optional[str] = None
    identity_id: Optional[str] = None
    profile_id: Optional[str] = None
    standard: str = "B-B"
    suffix: str = "_signed"
    reason: Optional[str] = None
    location: Optional[str] = None
    placement: Optional[Placement] = None
    profiles: list[AppearanceProfile] = Field(default_factory=list)
