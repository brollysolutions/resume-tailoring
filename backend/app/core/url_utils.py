from typing import Optional

def normalize_url(value: Optional[str]) -> Optional[str]:
    """Normalize a possibly-bare URL for href use.
    - None / null-sentinels -> None.
    - Strip leading 'mailto:' (we render email separately).
    - If already has scheme (http:// or https://), return unchanged.
    - If looks like a domain (contains '.' and no spaces), prepend 'https://'.
    - Else return raw stripped value (e.g. 'in/john-doe' shorthand).
    """
    if value is None:
        return None
    
    val = value.strip()
    if not val:
        return None

    # Drop dangerous URL schemes outright — these fields are rendered as href
    # attributes (HTML preview) and DOCX hyperlink relationships.
    if val.lower().startswith(("javascript:", "data:", "vbscript:", "file:")):
        return None

    # Remove mailto: if LLM extracted it into a web/linkedin field
    if val.lower().startswith("mailto:"):
        val = val[7:].strip()
        
    if not val:
        return None

    # Check for existing scheme
    if val.lower().startswith(("http://", "https://")):
        return val

    # If it looks like a domain (has . and no spaces)
    if "." in val and " " not in val:
        return f"https://{val}"

    return val
