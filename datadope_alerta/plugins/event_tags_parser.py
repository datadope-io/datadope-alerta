import re


TAG_REPLACE_REGEX = r"{([^}]+)}"
KEY_TAG_EXTRA_FOOTER = 'EXTRA_FOOTER'
KEY_TAG_EXTRA_TITLE = 'EXTRA_TITLE'
KEY_TAG_EXTRA_PRE_TITLE = 'EXTRA_PRE_TITLE'

KEY_TAG_ITEM_VALUE_ZABBIX = 'ITEM.VALUE'
KEY_TAG_ITEM_LASTVALUE_ZABBIX = 'ITEM.LASTVALUE'

KEY_MESSAGE_LINE_COMMON = "_MESSAGE_LINE_"


# ##### FUNCTIONS TO USE IN TAGS #######

def func_regsub(param_string, tags, logger):
    params = _extract_params(param_string)
    if len(params) < 3:
        logger.warning("Cannot replace tag with regsub func. 3 parameters needed and got %s", param_string)
        return None
    tag = params[0]
    if tag not in tags:
        logger.warning("Cannot replace tag with regsub func. Tag '%s' not available ('%s')", tag, param_string)
        return None
    origin = tags[tag]
    regex = params[1]
    result = params[2]
    matches = re.finditer(regex, origin, re.MULTILINE)
    for match in matches:
        for gr in range(0, match.lastindex):
            gr_number = gr + 1
            gr_value = match.group(gr_number)
            result = result.replace("\\%d" % gr_number, gr_value)
    return result


def _extract_params(param_string):
    params = []
    status = 0
    new_param = ''
    separator = None
    for char in param_string:
        if status == 2:
            if char == separator:
                new_param += char
            else:
                new_param += '\\' + char
            status = 1
        elif char == '"' or char == "'":
            if status == 0:
                status = 1
                separator = char
            elif char == separator:
                params.append(new_param)
                status = 0
                new_param = ''
            else:
                new_param += char
        elif (char == ',' or char == ' ') and status == 0:
            continue
        elif status == 1 and char == '\\':
            status = 2
        elif status == 1:
            new_param += char
    return params


# ######################################

class EventTagsParser:
    def __init__(self, event_tags, event_id, logger):
        self.event_tags = event_tags
        self.event_id = event_id
        self.logger = logger

    def parse(self):
        # Prepare usual tags to use in replacements
        current_id = self.event_tags.get('EVENT.ID', self.event_tags.get('EVENT_ID'))
        if self.event_id and not current_id:
            self.event_tags['EVENT.ID'] = self.event_id

        # Replace values
        times = 2
        while times > 0:
            self.event_tags = {tag: self.replace_tags(value, self.event_tags, tag, self.logger)
                          for tag, value in self.event_tags.items()}
            times -= 1
        return self.event_tags

    @staticmethod
    def replace_tags(value, tags, tag, logger):
        if not isinstance(value, str):
            return value
        matches = re.finditer(TAG_REPLACE_REGEX, value, re.MULTILINE)
        for match in matches:
            replacement = match.group()
            key = match.group(1)
            if key in tags:
                new_value = str(tags[key])
                logger.debug("REPLACED '%s' BY '%s' FOR TAG '%s'", replacement, new_value, tag)
                value = value.replace(replacement, new_value)
            elif key.endswith(')'):
                inic = key.find('(')
                if inic > 0:
                    func_name = key[:inic]
                    params = key[inic+1:-1]
                    # noinspection PyBroadException
                    try:
                        method = globals().get('func_' + func_name)
                        new_value = method(params, tags, logger)
                        if new_value is None:
                            return value
                        logger.debug("REPLACED FUNC '%s' BY '%s' FOR TAG '%s'", replacement, new_value, tag)
                        value = value.replace(replacement, new_value)
                    except Exception as e:
                        logger.exception("Exception replacing '%s': '%s'", value, str(e))
        return value

class MessageParserByTags:

    def __init__(self, event_tags, logger):
        self.event_tags = event_tags
        self.logger = logger

    def parse_message(self, original, operation_key):
        if operation_key in ('action', 'resolve'):
            operation_key = 'recovery'
        prefix = operation_key.upper() + KEY_MESSAGE_LINE_COMMON
        keys = [k for k in self.event_tags.keys() if k.startswith(prefix)]
        if keys:
            keys = sorted(keys)
            message = '\n'.join([self.event_tags[k] for k in keys])
        elif original is None:
            return None
        else:
            message = original
            message = EventTagsParser.replace_tags(message, self.event_tags, 'message', self.logger)
        message = message + '\n'

        # Add extra_footer
        extra_footer = self._get_extra_footer(operation_key)
        if extra_footer:
            message = '{}\n{}\n'.format(message, extra_footer)

        # Add extra title tags
        extra_title = self._get_extra_title(operation_key)
        extra_pre_title = self._get_extra_pre_title(operation_key)
        if extra_title or extra_pre_title:
            first_line, _, rest = message.partition('\n')
            if extra_title and not first_line.endswith('.'):
                first_line = first_line + '.'
            first_line = '{} {} {}'.format(extra_pre_title, first_line, extra_title).strip()
            message = '{}\n{}'.format(first_line, rest)
        return message

    def _get_tag_by_type_or_global(self, tag, operation_key):
        key = operation_key.upper() + '_' + tag
        if key in self.event_tags:
            return self.event_tags[key]
        else:
            return self.event_tags.get(tag) or ''

    def _get_extra_footer(self, operation_key):
        return self._get_tag_by_type_or_global(KEY_TAG_EXTRA_FOOTER, operation_key)

    def _get_extra_title(self, operation_key):
        return self._get_tag_by_type_or_global(KEY_TAG_EXTRA_TITLE, operation_key)

    def _get_extra_pre_title(self, operation):
        return self._get_tag_by_type_or_global(KEY_TAG_EXTRA_PRE_TITLE, operation)
