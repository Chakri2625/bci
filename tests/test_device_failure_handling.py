import pytest
import asyncio
import json
from unittest.mock import MagicMock, patch
import paho.mqtt.client as mqtt

from plugins.iot.plugin import IoTPlugin
from plugins.embedded.subplugins.rc_car.esp32_sender import ESP32Sender


# ==============================================================================
# IoT Device Communication & Failure Handling Tests
# ==============================================================================

@pytest.fixture
def iot_mock_client():
    with patch('paho.mqtt.client.Client') as MockClient:
        plugin = IoTPlugin()
        plugin.client = MockClient()
        yield plugin


def test_iot_normal_communication(iot_mock_client):
    """Test 1: Normal communication - available device, valid ACK received."""
    iot_mock_client.connected = True
    mock_msg_info = MagicMock()
    mock_msg_info.rc = mqtt.MQTT_ERR_SUCCESS
    iot_mock_client.client.publish.return_value = mock_msg_info

    async def run_test():
        async def simulate_valid_ack():
            await asyncio.sleep(0.05)
            mock_msg = MagicMock()
            mock_msg.topic = "iot/device/dev_100/ack"
            mock_msg.payload = json.dumps({"command_id": "cmd_100", "command": "Left_light_on", "status": "success"}).encode()
            iot_mock_client.on_message(iot_mock_client.client, None, mock_msg)

        task = asyncio.create_task(simulate_valid_ack())
        result = await iot_mock_client.execute_with_ack("Left_light_on", {"device_id": "dev_100", "command_id": "cmd_100"})
        await task
        return result

    result = asyncio.run(run_test())
    assert result["status"] == "success"
    assert result["message"] == "ACK received"
    assert result["ack_data"]["status"] == "success"


def test_iot_device_unavailable_disconnected(iot_mock_client):
    """Test 2: Device unavailable - MQTT client disconnected returns controlled failure."""
    iot_mock_client.connected = False

    result = asyncio.run(iot_mock_client.execute("Left_light_on", {"device_id": "dev_100", "command_id": "cmd_100"}))
    assert result["status"] == "error"
    assert "disconnected" in result["message"].lower()

    result_ack = asyncio.run(iot_mock_client.execute_with_ack("Left_light_on", {"device_id": "dev_100", "command_id": "cmd_101"}))
    assert result_ack["status"] == "error"
    assert "disconnected" in result_ack["message"].lower()
    assert "cmd_101" not in iot_mock_client.pending_acks


def test_iot_publish_transport_exception(iot_mock_client):
    """Test 2b: Transport exception during publish handled safely without crashing."""
    iot_mock_client.connected = True
    iot_mock_client.client.publish.side_effect = OSError("Socket broken pipe")

    result = asyncio.run(iot_mock_client.execute("Left_light_on", {"device_id": "dev_100", "command_id": "cmd_102"}))
    assert result["status"] == "error"
    assert "Exception during publish" in result["message"]
    assert iot_mock_client.connected is False


def test_iot_communication_timeout(iot_mock_client):
    """Test 3: Communication timeout when device does not return ACK within timeout."""
    iot_mock_client.connected = True
    mock_msg_info = MagicMock()
    mock_msg_info.rc = mqtt.MQTT_ERR_SUCCESS
    iot_mock_client.client.publish.return_value = mock_msg_info

    result = asyncio.run(
        iot_mock_client.execute_with_ack("Left_fan_on", {"device_id": "dev_100", "command_id": "cmd_timeout"}, timeout=0.1)
    )
    assert result["status"] == "error"
    assert "timeout" in result["message"].lower()
    assert "cmd_timeout" not in iot_mock_client.pending_acks


def test_iot_disconnect_during_communication(iot_mock_client):
    """Test 4: Disconnection while waiting for ACK resolves pending requests immediately."""
    iot_mock_client.connected = True
    mock_msg_info = MagicMock()
    mock_msg_info.rc = mqtt.MQTT_ERR_SUCCESS
    iot_mock_client.client.publish.return_value = mock_msg_info

    async def run_test():
        async def trigger_disconnect():
            await asyncio.sleep(0.05)
            iot_mock_client.on_disconnect(iot_mock_client.client, None, 1)

        task = asyncio.create_task(trigger_disconnect())
        result = await iot_mock_client.execute_with_ack("Left_pump_on", {"device_id": "dev_100", "command_id": "cmd_disc"}, timeout=2.0)
        await task
        return result

    result = asyncio.run(run_test())
    assert result["status"] == "error"
    assert "disconnected" in result["message"].lower()
    assert iot_mock_client.connected is False
    assert len(iot_mock_client.pending_acks) == 0


def test_iot_invalid_or_unexpected_response(iot_mock_client):
    """Test 5: Invalid/malformed response handling (malformed JSON, non-dict, error ACK)."""
    iot_mock_client.connected = True
    mock_msg_info = MagicMock()
    mock_msg_info.rc = mqtt.MQTT_ERR_SUCCESS
    iot_mock_client.client.publish.return_value = mock_msg_info

    # 5a: Malformed JSON in status or ACK topic should not crash
    mock_msg = MagicMock()
    mock_msg.topic = "iot/device/dev_100/status"
    mock_msg.payload = b"not_valid_json"
    iot_mock_client.on_message(iot_mock_client.client, None, mock_msg)
    assert "dev_100" not in iot_mock_client.latest_status

    # 5b: Non-dict JSON payload (e.g. array or primitive)
    mock_msg.payload = b"[1, 2, 3]"
    iot_mock_client.on_message(iot_mock_client.client, None, mock_msg)
    assert "dev_100" not in iot_mock_client.latest_status

    # 5c: Device error ACK
    async def run_error_ack():
        async def send_error_ack():
            await asyncio.sleep(0.05)
            err_msg = MagicMock()
            err_msg.topic = "iot/device/dev_100/ack"
            err_msg.payload = json.dumps({"command_id": "cmd_err", "status": "error", "message": "Relay fault"}).encode()
            iot_mock_client.on_message(iot_mock_client.client, None, err_msg)

        task = asyncio.create_task(send_error_ack())
        result = await iot_mock_client.execute_with_ack("Left_light_on", {"device_id": "dev_100", "command_id": "cmd_err"})
        await task
        return result

    result = asyncio.run(run_error_ack())
    assert result["status"] == "error"
    assert "Relay fault" in result["message"]


def test_iot_recovery_after_reconnection(iot_mock_client):
    """Test 6: Recovery - communication resumes once MQTT client reconnects."""
    # Start disconnected
    iot_mock_client.connected = False
    res1 = asyncio.run(iot_mock_client.execute("Left_light_on", {"device_id": "dev_100", "command_id": "cmd_1"}))
    assert res1["status"] == "error"

    # Reconnect
    iot_mock_client.on_connect(iot_mock_client.client, None, None, 0)
    assert iot_mock_client.connected is True

    # Publish succeeds after recovery
    mock_msg_info = MagicMock()
    mock_msg_info.rc = mqtt.MQTT_ERR_SUCCESS
    iot_mock_client.client.publish.return_value = mock_msg_info

    res2 = asyncio.run(iot_mock_client.execute("Left_light_on", {"device_id": "dev_100", "command_id": "cmd_2"}))
    assert res2["status"] == "success"


# ==============================================================================
# Embedded ESP32 Sender Failure Handling Tests
# ==============================================================================

@pytest.fixture
def esp32_sender():
    with patch('paho.mqtt.client.Client') as MockClient:
        sender = ESP32Sender(protocol="MQTT")
        sender.mqtt_client = MockClient()
        sender._mqtt_connected = True
        yield sender


def test_esp32_mqtt_normal_communication(esp32_sender):
    """ESP32 normal ACK confirmation."""
    mock_info = MagicMock()
    mock_info.rc = mqtt.MQTT_ERR_SUCCESS
    mock_info.is_published.return_value = True
    esp32_sender.mqtt_client.publish.return_value = mock_info

    import threading
    def trigger_ack():
        esp32_sender.last_ack = "LIFTCARFORWARD_ACK"
        esp32_sender._last_received_ack = "LIFTCARFORWARD_ACK"
        esp32_sender._ack_event.set()

    t = threading.Timer(0.05, trigger_ack)
    t.start()

    success, latency, msg = esp32_sender.send_payload_mqtt("LIFTCARFORWARD", wait_ack_timeout=0.5)
    t.join()
    assert success is True
    assert msg == "LIFTCARFORWARD_ACK"


def test_esp32_mqtt_timeout_handling(esp32_sender):
    """ESP32 timeout when no ACK is received."""
    mock_info = MagicMock()
    mock_info.rc = mqtt.MQTT_ERR_SUCCESS
    mock_info.is_published.return_value = True
    esp32_sender.mqtt_client.publish.return_value = mock_info

    success, latency, msg = esp32_sender.send_payload_mqtt("LIFTCARFORWARD", wait_ack_timeout=0.1)
    assert success is False
    assert "timeout" in msg.lower()


def test_esp32_mqtt_error_ack_response(esp32_sender):
    """ESP32 error ACK response rejection."""
    mock_info = MagicMock()
    mock_info.rc = mqtt.MQTT_ERR_SUCCESS
    mock_info.is_published.return_value = True
    esp32_sender.mqtt_client.publish.return_value = mock_info

    import threading
    def trigger_error_ack():
        esp32_sender.last_ack = json.dumps({"status": "error", "message": "Motor overload"})
        esp32_sender._last_received_ack = esp32_sender.last_ack
        esp32_sender._ack_event.set()

    t = threading.Timer(0.05, trigger_error_ack)
    t.start()

    success, latency, msg = esp32_sender.send_payload_mqtt("LIFTCARFORWARD", wait_ack_timeout=0.5)
    t.join()
    assert success is False
    assert "Motor overload" in msg


def test_esp32_mqtt_empty_ack_response(esp32_sender):
    """ESP32 empty ACK response rejection."""
    mock_info = MagicMock()
    mock_info.rc = mqtt.MQTT_ERR_SUCCESS
    mock_info.is_published.return_value = True
    esp32_sender.mqtt_client.publish.return_value = mock_info

    import threading
    def trigger_empty_ack():
        esp32_sender.last_ack = "   "
        esp32_sender._last_received_ack = "   "
        esp32_sender._ack_event.set()

    t = threading.Timer(0.05, trigger_empty_ack)
    t.start()

    success, latency, msg = esp32_sender.send_payload_mqtt("LIFTCARFORWARD", wait_ack_timeout=0.5)
    t.join()
    assert success is False
    assert "empty ACK" in msg
