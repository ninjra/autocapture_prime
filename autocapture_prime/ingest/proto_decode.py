from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from google.protobuf import descriptor_pb2
from google.protobuf import descriptor_pool
from google.protobuf import message_factory


def _add_field(
    msg: descriptor_pb2.DescriptorProto,
    *,
    name: str,
    number: int,
    label: int,
    field_type: int,
    type_name: str = "",
) -> None:
    field = msg.field.add()
    field.name = name
    field.number = number
    field.label = label
    field.type = field_type
    if type_name:
        field.type_name = type_name


@dataclass(frozen=True)
class ChronicleMessages:
    FrameMetaBatch: type
    InputEventBatch: type
    DetectionBatch: type


@lru_cache(maxsize=1)
def _messages() -> ChronicleMessages:
    fdp = descriptor_pb2.FileDescriptorProto()
    fdp.name = "chronicle_v0_minimal.proto"
    fdp.package = "chronicle.v0"
    fdp.syntax = "proto3"

    rect = fdp.message_type.add()
    rect.name = "RectI32"
    _add_field(rect, name="x", number=1, label=1, field_type=5)
    _add_field(rect, name="y", number=2, label=1, field_type=5)
    _add_field(rect, name="w", number=3, label=1, field_type=5)
    _add_field(rect, name="h", number=4, label=1, field_type=5)

    frame = fdp.message_type.add()
    frame.name = "FrameMeta"
    _add_field(frame, name="session_id", number=1, label=1, field_type=9)
    _add_field(frame, name="frame_index", number=2, label=1, field_type=4)
    _add_field(frame, name="qpc_ticks", number=3, label=1, field_type=3)
    _add_field(frame, name="unix_ns", number=4, label=1, field_type=3)
    _add_field(frame, name="width", number=5, label=1, field_type=13)
    _add_field(frame, name="height", number=6, label=1, field_type=13)
    _add_field(frame, name="desktop_rect", number=8, label=1, field_type=11, type_name=".chronicle.v0.RectI32")
    _add_field(frame, name="dirty_rects", number=9, label=3, field_type=11, type_name=".chronicle.v0.RectI32")
    _add_field(frame, name="artifact_path", number=11, label=1, field_type=9)

    frame_batch = fdp.message_type.add()
    frame_batch.name = "FrameMetaBatch"
    _add_field(
        frame_batch,
        name="items",
        number=1,
        label=3,
        field_type=11,
        type_name=".chronicle.v0.FrameMeta",
    )

    mouse = fdp.message_type.add()
    mouse.name = "MouseEvent"
    _add_field(mouse, name="x", number=1, label=1, field_type=5)
    _add_field(mouse, name="y", number=2, label=1, field_type=5)
    _add_field(mouse, name="delta_x", number=3, label=1, field_type=5)
    _add_field(mouse, name="delta_y", number=4, label=1, field_type=5)
    _add_field(mouse, name="buttons", number=5, label=1, field_type=13)
    _add_field(mouse, name="wheel_delta", number=6, label=1, field_type=5)

    control = fdp.message_type.add()
    control.name = "ControlEvent"
    _add_field(control, name="action", number=1, label=1, field_type=9)
    _add_field(control, name="payload_json", number=2, label=1, field_type=9)

    hid = fdp.message_type.add()
    hid.name = "GenericHidEvent"
    _add_field(hid, name="usage_page", number=1, label=1, field_type=13)
    _add_field(hid, name="usage", number=2, label=1, field_type=13)
    _add_field(hid, name="payload", number=3, label=1, field_type=12)

    input_msg = fdp.message_type.add()
    input_msg.name = "InputEvent"
    _add_field(input_msg, name="session_id", number=1, label=1, field_type=9)
    _add_field(input_msg, name="event_index", number=2, label=1, field_type=4)
    _add_field(input_msg, name="qpc_ticks", number=3, label=1, field_type=3)
    _add_field(input_msg, name="unix_ns", number=4, label=1, field_type=3)
    _add_field(input_msg, name="device_id", number=5, label=1, field_type=9)
    _add_field(input_msg, name="type", number=6, label=1, field_type=14, type_name=".chronicle.v0.InputEventType")
    _add_field(input_msg, name="mouse", number=10, label=1, field_type=11, type_name=".chronicle.v0.MouseEvent")
    _add_field(input_msg, name="control", number=11, label=1, field_type=11, type_name=".chronicle.v0.ControlEvent")
    _add_field(input_msg, name="generic_hid", number=12, label=1, field_type=11, type_name=".chronicle.v0.GenericHidEvent")

    input_batch = fdp.message_type.add()
    input_batch.name = "InputEventBatch"
    _add_field(input_batch, name="items", number=1, label=3, field_type=11, type_name=".chronicle.v0.InputEvent")

    enum_input = fdp.enum_type.add()
    enum_input.name = "InputEventType"
    for idx, name in enumerate(["INPUT_EVENT_UNSPECIFIED", "MOUSE", "CONTROL", "GENERIC_HID"]):
        value = enum_input.value.add()
        value.name = name
        value.number = idx

    element = fdp.message_type.add()
    element.name = "UiElement"
    _add_field(element, name="element_id", number=1, label=1, field_type=9)
    _add_field(element, name="type", number=2, label=1, field_type=14, type_name=".chronicle.v0.UiElementType")
    _add_field(element, name="bbox", number=3, label=1, field_type=11, type_name=".chronicle.v0.RectI32")
    _add_field(element, name="confidence", number=4, label=1, field_type=2)
    _add_field(element, name="label", number=5, label=1, field_type=9)
    _add_field(element, name="text", number=6, label=1, field_type=9)
    _add_field(element, name="parent_id", number=7, label=1, field_type=9)

    enum_elem = fdp.enum_type.add()
    enum_elem.name = "UiElementType"
    for idx, name in enumerate(["UI_ELEMENT_UNSPECIFIED", "WINDOW", "PANE", "TAB", "BUTTON", "TEXT", "ICON", "INPUT"]):
        value = enum_elem.value.add()
        value.name = name
        value.number = idx

    detection_frame = fdp.message_type.add()
    detection_frame.name = "DetectionFrame"
    _add_field(detection_frame, name="session_id", number=1, label=1, field_type=9)
    _add_field(detection_frame, name="frame_index", number=2, label=1, field_type=4)
    _add_field(detection_frame, name="qpc_ticks", number=3, label=1, field_type=3)
    _add_field(
        detection_frame,
        name="elements",
        number=4,
        label=3,
        field_type=11,
        type_name=".chronicle.v0.UiElement",
    )

    detection_batch = fdp.message_type.add()
    detection_batch.name = "DetectionBatch"
    _add_field(
        detection_batch,
        name="items",
        number=1,
        label=3,
        field_type=11,
        type_name=".chronicle.v0.DetectionFrame",
    )

    pool = descriptor_pool.DescriptorPool()
    pool.Add(fdp)
    frame_desc = pool.FindMessageTypeByName("chronicle.v0.FrameMetaBatch")
    input_desc = pool.FindMessageTypeByName("chronicle.v0.InputEventBatch")
    detection_desc = pool.FindMessageTypeByName("chronicle.v0.DetectionBatch")
    if hasattr(message_factory, "GetMessageClass"):
        frame_batch_cls = message_factory.GetMessageClass(frame_desc)
        input_batch_cls = message_factory.GetMessageClass(input_desc)
        detection_batch_cls = message_factory.GetMessageClass(detection_desc)
    else:
        factory = message_factory.MessageFactory(pool)
        frame_batch_cls = factory.GetPrototype(frame_desc)
        input_batch_cls = factory.GetPrototype(input_desc)
        detection_batch_cls = factory.GetPrototype(detection_desc)
    return ChronicleMessages(
        FrameMetaBatch=frame_batch_cls,
        InputEventBatch=input_batch_cls,
        DetectionBatch=detection_batch_cls,
    )


def message_classes() -> ChronicleMessages:
    return _messages()


def parse_batch_bytes(kind: str, payload: bytes) -> list[dict[str, Any]]:
    kind_norm = str(kind).strip().lower()
    messages = _messages()
    if kind_norm == "frames":
        batch = messages.FrameMetaBatch()
        batch.ParseFromString(payload)
        return [_frame_to_dict(item) for item in batch.items]
    if kind_norm == "input":
        batch = messages.InputEventBatch()
        batch.ParseFromString(payload)
        return [_input_to_dict(item) for item in batch.items]
    if kind_norm == "detections":
        batch = messages.DetectionBatch()
        batch.ParseFromString(payload)
        return [_detection_to_dict(item) for item in batch.items]
    raise ValueError(f"unknown batch kind: {kind}")


def _frame_to_dict(item: Any) -> dict[str, Any]:
    out = {
        "session_id": str(getattr(item, "session_id", "") or ""),
        "frame_index": int(getattr(item, "frame_index", 0) or 0),
        "qpc_ticks": int(getattr(item, "qpc_ticks", 0) or 0),
        "unix_ns": int(getattr(item, "unix_ns", 0) or 0),
        "width": int(getattr(item, "width", 0) or 0),
        "height": int(getattr(item, "height", 0) or 0),
        "artifact_path": str(getattr(item, "artifact_path", "") or ""),
    }
    if hasattr(item, "desktop_rect") and item.HasField("desktop_rect"):
        rect = item.desktop_rect
        out["desktop_rect"] = {"x": int(rect.x), "y": int(rect.y), "w": int(rect.w), "h": int(rect.h)}
    dirty_rects: list[dict[str, int]] = []
    for rect in getattr(item, "dirty_rects", []):
        dirty_rects.append({"x": int(rect.x), "y": int(rect.y), "w": int(rect.w), "h": int(rect.h)})
    if dirty_rects:
        out["dirty_rects"] = dirty_rects
    return out


def _input_to_dict(item: Any) -> dict[str, Any]:
    out = {
        "session_id": str(getattr(item, "session_id", "") or ""),
        "event_index": int(getattr(item, "event_index", 0) or 0),
        "qpc_ticks": int(getattr(item, "qpc_ticks", 0) or 0),
        "unix_ns": int(getattr(item, "unix_ns", 0) or 0),
        "device_id": str(getattr(item, "device_id", "") or ""),
        "type": int(getattr(item, "type", 0) or 0),
    }
    if item.HasField("mouse"):
        mouse = item.mouse
        out["mouse"] = {
            "x": int(mouse.x),
            "y": int(mouse.y),
            "delta_x": int(getattr(mouse, "delta_x", 0)),
            "delta_y": int(getattr(mouse, "delta_y", 0)),
            "buttons": int(mouse.buttons),
            "wheel_delta": int(mouse.wheel_delta),
        }
    if item.HasField("control"):
        control = item.control
        out["control"] = {"action": str(control.action), "payload_json": str(control.payload_json)}
    if item.HasField("generic_hid"):
        hid = item.generic_hid
        out["generic_hid"] = {
            "usage_page": int(hid.usage_page),
            "usage": int(hid.usage),
            "payload": bytes(hid.payload).hex(),
        }
    return out


def _detection_to_dict(item: Any) -> dict[str, Any]:
    out = {
        "session_id": str(getattr(item, "session_id", "") or ""),
        "frame_index": int(getattr(item, "frame_index", 0) or 0),
        "qpc_ticks": int(getattr(item, "qpc_ticks", 0) or 0),
        "elements": [],
    }
    for elem in getattr(item, "elements", []):
        row = {
            "element_id": str(elem.element_id),
            "type": int(elem.type),
            "confidence": float(elem.confidence),
            "label": str(elem.label),
            "text": str(elem.text),
            "parent_id": str(elem.parent_id),
        }
        if elem.HasField("bbox"):
            row["bbox"] = {"x": int(elem.bbox.x), "y": int(elem.bbox.y), "w": int(elem.bbox.w), "h": int(elem.bbox.h)}
        out["elements"].append(row)
    return out
