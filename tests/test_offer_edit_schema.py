from app.schemas.offer import OfferEdit


def test_offer_edit_accepts_link_opened_true() -> None:
    edit = OfferEdit(link_opened=True)
    assert edit.model_dump(exclude_unset=True) == {"link_opened": True}


def test_offer_edit_link_opened_defaults_to_none_when_unset() -> None:
    edit = OfferEdit()
    assert "link_opened" not in edit.model_dump(exclude_unset=True)
