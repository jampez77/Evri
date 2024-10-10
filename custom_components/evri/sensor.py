"""Sensors for Evri."""

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DATETIME,
    CONF_DESCRIPTION,
    CONF_OUT_FOR_DELIVERY,
    CONF_PARCELS,
    CONF_RESULTS,
    CONF_TRACKING_NUMBER,
    CONF_TRACKINGEVENTS,
    CONF_TRACKINGSTAGE,
    CONF_TRACKINGSTAGECODE,
    DOMAIN,
    PARCEL_DELIVERED,
    PARCEL_DELIVERY_TODAY,
    PARCEL_IN_TRANSIT,
)
from .coordinator import EvriCoordinator


def hasParcelExpired(hass: HomeAssistant, expiry_date_raw: str) -> bool:
    """Check if booking has expired."""

    user_timezone = dt_util.get_time_zone(hass.config.time_zone)

    dt_utc = datetime.strptime(expiry_date_raw, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=user_timezone
    )
    # Convert the datetime to the default timezone
    expiry_date = dt_utc.astimezone(user_timezone)
    return (datetime.today().timestamp() - expiry_date.timestamp()) >= 86400


async def removeParcel(hass: HomeAssistant, tracking_number: str):
    """Remove expired booking."""
    entries = hass.config_entries.async_entries(DOMAIN)

    if not entries:
        return

    entity_registry = er.async_get(hass)

    entities = [
        entity_id
        for entity_id, entry in entity_registry.entities.items()
        if entry.platform == DOMAIN
        and f"evri_{tracking_number}".lower() in entry.entity_id.lower()
    ]
    for entity in entities:
        entity_registry.async_remove(entity)

    # Find the config entry
    config_entry = entries[0]
    updated_data = config_entry.data.copy()

    # Remove the parcel from the CONF_PARCELS list
    updated_parcels = [
        parcel
        for parcel in updated_data.get(CONF_PARCELS, [])
        if parcel[CONF_TRACKING_NUMBER] != tracking_number
    ]

    # Update and persist the new parcel list
    updated_data[CONF_PARCELS] = updated_parcels
    hass.config_entries.async_update_entry(config_entry, data=updated_data)


async def get_sensors(hass: HomeAssistant, entry: ConfigEntry) -> list[SensorEntity]:
    """Get sensors."""
    sensors = []

    parcels = entry.data.get(CONF_PARCELS, [])

    sensors = []
    parcels_out_for_delivery = []
    for parcel in parcels:
        tracking_number = parcel[CONF_TRACKING_NUMBER]

        session = async_get_clientsession(hass)

        coordinator = EvriCoordinator(hass, session, parcel)

        await coordinator.async_refresh()

        if coordinator.last_exception is not None:
            return False

        most_recent_tracking_event = coordinator.data.get(CONF_RESULTS)[0][
            CONF_TRACKINGEVENTS
        ][0]

        most_recent_tracking_event_stage = most_recent_tracking_event[
            CONF_TRACKINGSTAGE
        ][CONF_TRACKINGSTAGECODE]
        most_recent_tracking_event_date_time = most_recent_tracking_event[CONF_DATETIME]

        if (
            parcel in parcels
            and most_recent_tracking_event_stage in PARCEL_DELIVERED
            and hasParcelExpired(hass, most_recent_tracking_event_date_time)
        ):
            await removeParcel(hass, tracking_number)
            parcels.remove(parcel)
        else:
            if most_recent_tracking_event_stage in PARCEL_DELIVERY_TODAY:
                parcels_out_for_delivery.append(parcel)

            sensors = [*sensors, ParcelSensor(coordinator, tracking_number)]
            for sensor in sensors:
                hass.data[DOMAIN][sensor.unique_id] = sensor

    total_sensor = None
    for entity in hass.data[DOMAIN].values():
        if isinstance(entity, TotalParcelsSensor):
            total_sensor = entity
            break

    if total_sensor:
        # Update existing total parcels sensor
        total_sensor.update_parcels()
    else:
        total_sensor = TotalParcelsSensor(hass, entry, parcels_out_for_delivery)
        hass.data[DOMAIN][total_sensor.unique_id] = total_sensor
        total_sensor.update_state()
        sensors = [*sensors, total_sensor]

    return sensors


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors for the Evri integration."""
    sensors = await get_sensors(hass, config_entry)

    async_add_entities(sensors, update_before_add=True)

    async def async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Triggered by config entry options updates."""
        sensors = await get_sensors(hass, entry)

        async_add_entities(sensors, update_before_add=True)

    config_entry.add_update_listener(async_options_updated)


class TotalParcelsSensor(SensorEntity):
    """Sensor to track the total number of parcels."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, parcels_out_for_delivery: list
    ) -> None:
        """Init."""
        self.total_parcels = entry.data[CONF_PARCELS]
        self.parcels_out_for_delivery = parcels_out_for_delivery
        self._state = len(self.total_parcels)
        self._name = "Tracked Parcels"
        self.hass = hass
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{DOMAIN}".upper())},
            manufacturer="Evri",
            model="Parcel Tracker",
            name="Evri - Parcel Tracker",
            configuration_url="https://github.com/jampez77/Evri/",
        )
        self._attr_unique_id = f"{DOMAIN}_tracked_parcels".lower()
        self.entity_id = f"sensor.{DOMAIN}_tracked_parcels".lower()
        self.attrs: dict[str, Any] = {}

    @property
    def name(self) -> str:
        """Name."""
        return self._name

    @property
    def state(self) -> str:
        """State."""
        return self._state

    def update_state(self):
        """Update the state based on the number of tracked parcels."""
        self._state = len(self.total_parcels)

    @property
    def icon(self) -> str:
        """Set total parcels icon."""
        return "mdi:package-variant-closed"

    def update_parcels(self):
        """Update parcels and re-calculate state."""
        entries = self.hass.config_entries.async_entries(DOMAIN)

        if entries:
            config_entry = entries[0]
            parcels = config_entry.data.get(CONF_PARCELS, [])

            parcels_out_for_delivery = [
                parcel for parcel in parcels if self.is_parcel_delivery_today(parcel)
            ]

            self.total_parcels = parcels
            self.parcels_out_for_delivery = parcels_out_for_delivery
            self.update_state()

            self.async_write_ha_state()

    def is_parcel_delivery_today(self, parcel: dict) -> bool:
        """Check if the parcel has been delivered."""
        tracking_events = parcel.get(CONF_TRACKINGEVENTS, [])
        if tracking_events:
            most_recent_event = tracking_events[0]
            last_tracking_stage_code = most_recent_event[CONF_TRACKINGSTAGE][
                CONF_TRACKINGSTAGECODE
            ]
            return last_tracking_stage_code in PARCEL_DELIVERY_TODAY
        return False

    async def async_remove(self) -> None:
        """Handle the removal of the entity."""
        # If you have any specific cleanup logic, add it here
        await super().async_remove()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Define entity attributes."""

        self.attrs[CONF_PARCELS] = [
            parcel[CONF_TRACKING_NUMBER] for parcel in self.total_parcels
        ]

        self.attrs[CONF_OUT_FOR_DELIVERY] = [
            parcel[CONF_TRACKING_NUMBER] for parcel in self.parcels_out_for_delivery
        ]

        return self.attrs


class ParcelSensor(CoordinatorEntity[DataUpdateCoordinator], SensorEntity):
    """Sensor to track an individual parcel."""

    def __init__(
        self, coordinator: DataUpdateCoordinator, tracking_number: str
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.data = coordinator.data.get(CONF_RESULTS)[0]
        self.tracking_number = tracking_number
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{DOMAIN}".upper())},
            manufacturer="Evri",
            model="Parcel Tracker",
            name="Evri - Parcel Tracker",
            configuration_url="https://github.com/jampez77/Evri/",
        )
        self._attr_unique_id = f"{DOMAIN}_parcel_{tracking_number}"
        self.entity_id = f"sensor.{DOMAIN}_parcel_{self.tracking_number}".lower()

        self._state = self.data[CONF_TRACKINGEVENTS][0][CONF_TRACKINGSTAGE][
            CONF_DESCRIPTION
        ]
        self._attr_icon = "mdi:package-variant-closed"
        self.attrs: dict[str, Any] = {}
        self._available = True

    def update_from_coordinator(self):
        """Update sensor state and attributes from coordinator data."""

        most_recent_tracking_event = self.data[CONF_TRACKINGEVENTS][0]

        most_recent_tracking_event_stage = most_recent_tracking_event[
            CONF_TRACKINGSTAGE
        ][CONF_TRACKINGSTAGECODE]
        most_recent_tracking_event_date_time = most_recent_tracking_event[CONF_DATETIME]

        if most_recent_tracking_event_stage in PARCEL_DELIVERED and hasParcelExpired(
            self.hass, most_recent_tracking_event_date_time
        ):
            self.hass.async_add_job(removeParcel(self.hass, self.tracking_number))
        elif CONF_RESULTS in self.coordinator.data:
            self.data = self.coordinator.data.get(CONF_RESULTS)[0]
            tracking_events = self.data.get(CONF_TRACKINGEVENTS, [])
            if tracking_events:
                most_recent_event = tracking_events[0]
                self._state = most_recent_event[CONF_TRACKINGSTAGE][CONF_DESCRIPTION]
                last_tracking_stage_code = most_recent_event[CONF_TRACKINGSTAGE][
                    CONF_TRACKINGSTAGECODE
                ]

                # Notify if the parcel is delivered
                if last_tracking_stage_code in PARCEL_DELIVERED:
                    self.notify_total_parcels()

                # Update icon based on tracking stage
                if last_tracking_stage_code in PARCEL_DELIVERED:
                    self._attr_icon = "mdi:package-variant-closed-check"
                elif last_tracking_stage_code in PARCEL_DELIVERY_TODAY:
                    self._attr_icon = "mdi:truck-delivery-outline"
                elif last_tracking_stage_code in PARCEL_IN_TRANSIT:
                    self._attr_icon = "mdi:transit-connection-variant"

            # Update attributes
            if isinstance(self.data, (dict, list)):
                for index, attribute in enumerate(self.data):
                    if isinstance(attribute, (dict, list)):
                        for attr in attribute:
                            self.attrs[str(attr) + str(index)] = attribute[attr]
                    else:
                        self.attrs[attribute] = self.data[attribute]

    def notify_total_parcels(self):
        """Notify the total parcels sensor to update its state."""
        total_sensor = None
        for entity in self.hass.data[DOMAIN].values():
            if isinstance(entity, TotalParcelsSensor):
                total_sensor = entity
                break

        if total_sensor:
            total_sensor.update_parcels()

    @property
    def name(self) -> str:
        """Name."""
        return self.tracking_number

    @property
    def available(self) -> bool:
        """Return if the entity is available."""
        return self.coordinator.last_update_success and self.data is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update_from_coordinator()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Handle adding to Home Assistant."""
        await super().async_added_to_hass()
        await self.async_update()

    async def async_remove(self) -> None:
        """Handle the removal of the entity."""
        # If you have any specific cleanup logic, add it here
        if self.hass is not None:
            await super().async_remove()

    @property
    def icon(self) -> str:
        """Return a representative icon of the timer."""
        return self._attr_icon

    @property
    def native_value(self) -> str | None:
        """Native value."""
        return self._state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Define entity attributes."""
        return self.attrs
