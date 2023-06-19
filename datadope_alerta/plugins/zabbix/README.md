ZABBIX PLUGIN
==============

This plugin is used to associate events received from one or more Zabbix platforms with alerts in Alerta, 
and to ensure that, when an alert is closed in Alerta, all its associated Zabbix events are also closed.

**IMPORTANT**: Zabbix triggers must support **Manual Closing** to allow this plugin to close their associated events.

This plugin supports several Zabbix platforms sending events to a Datadope-Alerta platform.

This package provides two Alerta plugins actually:

#### zabbix

IOMetrics Alerter plugin to run asynchronously.

It is in charge of closing all the Zabbix platform events associated to an alert when the alert is closed in Alerta.

Due to deduplication, several events in a Zabbix source platform may be associated to the same alert.
Closing that alert must close all the corresponding events in Zabbix, to keep coherence between Zabbix events and
Alerta alerts 


#### zabbix_base

Standard plugin (based on Alerta `PluginBase`).

This plugin has two functions:
* It is in charge of configuring previous plugin when an alert is received from a supported platform.
* It stores the reference of the event in the source Zabbix platform, associated to the id of the alert in IOMetrics Alerta.

## Configuration

These are the configuration parameters needed by these plugins:

| Parameter                       | default                   | Meaning                                                                                                                                                                    |
|---------------------------------|---------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| platform_field                  | origin                    | Field or attribute of the alert to use to obtain the platform associated to the alert                                                                                      |
| supported_platforms             | \[zabbix\]                | List of supported platforms. Only alerts received from that platforms will be processed by this plugin                                                                     |
| <platform>_reference_attributes | \[zabbixEventId,eventId\] | For each platform, these are the attributes to use for obtaining the event reference in the zabbix platform. These attributes are evaluated in order until getting a value | 
| <platform>_connection           |                           | For each supported platform, an object with the configuration needed to connect to that platform                                                                           |


`<platform>_connection` configuration objects will have the following parameters:

| Parameter  | default | Meaning                                                                         |
|------------|---------|---------------------------------------------------------------------------------|
| url        |         | Zabbix platform web url                                                         |
| api_token  |         | api_token to authenticate to Zabbix. If provided, user and password are ignored |
| user       |         | user to connect to Zabbix. If not provided, api_token must be provided          |
| password   |         | password to connect to Zabbix. If not provided, api_token must be provided      |                                                                        |
| verify_ssl | true    | false to avoid ssl certificate validation                                       | 
| timeout    | 12.1    | Connection and read timeout                                                     |

As for all Datadope-Alerta plugins, plugin configuration must be provided as a dict with the key `ZABBIX_CONFIG` and 
it may be provided as system configuration in `alertad.conf` file:

```python
ZABBIX_CONFIG = {
    "platform_field": "origin",
    "supported_platforms": "zabbix",
    "zabbix_reference_attributes": [
        "zabbixEventId",
        "eventId"
    ]
}
```

or by environment values:

```shell
ZABBIX_CONFIG__SUPPORTED_PLATFORMS=zabbix
ZABBIX_CONFIG__ZABBIX_REFERENCE_ATTRIBUTES=zabbixEventId,eventId
ZABBIX_CONFIG__ZABBIX_CONNECTION={"url":"http://localhost:8080","api_token":"the api token","verify_ssl":false}
```

Both methods may be used at the same time, obtaining the configuration as the merge of both configurations, having
configuration by environment higher priority.

## Zabbix configuration to send events to Datadope Alerta

A mediatype must be configured in Zabbix to connect to Alerta API to send events and actions.

A working webhook is provided in [alerta-mediatype-definition.yaml](alerta-mediatype-definition.yaml).
Fill in the placeholders and modify the parameters as needed to customize it to the final system.

An action and a user have to be configured in Zabbix to use this mediatype.
