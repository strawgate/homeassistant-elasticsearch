"""Create Elasticsearch documents from Home Assistant events."""

from datetime import datetime
from math import isinf

from homeassistant.components.sun import STATE_ABOVE_HORIZON, STATE_BELOW_HORIZON
from homeassistant.const import (
    STATE_CLOSED,
    STATE_HOME,
    STATE_LOCKED,
    STATE_NOT_HOME,
    STATE_OFF,
    STATE_ON,
    STATE_OPEN,
    STATE_UNKNOWN,
    STATE_UNLOCKED,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import state as state_helper
from homeassistant.util import dt as dt_util
from pytz import utc

from custom_components.elasticsearch.const import CONF_TAGS
from custom_components.elasticsearch.entity_details import EntityDetails
from custom_components.elasticsearch.es_serializer import get_serializer
from custom_components.elasticsearch.logger import LOGGER
from custom_components.elasticsearch.system_info import SystemInfo

ALLOWED_ATTRIBUTE_TYPES = tuple | dict | set | list | int | float | bool | str | None


class DocumentCreator:
    """Create ES documents from Home Assistant state change events."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize."""
        self._entity_details = EntityDetails(hass)
        self._static_doc_properties: dict | None = None
        self._serializer = get_serializer()
        self._system_info: SystemInfo = SystemInfo(hass)
        self._hass = hass
        self._config = config

    async def async_init(self) -> None:
        """Async initialization."""

        system_info = await self._system_info.async_get_system_info()
        LOGGER.debug("async_init: initializing static doc properties")
        hass_config = self._hass.config

        self._static_doc_properties = {
            "agent.name": "My Home Assistant",
            "agent.type": "hass",
            "agent.version": system_info.get("version", "UNKNOWN"),
            "ecs.version": "1.0.0",
            "host.geo.location": {
                "lat": hass_config.latitude,
                "lon": hass_config.longitude,
            },
            "host.architecture": system_info.get("arch", "UNKNOWN"),
            "host.os.name": system_info.get("os_name", "UNKNOWN"),
            "host.hostname": system_info.get("hostname", "UNKNOWN"),
            "tags": self._config.get(CONF_TAGS),
        }

    def _state_to_attributes(self, state: State) -> dict:
        orig_attributes = dict(state.attributes)
        attributes = {}
        for orig_key, orig_value in orig_attributes.items():
            if not orig_key or not isinstance(orig_key, str):
                LOGGER.debug(
                    "Not publishing attribute with unsupported key [%s] from entity [%s].",
                    orig_key if isinstance(orig_key, str) else f"type:{type(orig_key)}",
                    state.entity_id,
                )
                continue

            key = str.replace(orig_key, ".", "_")
            value = orig_value

            if not isinstance(orig_value, ALLOWED_ATTRIBUTE_TYPES):
                LOGGER.debug(
                    "Not publishing attribute [%s] of disallowed type [%s] from entity [%s].",
                    key,
                    type(orig_value),
                    state.entity_id,
                )
                continue

            if isinstance(orig_value, set):
                value = list(orig_value)

            if value and isinstance(value, list | tuple):
                should_serialize = isinstance(value[0], tuple | dict | set | list)
            else:
                attributes[key] = value
        return attributes

    def _state_to_entity_details(self, state: State) -> dict:
        entity_details = self._entity_details.async_get(state.entity_id)

        additions = {}

        if entity_details is not None:
            if entity_details.device:
                additions["device"]["id"] = entity_details.device.id
                additions["device"]["name"] = entity_details.device.name

            if entity_details.device_area:
                additions["device"]["area"] = {
                    "id": entity_details.device_area.id,
                    "name": entity_details.device_area.name,
                }

            if entity_details.platform:
                additions["platform"] = entity_details.platform
            if entity_details.name:
                additions["name"] = entity_details.name

            if entity_details.area:
                additions["area"] = {
                    "id": entity_details.area.id,
                    "name": entity_details.area.name,
                }

        return additions

    def _state_to_value_v1(self, state: State) -> str | float:
        """Try to coerce our state to a boolean."""

        _state = state.state

        if isinstance(_state, float):
            return _state

        elif isinstance(_state, str) and try_state_as_number(state):
            return state_helper.state_as_number(state)

        else:
            return _state

    def _state_to_value_v2(self, state: State) -> dict:
        """Try to coerce our state to a boolean."""
        additions = {"valueas": {}}

        _state = state.state

        if isinstance(_state, float):
            additions["valueas"]["float"] = _state

        elif isinstance(_state, str) and try_state_as_boolean(state):
            additions["valueas"]["boolean"] = state_as_boolean(state)

        elif isinstance(_state, str) and try_state_as_number(state):
            additions["valueas"]["float"] = state_helper.state_as_number(state)

        elif isinstance(_state, str) and try_state_as_datetime(state):
            _tempState = state_as_datetime(state)

            additions["valueas"]["datetime"] = _tempState.isoformat()
            additions["valueas"]["date"] = _tempState.date().isoformat()
            additions["valueas"]["time"] = _tempState.time().isoformat()

        else:
            additions["valueas"]["string"] = _state

        # in v2, value is always a string
        additions["value"] = _state

        return additions

    def state_to_document_v1(self, state: State, entity: dict, time: datetime) -> dict:
        """Convert entity state to Legacy ES document format."""
        additions = {
            "hass.domain": state.domain,
            "hass.object_id_lower": state.object_id.lower(),
            "hass.entity_id": state.entity_id,
            "hass.entity_id_lower": state.entity_id.lower(),
            "hass.attributes": entity["attributes"],
            "hass.entity": entity,
        }

        additions["hass.entity"]["value"] = self._state_to_value_v1(state)
        additions["hass.value"] = additions["hass.entity"]["value"]

        if "latitude" in entity["attributes"] and "longitude" in entity["attributes"]:
            additions["hass.geo.location"] = {
                "lat": entity["attributes"]["latitude"],
                "lon": entity["attributes"]["longitude"],
            }

        return additions

    def state_to_document_v2(self, state: State, entity: dict, time: datetime) -> dict:
        """Convert entity state to modern ES document format."""
        additions = {"hass.entity": entity}

        additions["hass.entity"].update(self._state_to_value_v2(state))

        if "latitude" in entity["attributes"] and "longitude" in entity["attributes"]:
            additions["hass.entity"]["geo.location"] = {
                "lat": entity["attributes"]["latitude"],
                "lon": entity["attributes"]["longitude"],
            }

        return additions

    def state_to_document(self, state: State, time: datetime, version: int = 2) -> dict:
        """Convert entity state to ES document."""

        if time.tzinfo is None:
            time_tz = time.astimezone(utc)
        else:
            time_tz = time

        attributes = self._state_to_attributes(state)

        entity = {
            "id": state.entity_id,
            "domain": state.domain,
            "attributes": attributes,
            "value": state.state,
        }

        # Add details from entity onto object
        entity.update(self._state_to_entity_details(state))

        """
        # log the python type of 'value' for debugging purposes
        LOGGER.debug(
            "Entity [%s] has value [%s] of type [%s]",
            state.entity_id,
            _state,
            type(_state)
        )
        """

        document_body = {
            "@timestamp": time_tz,
            "hass.object_id": state.object_id,
        }

        if version == 1:
            document_body.update(self.state_to_document_v1(state, entity, time_tz))

        if version == 2:
            document_body.update(self.state_to_document_v2(state, entity, time_tz))

        if self._static_doc_properties is None:
            LOGGER.warning(
                "Event for entity [%s] is missing static doc properties. This is a bug.",
                state.entity_id,
            )
        else:
            document_body.update(self._static_doc_properties)

        return document_body


def is_valid_number(number):
    """Determine if the passed number is valid for Elasticsearch."""
    is_infinity = isinf(number)
    is_nan = number != number  # pylint: disable=comparison-with-itself
    return not is_infinity and not is_nan


def try_state_as_number(state: State) -> bool:
    """Try to coerce our state to a number and return true if we can, false if we can't."""

    try:
        state_helper.state_as_number(state)
        return True
    except ValueError:
        return False


def try_state_as_boolean(state: State) -> bool:
    """Try to coerce our state to a boolean and return true if we can, false if we can't."""

    try:
        state_as_boolean(state)
        return True
    except ValueError:
        return False


def state_as_boolean(state: State) -> bool:
    """Try to coerce our state to a boolean."""
    # copied from helper state_as_number function
    if state.state in (
        STATE_ON,
        STATE_LOCKED,
        STATE_ABOVE_HORIZON,
        STATE_OPEN,
        STATE_HOME,
    ):
        return True
    if state.state in (
        STATE_OFF,
        STATE_UNLOCKED,
        STATE_UNKNOWN,
        STATE_BELOW_HORIZON,
        STATE_CLOSED,
        STATE_NOT_HOME,
    ):
        return False

    raise ValueError("Could not coerce state to a boolean.")


def try_state_as_datetime(state: State) -> datetime:
    """Try to coerce our state to a datetime and return True if we can, false if we can't."""

    try:
        state_as_datetime(state)
        return True
    except ValueError:
        return False


def state_as_datetime(state: State) -> datetime:
    """Try to coerce our state to a datetime."""

    parsed = dt_util.parse_datetime(state.state)

    # TODO: More recent versions of HA allow us to pass `raise_on_error`.
    # We can remove this explicit `raise` once we update the minimum supported HA version.
    # parsed = dt_util.parse_datetime(_state, raise_on_error=True)

    if parsed is None:
        raise ValueError("Could not coerce state to a datetime.")

    return parsed
