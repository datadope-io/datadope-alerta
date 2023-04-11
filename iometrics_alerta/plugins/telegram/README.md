iom_preprocess Alerta Plugin
============================

Standard alerta plugin that preprocess received alert to ensure IOMetrics specific attributes
have the expected format.

Current operations:

### Attribute `eventTags` must be a dictionary.

If it is received as a string it expects to be a json dictionary representation,
and it is converted to dict. If conversion fails, received value is replaced by an empty dictionary.
