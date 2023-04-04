# Google Chat Alerter

This document contains information about the configuration and usage
of the GChat Alerter plugin present in `IOMetrics_Alerter`.

## Usage

The GChat Alerter plugin processes incoming alerts from any source and
send a message to one or more Google Chat rooms.

In order for the plugin to be able to send messages to the Google Chat
rooms, a Webhook must have pre-configured on those rooms.

## Configuration

The `config.yaml` file contains the default values used by the plugin
in its process. These values can be overwritten using the provided priority
hierarchy by the Alerta project. That'd be:

* Alerter config
* IOMetrics Alerta default config file
* Environment file or environment vars
* Information provided by the alert as tags or attributes

#### Default Values

* **alerter_title**: Text representing the header of the message. `IOMetrics GChat Alerter` by default.
* **alerter_logos**: `Dictionary` containing the url to the logos that will be used by the alerter
  process when sending the message to Google Chat.
    - Example: `{"iometrics": {"security": "url", "critical": "url", "major": "url", "minor": "url", "warning": "url",
      "indeterminate": "url", "informational": "url", "normal": "url", "ok": "url", "cleared": "url",
      "debug": "url", "trace": "url", "unknown": "url"}`

* **max_message_characters**: Max number of characters that the message sent might have. `3500` by default.

## Tags

Among the normal tags that an incoming alert might have, containing the majority of its
information, there are a few that can be used to alter the behaviour of the plugin:

- `GCHAT`: A comma separated string containing the url to the Google Chat rooms.
  The url can be obtained when configuring the webhook on the chat room.
  **This tag is mandatory in order for the plugin to work.**
    - Example: `url_to_chat_1,url_to_chat_2,url_to_chat_3`.


- `ALERTER_LOGOS`: If this tag is present, its content will be added to the default logos' dict
  present on the alerter configuration file.


- `ALERTER_TITLE`: If this tag is present, it will replace the default usage of the variable `alerter_title`
  present on the default config file.


- `MAX_MESSAGE_CHARACTERS`: If this tag is present, it will replace the default usage of the variable
  `max_message_characters`  present on the default config file.