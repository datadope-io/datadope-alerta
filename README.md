# iometrics-alerta

## Backend: iometrics-alerta-backend-flexiblededup

Backend to connect to POSTGRESQL database that implements a special deduplication mechanism.

Standard deduplication provided by Alerta deduplicates if environment, resource, event and severity are the same.
Additionally, it correlates in the same case except if severity is different (apart from using `correlate` alert field).

With this backend an extra option is implemented to deduplicate alerts: having the same environment, two alerts 
deduplicate if they have the same value of attribute `deduplication` 
(if this attribute is part of the alert information).

To keep history of deduplicated alerts, alerts having `deduplication` attribute form the `value` field in each
history element data as `<resource>/<event>/<value>`, so a history element is appended to the alert information
if resource, event or value are modified.

A default value for deduplication may be provided with a configuration property: `DEFAULT_DEDUPLICATION_TEMPLATE`.
As the value should depend on the alert, the value is rendered as a jinja2 template providing the parameter `alert`
with the alert information. This value will be used only if alert doesn't provide a `deduplication` attribute.

For example:
`DEFAULT_DEDUPLICATION_TEMPLATE = '{{ alert.id }}'` => means no deduplication by attribute by default as each
alert has a different id. Only alerts providing `deduplication` attribute may deduplicate. 
(The same behavior is obtained if no ´DEFAULT_DEDUPLICATION_TEMPLATE` property is configured).

`DEFAULT_DEDUPLICATION_TEMPLATE = '{{ alert.environment }}-{{ alert.resource }}-{{ alert.event }}'` will 
provide a deduplication similar to the Alerta original deduplication

Backend may be configured to use original + new deduplication by attribute or only attribute deduplication. 
This behavior may be configured by alert using alert attribute `deduplicationType`. The default value for alerts
that don't provide this attribute is defined in configuration property `DEFAULT_DEDUPLICATION_TYPE` (default: 'both'). 
Possible values for the attribute or configuration are: 
* `both`: original + new deduplication by attribute will be executed.
* `attribute`: only new dediplication by attribute will be executed.

For `attribute` deduplication type, alerts with same environment, resource, event and severity will not be deduplicated
if attribute `deduplication` has a different value (or not provided).

Alert state transition flow is modified too: **Alerts are not reopened after being closed**. This means that, if
an alert is received that is duplicated or deduplicated with a current alert in 'closed' status, alert is not 
considered as duplicated and a new alert is created.

### Housekeeping 

Housekeeping in modified too, separating housekeeping of expired and closed alerts. Now the time to delete these
two kind of alerts is configured using different configuration properties:
* `DELETE_EXPIRED_AFTER`: alerta property now configures the time (in secodns) to delete expired alerts.
Default value is 7200. A value of 0 may be used to not deleting expired alerts.
* `DELETE_CLOSED_ALGETE`: new property to configure the time (in seconds) to delete closed alerts. If not configured,
the value of `DELETE_EXPIRED_AFTER` is used. Use a value of 0 to not deleting closed alerts.

### Configuration

To use this database backend, the database schema for connection scheme must be `flexiblededup`:

```
DATABASE_URL = 'flexiblededup://<pg_user>@<pg_server>/<pg_db>?connect_timeout=10&application_name=alerta'
```

## Asynchronous plugins

A mechanism to execute plugins asynchronously is provided. These plugins, named "alerters", may implement operations
to execute when a new alert is received and also when the alert is resolved (status moves to `Closed`).

Asynchronous execution is handled by celery python library using redis as celery broker and results backend.

Alerters must provide a class implementing `iometrics_alerta.plugins.iom_plugin.IOMAlerterPlugin`. 
This implementation defines the class that implements the alerter specific behaviour which is defined in another class
that has to implement `iometrics_alerta.plugins.Alerter` and its two main method `process_event` and `process_recovery`. 
These methods will execute the alerter operations when a new alert or a recovery is received.

Recovery operation will not be executed if a successful event operation has not been executed before for that alert.

If a recovery is received before the event operation starts executing (alert may be configured to have a delay from the
moment the alert is received and when the alerter event operation is launched), 
the event operation is cancelled so neither that event operation nor the recovery operation is executed.

If the recovery is received while event operation is being executed, recovery operation will wait until the event 
operation finishes. If it finishes ok, the recovery operation is launched. 
If it finishes with an error, possible pending retries of event operation are cancelled and recovery operation is not
launched.

## Special attribute list

| Attribute         | Type                  | Scope   | Meaning                                                        |
|-------------------|-----------------------|---------|----------------------------------------------------------------|
| deduplication     | string                | Global  |                                                                |
| deduplicationType | 'both' or 'attribute' | Global  |                                                                |
| alerters          | list \ json           | Global  |                                                                |
| eventTags         | dict \ json           | Global  |                                                                |
| autoCloseAt       | datetime              | Global  |                                                                |
| autoCloseAfter    | float (seconds)       | Global  | Fills / replaces `autoCloseAt` with last_received_time + value |
| ignoreRecovery    | bool                  | Alerter |                                                                |
| actionDelay       | float                 | Alerter |                                                                | 
| tasksDefinition   | dict \ json           | Alerter |                                                                |

Scope 'Alerter' means that the attribute value may be defined specifically for every alerter 
while 'Global' means that the same value will be used independently of the alerter.


## Deployment

### Package building

Project provides two python packages. One for the routing definition, and another for iometrics backend and plugins.
Routing must have a specific package name: `alerta_routing`. This is why it has to be build separately from the rest
of components.

To create the packages, go to the project folder, start the python virtual environment and issue the setup commands:

```shell
pipenv shell
python -m setup_routing bdist_wheel
python -m setup bdist_wheel
```

### Package installation

One the packages are build, they can be installed in an alerta python environment:

```shell
pipenv install iometrics-alerta/dist/alerta_routing-1.0.0-py3-none-any.whl
pipenv install iometrics-alerta/dist/iometrics_alerta-1.0.0-py3-none-any.whl
```

Or may be included in the Alerta deployment Pipfile.

## Full Alerta environment deployment

### Pipfile

Following, an example pipfile is provided to run Alerta server.

```
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
"alerta-server[postgres]" = "==8.7.0"  # master version has some patches so it may be better to use git repo
"celery[redis]" = "==5.2.7"
alerta = "==8.5.1"  # Client. Needed for periodic background tasks
python-dotenv = "*"
pyopenssl = "*"
zabbix-alerta = {git = "https://github.com/alerta/zabbix-alerta"}
bson = "*"  # Not needed with master version but needed for 8.7.0
requests = "*"
gunicorn = "*"
flower = "*"
python-dateutil = "*"

[dev-packages]

[requires]
python_version = "3.10"
```

IOMetrics packages may be included in this Pipfile to included in the Pipfile, pointing to the wheel files or to the
git repo.

### Configuration

An example configuration file is provided in [config_example/alertad.conf](config_example/alertad.conf).

To use the configuration, the environment var `ALERTA_SVR_CONF_FILE` must be established pointing to the configuration
file.

See [Alerta configuration documentation](https://docs.alerta.io/configuration.html) to get more information about
configuration options.

## Executing Alerta Server

Alerta server must be executed within the pip environment defined before, including the configuration file environment
var. The following command executes the server listing connections to port 8001:

```shell
alertad run --port 8001
```

The configuration file should include one or more users in `ADMIN_USERS` constant. To create these users in alerta, 
execute the following command:

```shell
alertad user --all
```

Once these users are created (they are created as admin users), you can log in the user interface (show below) 
and create the key to use for sending connecting to the server. 
This key must be configured in `SECRET_KEY` constant in configuration file.

### Requirements for background operations

A redis server must be available for alerta to run celery tasks in background. Redis server location must be 
configured in `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` constants in configuration file.

### User interface

To install the Alerta UI follow this procedure in a location of the server that will run the UI:

```shell
wget https://github.com/alerta/alerta-webui/releases/latest/download/alerta-webui.tar.gz
mkdir alerta-webui
cd alerta-webui
tar xzvf ../alerta-webui.tar.gz
cd dist
cp config.json.example config.json
-- edit config.json to point to alerta server url --
cat config.json
{"endpoint": "http://localhost:8001"}
```

You can now run the server for the UI. To run in port 8080:

```shell
python -m http.server 8000
```

### Background tasks execution

To execute background tasks for IOMetrics alerters plugins, at least one celery worker must be running.

To run a celery worker the same python environment for alerta may be used. Also, the same configuration file may be 
used (configuration file in config_example is prepared to run a celery worker consuming from all configured queues).

The command to run the worker might be (issued inside the pipenv environment):

```shell
celery -A "iometrics_alerta.plugins.bgtasks.celery" worker --loglevel=debug
```

This command will run a worker that will consume from all the queues defined in configuration file.

To run a worker to consume only specific queues include the parameter `-Q` with the list of queues to consume from.

See [celery worker command documentation](https://docs.celeryq.dev/en/stable/reference/cli.html#celery-worker) 
for other parameters that may be used for example to define the numer of concurrent
tasks that the worker will be able to run.

Apart from the workers, a celery beat process must also be started to manage scheduling of periodic tasks. 
The following periodic tasks will be executed:

| Task       | Interval config var                  | Operation                                                       |
|------------|--------------------------------------|-----------------------------------------------------------------|
| auto close | AUTO_CLOSE_TASK_INTERVAL (def 1 min) | Check if any alert is configured for auto close after some time |

The command to run celery beat process might be (issued inside the pipenv environment):

```shell
celery -A "iometrics_alerta.plugins.bgtasks.celery" beat -s /var/tmp/celerybeat-schedule --loglevel=debug
```


#### Celery Monitoring tool - Flower

A user interface to manage celery tasks and workers is available installing python library `flower` (included in the
example Pipfile provided before).

With this library installed, a server can be launched within the alert/celery pipenv:

```shell
celery -A "iometrics_alerta.plugins.bgtasks.celery" flower
```

Without parameters, the server will listent in port 5555. Use argument `--port` to change the port.

See [Flower documentation](https://flower.readthedocs.io/en/latest/index.html) for more information.


## Executing an Alerta client to send some alerts to server

To execute an alerta client, the python environment to use may be much simpler than the one needed for the server:

```
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
alerta = "*"

[dev-packages]

[requires]
python_version = "3.10"
```

Configuration file location is also defined using an environment var. 
In this case, the environment var to use is `ALERTA_CONF_FILE`.

The configuration file for the client is also much simpler than for the server. In this case, it is an ini file. 
For example:
```
[DEFAULT]
timezone = Europe/Madrid
output = json
key = <the server key>
endpoint = http://localhost:8001
sslverify = off
timeout = 300.0
debug = yes
```

Once the python environment is configured, an alert can be sent to the server:

```shell
alerta send -r web01 -e NodeDown -E Production -S Website -s major -t "Web server is down." -v ERROR
```

This `alerta` command supports a full bunch of arguments to customize the alert to be sent to the server. 
See [alerta client documentation](https://github.com/alerta/python-alerta-client).

# Development of alerters

## Manage alert and configuration information

### Getting a variable value using `Alerter.get_contextual_configuration`

Alerter base class provides the following utility method: 

`Alerter.get_contextual_configuration(var_definition: VarDefinition, alert: Alert, operation: str)`

using the following var definition structure:

```python
from dataclasses import dataclass
from typing import Any

@dataclass
class VarDefinition:
    var_name: str
    default: Any = None
    specific_event_tag: str = None
    var_type: type = None
    renderable = True
```

With this method, an alerter may get a configuration variable following a priority based steps.

Values are read from alert and application configuration in steps in the order below.

If the value is a dict, all steps are merged with priority from up to down.
If it is not a dict, the value is the return of the first step that provides a non-null value.

Variable names are not case-sensitive. CamelCase and snake_case formats are also considered the same
(*the_var*, *THE_VAR*, *THEVAR*, *thevar*, *TheVar*, *thevar*... correspond to the same variable).

Steps order:
  1. From event tags. Several tags are checked in order. Only the first one with a value is considered:
       - alert.attributes\['eventTags']\[<SPECIFIC_EVENT_TAG>]
       - alert.attributes\['eventTags']\[<ALERTER_NAME>_<VAR_NAME>]
       - alert.attributes\['eventTags']\[<VAR_NAME>]
  2. From attributes:
       - alert.attributes\[<ALERTER_NAME>]\[<VAR_NAME>]
       - alert.attributes\[<ALERTER_NAME>_<VAR_NAME>]
       - alert.attributes\[<VAR_NAME>]
  3. From alerter configuration:
       - config\[<ALERTER_NAME>_CONFIG\[<VAR_NAME>]]
  4. From alerter configuration as KEY:
       - config\[<ALERTER_NAME>_<VAR_NAME>]
  5. From default alerters configuration:
       - environ\[ALERTERS_DEFAULT_<VAR_NAME>]
       - config\[ALERTERS_DEFAULT_<VAR_NAME>]
  6. From default value if provided.

If the value obtained if a dict and an operation is provided, returned value will be the one
related to the operation. The keys for the dictionary should be the values of ALERTERS_TASK_BY_OPERATION
for each operation:

```python
ALERTERS_TASK_BY_OPERATION = {
    'process_event': 'new',
    'process_recovery': 'recovery'
}
```

For example, for the var 'my_var' may have two different values for new event operation and for recovery operation. 
In that case, it may be configured as an attribute this way:

```python
from alerta.models.alert import Alert

def create_alert(alert: Alert):
    alert.attributes['my_var'] = {"new": "value for new event", 'recovery': "value for recovery"}
```

For compatibility, a prefix 'new' or 'recovery' may be used to indicate a different value of a var for each operation.
When looking for a var value in alert attributes or in config first the var with the operation prefix is queried and,
if that var is not in the dict, then it is queried without the prefix.

So, we can achieve the same as the previous example defining two vars:

```python
from alerta.models.alert import Alert

def create_alert(alert: Alert):
     alert.attributes['new_my_var'] = "value for new event"
     alert.attributes['recovery_my_var'] = "value for recovery"
```

In either way, requesting the value of 'my_var' will return the correct value for the provided operation 
(`operation` is an argument to provide to the function).

### Rendering templated strings

By default, when requesting the value of a variable using the previous method, the obtained value is rendered as a 
Jinja2 template is the value is a string, a dict (all values of the dict as rendered recursively) or a list 
(all list elements are rendered recursively). 

`VarDefinition` provides a member field to avoid rendering a specific variable.

To render the jinja2 template 4 variables are provided to the renderer that can be used for templating:
* `alert`: Alert information as `Alert` object.
* `attributes`: Alert attributes. It is similar to `alert.attributes` but this variable is provided as a case-insensitive dict, so it should be used instead of `Alert.attributes`.
* `event_tags`: Value of `eventTags` attribute as a case-insensitive dict.
* `config`: Alerter configuration as a case-insensitive dict.

Alerters may use provided method of parent class `Alerter.render_template(self, template_path, alert)`. 
This method will return the result of rendering the template in the provided path with the four variables defined before.
