import logging

from unittest.mock import patch

# noinspection PyPackageRequirements
import pytest

from datadope_alerta.plugins.event_tags_parser import EventTagsParser, MessageParserByTags

@pytest.fixture
def test_tags():
    yield {
        "TAG1": "value1",
        "TAG2": "pre {TAG1} post",
        "TAG_FOR_REGSUB": "first second third",
        "TAG_REGSUB": 'pre {regsub("TAG_FOR_REGSUB", "^(.*) second third", "\\1")} post'
    }


@pytest.fixture
def logger():
    yield logging.getLogger('datadope_alerta.plugins.event_tags_parser')


@patch('logging.Logger.debug')
def test_replace_tags(mock_logger_debug, test_tags, logger):
    value = "pre {TAG1} post"
    replaced = EventTagsParser.replace_tags(value, test_tags, 'test', logger)
    mock_logger_debug.assert_called_once_with("REPLACED '%s' BY '%s' FOR TAG '%s'", '{TAG1}', 'value1', 'test')
    assert replaced == "pre value1 post"


@patch('logging.Logger.debug')
def test_replace_tags_regsub(mock_logger_debug, test_tags, logger):
    value = 'pre {regsub("TAG_FOR_REGSUB", "^(.*) second third", "\\1")} post'
    replaced = EventTagsParser.replace_tags(value, test_tags, 'test', logger)
    mock_logger_debug.assert_called_once_with("REPLACED FUNC '%s' BY '%s' FOR TAG '%s'",
                                              '{regsub("TAG_FOR_REGSUB", "^(.*) second third", "\\1")}',
                                              'first', 'test')
    assert replaced == "pre first post"


@patch('logging.Logger.debug')
@patch('logging.Logger.warning')
def test_replace_tags_regsub_non_existing(mock_logger_warning, mock_logger_debug, test_tags, logger):
    value = 'pre {regsub("TAG_NON_EXISTING", "^(.*) second third", "\\1")} post'
    replaced = EventTagsParser.replace_tags(value, test_tags, 'test', logger)
    mock_logger_debug.assert_not_called()
    mock_logger_warning.assert_called_once_with("Cannot replace tag with regsub func. Tag '%s' not available ('%s')",
                                                  'TAG_NON_EXISTING', '"TAG_NON_EXISTING", "^(.*) second third", "\\1"')
    assert replaced == value


def test_parse(test_tags, logger):
    event_id = 11111
    obj = EventTagsParser(test_tags, event_id, logger)
    result = obj.parse()
    assert  result == {
        "EVENT.ID": event_id,
        "TAG1": "value1",
        "TAG2": "pre value1 post",
        "TAG_FOR_REGSUB": "first second third",
        "TAG_REGSUB": 'pre first post'
    }

# ### MessageParserByTags

@pytest.fixture
def message_tags():
    yield {
        'EXTRA_PRE_TITLE': '[the common extra pre title]',
        'NEW_EXTRA_PRE_TITLE': '[the new extra pre title]',
        'RECOVERY_EXTRA_PRE_TITLE': '[the recovery extra pre title]',
        'EXTRA_TITLE': 'the common extra title',
        'NEW_EXTRA_TITLE': 'the new extra title',
        'RECOVERY_EXTRA_TITLE': 'the recovery extra title',
        'EXTRA_FOOTER': 'the common extra footer',
        'NEW_EXTRA_FOOTER': 'the new extra footer',
        'RECOVERY_EXTRA_FOOTER': 'the recovery extra footer',
        'TAG_TO_REPLACE': 'the tag value'
    }

@pytest.mark.parametrize(
    ('operation_key', 'expected'),
    [
        ('new', "[the new extra pre title] Original message first line. the new extra title\n"
                "Original message second line.\n"
                "Tag to replace value: the tag value.\n"
                "Original message last line.\n"
                "\nthe new extra footer\n"),
        ('recovery', "[the recovery extra pre title] Original message first line. the recovery extra title\n"
                     "Original message second line.\n"
                     "Tag to replace value: the tag value.\n"
                     "Original message last line.\n"
                     "\nthe recovery extra footer\n"),
        ('other', "[the common extra pre title] Original message first line. the common extra title\n"
                  "Original message second line.\n"
                  "Tag to replace value: the tag value.\n"
                  "Original message last line.\n"
                  "\nthe common extra footer\n"),
    ])
def test_parse_message(message_tags, logger, operation_key, expected):
    original = """Original message first line.
Original message second line.
Tag to replace value: {TAG_TO_REPLACE}.
Original message last line."""
    parser = MessageParserByTags(message_tags, logger)
    result = parser.parse_message(original, operation_key)
    assert result == expected

@pytest.mark.parametrize(
    ('operation_key', 'expected'),
    [
        ('new', "[the new extra pre title] Overriden message first line. the new extra title\n"
                "Overriden message second line.\n"
                "Overriden message last line.\n"
                "\nthe new extra footer\n"),
        ('recovery', "[the recovery extra pre title] Overriden recovery message first line. the recovery extra title\n"
                     "Overriden recovery message second line.\n"
                     "Overriden recovery message last line.\n"
                     "\nthe recovery extra footer\n"),
        ('other', "[the common extra pre title] Original message first line. the common extra title\n"
                  "Original message second line.\n"
                  "Tag to replace value: the tag value.\n"
                  "Original message last line.\n"
                  "\nthe common extra footer\n"),
    ])
def test_parse_message_override(message_tags, logger, operation_key, expected):
    original = """Original message first line.
Original message second line.
Tag to replace value: {TAG_TO_REPLACE}.
Original message last line."""
    message_tags['NEW_MESSAGE_LINE_1'] = 'Overriden message first line.'
    message_tags['NEW_MESSAGE_LINE_2'] = 'Overriden message second line.'
    message_tags['NEW_MESSAGE_LINE_3'] = 'Overriden message last line.'
    message_tags['RECOVERY_MESSAGE_LINE_1'] = 'Overriden recovery message first line.'
    message_tags['RECOVERY_MESSAGE_LINE_2'] = 'Overriden recovery message second line.'
    message_tags['RECOVERY_MESSAGE_LINE_3'] = 'Overriden recovery message last line.'
    parser = MessageParserByTags(message_tags, logger)
    result = parser.parse_message(original, operation_key)
    assert result == expected
