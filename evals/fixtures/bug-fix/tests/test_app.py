from app import calculate_total


def test_calculate_total_does_not_add_an_extra_unit():
    assert calculate_total([1, 2, 3]) == 6
