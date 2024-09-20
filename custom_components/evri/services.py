"""Services for Evri integration."""

import functools

import voluptuous as vol

from homeassistant.components.persistent_notification import (
    async_create as create_notification,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_PARCELS,
    CONF_POST_CODE,
    CONF_RESULTS,
    CONF_TRACK_A_PARCEL,
    CONF_TRACKING_NUMBER,
    CONF_TRACKINGEVENTS,
    CONF_TRACKINGSTAGE,
    CONF_TRACKINGSTAGECODE,
    DELIVERY_DELIVERED_EVENTS,
    DOMAIN,
)
from .coordinator import EvriCoordinator

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TRACKING_NUMBER): cv.string,
        vol.Optional(CONF_POST_CODE): cv.string,
    }
)


def async_cleanup_services(hass: HomeAssistant) -> None:
    """Cleanup Royal Mail services."""
    hass.services.async_remove(DOMAIN, CONF_TRACK_A_PARCEL)


def async_setup_services(hass: HomeAssistant) -> None:
    """Set up Royal Mail services."""
    services = [
        (
            CONF_TRACK_A_PARCEL,
            functools.partial(track_a_parcel, hass),
            SERVICE_SCHEMA,
        )
    ]
    for name, method, schema in services:
        if hass.services.has_service(DOMAIN, name):
            continue
        hass.services.async_register(DOMAIN, name, method, schema=schema)


async def notify_duplicate_parcel(hass: HomeAssistant, tracking_number: str) -> None:
    """Notify user that the parcel is already tracked."""
    message = (
        f"The parcel with tracking number {tracking_number} is already being tracked."
    )
    title = "Duplicate Parcel"
    notification_id = f"duplicate_parcel_{tracking_number}"

    # Create a persistent notification
    create_notification(hass, message, title=title, notification_id=notification_id)


async def notify_delivered_parcel(hass: HomeAssistant, tracking_number: str) -> None:
    """Notify user that the parcel is already tracked."""
    message = (
        f"The parcel with tracking number {tracking_number} has already been delivered."
    )
    title = "Parcel Already Delivered"
    notification_id = f"parcel_already_delivered_{tracking_number}"

    # Create a persistent notification
    create_notification(hass, message, title=title, notification_id=notification_id)


async def track_a_parcel(hass: HomeAssistant, call: ServiceCall) -> None:
    """Track a parcel."""
    tracking_number = call.data.get(CONF_TRACKING_NUMBER)

    for entry in hass.config_entries.async_entries(DOMAIN):
        if tracking_number in [
            parcel[CONF_TRACKING_NUMBER] for parcel in entry.data.get(CONF_PARCELS, [])
        ]:
            await notify_duplicate_parcel(hass, tracking_number)
            return False

    session = async_get_clientsession(hass)

    coordinator = EvriCoordinator(hass, session, call.data)

    await coordinator.async_refresh()

    if coordinator.last_exception is not None:
        return False

    most_recent_tracking_event = coordinator.data.get(CONF_RESULTS)[0][
        CONF_TRACKINGEVENTS
    ][0]

    most_recent_tracking_event_stage = most_recent_tracking_event[CONF_TRACKINGSTAGE][
        CONF_TRACKINGSTAGECODE
    ]

    if most_recent_tracking_event_stage in DELIVERY_DELIVERED_EVENTS:
        await notify_delivered_parcel(hass, tracking_number)
        return False

    await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "import"},
        data=call.data,
    )

    return True
