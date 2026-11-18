"""Turn listing HTML into readable text before any agent analyses it."""

import html
import re

from bs4 import BeautifulSoup


def plain_text(value: str | None) -> str:
    """Remove markup, preserve inline sentences, and separate paragraphs and lists."""
    value = value or ""
    # Some feeds escape their HTML more than once.
    for _ in range(3):
        decoded = html.unescape(value)
        if decoded == value:
            break
        value = decoded
    if not re.search(r"</?(?:p|br|div|span|strong|em|b|i|ul|ol|li|a|section|article|main|body|h[1-6]|script|style)\b[^>]*>", value, re.I):
        return "\n".join(line.strip() for line in value.splitlines() if line.strip())
    soup = BeautifulSoup(value, "html.parser")
    for tag in soup.select("script, style, nav, footer, header, aside, noscript, form"):
        tag.decompose()
    for tag in soup.find_all("br"):
        tag.replace_with("\n")
    for tag in soup.find_all(["p", "div", "li", "ul", "ol", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6"]):
        tag.insert_before("\n")
        tag.insert_after("\n")
    return "\n".join(line.strip() for line in soup.get_text().splitlines() if line.strip())
