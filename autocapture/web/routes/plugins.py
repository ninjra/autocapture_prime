"""Plugins route."""

from __future__ import annotations

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from autocapture.web.auth import check_request_token

router = APIRouter()


class ReloadRequest(BaseModel):
    plugin_ids: list[str] | None = None


class SettingsPatch(BaseModel):
    patch: dict


class InstallRequest(BaseModel):
    path: str
    dry_run: bool = True


class ApprovePermissionsRequest(BaseModel):
    accept_digest: str
    confirm: str = ""


class QuarantineRequest(BaseModel):
    reason: str


class LockSnapshotRequest(BaseModel):
    reason: str


class LockRollbackRequest(BaseModel):
    snapshot_path: str


class LockDiffRequest(BaseModel):
    a_path: str
    b_path: str


class LockUpdateRequest(BaseModel):
    plugin_id: str
    reason: str = "update"


class ApplyPlanRequest(BaseModel):
    plan_hash: str
    enable: list[str] | None = None
    disable: list[str] | None = None


@router.get("/api/plugins")
def list_plugins(request: Request):
    return request.app.state.facade.plugins_list()


@router.get("/api/plugins/timing")
def plugins_timing(request: Request):
    return request.app.state.facade.plugins_timing()


@router.get("/api/plugins/plan")
def plugins_plan(request: Request):
    return request.app.state.facade.plugins_plan()

@router.post("/api/plugins/apply")
def plugins_apply(req: ApplyPlanRequest, request: Request):
    return request.app.state.facade.plugins_apply(req.plan_hash, enable=req.enable, disable=req.disable)


@router.get("/api/plugins/capabilities")
def plugins_capabilities_matrix(request: Request):
    return request.app.state.facade.plugins_capabilities_matrix()


@router.post("/api/plugins/install")
def plugins_install(req: InstallRequest, request: Request):
    return request.app.state.facade.plugins_install_local(req.path, dry_run=bool(req.dry_run))


@router.post("/api/plugins/lock/snapshot")
def plugins_lock_snapshot(req: LockSnapshotRequest, request: Request):
    return request.app.state.facade.plugins_lock_snapshot(req.reason)


@router.post("/api/plugins/lock/rollback")
def plugins_lock_rollback(req: LockRollbackRequest, request: Request):
    return request.app.state.facade.plugins_lock_rollback(req.snapshot_path)

@router.post("/api/plugins/lock/diff")
def plugins_lock_diff(req: LockDiffRequest, request: Request):
    return request.app.state.facade.plugins_lock_diff(req.a_path, req.b_path)

@router.post("/api/plugins/lock/update")
def plugins_lock_update(req: LockUpdateRequest, request: Request):
    return request.app.state.facade.plugins_update_lock(req.plugin_id, reason=req.reason)


@router.post("/api/plugins/approve")
def approve_plugins(request: Request):
    return request.app.state.facade.plugins_approve()


@router.post("/api/plugins/reload")
def reload_plugins(req: ReloadRequest, request: Request):
    return request.app.state.facade.plugins_reload(plugin_ids=req.plugin_ids)


@router.post("/api/plugins/{plugin_id}/enable")
def plugin_enable(plugin_id: str, request: Request):
    request.app.state.facade.plugins_enable(plugin_id)
    return {"ok": True}


@router.post("/api/plugins/{plugin_id}/disable")
def plugin_disable(plugin_id: str, request: Request):
    request.app.state.facade.plugins_disable(plugin_id)
    return {"ok": True}


@router.get("/api/plugins/{plugin_id}/lifecycle")
def plugin_lifecycle(plugin_id: str, request: Request):
    return request.app.state.facade.plugins_lifecycle_state(plugin_id)


@router.get("/api/plugins/{plugin_id}/permissions")
def plugin_permissions(plugin_id: str, request: Request):
    return request.app.state.facade.plugins_permissions_digest(plugin_id)


@router.post("/api/plugins/{plugin_id}/permissions/approve")
def plugin_permissions_approve(plugin_id: str, req: ApprovePermissionsRequest, request: Request):
    return request.app.state.facade.plugins_approve_permissions(plugin_id, req.accept_digest, confirm=req.confirm)


@router.post("/api/plugins/{plugin_id}/quarantine")
def plugin_quarantine(plugin_id: str, req: QuarantineRequest, request: Request):
    return request.app.state.facade.plugins_quarantine(plugin_id, req.reason)


@router.post("/api/plugins/{plugin_id}/unquarantine")
def plugin_unquarantine(plugin_id: str, request: Request):
    return request.app.state.facade.plugins_unquarantine(plugin_id)


@router.get("/api/plugins/{plugin_id}/logs")
def plugin_logs(plugin_id: str, request: Request, limit: int = 80):
    # EXT-09: logs are sensitive; require local token even for GET.
    if not check_request_token(request, request.app.state.facade.config):
        raise HTTPException(status_code=401, detail="token_required")
    return request.app.state.facade.plugins_logs(plugin_id, limit=limit)


@router.get("/api/plugins/{plugin_id}/settings")
def plugin_settings_get(plugin_id: str, request: Request):
    return request.app.state.facade.plugins_settings_get(plugin_id)


@router.post("/api/plugins/{plugin_id}/settings")
def plugin_settings_set(plugin_id: str, req: SettingsPatch, request: Request):
    return request.app.state.facade.plugins_settings_set(plugin_id, req.patch)
