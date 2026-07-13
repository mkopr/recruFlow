from pydantic import BaseModel


class ConnectorOption(BaseModel):
    id: str
    label: str
