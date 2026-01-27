"""SST artifact types.

All persisted confidences are stored as integer basis points (0..10000)
to remain compatible with canonical JSON hashing rules that forbid floats.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


BBox = tuple[int, int, int, int]
ConfidenceBP = int


@dataclass(frozen=True)
class FrameRef:
    frame_id: str
    ts_ms: int
    width: int
    height: int
    image_sha256: str
    phash: str


@dataclass(frozen=True)
class TextToken:
    token_id: str
    text: str
    norm_text: str
    bbox: BBox
    confidence_bp: ConfidenceBP
    line_id: str | None = None
    block_id: str | None = None
    source: str = "ocr"
    flags: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UIElement:
    element_id: str
    type: str
    bbox: BBox
    text_refs: tuple[str, ...]
    label: str | None
    interactable: bool
    state: Mapping[str, bool]
    parent_id: str | None
    children_ids: tuple[str, ...]
    z: int
    app_hint: str | None = None


@dataclass(frozen=True)
class ElementEdge:
    src: str
    dst: str
    kind: str


@dataclass(frozen=True)
class ElementGraph:
    state_id: str
    elements: tuple[UIElement, ...]
    edges: tuple[ElementEdge, ...]


@dataclass(frozen=True)
class TextLine:
    line_id: str
    token_ids: tuple[str, ...]
    bbox: BBox
    text: str


@dataclass(frozen=True)
class TextBlock:
    block_id: str
    line_ids: tuple[str, ...]
    bbox: BBox
    text: str


@dataclass(frozen=True)
class TableCell:
    r: int
    c: int
    bbox: BBox
    text: str
    norm_text: str
    confidence_bp: ConfidenceBP


@dataclass(frozen=True)
class TableArtifact:
    table_id: str
    state_id: str
    bbox: BBox
    rows: int
    cols: int
    row_y: tuple[int, ...]
    col_x: tuple[int, ...]
    merges: tuple[Mapping[str, int], ...]
    cells: tuple[TableCell, ...]
    csv: str
    kind: str = "table"


@dataclass(frozen=True)
class SpreadsheetArtifact(TableArtifact):
    active_cell: Mapping[str, Any] | None = None
    formula_bar: Mapping[str, Any] | None = None
    headers: Mapping[str, Any] | None = None
    top_row_cells: tuple[TableCell, ...] = ()
    kind: str = "spreadsheet"


@dataclass(frozen=True)
class CodeBlock:
    code_id: str
    state_id: str
    bbox: BBox
    language: str
    text: str
    lines: tuple[str, ...]
    caret: Mapping[str, Any] | None
    selection: Mapping[str, Any] | None
    confidence_bp: ConfidenceBP


@dataclass(frozen=True)
class ChartArtifact:
    chart_id: str
    state_id: str
    bbox: BBox
    chart_type: str
    labels: tuple[str, ...]
    ticks_x: tuple[str, ...]
    ticks_y: tuple[str, ...]
    series: tuple[Mapping[str, Any], ...]
    evidence: Mapping[str, Any]
    confidence_bp: ConfidenceBP


@dataclass(frozen=True)
class CursorTrackPoint:
    bbox: BBox
    type: str
    confidence_bp: ConfidenceBP


@dataclass(frozen=True)
class ScreenState:
    state_id: str
    frame_id: str
    ts_ms: int
    phash: str
    width: int
    height: int
    tokens: tuple[TextToken, ...]
    element_graph: ElementGraph
    text_lines: tuple[TextLine, ...]
    text_blocks: tuple[TextBlock, ...]
    tables: tuple[TableArtifact, ...]
    spreadsheets: tuple[SpreadsheetArtifact, ...]
    code_blocks: tuple[CodeBlock, ...]
    charts: tuple[ChartArtifact, ...]
    cursor: CursorTrackPoint | None
    visible_apps: tuple[str, ...]
    focus_element_id: str | None
    state_confidence_bp: ConfidenceBP
    diagnostics: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class DeltaChange:
    kind: str
    target_id: str
    detail: Mapping[str, Any]


@dataclass(frozen=True)
class DeltaEvent:
    delta_id: str
    from_state_id: str
    to_state_id: str
    ts_ms: int
    changes: tuple[DeltaChange, ...]
    summary: Mapping[str, int]


@dataclass(frozen=True)
class ActionAlternative:
    kind: str
    target_element_id: str | None
    confidence_bp: ConfidenceBP
    evidence: Mapping[str, Any]


@dataclass(frozen=True)
class ActionImpact:
    created: bool
    modified: bool
    deleted: bool


@dataclass(frozen=True)
class ActionEvent:
    action_id: str
    from_state_id: str
    to_state_id: str
    ts_ms: int
    primary: ActionAlternative
    alternatives: tuple[ActionAlternative, ...]
    impact: ActionImpact


@dataclass(frozen=True)
class ArtifactEnvelope:
    artifact_id: str
    kind: str
    schema_version: int
    created_ts_ms: int
    extractor: Mapping[str, Any]
    provenance: Mapping[str, Any]
    confidence_bp: ConfidenceBP
    payload: Mapping[str, Any]

