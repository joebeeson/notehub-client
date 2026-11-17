"""Public stateless Notehub resource facades."""

from .base import RequestClient
from .billing_accounts import BillingAccountsFacade
from .devices import DeviceEnvironment, DeviceHandle, DevicesFacade
from .events import EventsFacade
from .fleets import FleetsFacade
from .jobs import JobsFacade
from .monitors import MonitorsFacade
from .notes import NotesFacade
from .organizations import OrganizationsFacade
from .projects import ProjectDevices, ProjectHandle, ProjectsFacade
from .routes import RoutesFacade
from .usage import UsageFacade

__all__ = [
    "BillingAccountsFacade",
    "DevicesFacade",
    "DeviceEnvironment",
    "DeviceHandle",
    "EventsFacade",
    "FleetsFacade",
    "JobsFacade",
    "MonitorsFacade",
    "NotesFacade",
    "OrganizationsFacade",
    "ProjectsFacade",
    "ProjectDevices",
    "ProjectHandle",
    "RequestClient",
    "RoutesFacade",
    "UsageFacade",
]

# TODO: Are our facades just like, descriptors that know they'll get a request client? Can we make descriptors and point
#  at a module? Or a decorator that builds up a descriptor that does it? We just have big classes in each of our .py
#  which isn't _awful_ and I'm likely overreacting. Maybe at least some mixins or such help for our classes?
