# Google Chat Alerter

This document contains information about the configuration and usage
of the GChat Alerter plugin present in `IOMetrics_Alerter`.

## Usage

The GChat Alerter plugin processes incoming alerts from any source and
send a message to one or more Google Chat rooms.

In order for the plugin to be able to send messages to the Google Chat
rooms, a Webhook must have pre-configured on those rooms.

## Tags

Among the normal tags that an incoming alert might have, containing the majority of its
information, there are a few that can be used to configure the behaviour of the plugin:

- `GCHAT`: A comma separated string containing the url to the Google Chat rooms.
  The url can be obtained when configuring the webhook on the chat room.
    - Example: `url_to_chat_1,url_to_chat_2,url_to_chat_3`.


- **HOST.HOST**: Name of the server that provoked the alert. If not present,
  this will be obtained from the `alert.resource`.


- **TRIGGER.NAME**: Name of the trigger that provoked the alert. If not present,
  this will be obtained from the `alert.service`.


- **TRIGGER.SEVERITY**: Severity of the trigger that provoked the alert. If not present,
  this will be obtained from the `alert.severity`. This will act as a key to obtain the 
  logo matching this severity from the logos' dict.


- **ALERTER_LOGOS**: `Dictionary` containing the url to the logos that will be used by the alerter
  process when sending the message to Google Chat.
    - Example: `{"zbxalerter": {"security": "url", "critical": "url", "major": "url", "minor": "url", "warning": "url",
              "indeterminate": "url", "informational": "url", "normal": "url", "ok": "url", "cleared": "url",
              "debug": "url", "trace": "url", "unknown": "url"}`


- **TYPE**: Type of the alerter that sent the alert. This will define the logos that
  will be used when sending the alert to Google Chat. This acts as a key to choose from
  the logos' dict. By default, `iometrics` will be used if no type is present.
    - Example: `zbxalerter` if the alert comes from zabbix or
      `incident_api` when the alert comes from incident_api.


- **ALERTER_TITLE**: Text representing the header of the message. `IOMetrics GChat Alerter` by default.


- **MAX_MESSAGE_CHARACTERS**: Max number of characters that the message sent might have. `3500` by default.