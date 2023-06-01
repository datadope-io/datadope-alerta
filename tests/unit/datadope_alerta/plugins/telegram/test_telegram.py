from unittest.mock import patch

import pytest  # noqa
import requests
from alerta import create_app
from alerta.models.alert import Alert

from datadope_alerta.plugins.telegram.telegram import TelegramPlugin


class TestTelegramPlugin:
    @pytest.fixture()
    def get_app(self):
        config = {
            'TESTING': True,
            'AUTH_REQUIRED': False,
            'PLUGINS': ['telegram']
        }

        app = create_app(config)

        with app.app_context():
            yield

    @pytest.fixture()
    def get_alerter(self, get_app):
        return TelegramPlugin().get_alerter_class()('telegram')

    @pytest.fixture()
    def get_alert(self) -> Alert:
        return Alert(
            resource='test_resource',
            event='test_event',
            environment='test_environment',
            severity='major',
            service='test_service',
            group='test_group',
            value='test_message',
            attributes={
                'alerters': 'telegram,test_async',  # noqa
                'eventTags': '{"TELEGRAM_CHATS":"@pruebaDataDope","TELEGRAM_SOUND": 0,"BOTS":"DataDope_bot"}'
            },
            text='test_text')

    # @pytest.fixture()
    # def get_alert_exception(self) -> Alert:
    #     return Alert(
    #         resource='test_resource',
    #         event='test_event',
    #         environment='test_environment',
    #         severity='major',
    #         service='test_service',
    #         group='test_group',
    #         value='test_message',
    #         attributes={
    #             'alerters': 'telegram,test_async',  # noqa
    #             'eventTags': '{"TELEGRAM_CHATS":"@pruebaDataDope","TELEGRAM_SOUND": 0,"BOTS":"DataDope_bot"}'
    #         },
    #         text='test_text')

    @pytest.fixture()
    def get_alert_split_message(self) -> Alert:
        return Alert(
            resource='test_resource',
            event='test_event',
            environment='test_environment',
            severity='major',
            service='test_service',
            group='test_group',
            value='test_message ',
            attributes={
                'alerters': 'telegram,test_async',  # noqa
                'eventTags': '{"TELEGRAM_CHATS":"@pruebaDataDope","TELEGRAM_SOUND": 0,"BOTS":"DataDope_bot"}'
            },
            text='Python is a high-level programming language that was first released in 1991 by Guido van Rossum. '
                 'It is an interpreted language that is widely used for web development, scientific computing, data '
                 'analysis, artificial intelligence, and many other applications. Python is popular among developers '
                 'due to its simplicity, readability, and large standard library. Python is an open-source language '
                 'that is available for free on various platforms, including Windows, macOS, and Linux. The language '
                 'has a simple and elegant syntax that makes it easy to learn and understand. Unlike other programming '
                 'languages, Python doesnt require a lot of boilerplate code, making it possible to write programs '
                 'quickly and efficiently. One of the key features of Python is its extensive standard library, which '
                 'contains a vast collection of modules and packages that provide a wide range of functionality. The '
                 'standard library includes modules for working with files, networking, regular expressions, databases,'
                 ' scientific computing, and much more. Additionally, Python has a vast ecosystem of third-party '
                 'packages that can be installed using the pip package manager. Python is an object-oriented '
                 'language, which means that everything in Python is an object. Python supports multiple '
                 'programming paradigms, including procedural, functional, and object-oriented programming. '
                 'Python also supports dynamic typing, which means that variables dont need to be declared '
                 'before use. This makes it easy to write code quickly, but it also means that its '
                 'essential to write well-structured code to avoid errors. Python is often used for web development, '
                 'and it has several popular web frameworks, including Django, Flask, Pyramid, and Bottle. These '
                 'frameworks provide developers with tools and libraries to build web applications quickly and'
                 ' efficiently. Django is particularly popular among developers due to its batteries-included '
                 'approach, which means that it includes everything you need to build a web application out of the box.'
                 'Python is also popular for scientific computing and data analysis. The language has several librarie'
                 's that provide advanced data analysis capabilities, including NumPy, SciPy, Pandas, and Matplotlib.'
                 ' These libraries enable developers to perform complex data analysis tasks efficiently.'
                 'Python is a high-level programming language that was first released in 1991 by Guido van Rossum. '
                 'It is an interpreted language that is widely used for web development, scientific computing, data '
                 'analysis, artificial intelligence, and many other applications. Python is popular among developers '
                 'due to its simplicity, readability, and large standard library. Python is an open-source language '
                 'that is available for free on various platforms, including Windows, macOS, and Linux. The language '
                 'has a simple and elegant syntax that makes it easy to learn and understand. Unlike other programming '
                 'languages, Python doesnt require a lot of boilerplate code, making it possible to write programs '
                 'quickly and efficiently. One of the key features of Python is its extensive standard library, which '
                 'contains a vast collection of modules and packages that provide a wide range of functionality. The '
                 'standard library includes modules for working with files, networking, regular expressions, databases,'
                 ' scientific computing, and much more. Additionally, Python has a vast ecosystem of third-party '
                 'packages that can be installed using the pip package manager. Python is an object-oriented '
                 'language, which means that everything in Python is an object. Python supports multiple '
                 'programming paradigms, including procedural, functional, and object-oriented programming. '
                 'Python also supports dynamic typing, which means that variables dont need to be declared '
                 'before use. This makes it easy to write code quickly, but it also means that its '
                 'essential to write well-structured code to avoid errors. Python is often used for web development, '
                 'and it has several popular web frameworks, including Django, Flask, Pyramid, and Bottle. These '
                 'frameworks provide developers with tools and libraries to build web applications quickly and'
                 ' efficiently. Django is particularly popular among developers due to its batteries-included '
                 'approach, which means that it includes everything you need to build a web application out of the box.'
                 'Python is also popular for scientific computing and data analysis. The language has several librarie'
                 's that provide advanced data analysis capabilities, including NumPy, SciPy, Pandas, and Matplotlib.'
                 ' These libraries enable developers to perform complex data analysis tasks efficiently.')

    @pytest.fixture()
    def get_alert_with_empty_chats_list(self) -> Alert:
        return Alert(
            resource='test_resource',
            event='test_event',
            environment='test_environment',
            severity='major',
            service='test_service',
            group='test_group',
            value='test_message',
            attributes={
                'alerters': 'telegram,test_async',  # noqa
                'eventTags': '{"TELEGRAM_SOUND": 0,"BOTS":"DataDope_bot"}'
            },
            text='test_text')

    @pytest.fixture()
    def get_alert_with_empty_telegram_sound(self) -> Alert:
        return Alert(
            resource='test_resource',
            event='test_event',
            environment='test_environment',
            severity='major',
            service='test_service',
            group='test_group',
            value='test_message',
            attributes={
                'alerters': 'telegram,test_async',  # noqa
                'eventTags': '{"TELEGRAM_CHATS":"@pruebaDataDope","BOTS":"DataDope_bot"}'
            },
            text='test_text')

    @pytest.fixture()
    def get_alert_with_empty_bots(self) -> Alert:
        return Alert(
            resource='test_resource',
            event='test_event',
            environment='test_environment',
            severity='major',
            service='test_service',
            group='test_group',
            value='test_message',
            attributes={
                'alerters': 'telegram,test_async',  # noqa
                'eventTags': '{"TELEGRAM_CHATS":"@pruebaDataDope"}'
            },
            text='test_text')

    @pytest.fixture()
    def get_alert_with_different_bot(self) -> Alert:
        return Alert(
            resource='test_resource',
            event='test_event',
            environment='test_environment',
            severity='major',
            service='test_service',
            group='test_group',
            value='test_message',
            attributes={
                'alerters': 'telegram,test_async',  # noqa
                'eventTags': '{"TELEGRAM_CHATS":"@pruebaDataDope","BOTS":"prueba"}'
            },
            text='test_text')

    @pytest.fixture()
    def get_alert_bot_tag_wrong(self) -> Alert:
        return Alert(
            resource='test_resource',
            event='test_event',
            environment='test_environment',
            severity='major',
            service='test_service',
            group='test_group',
            value='test_message',
            attributes={
                'alerters': 'telegram,test_async',  # noqa
                'eventTags': '{"TELEGRAM_CHATS":"@pruebaDataDope","TELEGRAM_SOUND": 0,"BOOOTS":"DataDope_bot"}'  # noqa
            },
            text='test_text')

    def test_get_default_configuration(self, get_alerter):
        config = get_alerter.get_default_configuration()
        assert isinstance(config, dict)
        assert config.get('bots') is not None
        assert config.get('url') is not None
        assert config.get('message_send_timeout_s') is not None
        assert config.get('max_message_characters') is not None

    def test_process_repeat(self, get_alerter, get_alert):
        alerter = get_alerter

        alert = get_alert
        result = alerter.process_repeat(alert=alert, reason='test_reason')
        assert result == (True, {})

    def test_process_action(self, get_alerter, get_alert):
        alerter = get_alerter
        alert = get_alert
        result = alerter.process_action(alert=alert, reason='test_reason', action='process_recovery')
        assert result == (True, {})

    @pytest.mark.parametrize(('telegram_alert', 'response_value'), [(get_alert, 200), (get_alert_with_empty_chats_list,
                                                                                       500),
                                                                    (get_alert_with_empty_telegram_sound, 200),
                                                                    (get_alert_with_empty_bots, 500),
                                                                    (get_alert_with_different_bot, 500),
                                                                    (get_alert_bot_tag_wrong, 500)])
    def test_process_recovery_and_event(self, get_alerter, telegram_alert, response_value, request, requests_mock):
        alerter = get_alerter
        alert = request.getfixturevalue(telegram_alert.__name__)

        requests_mock.get(
            url='https://api.telegram.org/bot%s/sendMessage' % alerter.config['bots']['DataDope_bot']['token'],
            status_code=response_value,
            json={'ok': True, 'result': {'message_id': 1, 'from': {'id': 1, 'is_bot': True, 'first_name': 'DataDope'}}}
        )

        if telegram_alert.__name__ == 'get_alert' or telegram_alert.__name__ == \
                'get_alert_with_empty_telegram_sound':
            result_recovery, _ = alerter.process_recovery(alert, reason='test_reason')
            result_event, _ = alerter.process_event(alert, reason='test_reason')
            assert result_recovery is True
            assert result_event is True
        elif telegram_alert.__name__ == 'get_alert_with_empty_chats_list' or telegram_alert.__name__ == \
                'get_alert_with_empty_bots' or telegram_alert.__name__ == 'get_alert_with_different_bot' or \
                telegram_alert.__name__ == 'get_alert_bot_tag_wrong':
            result_recovery, _ = alerter.process_recovery(alert, reason='test_reason')
            result_event, _ = alerter.process_event(alert, reason='test_reason')
            assert result_recovery is False
            assert result_event is False

    def test_process_recovery_and_event_json_not_ok(self, get_alerter, get_alert, requests_mock):
        alerter = get_alerter
        alert = get_alert

        requests_mock.get(
            url='https://api.telegram.org/bot%s/sendMessage' % alerter.config['bots']['DataDope_bot']['token'],
            status_code=200,
            json={
                "error": {
                    "errors": [
                        {
                            "reason": "invalid",
                            "message": "Invalid value for...",
                            "domain": "global"
                        }
                    ],
                    "warnings": [
                        {
                            "reason": "validation",
                            "message": "The GTIN is required.",
                            "domain": "content.ContentErrorDomain"
                        }
                    ],
                    "code": "400",
                    "message": "Invalid..."
                }
            }
        )

        result_recovery, _ = alerter.process_recovery(alert, reason='test_reason')
        result_event, _ = alerter.process_event(alert, reason='test_reason')

        assert result_recovery is True
        assert result_event is True

    def test_process_recovery_and_event_split_message(self, get_alerter, get_alert_split_message, requests_mock):
        alerter = get_alerter
        alert = get_alert_split_message

        requests_mock.get(
            url='https://api.telegram.org/bot%s/sendMessage' % alerter.config['bots']['DataDope_bot']['token'],
            status_code=200,
            json={'ok': True, 'result': {'message_id': 1, 'from': {'id': 1, 'is_bot': True, 'first_name': 'DataDope'}}}
        )

        result_recovery, _ = alerter.process_recovery(alert, reason='test_reason')
        result_event, _ = alerter.process_event(alert, reason='test_reason')

        assert result_recovery is True
        assert result_event is True

    def test_process_recovery_and_event_exception(self, get_alerter, get_alert):
        alerter = get_alerter
        alert = get_alert

        with patch('requests.get') as post_mock:
            post_mock.side_effect = requests.exceptions.RequestException()
            with pytest.raises(requests.exceptions.RequestException):
                alerter.process_recovery(alert, reason='test_reason')
