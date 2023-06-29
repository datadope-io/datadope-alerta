import os
from distutils.dir_util import remove_tree

from setuptools import setup, find_packages


def read(filename):
    with open(os.path.join(os.path.dirname(__file__), filename)) as f:
        return f.read().strip()


try:
    remove_tree('build')
except:  # noqa
    pass

setup(
    name="datadope-alerta",
    version=read('VERSION'),
    description='Alerta components customized by Datadope',
    long_description=read('README.md'),
    long_description_content_type='text/markdown',
    url='https://datadope.io',
    license='GPLv3',
    author='Victor Garcia',
    author_email='victor.garcia@datadope.io',
    packages=find_packages(exclude=['tests']),
    install_requires=[
        'alerta-server[postgres] @ git+https://github.com/datadope-io/alerta.git',
        'requests>=2.31.0',
        'celery[redis]~=5.2.7',
        'pyzabbix==1.3.0'
    ],
    include_package_data=True,
    zip_safe=False,
    classifiers=[
        # 'Development Status :: 5 - Production/Stable',
        'Development Status :: 4 - Beta',
        'Environment :: Web Environment',
        'Environment :: Plugins',
        'Framework :: Flask',
        'Intended Audience :: Information Technology',
        'Intended Audience :: System Administrators',
        'Intended Audience :: Telecommunications Industry',
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.10'
        'Topic :: System :: Monitoring',
    ],
    python_requires='>=3.10',
    entry_points={
        'alerta.database.backends': [
            'iometrics = datadope_alerta.backend.flexiblededup'
        ],
        'alerta.routing': [
            'rules = datadope_alerta.routing.routing:rules'
        ],
        'alerta.plugins': [
            'iom_preprocess = datadope_alerta.plugins.iom_preprocess.iom_preprocess_plugin:IOMAPreprocessPlugin',
            'blackout_manager = datadope_alerta.plugins.blackouts.plugin:BlackoutManager',
            'recovery_actions = datadope_alerta.plugins.recovery_actions.plugin:RecoveryActionsPlugin',
            'notifier = datadope_alerta.plugins.notifier.notifier_plugin:NotifierPlugin',
            'email = datadope_alerta.plugins.email.email_plugin:EMailPlugin',
            'test_async = datadope_alerta.plugins.test_async.test_async_plugin:TestPlugin',
            'telegram = datadope_alerta.plugins.telegram.telegram:TelegramPlugin',
            'test = datadope_alerta.plugins.test.test_plugin:TestPlugin',
            'gchat = datadope_alerta.plugins.gchat.gchat_plugin:GChatPlugin',
            'zabbix_base = datadope_alerta.plugins.zabbix.zabbix_plugin:ZabbixBasePlugin',
            'zabbix = datadope_alerta.plugins.zabbix.zabbix_plugin:ZabbixIOMPlugin'        ],
        'alerta.recovery_actions.providers': [
            'awx = datadope_alerta.plugins.recovery_actions.providers.awx:Provider',
            'test = datadope_alerta.plugins.recovery_actions.providers.test:TestProvider'
        ],
        'alerta.blackout.providers': [
            'internal = datadope_alerta.plugins.blackouts.providers.internal:Provider'
        ]
    }
)
