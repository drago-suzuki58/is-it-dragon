from is_it_dragon.apps.lab import expand_inputs


def test_expand_inputs_lists_images_in_directory(tmp_path):
    for name in ("b.png", "a.JPG", "notes.txt"):
        (tmp_path / name).write_bytes(b"")
    (tmp_path / "sub").mkdir()
    url = "https://example.com/x.png"
    assert expand_inputs([str(tmp_path), url, "missing.png"]) == [
        str(tmp_path / "a.JPG"),
        str(tmp_path / "b.png"),
        url,
        "missing.png",
    ]
