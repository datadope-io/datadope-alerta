# 2.4.2
* fix (notifier): error when running async (issue #2)
* fix (backend): logging error when running async
* fix (backend): alert processing failed if deduplication contained a '%' (issue #1)

# 2.4.1
* make reason value renderable
* support to provide auto close/resolve alert reason with autoCloseText/autoResolve attributes
* COLUMNS config can now be provided as environment variable
* do not use alert.text as default reason when recovering


# 2.4.0
* jira plugin: added support for remote configuration depending on a field (usually customer)
* support for synthetix-ssas

# 2.3.0
* New plugin to send alerts to JIRA.

# 2.2.1

* Contextualizer api: fixed to now parse the data as a string before sending it to the database.
* Alerts dependencies api: fixed to now parse the data as a string before sending it to the database.
* Contextualizer api tests
* Alerts dependencies api tests

# 2.2.0

* FIX: Environment processing now admits a key with a dict and a key as a dict field of the same dict.
* Alerts dependencies: data structure to store alerts dependencies in order to check if an alert is dependent of another alert.

# 2.1.0

* Inferred correlation: support for attribute inferredCorrelation. If received with an alert id, new alert is deduplicated with that alert.

# 2.0.0

* Change main package name to datadope_alerta
* Blackouts management plugin
* GCHAT notifier plugin
* Telegram notifier plugin
* Contextualizer API to manage (read, add, delete, update) the rules
  that will be used by the Notifier plugin.
* Notifier plugin to compare the rules stored in the database with
  the incoming alerts in order to enrich the alert's information.
* Zabbix plugin: when closing an alert, close all zabbix events associated to that alert.

# 1.1.0

* API contexts to read alerters information and to process an alert asynchronously
* Refactor: bgtasks moved to package first level

# 1.0.1

* Catch unique exception when creating alerter status.

# 1.0.0

Backend: Deduplicate using attribute `deduplication`
Asyncronous plugins implementation
