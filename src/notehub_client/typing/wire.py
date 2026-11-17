"""Typed Notehub wire records and response envelopes."""

from __future__ import annotations

from typing import Literal, NotRequired, TypeAlias, TypedDict

from .json import JSONObject


# Device and event records are intentionally permissive because fields vary by device and event.
class Device(TypedDict):
    """A device record returned by project and fleet endpoints.

    Device fields vary with hardware, firmware, and requested projections, so
    most values remain optional even when common responses usually include them.
    :seealso: https://dev.blues.io/api-reference/notehub-api/device-api/
    """

    best_id: NotRequired[str]
    best_location: NotRequired[Location]
    cellular_usage: NotRequired[CellularUsage]
    contact: NotRequired[Contact]
    dfu: NotRequired[DFUEnv]
    disabled: NotRequired[bool]
    firmware_host: NotRequired[str]
    firmware_notecard: NotRequired[str]
    fleet_uids: list[str]
    gps_location: NotRequired[Location]
    health_log: NotRequired[list[HealthLog]]
    last_activity: NotRequired[str]
    product_uid: str
    provisioned: str
    recent_event_count: NotRequired[list[int]]
    recent_session_count: NotRequired[list[int]]
    recent_session_seconds: NotRequired[list[int]]
    recent_when: NotRequired[str]
    sensors: NotRequired[DeviceSensors]
    serial_number: NotRequired[str]
    sku: NotRequired[str]
    tags: NotRequired[str]
    temperature: NotRequired[float]
    tower_info: NotRequired[JSONObject]
    tower_location: NotRequired[Location]
    triangulated_location: NotRequired[Location]
    uid: str
    voltage: NotRequired[float]


class Event(TypedDict):
    """An event record whose fields depend on its event type and Notefile.

    ``when`` is the event's captured time; ``received`` is the time Notehub
    received it. Either may be absent depending on the source record.
    :seealso: https://dev.blues.io/api-reference/notehub-api/event-api/
    """

    app: NotRequired[str]
    bars: NotRequired[int]
    best_country: NotRequired[str]
    best_id: NotRequired[str]
    best_lat: NotRequired[float]
    best_location: NotRequired[str]
    best_location_type: NotRequired[str]
    best_location_when: NotRequired[int]
    best_lon: NotRequired[float]
    best_timezone: NotRequired[str]
    body: NotRequired[JSONObject]
    bssid: NotRequired[str]
    device: NotRequired[str]
    environment: NotRequired[JSONObject]
    event: NotRequired[str]
    file: NotRequired[str]
    moved: NotRequired[int]
    note: NotRequired[str]
    ordering_code: NotRequired[str]
    orientation: NotRequired[str]
    payload: NotRequired[str]
    platform: NotRequired[bool]
    product: NotRequired[str]
    rat: NotRequired[str]
    received: NotRequired[float]
    req: NotRequired[str]
    rsrp: NotRequired[int]
    rsrq: NotRequired[int]
    rssi: NotRequired[int]
    sensor: NotRequired[str]
    session: NotRequired[str]
    sinr: NotRequired[int]
    sku: NotRequired[str]
    sn: NotRequired[str]
    ssid: NotRequired[str]
    temp: NotRequired[float]
    tls: NotRequired[bool]
    tower_country: NotRequired[str]
    tower_id: NotRequired[str]
    tower_lat: NotRequired[float]
    tower_location: NotRequired[str]
    tower_lon: NotRequired[float]
    tower_timezone: NotRequired[str]
    tower_when: NotRequired[int]
    transport: NotRequired[str]
    tri_country: NotRequired[str]
    tri_lat: NotRequired[float]
    tri_location: NotRequired[str]
    tri_lon: NotRequired[float]
    tri_points: NotRequired[int]
    tri_timezone: NotRequired[str]
    tri_when: NotRequired[int]
    updates: NotRequired[int]
    voltage: NotRequired[float]
    when: NotRequired[int]
    when_ms: NotRequired[int]
    where_country: NotRequired[str]
    where_lat: NotRequired[float]
    where_location: NotRequired[str]
    where_lon: NotRequired[float]
    where_olc: NotRequired[str]
    where_timezone: NotRequired[str]
    where_when: NotRequired[int]
    wire_length: NotRequired[int]


class Project(TypedDict):
    """Project metadata returned by Notehub project endpoints."""

    administrative_contact: NotRequired[Contact]
    created: str
    label: str
    role: NotRequired[Role]
    technical_contact: NotRequired[Contact]
    uid: str


class Fleet(TypedDict):
    """Fleet metadata and optional fleet-level configuration."""

    connectivity_assurance: NotRequired[FleetConnectivityAssurance]
    created: str
    environment_variables: NotRequired[dict[str, str]]
    label: str
    smart_rule: NotRequired[FleetRule]
    smart_rule_enabled: NotRequired[bool]
    uid: str
    watchdog_mins: NotRequired[int]


class Organization(TypedDict):
    """Organization identity and the authenticated user's organization role.

    :seealso: https://dev.blues.io/api-reference/notehub-api/organization-api/
    """

    name: str
    role: OrganizationRole
    uid: str


class BillingPlan(TypedDict):
    """Plan name, capacity, balance, and date fields when returned by Notehub."""

    current_balance: NotRequired[int]
    end_date: NotRequired[str]
    event_capacity: NotRequired[int]
    start_date: NotRequired[str]
    type: NotRequired[Literal["Enterprise", "Essentials"]]


class BillingAccount(TypedDict):
    """Legacy billing-account identity and role record.

    Prefer the organization API for current billing-account operations.
    :seealso: https://dev.blues.io/api-reference/notehub-api/billing-account-api/
    """

    name: str
    role: BillingAccountRole
    uid: str


class AccountDetails(TypedDict):
    """Optional account contact, plan, suspension, and ownership details."""

    contact_uid: NotRequired[str]
    email: NotRequired[str]
    name: NotRequired[str]
    owner: NotRequired[str]
    plan: NotRequired[BillingPlan]
    suspended: NotRequired[bool]
    uid: NotRequired[str]


OrganizationDetails: TypeAlias = AccountDetails
BillingAccountDetails: TypeAlias = AccountDetails


class BalanceHistoryEntry(TypedDict):
    """Event-capacity totals for one balance-history period."""

    period: str
    remaining_event_capacity: int
    total_event_capacity_used: int


class BalanceHistoryResponse(TypedDict):
    """Optional ``data`` collection returned by a balance-history request."""

    data: NotRequired[list[BalanceHistoryEntry]]


class BillingAccountsResponse(TypedDict):
    """Response envelope containing visible legacy billing accounts."""

    billing_accounts: NotRequired[list[BillingAccount]]


# Job, monitor, route, session, and usage records.
class Job(TypedDict):
    """Project job identity, creator, and most recent run status."""

    created: int
    created_by: str
    job_uid: str
    last_run_completed: NotRequired[int]
    last_run_status: NotRequired[str]
    last_run_submitted: NotRequired[int]
    name: str


class Monitor(TypedDict):
    """Monitor configuration and optional alert-routing details."""

    aggregate_function: NotRequired[Literal["none", "avg", "max", "min", "sum", "count"]]  # TODO: Might want to pull this literal up
    aggregate_window: NotRequired[str]
    alert: NotRequired[bool]
    alert_routes: NotRequired[
        list[SlackWebHookNotification | SlackBearerNotification | EmailNotification]  # TODO: Another possible pull up
    ]
    condition_type: NotRequired[
        Literal[  # TODO: Possible pull up
            "greater_than",
            "greater_than_or_equal_to",
            "less_than",
            "less_than_or_equal_to",
            "equal_to",
            "not_equal_to",
        ]
    ]
    description: NotRequired[str]
    disabled: NotRequired[bool]
    fleet_filter: NotRequired[list[str]]
    last_routed_at: NotRequired[str]
    name: NotRequired[str]
    notefile_filter: NotRequired[list[str]]
    per_device: NotRequired[bool]
    routing_cooldown_period: NotRequired[str]
    silenced: NotRequired[bool]
    source_selector: NotRequired[str]
    source_type: NotRequired[Literal["event", "heartbeat", "usage"]]  # TODO: Maybe pull up
    threshold: NotRequired[float]
    uid: NotRequired[str]
    usage_scope: NotRequired[str]
    usage_type: NotRequired[str]
    usage_window: NotRequired[int]


class NotehubRouteSummary(TypedDict):
    """Summary of a route configured for a Notehub project."""

    disabled: NotRequired[bool]
    label: NotRequired[str]
    modified: NotRequired[str]
    type: NotRequired[str]
    uid: NotRequired[str]


class DeviceSession(TypedDict):
    """A device connection session with optional radio, location, and usage data."""

    apn: NotRequired[str]
    bars: NotRequired[int]
    bearer: NotRequired[str]
    bssid: NotRequired[str]
    cell: NotRequired[str]
    continuous: NotRequired[bool]
    device: NotRequired[str]
    events: NotRequired[int]
    failed_connects: NotRequired[int]
    fleets: NotRequired[list[str]]
    hp_cycles_data: NotRequired[int]
    hp_cycles_gps: NotRequired[int]
    hp_cycles_total: NotRequired[int]
    hp_secs_data: NotRequired[int]
    hp_secs_gps: NotRequired[int]
    hp_secs_total: NotRequired[int]
    iccid: NotRequired[str]
    ip: NotRequired[str]
    moved: NotRequired[int]
    orientation: NotRequired[str]
    penalty_secs: NotRequired[int]
    period: NotRequired[DeviceUsage]
    power_charging: NotRequired[bool]
    power_mah: NotRequired[float]
    power_primary: NotRequired[bool]
    power_usb: NotRequired[bool]
    product: NotRequired[str]
    rat: NotRequired[str]
    rsrp: NotRequired[int]
    rsrq: NotRequired[int]
    rssi: NotRequired[int]
    scan: NotRequired[str]
    session: NotRequired[str]
    session_began: NotRequired[int]
    session_ended: NotRequired[int]
    sinr: NotRequired[int]
    sn: NotRequired[str]
    ssid: NotRequired[str]
    temp: NotRequired[float]
    tls: NotRequired[bool]
    tower: NotRequired[TowerLocation]
    transport: NotRequired[str]
    tri: NotRequired[TowerLocation]
    triangulate: NotRequired[JSONObject]
    usage_actual: NotRequired[bool]
    voltage: NotRequired[float]
    when: NotRequired[int]
    where: NotRequired[str]
    where_country: NotRequired[str]
    where_lat: NotRequired[float]
    where_location: NotRequired[str]
    where_lon: NotRequired[float]
    where_timezone: NotRequired[str]
    where_when: NotRequired[int]
    why_session_closed: NotRequired[str]
    why_session_opened: NotRequired[str]
    work: NotRequired[int]


class UsageApiData(TypedDict):
    """API request counts for one usage period and optional endpoint."""

    endpoint: NotRequired[str]
    method: NotRequired[str]
    period: str
    requests: int


# API envelopes retain documented pagination and optional response fields.
class FleetsResponse(TypedDict):
    """Response envelope containing the project's fleets."""

    fleets: list[Fleet]


class DevicesResponse(TypedDict):
    """Page of devices plus the indicator for another available page."""

    devices: list[Device]
    has_more: bool
    next_cursor: NotRequired[str]


class EventsResponse(TypedDict):
    """Page of events plus cursor and continuation metadata."""

    events: list[Event]
    has_more: bool
    through: NotRequired[str]
    next_cursor: NotRequired[str]


class GetJobsResponse(TypedDict):
    """Response envelope containing project jobs."""

    jobs: list[Job]


class SessionResponse(TypedDict):
    """Page of device sessions and the indicator for another available page."""

    has_more: bool
    sessions: list[DeviceSession]


class LatestResponse(TypedDict):
    """Optional collection of the latest events returned for a device."""

    latest_events: NotRequired[list[Event]]


class GetDeviceEnvironmentVariablesResponse(TypedDict):
    """Device environment-variable values at configured and effective scopes.

    ``environment_variables`` and ``environment_variables_env_default`` expose
    device values and environment defaults; ``environment_variables_effective``
    and ``environment_variable_notes`` are included when the endpoint provides them.
    """

    environment_variable_notes: NotRequired[dict[str, str]]
    environment_variables: dict[str, str]
    environment_variables_effective: NotRequired[dict[str, str]]
    environment_variables_env_default: dict[str, str]


class UsageApiResponse(TypedDict):
    """API usage collection and optional truncation indicator."""

    data: list[UsageApiData]
    truncated: NotRequired[UsageTruncatedField]


class OrganizationsResponse(TypedDict):
    """Optional organization collection returned by the list endpoint."""

    organizations: NotRequired[list[Organization]]


class ProjectsResponse(TypedDict):
    """Optional project collection returned by the list endpoint."""

    projects: NotRequired[list[Project]]


# Shared nested values referenced by the top-level API records.
class Location(TypedDict):
    """Resolved geographic location and the time of its position fix."""

    country: str
    latitude: float
    longitude: float
    name: str
    timezone: str
    when: str


CellularUsage: TypeAlias = list["SimUsage"]


class Contact(TypedDict):
    """Optional contact details attached to a project or account."""

    email: NotRequired[str]
    name: NotRequired[str]
    organization: NotRequired[str]
    role: NotRequired[str]


class DFUEnv(TypedDict):
    """Device firmware-update status for its card and user components."""

    card: NotRequired[DFUState]
    user: NotRequired[DFUState]


class HealthLog(TypedDict):
    """Timestamped health-log entry with its alert status and message."""

    alert: bool
    text: str
    when: str


DeviceSensors: TypeAlias = list["DeviceSensor"]

Role: TypeAlias = Literal["owner", "developer", "viewer", "support", None]


class FleetConnectivityAssurance(TypedDict):
    """Fleet connectivity-assurance setting when returned by Notehub."""

    enabled: NotRequired[bool]


FleetRule: TypeAlias = str

OrganizationRole: TypeAlias = Literal[
    "org_admin", "billing_manager", "project_creator", "org_member"
]
BillingAccountRole: TypeAlias = Literal[
    "billing_admin", "billing_manager", "project_creator", "billing_member"
]


class SlackWebHookNotification(TypedDict):
    """Slack webhook destination and optional text or block message content."""

    message_type: NotRequired[Literal["text", "blocks"]]
    text: NotRequired[str]
    url: NotRequired[str]


class SlackBearerNotification(TypedDict):
    """Slack bearer-token destination and optional text or block message content."""

    channel: NotRequired[str]
    message_type: NotRequired[Literal["text", "blocks"]]
    text: NotRequired[str]
    token: NotRequired[str]


class EmailNotification(TypedDict):
    """Email alert destination."""

    email: NotRequired[str]


class DeviceUsage(TypedDict):
    """Usage counters for a device over a period or session."""

    bytes_rcvd: NotRequired[int]
    bytes_rcvd_secondary: NotRequired[int]
    bytes_sent: NotRequired[int]
    bytes_sent_secondary: NotRequired[int]
    duration: NotRequired[int]
    notes_rcvd: NotRequired[int]
    notes_sent: NotRequired[int]
    sessions_tcp: NotRequired[int]
    sessions_tls: NotRequired[int]
    since: NotRequired[int]


class TowerLocation(TypedDict):
    """Cell-tower location data using Notehub's compact wire-field names."""

    c: NotRequired[str]
    cid: NotRequired[int]
    l: NotRequired[str]  # noqa: E741 - Notehub's wire key is literally "l".
    lac: NotRequired[int]
    lat: NotRequired[float]
    lon: NotRequired[float]
    mcc: NotRequired[int]
    mnc: NotRequired[int]
    n: NotRequired[str]
    source: NotRequired[str]
    time: NotRequired[int]
    towers: NotRequired[int]
    z: NotRequired[int]
    zone: NotRequired[str]


UsageTruncatedField: TypeAlias = bool


class SimUsage(TypedDict):
    """SIM usage totals and limits when available for a device."""

    iccid: NotRequired[str]
    last_updated: NotRequired[int]
    lifetime_used: NotRequired[int]
    limit: NotRequired[int]
    used: NotRequired[int]


class DFUState(TypedDict):
    """Status and progress metadata for one firmware-update component."""

    began: NotRequired[int]
    crc32: NotRequired[int]
    errors: NotRequired[int]
    file: NotRequired[str]
    length: NotRequired[int]
    md5: NotRequired[str]
    mode: NotRequired[
        Literal[
            "idle",
            "error",
            "downloading",
            "sideloading",
            "ready",
            "ready-retry",
            "updating",
            "completed",
        ]
    ]
    read: NotRequired[int]
    retry: NotRequired[int]
    status: NotRequired[str]
    type: NotRequired[Literal["card", "user"]]
    updated: NotRequired[int]
    version: NotRequired[str]


class DeviceSensor(TypedDict):
    """Sensor identity and most recent activity on a device."""

    last_activity_date: NotRequired[str]
    sensor_uid: str
