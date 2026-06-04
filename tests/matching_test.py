from utils.matching import filter_matches

def test_matching():
    assert filter_matches("order.created", "order.created") is True
    assert filter_matches("order.created", "order.*")       is True
    assert filter_matches("order.created", "user.*")        is False
    assert filter_matches("order.created", "*")             is True