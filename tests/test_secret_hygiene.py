from pathlib import Path
import re


def test_no_secret_artifacts_or_token_literals():
    root = Path(__file__).parents[1]
    names = {p.name for p in root.rglob("*") if p.is_file()}
    assert "credentials.json" not in names
    for path in [*root.joinpath("src").rglob("*.py"), *root.joinpath("tests").rglob("*.py")]:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\b\d{4,}~[A-Za-z0-9]{30,}\b", text)
        assert "Authorization:" + " Bearer" not in text
