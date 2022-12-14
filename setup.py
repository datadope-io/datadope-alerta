from distutils.dir_util import remove_tree
import os
from setuptools import setup, find_packages


def read(filename):
    with open(os.path.join(os.path.dirname(__file__), filename)) as f:
        return f.read().strip()


try:
    remove_tree('build')
except:  # noqa
    pass

setup(
    name="iometrics-alerta",
    version=read('VERSION'),
    description='Alerta components for IOMetrics',
    long_description=read('README.md'),
    long_description_content_type='text/markdown',
    url='https://datadope.io',
    license='GPLv3',
    author='Victor Garcia',
    author_email='victor.garcia@datadope.io',
    package_dir={
        'alerta.database.backends': 'backend',
        'iometrics_alerta': 'iometrics_alerta'
    },
    # packages=[
    #     'alerta.database.backends.flexiblededup',
    #     'iometrics_alerta',
    # ] + ['iometrics_alerta.' + x for x in find_packages(exclude=['routing'])],
    packages=['alerta.database.backends.flexiblededup'] + find_packages(exclude=['iometrics_alerta.routing']),
    install_requires=[
        'alerta-server[postgres]~=8.7.0',
        'requests',
        'celery[redis]~=5.2.7'
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
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.7',
        'Topic :: System :: Monitoring',
    ],
    python_requires='>=3.7',
    entry_points={
        'alerta.plugins': [
            'iom_preprocess = iometrics_alerta.plugins.iom_preprocess.iom_preprocess_plugin:IOMAPreprocessPlugin',
            'email = iometrics_alerta.plugins.email.email_plugin:EMailPlugin',
            'test_async = iometrics_alerta.plugins.test_async.test_async_plugin:TestPlugin',
            'test = iometrics_alerta.plugins.test.test_plugin:TestPlugin',
        ]
    }
)