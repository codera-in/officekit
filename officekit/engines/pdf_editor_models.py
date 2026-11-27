"""Strict, bounded input contracts for the local PDF workspace."""
from typing import Annotated, Literal
import math

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Operation(StrictModel):
    kind: Literal['replace_text', 'image_change', 'add_text', 'add_image', 'annotation', 'apply_ocr']
    page: int = Field(ge=1, le=2000)
    rect: list[float] | None = Field(default=None, min_length=4, max_length=4)
    object_id: str | None = Field(default=None, max_length=100)
    review_id: str | None = Field(default=None, max_length=100)
    region_id: str | None = Field(default=None, max_length=100)
    text: str = Field(default='', max_length=100000)
    font: Literal['Helvetica', 'Times-Roman', 'Courier'] = 'Helvetica'
    font_size: float = Field(default=12, ge=1, le=300, allow_inf_nan=False)
    color: str = Field(default='#000000', pattern=r'^#[0-9a-fA-F]{6}$')
    outer_color: str = Field(default='#ffffff', pattern=r'^#[0-9a-fA-F]{6}$')
    outer_width: float = Field(default=0, ge=0, le=30, allow_inf_nan=False)
    stroke_width: float = Field(default=2, ge=.1, le=30, allow_inf_nan=False)
    annotation_type: Literal['text', 'highlight', 'rectangle', 'circle', 'freehand', 'line', 'arrow', 'callout', 'signature'] = 'text'
    points: list[list[float]] = Field(default_factory=list, max_length=10000)
    image_base64: str | None = Field(default=None, max_length=24000000)
    action: Literal['move', 'delete', 'replace', 'rotate', 'crop'] = 'move'
    image_crop: list[int] | None = Field(default=None, min_length=4, max_length=4)
    rotation_delta: Literal[90, 180, 270] = 90
    ocr_mode: Literal['searchable', 'reconstruction'] = 'searchable'

    @model_validator(mode='after')
    def replacement_font(self):
        if self.kind == 'replace_text' and 'font' not in self.model_fields_set:
            raise ValueError('Choose an explicit replacement font.')
        return self

    @field_validator('text')
    @classmethod
    def valid_text(cls, value):
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError('Place each text line separately; control characters are unsupported.')
        return value

    @field_validator('rect')
    @classmethod
    def valid_rect(cls, value):
        if value is not None and (not all(math.isfinite(x) for x in value)
                or value[2] <= value[0] or value[3] <= value[1]):
            raise ValueError('Rectangle must be finite with positive dimensions.')
        return value

    @field_validator('points')
    @classmethod
    def valid_points(cls, value):
        if any(len(point) != 2 or not all(math.isfinite(x) for x in point) for point in value):
            raise ValueError('Points must contain finite coordinate pairs.')
        return value


class RevisionCreate(StrictModel):
    base_revision: int = Field(ge=0)
    operations: list[Operation] = Field(min_length=1, max_length=1000)

    @model_validator(mode='after')
    def text_budget(self):
        if sum(len(op.text) for op in self.operations) > 100000:
            raise ValueError('Revision text limit exceeded.')
        return self


class OcrCreate(StrictModel):
    base_revision: int = Field(ge=0)
    pages: list[int] = Field(min_length=1, max_length=20)
    language: str = Field(default='eng', pattern=r'^[a-z]{3}(\+[a-z]{3})*$' , max_length=60)
    mode: Literal['searchable', 'reconstruction'] = 'searchable'

    @field_validator('pages')
    @classmethod
    def valid_pages(cls, value):
        if len(set(value)) != len(value) or any(page < 1 or page > 2000 for page in value):
            raise ValueError('Pages must be unique and between 1 and 2000.')
        return value
