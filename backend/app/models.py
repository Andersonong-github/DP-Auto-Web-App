"""Request / response schemas."""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    base_url: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Deltapath PBX host, e.g. suc.digitalwave.net.my or 192.168.1.10",
        examples=["suc.digitalwave.net.my"],
    )
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=512)
    tls_verify: Optional[bool] = Field(
        default=None,
        description="Override certificate verification for this login only.",
    )


class SessionResponse(BaseModel):
    authenticated: bool
    baseUrl: Optional[str] = None
    username: Optional[str] = None
    loginMode: Optional[str] = None
    createdAt: Optional[float] = None
    lastSeen: Optional[float] = None
    ageSeconds: Optional[int] = None
    idleSeconds: Optional[int] = None
    idleTimeoutSeconds: Optional[int] = None
    absoluteTimeoutSeconds: Optional[int] = None


class ProbeResult(BaseModel):
    label: str
    endpoint: str
    ok: bool
    statusCode: Optional[int] = None
    latencyMs: Optional[int] = None
    rows: Optional[int] = None
    detail: str = ""


class ProbeResponse(BaseModel):
    baseUrl: str
    ok: bool
    checkedAt: float
    results: List[ProbeResult]


class HealthResponse(BaseModel):
    status: str
    name: str
    version: str
    time: float
    activeSessions: int


class PublicConfig(BaseModel):
    appName: str
    version: str
    defaultBaseUrl: str
    sessionIdleMinutes: int
    tlsVerifyDefault: bool
    tasks: List[dict]


# --------------------------------------------------------------- Pipeline execution
class PipelineParams(BaseModel):
    """Shared parameter set for Standard and Complex modes (key names match the desktop session)."""

    group_name: str = Field(default="", max_length=200)
    group_code: str = Field(default="", max_length=200)
    unified_limit: str = Field(default="10", max_length=10)
    host_ip: str = Field(default="", max_length=255)
    port: str = Field(default="5060", max_length=10)
    context_prefix: str = Field(default="", max_length=60)
    perm_group_prefix: str = Field(default="", max_length=60)
    inbound_ranges: str = Field(default="", max_length=2000)
    user_ext: str = Field(default="", max_length=2000)
    htek_model: str = Field(default="uc902g", max_length=40)
    htek_mac_data: List[dict] = Field(default_factory=list)
    custom_number: str = Field(default="", max_length=64)
    custom_routing_mode: bool = False
    custom_context: str = Field(default="", max_length=64)
    number_strip_context: str = Field(default="", max_length=120)
    usernames: List[str] = Field(default_factory=list)
    emails: List[str] = Field(default_factory=list)
    acl_managers: str = Field(default="", max_length=2000)
    acl_supervisors: str = Field(default="", max_length=2000)
    acl_users: str = Field(default="", max_length=2000)

    # ---- Complex mode only (stage 3) ----
    context_suffixes: Optional[List[str]] = Field(
        default=None,
        description="Context suffixes to create for the Context task, e.g. _Internal/_Fixed/_Mobile/_IDD or custom.",
    )
    pg_spec: Optional[dict] = Field(
        default=None,
        description=(
            'Permission Group spec: '
            '{"classes":[{"class":1,"source_class":1,"enabled":true,"key":"c_i","ctx":[]}]}. '
            'A non-empty "ctx" lists the exact context names to include (in order) and overrides "key".'
        ),
    )
    pg_server_data: Optional[dict] = Field(default=None, description="Server context data needed by the Permission Group dropdown.")
    pg_lead: str = Field(
        default="",
        max_length=200,
        description=(
            "Context forced to position 1 of every Permission Group Class "
            "(the Complex page's “Add context in front of every Class” dropdown)."
        ),
    )
    acl_group_selection: Optional[List[str]] = Field(default=None, description='ACL Groups to create, e.g. ["_Managers","_Users"].')
    profile_classes_selection: Optional[List[str]] = Field(
        default=None,
        description='User Profile classes to create, e.g. ["Class_1","Class_3"].',
    )
    profile_recording: bool = False
    profile_number_context: str = Field(default="", max_length=120)


class PipelineRunRequest(BaseModel):
    mode: Literal["standard", "complex"] = "standard"
    tasks: List[str] = Field(
        default_factory=list,
        description="UI task names to run; empty runs all tasks in this mode.",
    )
    params: PipelineParams = Field(default_factory=PipelineParams)
    custom_payloads: Dict[str, str] = Field(
        default_factory=dict,
        description="Override/merge the default API payload per UI task name (JSON string).",
    )


class PipelineTaskState(BaseModel):
    name: str
    status: int
    startedAt: Optional[float] = None
    finishedAt: Optional[float] = None


class PipelineProgress(BaseModel):
    total: int
    done: int
    success: int
    error: int
    current: Optional[str] = None


class PipelineRunSnapshot(BaseModel):
    id: str
    mode: str
    status: str
    createdAt: float
    finishedAt: Optional[float] = None
    customerId: str = ""
    tasks: List[PipelineTaskState]
    records: List[dict]
    progress: PipelineProgress
    lastSeq: int
    droppedEvents: int
