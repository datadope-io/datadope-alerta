# CMDB Context

This document contains information about the configuration and usage
for the CMDB Context plugin present in `IOMetrics_Alerter`.

## Usage

The plugin retrieves information from the CMDB regarding the watchers and the functional information
configured for the alert's resource, if present.

If one or more `watchers` were configured for the alert's resource, they will be added to the alert's attributes
in order to use the `Email` plugin to email these watchers.

## Configuration

The plugin needs certain values to work as intended. These values can be specified as
environment values or in the datadope_alerta global configuration.


#### Default Values
    CMDB_GATEWAY_URL: the url to the cmdb gateway, used for the api calls to the cmdb.
    CDMDB_GATEWAY_API_KEY: the api_key for the cmdb gateway.
    CMDB_GATEWAY_VERIFY_SSL: used to specify if the connection is to be made with ssl verification.