import re

_ANSI_ESCAPE_PATTERN = re.compile(r'(?:[@-Z\-_]|\[[0-?]*[ -/]*[@-~])')

def strip_ansi_codes(text: str) -> str:
    """Zero-dependency ANSI stripper replacing strip-ansi."""
    if not text:
        return text
    return _ANSI_ESCAPE_PATTERN.sub('', text)
