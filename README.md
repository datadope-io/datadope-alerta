# iometrics-alerta

**WARNING**: This is a WIP version of the project. It is under construction so important modifications
may (and will) be done before releasing first version.

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
(The same behavior is obtained if no `DEFAULT_DEDUPLICATION_TEMPLATE` property is configured).

`DEFAULT_DEDUPLICATION_TEMPLATE = '{{ alert.environment }}-{{ alert.resource }}-{{ alert.event }}'` will 
provide a deduplication similar to the Alerta original deduplication

Backend may be configured to use original + new deduplication by attribute or only attribute deduplication. 
This behavior may be configured by alert using alert attribute `deduplicationType`. The default value for alerts
that don't provide this attribute is defined in configuration property `DEFAULT_DEDUPLICATION_TYPE` (default: 'both'). 
Possible values for the attribute or configuration are: 
* `both`: original + new deduplication by attribute will be executed.
* `attribute`: only new deduplication by attribute will be executed.

For `attribute` deduplication type, alerts with same environment, resource, event and severity will not be deduplicated
if attribute `deduplication` has a different value (or not provided).

Alert state transition flow is modified too: **Alerts are not reopened after being closed**. This means that, if
an alert is received that is duplicated or deduplicated with a current alert in 'closed' status, alert is not 
considered as duplicated and a new alert is created.

### Housekeeping 

Housekeeping in modified too, separating housekeeping of expired and closed alerts. Now the time to delete these
two kind of alerts is configured using different configuration properties:
* `DELETE_EXPIRED_AFTER`: alerta property now configures the time (in seconds) to delete expired alerts.
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

| Attribute               | Type                  | Scope   | Meaning                                                                                          |
|-------------------------|-----------------------|---------|--------------------------------------------------------------------------------------------------|
| deduplication           | string                | Global  |                                                                                                  |
| deduplicationType       | 'both' or 'attribute' | Global  |                                                                                                  |
| alerters                | list \ json           | Global  |                                                                                                  |
| eventTags               | dict \ json           | Global  |                                                                                                  |
| autoCloseAt             | datetime              | Global  |                                                                                                  |
| autoCloseAfter          | float (seconds)       | Global  | Fills / replaces `autoCloseAt` with last_received_time + value                                   |
| ignoreRecovery          | bool                  | Alerter |                                                                                                  |
| actionDelay             | float                 | Alerter |                                                                                                  | 
| tasksDefinition         | dict \ json           | Alerter |                                                                                                  |
| repeatMinInterval       | dict \ json           | Alerter | Min interval from last repetition to send a new repeat event                                     |
| recoveryActions         | dict \ json           | Global  | Recovery actions definition                                                                      |

Scope 'Alerter' means that the attribute value may be defined specifically for every alerter 
while 'Global' means that the same value will be used independently of the alerter.

## Recovery actions

A plugin is provided to execute recovery actions before alerting. 

This plugin will use one of the configured recovery actions providers to execute some recovery action before alerting.
Available recovery actions are read from python `entry_points` with type `alerta.recovery_actions.providers`.

AWX provider is provided as part of this python library.

Recovery action plugin is executed if the attribute `recoveryActions` is present as part of an alert.
In this case, configured alerters are not launched after receiving the alert but this recovery actions plugins is 
launched instead. It will be in charge of executing the configured recovery actions using the selected provider.
After actions are executed it will leave some time to the alert to be recovered. If the alert is not closed during
that time, it will launch the configured alerters.


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
pipenv install iometrics-alerta/dist/alerta_routing-1.0.1-py3-none-any.whl
pipenv install iometrics-alerta/dist/iometrics_alerta-1.0.1-py3-none-any.whl
```

Or may be included in the Alerta deployment Pipfile.

## Full Alerta environment deployment

**Minimum Python version is 3.10**

### Pipfile

Following, an example pipfile is provided to run Alerta server.

```
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
alerta-server = {extras=["postgres"], git = "https://github.com/datadope-io/alerta.git"}
"celery[redis]" = "==5.2.7"
alerta = "==8.5.1"  # Client. Needed for periodic background tasks
python-dotenv = "*"
pyopenssl = "*"
# zabbix-alerta = {git = "https://github.com/alerta/zabbix-alerta"}
# bson = "*"  # Not needed with master version but needed for 8.7.0
requests = "*"
gunicorn = "*"
flower = "*"
python-dateutil = "*"

[dev-packages]

[requires]
python_version = "3.10"
```

IOMetrics packages may be included in this Pipfile pointing to the wheel files or to the git repo.

### Configuration

An example configuration file is provided in [config_example/alertad.conf](config_example/alertad.conf).

To use the configuration, the environment var `ALERTA_SVR_CONF_FILE` must be established pointing to the configuration
file.

See [Alerta configuration documentation](https://docs.alerta.io/configuration.html) to get more information about
configuration options.

#### Logging configuration

Logging format strings can use the following fields to enrich log information:

* alert_id: id of the alert being handled.
* alerter_name: name of the alertar handling the alert.
* operation: 'new', 'repeat' or 'recovery' will be the possible values for this field.


If any of those field is not available, '-' will be printed instead.

These fields can be used for any logger associated to alerta server and in celery task logger. 
They can't be used in celery logger.

Apart from previous fields, celery task logger can also use the following fields:

* task_id: id of celery task that is running.
* task_name: name os celery task that is running.

Example of format string configuration variable: 

```python
CELERYD_TASK_LOG_FORMAT = \
    "%(asctime)s|%(levelname)s|%(alert_id)s|%(alerter_name)s|%(operation)s|%(message)s" \
    "[[%(name)s|%(processName)s][%(task_name)s|%(task_id)s]]"

```

#### Configuration for Recovery Actions Providers

Use `RA_PROVIDER_<provider>_CONFIG` to provide a dictionary with the provider configuration. 
For example `RA_PROVIDER_AWX_CONFIG` will be the expected configuration for awx provider.

Configuration may be provided in alertad.conf config file and/or environment variables. If both
provided, a merge will be done, having more priority the configuration from environment variables.


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

Without parameters, the server will listen in port 5555. Use argument `--port` to change the port.

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

### Installation using docker-compose

A full working environment can be launched running [docker-compose.yml](deployment/docker-compose.yml) file 
provided in [deployment](deployment) folder.

To use this docker-compose file an environment file with name `.env` must be generated in the same deployment folder.
An example file [example.env](deployment/example.env) is provided. It can be copied as `.env` and modified to
use specific secrets.

Once `.env` file si available, docker-compose can be executed from [deployment](deployment) folder using:

```shell
VERSION=$(cat ../VERSION) docker-compose up -d
```

This command will create the following containers:
* iometrics-alerta-postgres
* iometrics-alerta-redis
* iometrics-alerta-server (listening in port 8001 of host computer, port 8000 in container)
* iometrics-alerta-webui (listening in port 8000 of host computer and in container)
* iometrics-alerta-celery-worker-1
* iometrics-alerta-celery-beat (schedules periodic background tasks)
* iometrics-alerta-celery-flower (UI to manage celery tasks listening in port 5555 of host computer and in container)

The number of celery workers to run may be modified using:

```shell
VERSION=$(cat ../VERSION) docker-compose up -d --scale celery-worker=2
```

In this case, 2 celery workers will run.

Default configuration for alerta and celery environments is obtained from [config_example/alertad.conf](config_example/alertad.conf).
Most of the configuration may be overriden using environment vars. An example of environment file is located at [deployment/example.env](deployment/example.env) file.

### Installation using dockers

#### Image generation

Three docker files are provided to create images for: 
* alerta server: Dockerfile.alerta
* celery workers, beat and flower services: Dockerfile.celery
* alerta webui: Dockerfile.webui

Dockerfiles and needed files to build dockers are available in [deployment](deployment) folder.

To create the images:

```shell
docker build --build-arg VERSION=$(cat VERSION) -f deployment/alerta.dockerfile -t iometrics-alerta-server:$(cat VERSION)  .
docker build --build-arg VERSION=$(cat VERSION) -f deployment/celery.dockerfile -t iometrics-alerta-celery:$(cat VERSION) .
docker build -f deployment/webui.dockerfile -t iometrics-alerta-webui .
```

These commands must be executed from repository root folder.

Alerta and celery dockers will include [config files in config_example](config_example) 
but environment vars should be provided when running dockers to provide the actual 
configuration for the installation environment. These env vars can be provided with
`-e` and/or `--env-file` docker run arguments.

To run a full environment:

```shell
docker run -d --rm --name iometrics-alerta-server --env-file .env -e "ALERTA_SVR_CONF_FILE=/etc/iometrics-alerta/alertad.conf" -p 8001:8000 iometrics-alerta-server
docker run -d --rm --name iometrics-alerta-celery-worker1 --env-file .env -e "ALERTA_SVR_CONF_FILE=/etc/iometrics-alerta/alertad.conf" iometrics-alerta-celery
docker run -d --rm --name iometrics-alerta-celery-worker2 --env-file .env -e "ALERTA_SVR_CONF_FILE=/etc/iometrics-alerta/alertad.conf" iometrics-alerta-celery
docker run -d --rm --name iometrics-alerta-celery-beat --env-file .env -e "ALERTA_SVR_CONF_FILE=/etc/iometrics-alerta/alertad.conf" iometrics-alerta-celery entry_point_celery_beat.sh
docker run -d --rm --name iometrics-alerta-celery-flower --env-file .env -e "ALERTA_SVR_CONF_FILE=/etc/iometrics-alerta/alertad.conf" -p 5555:5555 iometrics-alerta-celery entry_point_celery_flower.sh
docker run -d --rm --name iometrics-alerta-webui -p 8000:8000 iometrics-alerta-webui
```

These configuration expects to have a running postgres and redis. The connection with them
is done using env vars `DATABASE_URL` and `CELERY_BROKER_URL`.

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
related to the operation. The keys for the dictionary should be the values of [ALERTERS_KEY_BY_OPERATION](iometrics_alerta/__init__.py)
for each operation:

```python
ALERTERS_KEY_BY_OPERATION = {
    'process_event': 'new',
    'process_recovery': 'recovery',
    'process_repeat': 'repeat',
    'process_action': 'action'
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
