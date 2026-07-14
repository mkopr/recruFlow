from pydantic import BaseModel


class ConnectorOption(BaseModel):
    id: str
    label: str
    offer_count: int
    scored_count: int
    unscored_count: int
