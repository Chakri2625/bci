# Design API/Service Interfaces

## 1. Introduction

In a modular backend system where independent domains collaborate to achieve complex workflows, clear communication contracts are essential. The purpose of designing API and service interfaces in the Python backend is to establish structured, predictable boundaries between the core routing logic and the distinct operational domains, such as the IoT, Embedded, AIML, and Desktop modules. By standardizing these contracts, the system guarantees that any module can confidently parse inputs, execute domain-specific logic, and emit consistent responses, thereby reducing integration friction and enhancing the maintainability of the entire application.

## 2. Existing System Context

The current Python backend is built on top of a modular plugin architecture coordinated by a core routing and automation engine, and exposed via a FastAPI server. Incoming commands arrive at the backend through established endpoints (like BCI command ingestion or automation triggers). The core engine resolves these commands and transitions the system state, eventually dispatching actionable tasks to the appropriate domain plugin using a central `plugin_manager`. 

Prior to this task, while the `Desktop` domain utilized a formalized interface (`DesktopPluginInterface`), other domains such as `IoT`, `Embedded`, and `AIML` lacked explicit structural contracts for their plugin implementations, operating either as empty stubs or with informal execution signatures.

## 3. Objective

The objectives of this task were focused on establishing structural integrity across the backend's domain modules without redesigning the existing architecture. Specifically, the task aimed to:

* Establish clear communication contracts between the core backend and all operational plugins.
* Standardize inputs and outputs across all domain modules using a consistent execution signature.
* Define strict service and module boundaries to prevent tight coupling.
* Ensure predictable error handling when interacting with plugins.
* Maintain complete compatibility with existing backend routing and API functionality.

## 4. API/Service Interface Design

The backend interacts with the domain modules through a formalized plugin interface architecture. During this task, we formalized the contracts for the IoT, Embedded, and AIML domains by introducing specific interface definitions.

| Interface Name | Purpose | Location | Input Structure | Output Structure | Error Behavior |
| --- | --- | --- | --- | --- | --- |
| `IoTPluginInterface` | Contract for IoT operations | `plugin_sdk/interfaces/iot_plugin.py` | `command` (str), `payload` (Optional[Dict]) | `Dict` (status, message, etc.) | Returns `{"status": "error", "message": "..."}` |
| `EmbeddedPluginInterface` | Contract for Embedded operations | `plugin_sdk/interfaces/embedded_plugin.py` | `command` (str), `payload` (Optional[Dict]) | `Dict` (status, message, etc.) | Returns `{"status": "error", "message": "..."}` |
| `AIMLPluginInterface` | Contract for AIML operations | `plugin_sdk/interfaces/aiml_plugin.py` | `command` (str), `payload` (Optional[Dict]) | `Dict` (status, message, etc.) | Returns `{"status": "error", "message": "..."}` |

All of these interfaces inherit from the core `BasePlugin` class and explicitly define the `execute` method signature, ensuring that any new or existing plugin adheres to the same communication method.

## 5. Request Contracts

Requests entering the domain modules are structured around a formalized `execute` method signature. This method serves as the singular entry point for domain-specific logic. 

The request contract consists of two primary fields:
* **`command` (str)**: A required string representing the specific action or command the domain needs to process (e.g., `"MOVE_FORWARD"`, `"open_app"`).
* **`payload` (Optional[Dict[str, Any]])**: An optional dictionary containing metadata, parameters, and identifiers necessary for the execution of the command. For instance, the payload may include a `device_id` or an `app` target.

At the API level, requests are validated using Pydantic models (e.g., `BCICommandRequest` or `AutomationRequest`), ensuring that only well-formed data reaches the internal plugin manager before being transformed into the `command` and `payload` structure for the plugins.

## 6. Response Contracts

The response format returned by all domain plugins is a standardized Python dictionary, ensuring that the core routing layer can uniformly process results regardless of which domain executed the command.

* **Successful Responses**: Contain a `"status"` key set to `"success"`. They typically include a `"message"` describing the outcome, and optionally echo back identifiers like `"command_id"` or `"payload"`.
* **Failure Responses**: Contain a `"status"` key set to `"error"`. They must include a `"message"` key that provides a descriptive explanation of the failure.
* **Returned Data**: Any additional data resulting from the command (such as retrieved widgets or operational state) is appended as additional keys within the dictionary.

This consistent structure allows components like the `recovery_handler` and `iot_adapter` to predictably inspect the `"status"` field and gracefully manage subsequent logic.

## 7. Service/Module Communication

The communication flow between the backend and its modules follows a strict sequence, heavily utilizing the newly formalized interfaces:

1. **Input**: A request is received via an API endpoint (e.g., FastAPI route `/api/v1/bci/command`).
2. **Validation**: The request is validated against Pydantic models to ensure structural correctness.
3. **Backend Processing**: The core routing engine resolves the command against the current state and determines the target domain (e.g., `IOT`, `EMBEDDED`).
4. **Domain/Module**: The `plugin_manager` retrieves the corresponding plugin instance (which now strictly adheres to its domain interface) and invokes the `execute(command, payload)` method.
5. **Response**: The plugin processes the task and returns a standardized response dictionary back up the chain. The API server bundles this result along with the updated state and returns it to the client.

## 8. Error Handling Contract

Error handling is tightly integrated into the response contract to ensure that the calling services can react appropriately to failures.

* **Missing Fields or Invalid Data**: If a plugin detects that a required parameter (like a `device_id`) is missing from the payload, it catches the issue internally and returns a dictionary with `"status": "error"` and a `"message"` detailing the missing requirement.
* **Unsupported Operations**: If a command string is not recognized by the plugin, the plugin gracefully falls back to returning an error dictionary rather than raising an unhandled exception.
* **Internal/Service Errors**: If an internal error occurs (such as an MQTT publish failure in the IoT domain), the exception is caught within the plugin or the adapter layer (e.g., `IoTSyncAdapter`), and transformed into the standard error dictionary format.

The core `api_server` and `recovery_handler` evaluate the returned `"status"` field. If the status is `"error"`, the system initiates recovery protocols without crashing the backend thread.

## 9. Integration With Existing Architecture

The introduction of these interfaces was accomplished with minimal disruption to the existing architecture. The `BasePlugin` abstract base class and the central `plugin_manager` were completely preserved. 

By simply creating new domain-specific interface files (`iot_plugin.py`, `embedded_plugin.py`, `aiml_plugin.py`) and updating the respective plugin implementations to inherit from them, we established strict contracts without changing how the `plugin_manager` discovers or loads the modules. Additionally, existing components like the `IoTSyncAdapter` and FastAPI schemas were entirely reused, avoiding any duplicate logic or redundant API layers.

## 10. UI Integration

The existing UI was completely preserved during this task. Because the changes focused entirely on formalizing backend service contracts and internal plugin interfaces, no modifications to the frontend or desktop UI were required. The API responses consumed by the UI remained structurally identical, ensuring backward compatibility.

## 11. Validation and Verification

The implementation was validated using the following methods:

* **Integration Verification**: The FastAPI server (`main.py`) was launched to verify that the `plugin_manager` could still successfully discover, instantiate, and load all plugins despite the new inheritance structures.
* **Syntax and Conflict Resolution**: A series of Git merge conflict markers across the `iot_adapter.py`, `sequential_processor.py`, and test files were systematically cleaned up, allowing the codebase to parse correctly.
* **Existing Functionality Compatibility**: The `pytest` suite was run to ensure that the foundational architecture remained intact. The interface formalization proved non-destructive, with the plugins correctly satisfying the standard `execute` method signature expected by the core system.

## 12. Files Modified/Created

| File | Change | Reason |
| ---- | ------ | ------ |
| `core/communication/iot_adapter.py` | Modified | Cleaned up duplicate Git merge conflict markers to restore valid syntax. |
| `core/navigation/sequential_processor.py` | Modified | Cleaned up duplicate Git merge conflict markers to restore valid syntax. |
| `tests/test_iot_adapter.py`, `tests/test_iot_plugin.py`, `tests/test_iot_routing.py` | Modified | Cleaned up duplicate Git merge conflict markers to restore valid syntax and allow `pytest` to execute. |
| `plugin_sdk/interfaces/iot_plugin.py` | Created | Defined the strict `IoTPluginInterface` to formalize the IoT domain communication contract. |
| `plugin_sdk/interfaces/embedded_plugin.py` | Created | Defined the strict `EmbeddedPluginInterface` to formalize the Embedded domain communication contract. |
| `plugin_sdk/interfaces/aiml_plugin.py` | Created | Defined the strict `AIMLPluginInterface` to formalize the AIML domain communication contract. |
| `plugins/iot/plugin.py` | Modified | Implemented `IoTPluginInterface` and added the default `execute` contract. |
| `plugins/embedded/plugin.py` | Modified | Inherited from `EmbeddedPluginInterface` to formalize its existing functionality. |
| `plugins/aiml/plugin.py` | Modified | Implemented `AIMLPluginInterface` and added the default `execute` contract. |

## 13. Implementation Outcome

Through this task, the backend successfully transitioned from relying on loosely defined domain modules to operating on strictly formalized interfaces. The newly defined contracts guarantee that all plugins will accept standard inputs and produce predictable dictionary outputs. This structured approach significantly improves the robustness of the backend, making it easier to integrate new features, handle errors predictably, and maintain the system as it scales.

## 14. Conclusion

By focusing on the minimum necessary modifications to establish clear communication contracts, we enhanced the reliability of the Python backend. The creation of explicit plugin interfaces for the IoT, Embedded, and AIML domains integrates seamlessly with the existing architecture, ensuring that the system remains modular, decoupled, and thoroughly predictable in its internal communications.
