import unittest
import json
import os
import logging
from unittest.mock import patch
from datetime import datetime
from core.logging.log_schema import StructuredLogEvent, LogLevel, EventType
from core.logging.structured_logger import StructuredLogger, structured_logger, JSONFormatter

class TestStructuredLogger(unittest.TestCase):
    def setUp(self):
        # Reset singleton for testing
        StructuredLogger._instance = None
        
        # Make sure the log directory exists
        self.log_dir = os.path.join("data", "logs")
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_file = os.path.join(self.log_dir, "structured.log")
        
        # Clear log file before each test
        if os.path.exists(self.log_file):
            open(self.log_file, 'w').close()
            
        self.logger = StructuredLogger()
        
    def tearDown(self):
        # Remove handlers to avoid duplicate logs in other tests
        for handler in list(self.logger.logger.handlers):
            self.logger.logger.removeHandler(handler)
            handler.close()

    def test_singleton(self):
        logger1 = StructuredLogger()
        logger2 = StructuredLogger()
        self.assertIs(logger1, logger2)
        
    def test_initialization(self):
        self.assertIsNotNone(self.logger.logger)
        self.assertEqual(len(self.logger.logger.handlers), 2)
        
    def test_duplicate_handlers(self):
        # Call initialization again, it shouldn't add more handlers
        self.logger._initialize()
        self.assertEqual(len(self.logger.logger.handlers), 2)

    def test_structured_event_creation(self):
        event = StructuredLogEvent(
            event_type=EventType.COMMAND_RECEIVED.value,
            log_level=LogLevel.INFO.value,
            request_id="REQ-001",
            message="Test message"
        )
        self.assertEqual(event.event_type, "COMMAND_RECEIVED")
        self.assertEqual(event.log_level, "INFO")
        self.assertEqual(event.request_id, "REQ-001")
        self.assertEqual(event.message, "Test message")
        self.assertIsNotNone(event.timestamp)
        self.assertIn("T", event.timestamp)

    def test_missing_optional_fields(self):
        event = StructuredLogEvent(
            event_type=EventType.SESSION_STARTED.value,
            log_level=LogLevel.DEBUG.value
        )
        self.assertIsNone(event.request_id)
        self.assertIsNone(event.execution_id)
        self.assertEqual(event.metadata, {})

    def test_metadata_support(self):
        event = StructuredLogEvent(
            event_type="CUSTOM_EVENT",
            log_level="INFO",
            metadata={"key1": "value1", "key2": 123}
        )
        self.assertEqual(event.metadata["key1"], "value1")
        self.assertEqual(event.metadata["key2"], 123)

    def test_json_serialization(self):
        self.logger.log_command_received(
            request_id="REQ-123",
            command="test_command",
            status="RECEIVED",
            message="Testing json serialization"
        )
        
        # Read the file
        with open(self.log_file, 'r') as f:
            lines = f.readlines()
            
        self.assertGreater(len(lines), 0)
        
        # The last line should be our JSON
        last_log = lines[-1].strip()
        data = json.loads(last_log)
        
        self.assertEqual(data["event_type"], EventType.COMMAND_RECEIVED.value)
        self.assertEqual(data["log_level"], LogLevel.INFO.value)
        self.assertEqual(data["request_id"], "REQ-123")
        self.assertEqual(data["command"], "test_command")
        self.assertEqual(data["status"], "RECEIVED")
        self.assertEqual(data["message"], "Testing json serialization")
        self.assertIsNotNone(data["timestamp"])

    def test_log_levels(self):
        # Log an error
        self.logger.log_execution_failed(
            command_id="CMD-999",
            message="Execution failed!"
        )
        
        with open(self.log_file, 'r') as f:
            lines = f.readlines()
            
        last_log = json.loads(lines[-1].strip())
        self.assertEqual(last_log["log_level"], LogLevel.ERROR.value)
        self.assertEqual(last_log["event_type"], EventType.EXECUTION_FAILED.value)

if __name__ == '__main__':
    unittest.main()
