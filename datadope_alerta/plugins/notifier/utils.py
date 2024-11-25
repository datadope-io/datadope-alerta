import re
from typing import Dict, List, MutableMapping

from datadope_alerta import NormalizedDictView
from datadope_alerta.backend.flexiblededup.models.rules import ContextualRule


def compare_conditions(source: Dict, conditions: List[ContextualRule]) -> Dict:  # 2
    for condition in conditions:
        to_merge = compare_condition(source, condition)
        if to_merge:
            merge_advanced(source, to_merge, condition.append_lists)
            if condition.last_check:
                return source
    return source


def compare_condition(source: Dict, condition: ContextualRule) -> Dict:  # 3
    for rule in condition.contextual_rules:
        if compare_rules(source, rule):
            return condition.context
    return {}


def compare_rules(source: Dict | MutableMapping, rule: Dict) -> bool:  # 4
    for key, value in rule.items():
        existing_value = source.get(key)
        if existing_value is None:
            if value is not None:
                return False
        elif value is None:
            return False
        elif isinstance(existing_value, dict) and not isinstance(value, dict):
            return False
        elif isinstance(existing_value, dict):
            if not compare_rules(NormalizedDictView(existing_value), value):
                return False
        elif isinstance(existing_value, list):
            # Value must exist in the existing list
            if not isinstance(value, list):
                value = [value]
            if len(value) == 0 and len(existing_value) > 0:
                return False
            elif len(value) > 0:
                # All values must exist in the existing list
                for value_element in value:
                    for existing_element in existing_value:
                        if isinstance(value_element, str):
                            if re.match(value_element, str(existing_element), re.IGNORECASE):
                                break
                        else:
                            if str(value_element) == str(existing_element):
                                break
                    else:
                        return False
        elif isinstance(value, str):
            # Compare existing value with value considering the value as a regex pattern string
            if not re.match(value, str(existing_value), re.IGNORECASE):
                return False
        elif str(existing_value) != str(value):
            return False
    return True

def merge_advanced(dict1, dict2, append_lists=True):
    """
    Merge two dictionaries.
    :param dict1:
    :param dict2:
    :param append_lists:
    :return:
    """
    for k in dict2:
        if k in dict1 and isinstance(dict1[k], dict) and isinstance(dict2[k], dict):
            merge_advanced(dict1[k], dict2[k])
        elif isinstance(dict1.get(k), list) and isinstance(dict2.get(k), list) and append_lists:
            dict1[k].extend([v for v in dict2[k] if v not in dict1[k]])
        else:
            dict1[k] = dict2[k]