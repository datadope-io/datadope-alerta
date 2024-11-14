from typing import Dict, List

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


def compare_rules(source: Dict, rule: Dict) -> bool:  # 4
    for key, value in rule.items():
        existing_value = source.get(key)
        if existing_value is None:
            if value is not None:
                return False
        elif isinstance(existing_value, dict) and not isinstance(value, dict):
            return False
        elif isinstance(existing_value, dict):
            if not compare_rules(NormalizedDictView(NormalizedDictView(existing_value)), value):
                return False
        elif isinstance(existing_value, list):
            if not isinstance(value, list):
                if value not in existing_value:
                    return False
            elif len(value) > 0:
                if not all([v in existing_value for v in value]):
                    return False
        elif str(source.get(key)) != str(value):
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