from models.base import CamelModel


class Citation(CamelModel):
    text: str
    pmid: str


class StringInteractor(CamelModel):
    symbol: str
    combined_score: float
    direction: str


class GeneDetail(CamelModel):
    symbol: str
    dark_score: float | None = None
    pubs: int | None = None
    screens: int | None = None
    correlation: float | None = None
    is_bright: bool | None = None
    hypothesis: str | None = None
    mechanistic_context: str | None = None
    citations: list[Citation] = []
    suggested_validation: str | None = None
    string_interactors: list[StringInteractor] | None = None
