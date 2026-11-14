import inspect

import formatting


def test_shared_normalizer_exists_and_is_used_by_both_formatters():
    assert callable(getattr(formatting, "normalize_label", None))
    assert "normalize_label" in inspect.getsource(formatting.format_customer)
    assert "normalize_label" in inspect.getsource(formatting.format_product)
    assert formatting.format_customer("  jane   DOE ") == "Jane Doe"
    assert formatting.format_product("  blue   widget ") == "Blue Widget"
