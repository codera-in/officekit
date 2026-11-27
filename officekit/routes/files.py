"""Files slice routes (track B restore and any non-job endpoints)."""

from fastapi import APIRouter

router = APIRouter()

BODY_LIMITS = {}

EXPOSE_HEADERS = ()
