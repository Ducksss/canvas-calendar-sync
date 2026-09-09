from pathlib import Path


def test_no_secret_artifacts_or_token_literals():
    root = Path(__file__).parents[1]
    names = {p.name for p in root.rglob("*") if p.is_file()}
    assert "credentials.json" not in names
    for path in [*root.joinpath("src").rglob("*.py"), *root.joinpath("tests").rglob("*.py")]:
        text = path.read_text(encoding="utf-8")
        assert "214" + "50~" not in text
        assert "Authorization:" + " Bearer" not in text
