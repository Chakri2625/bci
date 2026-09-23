from pydantic import ValidationError

from models.command_models import NavigationCommand


def validate_command(command_data: dict):
    """
    Validate an incoming SynaptiMesh command.

    Returns:
        (True, NavigationCommand)
        for valid commands.

        (False, error dictionary)
        for invalid commands.
    """

    try:
        validated_command = NavigationCommand(**command_data)

        return True, validated_command

    except ValidationError as error:

        return False, {
            "status": "error",
            "error_code": "INVALID_COMMAND",
            "message": "Command validation failed",
            "details": error.errors()
        }


def validate_command_for_router(command_data: dict):
    """
    Validate a command and return only the command value
    required by the existing rule_router.py.
    """

    valid, result = validate_command(command_data)

    if not valid:
        return False, result

    return True, result.command


def validate_and_prioritize(command_data: dict, priority_manager=None):
    """
    Validate an incoming command and determine/assign priority for Member 7 integration.
    """
    from core.managers.priority_manager import get_command_priority

    valid, result = validate_command(command_data)
    if not valid:
        return False, result, None

    priority = get_command_priority(result)
    if priority_manager is not None:
        priority_manager.enqueue(result, priority=priority)

    return True, result, priority


from core.validation.invalid_combination_rules import check_navigation_combination, InvalidCombinationRules

