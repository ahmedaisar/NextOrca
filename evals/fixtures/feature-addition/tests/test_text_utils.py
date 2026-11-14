from text_utils import slugify


def test_slugify_normalizes_spaces_and_punctuation():
    assert slugify("  Hello, World!  ") == "hello-world"


def test_slugify_removes_edge_hyphens():
    assert slugify("---Next Orca---") == "next-orca"
