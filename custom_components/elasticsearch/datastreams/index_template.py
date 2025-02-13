"""Defines the index template for Elasticsearch data streams."""

from typing import Any

index_template_definition: dict[str, Any] = {
    "index_patterns": ["metrics-homeassistant.*-default"],
    "template": {
        "mappings": {
            "dynamic": "false",
            "dynamic_templates": [
                {
                    "hass_entity_attributes": {
                        "path_match": "hass.entity.attributes.*",
                        "mapping": {
                            "type": "text",
                            "fields": {
                                "keyword": {"ignore_above": 1024, "type": "keyword"},
                            },
                        },
                    }
                }
            ],
            "properties": {
                "data_stream": {
                    "properties": {
                        "type": {"type": "constant_keyword", "value": "metrics"},
                        "dataset": {"type": "constant_keyword"},
                        "namespace": {"type": "constant_keyword"},
                    }
                },
                "hass": {
                    "type": "object",
                    "properties": {
                        "entity": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "keyword"},
                                "domain": {"type": "keyword"},
                                "friendly_name": {"type": "keyword"},
                                "name": {"type": "keyword"},
                                "attributes": {"type": "object", "dynamic": True},
                                "object": {
                                    "type": "object",
                                    "properties": {"id": {"type": "keyword", "time_series_dimension": True}},
                                },
                                "location": {"type": "geo_point"},
                                "value": {
                                    "type": "text",
                                    "fields": {"keyword": {"ignore_above": 1024, "type": "keyword"}},
                                },
                                "valueas": {
                                    "properties": {
                                        "string": {
                                            "type": "text",
                                            "fields": {"keyword": {"ignore_above": 1024, "type": "keyword"}},
                                        },
                                        "float": {"ignore_malformed": True, "type": "float"},
                                        "boolean": {"type": "boolean"},
                                        "datetime": {"type": "date"},
                                        "date": {"type": "date", "format": "strict_date"},
                                        "time": {
                                            "type": "date",
                                            "format": "HH:mm:ss.SSSSSS||time||strict_hour_minute_second||time_no_millis",
                                        },
                                        "integer": {"ignore_malformed": True, "type": "integer"},
                                    }
                                },
                                "platform": {"type": "keyword"},
                                "unit_of_measurement": {"type": "keyword"},
                                "state": {"properties": {"class": {"type": "keyword"}}},
                                "labels": {"type": "keyword"},
                                "area": {
                                    "type": "object",
                                    "properties": {
                                        "floor": {
                                            "type": "object",
                                            "properties": {
                                                "id": {"type": "keyword"},
                                                "name": {"type": "keyword"},
                                            },
                                        },
                                        "id": {"type": "keyword"},
                                        "name": {"type": "keyword"},
                                    },
                                },
                                "device": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "keyword"},
                                        "name": {"type": "keyword"},
                                        "class": {"type": "keyword"},
                                        "labels": {"type": "keyword"},
                                        "area": {
                                            "type": "object",
                                            "properties": {
                                                "floor": {
                                                    "type": "object",
                                                    "properties": {
                                                        "id": {"type": "keyword"},
                                                        "name": {"type": "keyword"},
                                                    },
                                                },
                                                "id": {"type": "keyword"},
                                                "name": {"type": "keyword"},
                                            },
                                        },
                                    },
                                },
                            },
                        }
                    },
                },
                "@timestamp": {"type": "date_nanos", "format": "strict_date_optional_time_nanos"},
                "tags": {"ignore_above": 1024, "type": "keyword"},
                "event": {
                    "properties": {
                        "action": {"type": "keyword", "ignore_above": 1024},
                        "type": {"ignore_above": 1024, "type": "keyword"},
                        "kind": {"ignore_above": 1024, "type": "keyword"},
                    }
                },
                "agent": {
                    "properties": {
                        "version": {"ignore_above": 1024, "type": "keyword"},
                    }
                },
                "host": {
                    "properties": {
                        "architecture": {"ignore_above": 1024, "type": "keyword"},
                        "location": {"type": "geo_point"},
                        "hostname": {"ignore_above": 1024, "type": "keyword"},
                        "name": {"ignore_above": 1024, "type": "keyword"},
                        "os": {"properties": {"name": {"ignore_above": 1024, "type": "keyword"}}},
                    }
                },
                "ecs": {"properties": {"version": {"ignore_above": 1024, "type": "keyword"}}},
            },
        },
        "settings": {
            "codec": "best_compression",
            "index.mode": "time_series",
            "mapping": {"total_fields": {"limit": "10000"}},
        },
        "lifecycle": {"data_retention": "365d"},
    },
    "composed_of": "metrics-homeassistant@custom",
    "ignore_missing_component_templates": "metrics-homeassistant@custom",
    "priority": 500,
    "data_stream": {},
    "version": 5,
}
