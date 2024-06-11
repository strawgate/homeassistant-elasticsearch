"""Support for sending event data to an Elasticsearch cluster."""

from elasticsearch.config_flow import ElasticFlowHandler
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from custom_components.elasticsearch.errors import (
    AuthenticationRequired,
    InsufficientPrivileges,
    UnsupportedVersion,
)
from custom_components.elasticsearch.logger import LOGGER, async_log_enter_exit, have_child, log_enter_exit

from .const import (
    CONF_HEALTH_SENSOR_ENABLED,
    CONF_INDEX_MODE,
    DOMAIN,
    INDEX_MODE_LEGACY,
)
from .es_integration import ElasticIntegration


@async_log_enter_exit
async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:  # pylint: disable=unused-argument
    """Migrate old entry."""

    latest_version = ElasticFlowHandler.VERSION

    if config_entry.version == latest_version:
        return True

    migrated_data, migrated_options, migrated_version = migrate_data_and_options_to_version(
        config_entry,
        latest_version,
    )

    if migrated_version != latest_version:
        LOGGER.error(
            "Migration failed attempting to migrate from version %s to version %s. Ended on %s.",
            config_entry.version,
            latest_version,
            migrated_version,
        )
        return False

    hass.config_entries.async_update_entry(
        config_entry,
        data=migrated_data,
        options=migrated_options,
        version=migrated_version,
    )

    return True


@async_log_enter_exit
async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up integration via config flow."""
    init = await _async_init_integration(hass, config_entry)

    config_entry.add_update_listener(async_config_entry_updated)

    return init


@async_log_enter_exit
async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Teardown integration."""
    existing_instances = hass.data.get(DOMAIN)
    if existing_instances is None:
        return True

    existing_instance = existing_instances.get(config_entry.entry_id)

    if isinstance(existing_instance, ElasticIntegration):
        LOGGER.debug("Shutting down previous integration")
        await existing_instance.async_shutdown()
        hass.data[DOMAIN][config_entry.entry_id] = None

    return True


@async_log_enter_exit
async def async_config_entry_updated(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Respond to config changes."""
    await _async_init_integration(hass, config_entry)


@async_log_enter_exit
async def _async_init_integration(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Initialize integration."""
    await async_unload_entry(hass=hass, config_entry=config_entry)

    _logger = have_child(name=config_entry.title)
    _logger.info("Initializing integration for %s", config_entry.title)

    try:
        integration = ElasticIntegration(hass=hass, config_entry=config_entry, log=_logger)
        await integration.async_init()
    except UnsupportedVersion as err:
        msg = "Unsupported Elasticsearch version detected"
        _logger.exception(msg)
        raise ConfigEntryNotReady(msg) from err
    except AuthenticationRequired as err:
        msg = "Missing or invalid credentials"
        _logger.exception(msg)
        raise ConfigEntryAuthFailed(msg) from err
    except InsufficientPrivileges as err:
        msg = "Account does not have sufficient privileges"
        _logger.exception(msg)
        raise ConfigEntryAuthFailed from err
    except ConnectionError as err:
        msg = "Error connecting to Elasticsearch"
        _logger.exception(msg)
        raise ConfigEntryNotReady(msg) from err
    except Exception as err:  # pylint disable=broad-exception-caught
        msg = "Exception during component initialization"
        _logger.exception(msg)
        raise ConfigEntryNotReady(msg) from err

    if hass.data.get(DOMAIN) is None:
        hass.data[DOMAIN] = {}

    hass.data[DOMAIN][config_entry.entry_id] = integration

    return True


@log_enter_exit
def migrate_data_and_options_to_version(
    config_entry: ConfigEntry,
    desired_version: int,
) -> tuple[dict, dict, int]:
    """Migrate a config entry from its current version to a desired version."""
    LOGGER.debug(
        "Migrating config entry from version %s to %s",
        config_entry.version,
        desired_version,
    )

    data = {**config_entry.data}
    options = {**config_entry.options}
    begin_version = config_entry.version
    current_version = begin_version

    if current_version < desired_version:
        for version in range(current_version + 1, desired_version + 1):
            migration_func = globals().get(f"migrate_to_version_{version}")
            if migration_func:
                data, options = migration_func(data, options)
                current_version = version

    end_version = current_version

    LOGGER.info("Migration from version %s to version %s successful", begin_version, end_version)

    return data, options, end_version


def migrate_to_version_2(data: dict, options: dict) -> tuple[dict, dict]:
    """Migrate config to version 2."""
    only_publish_changed = data.get("only_publish_changed", False)
    data["publish_mode"] = "All" if not only_publish_changed else "Any changes"

    if "only_publish_changed" in data:
        del data["only_publish_changed"]

    return data, options


def migrate_to_version_3(data: dict, options: dict) -> tuple[dict, dict]:
    """Migrate config to version 3."""
    if CONF_HEALTH_SENSOR_ENABLED in data:
        del data[CONF_HEALTH_SENSOR_ENABLED]

    return data, options


def migrate_to_version_4(data: dict, options: dict) -> tuple[dict, dict]:
    """Migrate config to version 4."""
    if CONF_INDEX_MODE not in data:
        data[CONF_INDEX_MODE] = INDEX_MODE_LEGACY

    conf_ilm_max_size = "ilm_max_size"
    if conf_ilm_max_size in data:
        del data[conf_ilm_max_size]

    conf_ilm_delete_after = "ilm_delete_after"
    if conf_ilm_delete_after in data:
        del data[conf_ilm_delete_after]

    return data, options


def migrate_to_version_5(data: dict, options: dict) -> tuple[dict, dict]:
    """Migrate config to version 5."""
    keys_to_remove = [
        "datastream_type",
        "datastream_name_prefix",
        "datastream_namespace",
    ]

    for key in keys_to_remove:
        if key in data:
            del data[key]

    keys_to_migrate = [
        "publish_enabled",
        "publish_frequency",
        "publish_mode",
        "excluded_domains",
        "excluded_entities",
        "included_domains",
        "included_entities",
    ]

    for key in keys_to_migrate:
        if key not in options and key in data:
            options[key] = data[key]
        if key in data:
            del data[key]

    remove_keys_if_empty = [
        "username",
        "password",
        "api_key",
    ]

    for key in remove_keys_if_empty:
        if key in data and data[key] == "":
            del data[key]

    return data, options


def migrate_to_version_6(data: dict, options: dict) -> tuple[dict, dict]:
    """Migrate config to version 6."""

    if data.get("index_mode") is not None:
        del data["index_mode"]

    # Change publish mode to change_detection_type
    if options.get("publish_mode") is not None:
        if options["publish_mode"] == "All":
            options["polling_frequency"] = options["publish_frequency"]
            options["change_detection_type"] = ["STATE", "ATTRIBUTE"]

        if options["publish_mode"] == "Any changes":
            options["change_detection_type"] = ["STATE", "ATTRIBUTE"]

        if options["publish_mode"] == "State changes":
            options["change_detection_type"] = ["STATE"]

        del options["publish_mode"]

    else:
        options["change_detection_type"] = ["STATE", "ATTRIBUTE"]

    # add dedicated settings for polling
    options_to_remove = [
        "ilm_enabled",
        "ilm_policy_name",
        "publish_mode",
        "publish_enabled",
        "index_format",
        "index_mode",
        "alias",
    ]

    for key in options_to_remove:
        if key in options:
            del options[key]

    return data, options
