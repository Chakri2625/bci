import pytest
import asyncio
from unittest.mock import MagicMock, patch
from plugins.iot.plugin import IoTPlugin
import paho.mqtt.client as mqtt


@pytest.fixture
def iot_plugin():
    with patch("paho.mqtt.client.Client") as MockClient:
        plugin = IoTPlugin()
        plugin.client = MockClient()
        yield plugin


def test_initialize_shutdown(iot_plugin):
    iot_plugin.initialize()
    iot_plugin.client.connect.assert_called_with(
        "broker.hivemq.com", 1883, 60
    )
    iot_plugin.client.loop_start.assert_called_once()

    iot_plugin.shutdown()
    iot_plugin.client.loop_stop.assert_called_once()
    iot_plugin.client.disconnect.assert_called_once()
    assert not iot_plugin.connected


def test_execute_missing_device_id(iot_plugin):
    result = asyncio.run(
        iot_plugin.execute(
            "MOVE_FORWARD",
            {"command_id": "123"}
        )
    )

    assert result["status"] == "error"
    assert "device_id missing" in result["message"]
    assert result["command_id"] == "123"


def test_execute_disconnected(iot_plugin):
    iot_plugin.connected = False

    result = asyncio.run(
        iot_plugin.execute(
            "MOVE_FORWARD",
            {"device_id": "test_device"}
        )
    )

    assert result["status"] == "error"
    assert "disconnected" in result["message"]


def test_execute_success(iot_plugin):
    iot_plugin.connected = True

    mock_msg_info = MagicMock()
    mock_msg_info.rc = mqtt.MQTT_ERR_SUCCESS
    iot_plugin.client.publish.return_value = mock_msg_info

    payload = {
        "device_id": "test_device",
        "priority": 1
    }

    result = asyncio.run(
        iot_plugin.execute(
            "Left_light_on",
            payload
        )
    )

    assert result["status"] == "success"
    assert result["topic"] == (
        "iot/device/test_device/action"
    )
    assert "command_id" in result

    args, kwargs = iot_plugin.client.publish.call_args

    assert args[0] == (
        "iot/device/test_device/action"
    )
    assert '"command": "Left_light_on"' in args[1]
    assert '"command_id":' in args[1]
    assert '"device_id":' not in args[1]


def test_execute_publish_failure(iot_plugin):
    iot_plugin.connected = True

    mock_msg_info = MagicMock()
    mock_msg_info.rc = mqtt.MQTT_ERR_NO_CONN
    iot_plugin.client.publish.return_value = mock_msg_info

    payload = {
        "device_id": "test_device"
    }

    result = asyncio.run(
        iot_plugin.execute(
            "Left_fan_on",
            payload
        )
    )

    assert result["status"] == "error"
    assert "Publish failed" in result["message"]


def test_execute_get_status(iot_plugin):
    iot_plugin.latest_status["dev_123"] = {
        "bulb": "ON",
        "fan": "OFF"
    }

    iot_plugin.latest_ack["dev_123"] = {
        "pump": "ON"
    }

    result = asyncio.run(
        iot_plugin.execute(
            "GET_STATUS",
            {"device_id": "dev_123"}
        )
    )

    assert result["status"] == "success"
    assert result["device_id"] == "dev_123"
    assert result["latest_status"] == {
        "bulb": "ON",
        "fan": "OFF"
    }
    assert result["latest_ack"] == {
        "pump": "ON"
    }


def test_on_message_status(iot_plugin):
    mock_msg = MagicMock()
    mock_msg.topic = (
        "iot/device/dev_123/status"
    )
    mock_msg.payload = b'{"battery": 80}'

    iot_plugin.on_message(
        iot_plugin.client,
        None,
        mock_msg
    )

    assert "dev_123" in iot_plugin.latest_status
    assert iot_plugin.latest_status["dev_123"] == {
        "battery": 80
    }


def test_on_message_malformed_json(iot_plugin, caplog):
    mock_msg = MagicMock()
    mock_msg.topic = (
        "iot/device/dev_123/status"
    )
    mock_msg.payload = b"invalid json"

    iot_plugin.on_message(
        iot_plugin.client,
        None,
        mock_msg
    )

    assert "Malformed JSON" in caplog.text


def test_on_message_ack_tracking(iot_plugin):
    mock_msg = MagicMock()
    mock_msg.topic = (
        "iot/device/dev_123/ack"
    )
    mock_msg.payload = (
        b'{"command_id": "cmd_999", '
        b'"status": "executed"}'
    )

    iot_plugin.on_message(
        iot_plugin.client,
        None,
        mock_msg
    )

    assert "dev_123" in iot_plugin.latest_ack
    assert "cmd_999" in iot_plugin.command_acks

    ack_info = iot_plugin.get_command_ack(
        "cmd_999"
    )

    assert ack_info["device_id"] == "dev_123"
    assert ack_info["data"]["status"] == "executed"


def test_execute_get_status_with_command_id(iot_plugin):
    iot_plugin.latest_status["dev_123"] = {
        "bulb": "ON"
    }

    iot_plugin.command_acks["cmd_888"] = {
        "device_id": "dev_123",
        "data": {
            "status": "ok"
        }
    }

    result = asyncio.run(
        iot_plugin.execute(
            "GET_STATUS",
            {
                "device_id": "dev_123",
                "command_id": "cmd_888"
            }
        )
    )

    assert result["status"] == "success"
    assert "command_ack" in result
    assert result["command_ack"]["data"]["status"] == "ok"


def test_supported_actions_and_capabilities():
    assert IoTPlugin.is_action_supported(
        "LIGHT",
        "Left_light_on"
    )

    assert IoTPlugin.is_action_supported(
        "LIGHT",
        "Left_light_off"
    )

    assert IoTPlugin.is_action_supported(
        "FAN",
        "Left_fan_on"
    )

    assert IoTPlugin.is_action_supported(
        "PUMP",
        "Left_pump_off"
    )

    assert not IoTPlugin.is_action_supported(
        "LIGHT",
        "Left_fan_on"
    )

    assert not IoTPlugin.is_action_supported(
        "UNKNOWN_DEVICE",
        "some_action"
    )

    all_supported = IoTPlugin.get_supported_actions()

    assert "LIGHT" in all_supported
    assert "FAN" in all_supported
    assert "PUMP" in all_supported


def test_on_disconnect(iot_plugin):
    iot_plugin.connected = True

    iot_plugin.on_disconnect(
        iot_plugin.client,
        None,
        0
    )

    assert iot_plugin.connected is False

    iot_plugin.connected = True

    iot_plugin.on_disconnect(
        iot_plugin.client,
        None,
        1
    )

    assert iot_plugin.connected is False


def test_execute_with_ack_success(iot_plugin):
    iot_plugin.connected = True

    mock_msg_info = MagicMock()
    mock_msg_info.rc = mqtt.MQTT_ERR_SUCCESS
    iot_plugin.client.publish.return_value = mock_msg_info

    async def run_test():

        async def simulate_ack():
            await asyncio.sleep(0.1)

            mock_msg = MagicMock()
            mock_msg.topic = (
                "iot/device/test_device/ack"
            )
            mock_msg.payload = (
                b'{"command_id": "test_cmd", '
                b'"status": "success"}'
            )

            iot_plugin.on_message(
                iot_plugin.client,
                None,
                mock_msg
            )

        task = asyncio.create_task(
            simulate_ack()
        )

        result = await iot_plugin.execute_with_ack(
            "TURN_ON",
            {
                "device_id": "test_device",
                "command_id": "test_cmd"
            }
        )

        await task
        return result

    result = asyncio.run(run_test())

    assert result["status"] == "success"
    assert result["message"] == "ACK received"
    assert result["ack_data"]["command_id"] == "test_cmd"


def test_execute_with_ack_timeout(iot_plugin):
    iot_plugin.connected = True

    mock_msg_info = MagicMock()
    mock_msg_info.rc = mqtt.MQTT_ERR_SUCCESS
    iot_plugin.client.publish.return_value = mock_msg_info

    result = asyncio.run(
        iot_plugin.execute_with_ack(
            "TURN_ON",
            {
                "device_id": "test_device",
                "command_id": "test_cmd"
            },
            timeout=0.1
        )
    )

    assert result["status"] == "error"
    assert result["message"] == "ACK timeout"
    assert "test_cmd" not in iot_plugin.pending_acks


def test_execute_with_ack_device_error(iot_plugin):
    iot_plugin.connected = True

    mock_msg_info = MagicMock()
    mock_msg_info.rc = mqtt.MQTT_ERR_SUCCESS
    iot_plugin.client.publish.return_value = mock_msg_info

    async def run_test():

        async def simulate_ack():
            await asyncio.sleep(0.1)

            mock_msg = MagicMock()
            mock_msg.topic = (
                "iot/device/test_device/ack"
            )
            mock_msg.payload = (
                b'{"command_id": "test_cmd", '
                b'"status": "error", '
                b'"message": "Motor stalled"}'
            )

            iot_plugin.on_message(
                iot_plugin.client,
                None,
                mock_msg
            )

        task = asyncio.create_task(
            simulate_ack()
        )

        result = await iot_plugin.execute_with_ack(
            "TURN_ON",
            {
                "device_id": "test_device",
                "command_id": "test_cmd"
            }
        )

        await task
        return result

    result = asyncio.run(run_test())

    assert result["status"] == "error"
    assert result["message"] == "Motor stalled"


def test_handle_ack_unknown_future(iot_plugin, caplog):
    caplog.set_level("DEBUG")

    mock_msg = MagicMock()
    mock_msg.topic = (
        "iot/device/test_device/ack"
    )
    mock_msg.payload = (
        b'{"command_id": "unknown_cmd", '
        b'"status": "success"}'
    )

    iot_plugin.on_message(
        iot_plugin.client,
        None,
        mock_msg
    )

    assert "unknown_cmd" not in iot_plugin.pending_acks
    assert (
        "Received ACK for unknown/resolved command_id"
        in caplog.text
    )


def test_handle_ack_duplicate_future(iot_plugin, caplog):
    caplog.set_level("DEBUG")

    iot_plugin.connected = True

    mock_msg_info = MagicMock()
    mock_msg_info.rc = mqtt.MQTT_ERR_SUCCESS
    iot_plugin.client.publish.return_value = mock_msg_info

    async def run_test():

        async def simulate_duplicate_ack():
            await asyncio.sleep(0.1)

            mock_msg = MagicMock()
            mock_msg.topic = (
                "iot/device/test_device/ack"
            )
            mock_msg.payload = (
                b'{"command_id": "test_cmd", '
                b'"status": "success"}'
            )

            iot_plugin.on_message(
                iot_plugin.client,
                None,
                mock_msg
            )

            await asyncio.sleep(0.1)

            iot_plugin.on_message(
                iot_plugin.client,
                None,
                mock_msg
            )

        task = asyncio.create_task(
            simulate_duplicate_ack()
        )

        result = await iot_plugin.execute_with_ack(
            "TURN_ON",
            {
                "device_id": "test_device",
                "command_id": "test_cmd"
            }
        )

        await task
        return result

    result = asyncio.run(run_test())

    assert result["status"] == "success"
    assert (
        "Received ACK for unknown/resolved command_id"
        in caplog.text
    )