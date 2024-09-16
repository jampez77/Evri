"""Evri Coordinator."""

from datetime import timedelta
import logging
import urllib.parse

from aiohttp import ClientSession

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_GET,
    CONF_POST_CODE,
    CONF_TRACKING_NUMBER,
    DOMAIN,
    REQUEST_HEADERS,
    TRACKING_INFO_URL,
    UNIQUE_ID_URL,
)

_LOGGER = logging.getLogger(__name__)


class EvriCoordinator(DataUpdateCoordinator):
    """Data coordinator."""

    def __init__(self, hass: HomeAssistant, session: ClientSession, data: dict) -> None:
        """Initialize coordinator."""

        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name=DOMAIN,
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(seconds=300),
        )
        self.session = session
        self.tracking_number = data[CONF_TRACKING_NUMBER]
        self.postcode = data.get(CONF_POST_CODE)

    async def _async_update_data(self):
        """Fetch data from API endpoint."""

        def validate_response(body):
            if not isinstance(body, (dict, list)):
                raise TypeError("Unexpected response format")

        try:
            body = {}

            unique_ids_resp = await self.session.request(
                method=CONF_GET,
                url=UNIQUE_ID_URL.format(trackingNumber=self.tracking_number),
                headers=REQUEST_HEADERS,
            )

            if unique_ids_resp.status == 200:
                unique_ids = await unique_ids_resp.json()

                validate_response(unique_ids)

                tracking_info_resp = await self.session.request(
                    method=CONF_GET,
                    url=TRACKING_INFO_URL.format(
                        uniqueIds=urllib.parse.quote(unique_ids[0], safe=":/?=&"),
                        postCode=str(self.postcode).replace(" ", ""),
                    ),
                    headers=REQUEST_HEADERS,
                )

                if tracking_info_resp.status == 200:
                    body = await tracking_info_resp.json()

                    validate_response(body)

        except InvalidAuth as err:
            raise ConfigEntryAuthFailed from err
        except EvriError as err:
            raise UpdateFailed(str(err)) from err
        except ValueError as err:
            _LOGGER.error("Value error occurred: %s", err)
            raise UpdateFailed(f"Unexpected response: {err}") from err
        except Exception as err:
            _LOGGER.error("Unexpected exception: %s", err)
            raise UnknownError from err
        else:
            return body


class EvriError(HomeAssistantError):
    """Base error."""


class InvalidAuth(EvriError):
    """Raised when invalid authentication credentials are provided."""


class APIRatelimitExceeded(EvriError):
    """Raised when the API rate limit is exceeded."""


class UnknownError(EvriError):
    """Raised when an unknown error occurs."""
