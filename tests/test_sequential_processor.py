import pytest
import asyncio
from core.navigation.sequential_processor import (
    SequentialProcessor,
    CommandLifecycleState,
    QueuedCommand,
    sequential_processor
)
from core.navigation.models import NavigationRequest, NavigationResponse
from core.state.state_manager import state_manager

@pytest.fixture(autouse=True)
def reset_test_state():
    state_manager.states.clear()
    sequential_processor.history.clear()
    while not sequential_processor.queue.empty():
        try:
            sequential_processor.queue.get_nowait()
        except asyncio.QueueEmpty:
            break
    sequential_processor.active_command = None
    sequential_processor.is_running = False

def test_single_command_execution():
    async def run():
        processor = SequentialProcessor()
        cmd = await processor.enqueue("PUSH")
        assert cmd.status == CommandLifecycleState.QUEUED
        assert cmd.command == "PUSH"

        executed = await processor.execute_command(cmd)
        assert executed.status == CommandLifecycleState.COMPLETED
        assert executed.result is not None
        assert executed.result.status == "success"
        assert executed.result.target_domain == "PYTHON"

    asyncio.run(run())

def test_multiple_commands_in_order():
    async def run():
        processor = SequentialProcessor()
        cmd1 = await processor.enqueue("PUSH")
        cmd2 = await processor.enqueue("PUSH")

        assert processor.queue.qsize() == 2

        res1 = await processor.process_next()
        assert res1.command == "PUSH"
        assert res1.status == CommandLifecycleState.COMPLETED
        assert res1.result.target_domain == "PYTHON"

        res2 = await processor.process_next()
        assert res2.command == "PUSH"
        assert res2.status == CommandLifecycleState.COMPLETED
        assert res2.result.target_domain == "PYTHON"

    asyncio.run(run())

def test_second_command_blocked_while_first_active():
    async def run():
        processor = SequentialProcessor()
        cmd1 = await processor.enqueue("PUSH")
        cmd2 = await processor.enqueue("PULL")

        execution_order = []

        async def run_first():
            async with processor._lock:
                execution_order.append("start_1")
                await asyncio.sleep(0.05)
                execution_order.append("end_1")

        async def run_second():
            await asyncio.sleep(0.01)
            await processor.execute_command(cmd2)
            execution_order.append("end_2")

        await asyncio.gather(run_first(), run_second())

        assert execution_order == ["start_1", "end_1", "end_2"]
        assert cmd2.status == CommandLifecycleState.COMPLETED

    asyncio.run(run())

def test_command_progression_lifecycle():
    async def run():
        processor = SequentialProcessor()
        cmd = await processor.enqueue("LEFT")
        assert cmd.status == CommandLifecycleState.QUEUED
        assert cmd.started_at is None
        assert cmd.completed_at is None

        res = await processor.execute_command(cmd)
        assert res.status == CommandLifecycleState.COMPLETED
        assert res.started_at is not None
        assert res.completed_at is not None
        assert res.started_at <= res.completed_at

    asyncio.run(run())

def test_failed_command_handling():
    async def run():
        processor = SequentialProcessor()
        cmd = await processor.enqueue("JUMP")
        res = await processor.execute_command(cmd)

        assert res.status == CommandLifecycleState.FAILED
        assert res.error == "invalid command"

    asyncio.run(run())

def test_empty_queue_handling():
    async def run():
        processor = SequentialProcessor()
        res = await processor.process_next()
        assert res is None

    asyncio.run(run())

def test_processor_start_stop_behavior():
    processor = SequentialProcessor()
    assert not processor.is_running
    
    processor.start()
    assert processor.is_running
    status = processor.get_status()
    assert status["is_running"] is True

    processor.stop()
    assert not processor.is_running
    status_stop = processor.get_status()
    assert status_stop["is_running"] is False

def test_duplicate_execution_prevention():
    async def run():
        processor = SequentialProcessor()
        await processor.execute_command(QueuedCommand(command="PUSH")) # Level 2
        await processor.execute_command(QueuedCommand(command="PUSH")) # Level 3
        await processor.execute_command(QueuedCommand(command="PUSH")) # Start MOVING

        # Duplicate movement command
        dup_cmd = await processor.enqueue("PUSH")
        res = await processor.execute_command(dup_cmd)
        assert res.status == CommandLifecycleState.COMPLETED
        assert res.result.error == "ignored duplicate"

    asyncio.run(run())
