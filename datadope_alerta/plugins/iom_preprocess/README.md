iom_preprocess Alerta Plugin
============================

Standard alerta plugin that preprocess received alert to ensure IOMetrics specific attributes
have the expected format.

Current operations:

### Attribute `eventTags` must be a dictionary. 
If it is received as a string it expects to be a json dictionary representation,
and it is converted to dict. If conversion fails, received value is replaced by an empty dictionary.

### Replace eventTag values in other eventTags

For example, if these eventTags are received:

```yaml
EVENT_TAG1: A value
EVENT_TAG2: tag1 value is '{EVENT_TAG1}'
```

stored tags will be:

```yaml
EVENT_TAG1: A value
EVENT_TAG2: tag1 value is 'A value'
```

A function `regsub`may also be used to generate a tag value applying a regex to another tag:

For example, if the following tags are received:

```yaml
SOURCE_TAG: "process1 is not running. Error"
DESTINATION_TAG: "{regsub('SOURCE_TAG', '(.*) is not running.*', '\\1')}"
```

stored tags will be:

```yaml
SOURCE_TAG: "process 1 is not running. Error"
DESTINATION_TAG: "process1"
```

### Some special tags are removed from eventTags and stores as attributes

| Event tag                     | Corresponding attribute    |
|-------------------------------|----------------------------|
| DEDUPLICATION                 | deduplication              |
| ACTION_DELAY                  | actionDelay                |
| START_ACTION_DELAY_SECONDS    | actionDelay                |
| IGNORE_RECOVERY               | ignoreRecovery             |
| ALERTERS                      | alerters                   |
| AUTO_CLOSE_AT                 | autoCloseAt                |
| AUTO_CLOSE_AFTER              | autoCloseAfter             |
| CONDITION_RESOLVED_MUST_CLOSE | conditionResolvedMustClose |

### Manage action `resolve`

If `conditionResolvedMustClose` attribute is set to True, this plugin converts action `resolve` into
action `close`
