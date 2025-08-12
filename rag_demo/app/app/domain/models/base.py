# models/base.py
from pydantic import BaseModel, ConfigDict

class AppBaseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # v2 권장
