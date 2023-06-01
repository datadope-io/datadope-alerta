from typing import Dict, List

from alerta.utils.collections import merge
from datadope_alerta.backend.flexiblededup.models.rules import ContextualRule


def compare_conditions(source: Dict, conditions: List[ContextualRule]) -> Dict:  # 2
    result = {}
    for condition in conditions:
        to_merge = compare_condition(source, condition)
        merge(to_merge, result)
        result = to_merge
        if condition.last_check:
            return result
    return result


def compare_condition(source: Dict, condition: ContextualRule) -> Dict:  # 3
    for rule in condition.contextual_rules:
        if compare_rules(source, rule):
            return condition.context
    return {}


def compare_rules(source: Dict, rule: Dict) -> bool:  # 4
    for key, value in rule.items():
        if isinstance(value, dict):
            if not compare_rules(source.get(key, {}), value):
                return False
        elif isinstance(value, list):
            if not set(value).issubset(set(source.get(key, []))):
                return False
        elif source.get(key) != value:
            return False
    return True
