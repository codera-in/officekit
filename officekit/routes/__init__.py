"""Per-slice API router slots mounted by ``app.py``.

Each slice module exports ``router`` (an ``APIRouter``), ``BODY_LIMITS``
(pre-parse body caps keyed by path pattern) and ``EXPOSE_HEADERS`` (custom
response headers the UI reads). Slices edit only their own module.
"""

from officekit.routes import calculators, developer, files, image, pdf_tools

SLICES = (calculators, developer, files, image, pdf_tools)


def slice_routers():
    return [module.router for module in SLICES]


def merge_body_limits(base, extra):
    overlap = base.keys() & extra.keys()
    if overlap:
        raise ValueError(f"duplicate body limit paths: {sorted(overlap)}")
    return {**base, **extra}


def slice_body_limits():
    limits = {}
    for module in SLICES:
        limits = merge_body_limits(limits, module.BODY_LIMITS)
    return limits


def slice_expose_headers():
    return [header for module in SLICES for header in module.EXPOSE_HEADERS]
