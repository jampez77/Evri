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
    CONF_AVAILABLE_FOR_COLLECTION,
    CONF_DATETIME,
    CONF_DESCRIPTION,
    CONF_OUT_FOR_DELIVERY,
    CONF_PARCELS,
    CONF_RESULTS,
    CONF_TRACKING_NUMBER,
    CONF_TRACKINGEVENTS,
    CONF_TRACKINGPOINT,
    CONF_TRACKINGSTAGE,
    CONF_TRACKINGSTAGECODE,
    DOMAIN,
    PARCEL_CALL_TO_ACTION,
    PARCEL_COLLECTION,
    PARCEL_DELIVERED,
    PARCEL_DELIVERY_TODAY,
    PARCEL_IN_TRANSIT,
    PARCEL_INFORMATION,
    PARCEL_IS_FINISHED,
    PARCEL_READY_FOR_COLLECTION,
    PARCEL_RETURNED,
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
        and f"evri_parcel_{tracking_number}".lower() in entry.unique_id.lower()
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
    parcels_available_for_collection = []
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
            and most_recent_tracking_event_stage in PARCEL_IS_FINISHED
            and hasParcelExpired(hass, most_recent_tracking_event_date_time)
        ):
            await removeParcel(hass, tracking_number)
            parcels.remove(parcel)
        else:
            if most_recent_tracking_event_stage in PARCEL_DELIVERY_TODAY:
                parcels_out_for_delivery.append(parcel)

            if most_recent_tracking_event_stage in PARCEL_READY_FOR_COLLECTION:
                parcels_available_for_collection.append(parcel)

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
        updated_data = entry.data.copy()

        # Update and persist the new parcel lists
        updated_data[CONF_PARCELS] = parcels
        updated_data[CONF_OUT_FOR_DELIVERY] = parcels_out_for_delivery
        updated_data[CONF_AVAILABLE_FOR_COLLECTION] = parcels_available_for_collection

        hass.config_entries.async_update_entry(entry, data=updated_data)

        total_sensor = TotalParcelsSensor(
            hass, entry, parcels_out_for_delivery, parcels_available_for_collection
        )
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


async def remove_unavailable_entities(hass: HomeAssistant):
    """Remove entities no longer provided by the integration."""
    # Access the entity registry
    registry = er.async_get(hass)

    # Loop through all registered entities
    for entity_id in list(registry.entities):
        entity = registry.entities[entity_id]
        # Check if the entity belongs to your integration (by checking domain)
        if entity.platform == DOMAIN:
            # Check if the entity is not available in `hass.states`
            state = hass.states.get(entity_id)

            # If the entity's state is unavailable or not in `hass.states`
            if state is None or state.state == "unavailable":
                registry.async_remove(entity_id)


class TotalParcelsSensor(SensorEntity):
    """Sensor to track the total number of parcels."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        parcels_out_for_delivery: list,
        parcels_available_for_collection: list,
    ) -> None:
        """Init."""
        self.total_parcels = entry.data[CONF_PARCELS]
        self.parcels_out_for_delivery = parcels_out_for_delivery
        self.parcels_available_for_collection = parcels_available_for_collection
        self._state = len(self.total_parcels)
        self._name = "Evri Parcels"
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
            parcels_out_for_delivery = config_entry.data.get(CONF_OUT_FOR_DELIVERY, [])
            parcels_available_for_collection = config_entry.data.get(
                CONF_AVAILABLE_FOR_COLLECTION, []
            )

            self.total_parcels = parcels
            self.parcels_out_for_delivery = parcels_out_for_delivery
            self.parcels_available_for_collection = parcels_available_for_collection
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

    def is_parcel_available_for_collection(self, parcel: dict) -> bool:
        """Check if the parcel is ready to collect."""
        tracking_events = parcel.get(CONF_TRACKINGEVENTS, [])
        if tracking_events:
            most_recent_event = tracking_events[0]
            last_tracking_stage_code = most_recent_event[CONF_TRACKINGSTAGE][
                CONF_TRACKINGSTAGECODE
            ]
            return last_tracking_stage_code in PARCEL_READY_FOR_COLLECTION
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

        self.attrs[CONF_AVAILABLE_FOR_COLLECTION] = [
            parcel[CONF_TRACKING_NUMBER]
            for parcel in self.parcels_available_for_collection
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

        self._state = self.update_state()
        self._attr_icon = self.update_icon()
        self.attrs = self.update_attributes()
        self._available = True

    def update_state(self) -> str:
        """Update State."""

        value = self.data[CONF_TRACKINGEVENTS][0][CONF_TRACKINGSTAGE][CONF_DESCRIPTION]

        most_recent_tracking_event = self.data[CONF_TRACKINGEVENTS][0]

        most_recent_tracking_event_stage = most_recent_tracking_event[
            CONF_TRACKINGSTAGE
        ][CONF_TRACKINGSTAGECODE]

        if most_recent_tracking_event_stage not in PARCEL_IS_FINISHED:
            value = most_recent_tracking_event[CONF_TRACKINGPOINT][CONF_DESCRIPTION]

        return value

    def update_icon(self) -> str:
        """Update icon."""

        most_recent_event = self.data[CONF_TRACKINGEVENTS][0]

        last_tracking_stage_code = most_recent_event[CONF_TRACKINGSTAGE][
            CONF_TRACKINGSTAGECODE
        ]

        if (
            last_tracking_stage_code in PARCEL_DELIVERED
            or last_tracking_stage_code == PARCEL_RETURNED
        ):
            return "mdi:package-variant-closed-check"
        elif last_tracking_stage_code in PARCEL_COLLECTION:
            return "mdi:human-dolly"
        elif last_tracking_stage_code in PARCEL_DELIVERY_TODAY:
            return "mdi:truck-delivery-outline"
        elif last_tracking_stage_code in PARCEL_IN_TRANSIT:
            return "mdi:transit-connection-variant"
        elif last_tracking_stage_code == PARCEL_CALL_TO_ACTION:
            return "mdi:alert-box"
        elif last_tracking_stage_code == PARCEL_INFORMATION:
            return "mdi:information-box"
        else:
            return "mdi:package-variant-closed"

    def update_attributes(self) -> dict[str, Any]:
        """Update attributes."""
        attributes = {}

        if isinstance(self.data, (dict, list)):
            for index, attribute in enumerate(self.data):
                if isinstance(attribute, (dict, list)):
                    for attr in attribute:
                        attributes[str(attr) + str(index)] = attribute[attr]
                else:
                    attributes[attribute] = self.data[attribute]

        return attributes

    def update_from_coordinator(self):
        """Update sensor state and attributes from coordinator data."""

        most_recent_tracking_event = self.data[CONF_TRACKINGEVENTS][0]

        most_recent_tracking_event_stage = most_recent_tracking_event[
            CONF_TRACKINGSTAGE
        ][CONF_TRACKINGSTAGECODE]
        most_recent_tracking_event_date_time = most_recent_tracking_event[CONF_DATETIME]

        if most_recent_tracking_event_stage in PARCEL_IS_FINISHED and hasParcelExpired(
            self.hass, most_recent_tracking_event_date_time
        ):
            self.hass.async_add_job(removeParcel(self.hass, self.tracking_number))
        elif CONF_RESULTS in self.coordinator.data:
            self.data = self.coordinator.data.get(CONF_RESULTS)[0]
            self._state = self.update_state()
            self._attr_icon = self.update_icon()

            self.attrs = self.update_attributes()

            self.notify_total_parcels()
            self.hass.add_job(remove_unavailable_entities(self.hass))

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
