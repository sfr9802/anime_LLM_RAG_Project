from pydantic import BaseModel

class AppBaseModel(BaseModel):
    class Config:
        orm_mode = True
        extra = "ignore"