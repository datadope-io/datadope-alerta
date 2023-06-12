# 2.0.0

* Change main package name to datadope_alerta
* Blackouts management plugin
* GCHAT notifier plugin
* Telegram notifier plugin
* Contextualizer API to manage (read, add, delete, update) the rules
  that will be used by the Notifier plugin.
* Notifier plugin to compare the rules stored in the database with
  the incoming alerts in order to enrich the alert's information.

# 1.1.0

* API contexts to read alerters information and to process an alert asynchronously
* Refactor: bgtasks moved to package first level

# 1.0.1

* Catch unique exception when creating alerter status.

# 1.0.0

Backend: Deduplicate using attribute `deduplication`
Asyncronous plugins implementation
