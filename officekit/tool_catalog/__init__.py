"""Per-slice tool catalogue slots merged into ``engine_comms.TOOL_REGISTRY``.

Each slice module exports ``TOOLS`` (registry records) and ``KEYWORDS``
(search aliases keyed by tool id). Slices edit only their own module, so
parallel branches never touch the shared registry literal.
"""

from officekit.tool_catalog import calculators, developer, files, image, pdf_tools, invoices

SLICES = (calculators, developer, files, image, pdf_tools, invoices)


def slice_tools():
    return [tool for module in SLICES for tool in module.TOOLS]


def slice_keywords():
    keywords = {}
    for module in SLICES:
        keywords.update(module.KEYWORDS)
    return keywords
