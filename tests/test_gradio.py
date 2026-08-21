from src.gradio_app import extract_sources


def test_extract_sources_separates_obsidian_and_web():
    text = "[OBSIDIAN-1] notes/project.md\nSee https://example.com/docs and https://example.com/docs"
    result = extract_sources(text)
    assert "Источники Obsidian" in result
    assert "notes/project.md" in result
    assert result.count("https://example.com/docs") == 1
