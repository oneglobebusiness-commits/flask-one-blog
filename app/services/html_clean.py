import nh3

TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "strong", "b", "em", "i", "u", "s", "ul", "ol", "li",
    "blockquote", "table", "thead", "tbody", "tfoot", "tr", "th", "td", "a", "br", "hr", "div",
    "span", "img", "pre", "code",
}
ATTRIBUTES = {
    "*": {"style", "class", "title", "align"},
    "a": {"href", "target"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}


def clean_html(html):
    """Remove scripts, event handlers and unsafe URLs while keeping blog formatting."""
    if not html:
        return html or ""
    return nh3.clean(html, tags=TAGS, attributes=ATTRIBUTES, url_schemes={"http", "https", "mailto"})
