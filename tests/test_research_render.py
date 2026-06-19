from pathlib import Path

from weather_markets.research_render import (
    html_path_for,
    main,
    render_markdown,
)


def test_render_produces_self_contained_html():
    html = render_markdown("# My Title\n\nSome **bold** text.\n", title="My Title")
    assert "<!DOCTYPE html>" in html
    assert "<style>" in html                 # CSS embedded inline
    assert 'rel="stylesheet"' not in html    # never links external CSS
    assert "<script" not in html             # no JS
    assert "<title>My Title</title>" in html
    assert "<strong>bold</strong>" in html


def test_render_supports_tables():
    html = render_markdown("| a | b |\n| - | - |\n| 1 | 2 |\n", title="t")
    assert "<table>" in html
    assert "<td>1</td>" in html


def test_html_path_maps_md_dir_to_html_dir():
    md_path = Path("docs/research/md/2026-06-19-foo.md")
    assert html_path_for(md_path) == Path("docs/research/html/2026-06-19-foo.html")


def test_main_writes_html_using_h1_as_title(tmp_path):
    md_dir = tmp_path / "docs" / "research" / "md"
    md_dir.mkdir(parents=True)
    md_file = md_dir / "2026-06-19-sample.md"
    md_file.write_text("# Sample Paper\n\nbody\n", encoding="utf-8")

    rc = main(["render_research.py", str(md_file)])

    assert rc == 0
    out = tmp_path / "docs" / "research" / "html" / "2026-06-19-sample.html"
    assert out.exists()
    assert "<title>Sample Paper</title>" in out.read_text(encoding="utf-8")
