import logging
import asyncio
import time
import uuid
from typing import Union, Optional
from core.plugin_manager.manager import execute
from core.state.state_manager import state_manager
from core.routing.rule_router import resolve_command, navigate_back, navigate_home
from core.navigation.sequence_validator import sequence_validator
from core.managers.retry_manager import retry_manager
from core.orchestration.parallel_engine import parallel_engine
from core.managers.async_task_manager import async_task_manager
from core.managers.resource_lock_manager import resource_lock_manager
from core.managers.command_lock_manager import command_lock_manager
from core.managers.lifecycle_tracker import lifecycle_tracker
from core.logging.execution_logger import execution_logger

logger = logging.getLogger("orchestrator")

class EcosystemOrchestrator:
    async def process_command(self, command: Union[str, list], session: Optional[str] = None, confidence: float = 1.0, source: str = "unknown", device_id: str = None, command_id: str = None, execution_id: str = None):
        t0 = time.perf_counter()
        
        if not session or session == "default":
            session = state_manager.get_active_session_id()

        if not command_id:
            command_id = uuid.uuid4().hex
            
        if not execution_id:
            execution_id = uuid.uuid4().hex
            
        if isinstance(command, list):
            try:
                from core.validation.command_normalizer import normalize_command
                norm_check = normalize_command(command)
                if norm_check in ("PUSH_LEFT", "PUSH_RIGHT") or len(command) == 1:
                    command = norm_check
                else:
                    logger.info(f"[ORCHESTRATOR] PARALLEL COMMANDS INPUT: {command}")
                    return await self._process_parallel(command, session, confidence, source, device_id, execution_id)
            except Exception:
                logger.info(f"[ORCHESTRATOR] PARALLEL COMMANDS INPUT: {command}")
                return await self._process_parallel(command, session, confidence, source, device_id, execution_id)
        
        logger.info(f"[ORCHESTRATOR] COMMAND INPUT: {command}")
        
        try:
            from core.validation.command_normalizer import normalize_command
            cmd = normalize_command(command)
        except ImportError:
            cmd = str(command).upper()

        t_norm_end = time.perf_counter()

        # Log event in execution logger
        execution_logger.log_command_received(execution_id, cmd)
        execution_logger.log_priority_assigned(execution_id, cmd, "NORMAL")

        # Register in lifecycle tracker
        lifecycle_tracker.start_execution(command=cmd, priority="NORMAL", execution_id=execution_id)
        lc_record = lifecycle_tracker.create_command(command=cmd, session_id=session, command_id=command_id, domain="Core")

        # Always record incoming command in state history and commands map
        state_manager.add_command(session, cmd, command_id)

        # Sequence validation stage
        lifecycle_tracker.track_validating(command_id)
        state = state_manager.get_state(session)
        is_direct_api = source in ("iot_dashboard", "dashboard", "api", "rest", "web", "iot")
        
        if is_direct_api:
            validation = {
                "previous_command": None,
                "current_command": cmd,
                "status": "VALID",
                "is_valid": True,
                "allowed_next_commands": list(sequence_validator.CANDIDATE_COMMANDS),
                "rejection_reason": None,
                "current_state": state,
            }
        else:
            validation = sequence_validator.validate(cmd, state)
        t_val_end = time.perf_counter()

        logger.info(f"[ORCHESTRATOR] COMMAND VALIDATED: {validation['is_valid']}")
        
        print("\n========== COMMAND CONTEXT ==========")
        print(f"Execution ID: {execution_id}")
        print(f"Session ID  : {session}")
        print(f"Command ID  : {command_id}")
        print(f"Command     : {cmd}")
        print("======================================")

        sequence_validator.record(session, validation, state_manager)
        lifecycle_tracker.track_validation(command_id, is_valid=validation["is_valid"], reason=validation.get("rejection_reason"))
        
        if not validation["is_valid"]:
            raw_rej = validation.get("rejection_reason", "Invalid command sequence")
            err_reason = f"Invalid command: {raw_rej}" if "invalid" not in raw_rej.lower() else raw_rej
            execution_logger.log_execution_failed(execution_id, cmd, "NORMAL", 0.0, "VALIDATION_ERROR", err_reason)
            lifecycle_tracker.update_status(execution_id, "FAILED", error=err_reason)
            lifecycle_tracker.track_failure(command_id, error=err_reason, error_code="VALIDATION_ERROR")
            state_manager.record_failure(
                command_id=command_id,
                domain=state.get("active_domain") or "Core",
                affected_component="Validation Engine",
                failure_type="VALIDATION_ERROR",
                failure_reason=err_reason,
                error_source="SequenceValidator",
                recovery_status="PENDING",
                session=session
            )
            proc_ms = max(0.05, (time.perf_counter() - t0) * 1000.0)
            state_manager.record_performance_metrics(
                processing_ms=proc_ms,
                execution_ms=0.0,
                stage_breakdown={"normalization": (t_norm_end - t0)*1000.0, "validation": (t_val_end - t_norm_end)*1000.0}
            )
            state_manager.update_command_state(command_id, status="FAILED", error=err_reason)
            state_manager.remove_active_command(command_id)
            return {
                "status": "invalid",
                "command": cmd,
                "command_id": command_id,
                "execution_id": execution_id,
                "resolved": {"type": "no_action"},
                "executed": False,
                "validation": validation,
                "lock": command_lock_manager.get_lock_state(session),
                "state": state_manager.get_state(session),
                "lifecycle": lc_record.to_dict(),
                "timing": lifecycle_tracker.get_execution_timing(command_id),
            }

        # Enforce Command Lock and Combination formation
        if not is_direct_api:
            lock_res = command_lock_manager.acquire_or_combine(session, cmd, command_id=command_id)
            if lock_res.get("status") == "ignored":
                logger.info(f"[ORCHESTRATOR] Command '{cmd}' ignored by lock manager: {lock_res.get('reason')}")
                ign_reason = lock_res.get("reason", "Command locked")
                lifecycle_tracker.update_status(execution_id, "FAILED", error=ign_reason)
                lifecycle_tracker.track_failure(command_id, error=ign_reason, error_code="COMMAND_LOCKED")
                proc_ms = max(0.05, (time.perf_counter() - t0) * 1000.0)
                state_manager.record_performance_metrics(proc_ms, 0.0)
                return {
                    "status": "ignored",
                    "command": cmd,
                    "command_id": command_id,
                    "execution_id": execution_id,
                    "reason": ign_reason,
                    "active_command": lock_res.get("active_command"),
                    "timer_started": lock_res.get("timer_started"),
                    "timer_deadline": lock_res.get("timer_deadline"),
                    "time_remaining": lock_res.get("time_remaining"),
                    "lock": command_lock_manager.get_lock_state(session),
                    "executed": False,
                    "resolved": {"type": "no_action"},
                    "state": state_manager.get_state(session),
                    "lifecycle": lc_record.to_dict(),
                    "timing": lifecycle_tracker.get_execution_timing(command_id),
                }

            # If a combination was formed, use the resulting combined command (e.g. PUSH_LEFT, PUSH_RIGHT)
            if lock_res.get("is_combination") and lock_res.get("command"):
                cmd = lock_res["command"]
            
        logger.info(f"[ORCHESTRATOR] COMMAND PARSED: {cmd}")
        
        t_rout_start = time.perf_counter()
        resolution = resolve_command(cmd, state)
        if is_direct_api and resolution.get("type") == "no_action":
            resolution = {
                "type": "action",
                "domain": "IOT",
                "app": "RELAY",
                "action": command,
                "level": 3
            }
        t_rout_end = time.perf_counter()
        
        r_domain = resolution.get("domain") or state.get("active_domain") or "Core"
        r_app = resolution.get("app") or state.get("active_app") or "N/A"
        r_op = resolution.get("action") or resolution.get("type") or "N/A"
        
        lc_record.domain = r_domain
        state_manager.register_active_command(command_id=command_id, command=cmd, domain=r_domain, app=r_app, session=session)
        lifecycle_tracker.update_status(execution_id, "RUNNING")
        lifecycle_tracker.track_execution_started(command_id, target=r_domain)
        
        print("\n========== COMMAND ROUTER ==========")
        print(f"Command     : {cmd}")
        print(f"Domain      : {r_domain}")
        print(f"Application : {r_app}")
        print(f"Operation   : {r_op}")
        print("=====================================\n")
        
        result = {
            "status": "success",
            "command": cmd,
            "command_id": command_id,
            "execution_id": execution_id,
            "resolved": resolution,
            "executed": False,
            "validation": validation,
        }
        
        t_exec_start = time.perf_counter()
        
        if resolution["type"] == "transition":
            state_manager.update_state(session, {
                "current_level": resolution["level"],
                "active_domain": resolution["domain"],
                "active_app": resolution["app"],
                "last_resolved_action": None
            })
            t_exec_end = time.perf_counter()
            exec_ms = max(0.05, (t_exec_end - t_exec_start) * 1000.0)
            proc_ms = max(0.05, (t_exec_start - t0) * 1000.0)
            state_manager.record_performance_metrics(
                proc_ms, exec_ms,
                stage_breakdown={
                    "normalization": (t_norm_end - t0)*1000.0,
                    "validation": (t_val_end - t_norm_end)*1000.0,
                    "routing": (t_rout_end - t_rout_start)*1000.0,
                    "execution": exec_ms
                }
            )
            trans_res = {"action": "transition", "domain": resolution["domain"], "level": resolution["level"]}
            lifecycle_tracker.update_status(execution_id, "SUCCESS", result=trans_res)
            lifecycle_tracker.track_success(command_id, result=trans_res)
            state_manager.update_command_state(command_id, status="SUCCESS", result=trans_res)
            state_manager.remove_active_command(command_id)
            state_manager.update_recovery_status(command_id=command_id, domain=r_domain, recovery_status="RECOVERED", session=session)
            
        elif resolution["type"] == "action":
            domain_to_plugin = {
                "PYTHON": "desktop",
                "EMBEDDED": "embedded",
                "IOT": "iot",
                "AIML": "aiml",
                "MEDIA": "media"
            }
            plugin_id = domain_to_plugin.get(resolution["domain"], "desktop")
            
            payload = {
                "domain": resolution["domain"], 
                "app": resolution["app"],
                "confidence": confidence,
                "source": source,
                "execution_id": execution_id
            }
            
            if plugin_id == "iot":
                if not device_id:
                    err_msg = "Missing device_id: Validation Error: device_id is required for IoT actions"
                    result["action_result"] = {"status": "failed", "error": err_msg}
                    t_exec_end = time.perf_counter()
                    proc_ms = max(0.05, (t_exec_end - t0) * 1000.0)
                    state_manager.record_performance_metrics(proc_ms, 0.0)
                    lifecycle_tracker.update_status(execution_id, "FAILED", error=err_msg)
                    lifecycle_tracker.track_failure(command_id, error=err_msg, error_code="VALIDATION_ERROR")
                    state_manager.record_failure(
                        command_id=command_id,
                        domain="IOT",
                        affected_component="IoT Handler",
                        failure_type="VALIDATION_ERROR",
                        failure_reason="device_id is required for IoT actions",
                        session=session
                    )
                    state_manager.update_command_state(command_id, status="FAILED", error=err_msg)
                    state_manager.remove_active_command(command_id)
                    result["lifecycle"] = lc_record.to_dict()
                    result["timing"] = lifecycle_tracker.get_execution_timing(command_id)
                    return result
                payload["device_id"] = device_id
                
            def state_updater_cb(attempt, status, reason):
                st = state_manager.get_state(session)
                logs = st.get("action_logs", [])
                logs.append({
                    "attempt": attempt,
                    "status": status,
                    "reason": reason,
                    "action": resolution["action"],
                    "app": resolution["app"]
                })
                state_manager.update_state(session, {
                    "retry_status": status,
                    "retry_attempt": attempt,
                    "retry_reason": reason,
                    "action_logs": logs[-50:]
                })
                if status in ("RETRYING", "RECOVERING"):
                    state_manager.update_recovery_status(
                        command_id=command_id,
                        domain=resolution.get("domain"),
                        recovery_status=status,
                        attempt=attempt,
                        reason=reason,
                        session=session
                    )
                
            if plugin_id == "iot" and device_id:
                resource_id = f"device:{device_id}"
            else:
                resource_id = f"resource:{resolution['domain']}:{resolution['app']}"

            async def run_action():
                async with resource_lock_manager.lock(resource_id, owner=session):
                    action_res = await retry_manager.execute_with_retry(
                        command_name=resolution["action"],
                        session=session,
                        state_updater_cb=state_updater_cb,
                        func=execute,
                        plugin_id=plugin_id,
                        command=resolution["action"],
                        payload=payload
                    )
                    t_exec_end = time.perf_counter()
                    exec_ms = max(0.05, (t_exec_end - t_exec_start) * 1000.0)
                    proc_ms = max(0.05, (t_exec_start - t0) * 1000.0)
                    state_manager.record_performance_metrics(
                        proc_ms, exec_ms,
                        stage_breakdown={
                            "normalization": (t_norm_end - t0)*1000.0,
                            "validation": (t_val_end - t_norm_end)*1000.0,
                            "routing": (t_rout_end - t_rout_start)*1000.0,
                            "execution": exec_ms
                        }
                    )
                    
                    is_action_success = True
                    if isinstance(action_res, dict):
                        st_check = (action_res.get("status") or "").upper()
                        if st_check in ("FAILED", "ERROR"):
                            is_action_success = False
                            
                    if is_action_success:
                        lifecycle_tracker.update_status(execution_id, "SUCCESS", result=action_res)
                        lifecycle_tracker.track_success(command_id, result=action_res)
                        state_manager.update_command_state(command_id, status="SUCCESS", result=action_res)
                        state_manager.remove_active_command(command_id)
                        state_manager.update_recovery_status(command_id=command_id, domain=r_domain, recovery_status="RECOVERED", session=session)
                    else:
                        err_text = action_res.get("reason") or action_res.get("error") or action_res.get("message") or "Action execution failed"
                        lifecycle_tracker.update_status(execution_id, "FAILED", error=err_text)
                        lifecycle_tracker.track_failure(command_id, error=err_text, error_code="EXECUTION_ERROR")
                        state_manager.record_failure(
                            command_id=command_id,
                            domain=r_domain,
                            affected_component=f"{r_domain} Handler",
                            failure_type="EXECUTION_ERROR",
                            failure_reason=str(err_text),
                            session=session
                        )
                        state_manager.update_command_state(command_id, status="FAILED", error=err_text)
                        state_manager.remove_active_command(command_id)

                    if isinstance(action_res, dict):
                        state_manager.update_state(session, {
                            "last_resolved_action": resolution["action"],
                            "action_status": action_res.get("status")
                        })
                    else:
                        state_manager.update_state(session, {
                            "last_resolved_action": resolution["action"],
                            "action_status": None
                        })
                    return action_res

            if plugin_id in ("iot", "embedded"):
                action_res = await run_action()
                if isinstance(action_res, dict) and "result" in action_res:
                    wrapper_status = (action_res.get("status") or "").upper()
                    inner = action_res.get("result") or {}
                    if wrapper_status in ("SUCCESS", "COMPLETED"):
                        if isinstance(inner, dict):
                            inner.setdefault("status", "success")
                            if isinstance(inner["status"], str):
                                inner["status"] = inner["status"].lower()
                            result["action_result"] = inner
                        else:
                            result["action_result"] = {"status": "success", "result": inner}
                    else:
                        err = action_res.get("reason") or (inner.get("message") if isinstance(inner, dict) else None)
                        out = {"status": "failed", "error": err}
                        if isinstance(inner, dict):
                            if "action" in inner:
                                out["action"] = inner["action"]
                            for k, v in inner.items():
                                if k not in out:
                                    out[k] = v
                        result["action_result"] = out
                else:
                    if isinstance(action_res, dict) and "status" in action_res and isinstance(action_res["status"], str):
                        action_res["status"] = action_res["status"].lower()
                    result["action_result"] = action_res
            else:
                async_task_manager.submit(run_action())
                
            result["executed"] = True

        elif resolution["type"] == "navigate_back":
            active_app = state.get("active_app")
            if active_app:
                await execute("desktop", "close_app", {"domain": state.get("active_domain"), "app": active_app})
            updates = navigate_back(state)
            if updates:
                state_manager.update_state(session, updates)
            t_exec_end = time.perf_counter()
            exec_ms = max(0.05, (t_exec_end - t_exec_start) * 1000.0)
            proc_ms = max(0.05, (t_exec_start - t0) * 1000.0)
            state_manager.record_performance_metrics(proc_ms, exec_ms, stage_breakdown={"execution": exec_ms})
            lifecycle_tracker.update_status(execution_id, "SUCCESS", result={"action": "navigate_back"})
            lifecycle_tracker.track_success(command_id, result={"action": "navigate_back"})
            state_manager.update_command_state(command_id, status="SUCCESS", result={"action": "navigate_back"})
            state_manager.remove_active_command(command_id)
            
        elif resolution["type"] == "navigate_home":
            active_app = state.get("active_app")
            if active_app:
                await execute("desktop", "close_app", {"domain": state.get("active_domain"), "app": active_app})
            updates = navigate_home(state)
            if updates:
                state_manager.update_state(session, updates)
            t_exec_end = time.perf_counter()
            exec_ms = max(0.05, (t_exec_end - t_exec_start) * 1000.0)
            proc_ms = max(0.05, (t_exec_start - t0) * 1000.0)
            state_manager.record_performance_metrics(proc_ms, exec_ms, stage_breakdown={"execution": exec_ms})
            lifecycle_tracker.update_status(execution_id, "SUCCESS", result={"action": "navigate_home"})
            lifecycle_tracker.track_success(command_id, result={"action": "navigate_home"})
            state_manager.update_command_state(command_id, status="SUCCESS", result={"action": "navigate_home"})
            state_manager.remove_active_command(command_id)
        else:
            result["status"] = "no_action"
            lifecycle_tracker.update_status(execution_id, "SUCCESS", result={"action": "no_action"})
            lifecycle_tracker.track_success(command_id, result={"action": "no_action"})
            state_manager.remove_active_command(command_id)
            
        current_state = state_manager.get_state(session)
        validation = sequence_validator.refresh(validation, current_state)
        sequence_validator.record(session, validation, state_manager)
        result["validation"] = validation
        result["state"] = current_state
        result["lock"] = command_lock_manager.get_lock_state(session)
        result["lifecycle"] = lc_record.to_dict()
        result["lifecycle_stage"] = lc_record.current_stage.value if hasattr(lc_record.current_stage, "value") else str(lc_record.current_stage)
        result["timing"] = lifecycle_tracker.get_execution_timing(command_id)
        return result

    async def _process_parallel(self, commands: list, session: str, confidence: float, source: str, device_id: str, execution_id: str):
        try:
            from core.validation.command_normalizer import normalize_command
        except ImportError:
            normalize_command = lambda c: c.upper()
            
        executables = []
        for cmd_raw in commands:
            cmd = normalize_command(cmd_raw)
            parallel_command_id = uuid.uuid4().hex
            
            lifecycle_tracker.start_execution(command=cmd, priority="NORMAL", execution_id=parallel_command_id)
            lc_rec = lifecycle_tracker.create_command(command=cmd, session_id=session, command_id=parallel_command_id)
            
            print("\n========== COMMAND CONTEXT ==========")
            print(f"Execution ID: {execution_id}")
            print(f"Session ID  : {session}")
            print(f"Command ID  : {parallel_command_id}")
            print(f"Command     : {cmd}")
            print("======================================")
            
            state = state_manager.get_state(session)
            validation = sequence_validator.validate(cmd, state)
            
            state_manager.add_command(session, cmd, parallel_command_id)
            sequence_validator.record(session, validation, state_manager)
            lifecycle_tracker.track_validation(parallel_command_id, is_valid=validation["is_valid"], reason=validation.get("rejection_reason"))
            
            if not validation["is_valid"]:
                err_text = validation.get("rejection_reason", "Invalid command sequence")
                lifecycle_tracker.update_status(parallel_command_id, "FAILED", error=err_text)
                lifecycle_tracker.track_failure(parallel_command_id, error=err_text)
                executables.append({
                    "cmd": cmd,
                    "command_id": parallel_command_id,
                    "resolution": {"type": "invalid"},
                    "conflict": err_text,
                    "validation": validation,
                    "status": "FAILED",
                    "error": err_text,
                    "base_result": {
                        "status": "invalid",
                        "command": cmd,
                        "command_id": parallel_command_id,
                        "execution_id": execution_id,
                        "resolved": {"type": "no_action"},
                        "executed": False,
                        "validation": validation,
                        "state": state_manager.get_state(session),
                        "lifecycle": lc_rec.to_dict(),
                        "timing": lifecycle_tracker.get_execution_timing(parallel_command_id),
                    }
                })
                continue
                
            resolution = resolve_command(cmd, state)
            r_domain = resolution.get("domain") or state.get("active_domain") or "Core"
            lc_rec.domain = r_domain
            lifecycle_tracker.update_status(parallel_command_id, "RUNNING")
            lifecycle_tracker.track_execution_started(parallel_command_id, target=r_domain)
            
            result = {
                "status": "success",
                "command": cmd,
                "command_id": parallel_command_id,
                "execution_id": execution_id,
                "resolved": resolution,
                "executed": False,
                "validation": validation,
                "lifecycle": lc_rec.to_dict(),
                "timing": lifecycle_tracker.get_execution_timing(parallel_command_id),
            }
            
            execute_func = None
            payload = {}
            
            if resolution["type"] == "transition":
                async def trans_func(r=resolution, s=session, cid=parallel_command_id):
                    state_manager.update_state(s, {
                        "current_level": r["level"],
                        "active_domain": r["domain"],
                        "active_app": r["app"],
                        "last_resolved_action": None
                    })
                    lifecycle_tracker.update_status(cid, "SUCCESS", result={"action": "transition"})
                    lifecycle_tracker.track_success(cid, result={"action": "transition"})
                    return {"status": "success", "action": "transition"}
                execute_func = trans_func
                
            elif resolution["type"] == "action":
                domain_to_plugin = {
                    "PYTHON": "desktop",
                    "EMBEDDED": "embedded",
                    "IOT": "iot",
                    "AIML": "aiml",
                    "MEDIA": "media"
                }
                plugin_id = domain_to_plugin.get(resolution["domain"], "desktop")
                
                payload = {
                    "domain": resolution["domain"], 
                    "app": resolution["app"],
                    "confidence": confidence,
                    "source": source,
                    "execution_id": execution_id
                }
                if plugin_id == "iot":
                    if not device_id:
                        err_iot = "Validation Error: device_id is required for IoT actions"
                        lifecycle_tracker.update_status(parallel_command_id, "FAILED", error=err_iot)
                        lifecycle_tracker.track_failure(parallel_command_id, error=err_iot)
                        executables.append({
                            "cmd": cmd,
                            "command_id": parallel_command_id,
                            "resolution": resolution,
                            "conflict": "Missing device_id",
                            "status": "FAILED",
                            "error": err_iot,
                            "base_result": result
                        })
                        continue
                    payload["device_id"] = device_id
                    
                def make_state_updater(res, sess):
                    def cb(attempt, status, reason):
                        st = state_manager.get_state(sess)
                        logs = st.get("action_logs", [])
                        logs.append({
                            "attempt": attempt,
                            "status": status,
                            "reason": reason,
                            "action": res["action"],
                            "app": res["app"]
                        })
                        state_manager.update_state(sess, {
                            "retry_status": status,
                            "retry_attempt": attempt,
                            "retry_reason": reason,
                            "action_logs": logs[-50:]
                        })
                    return cb
                
                async def run_act(pid=plugin_id, res=resolution, p=payload, cb=make_state_updater(resolution, session), sess=session, cid=parallel_command_id):
                    action_res = await retry_manager.execute_with_retry(
                        command_name=res["action"],
                        session=sess,
                        state_updater_cb=cb,
                        func=execute,
                        plugin_id=pid,
                        command=res["action"],
                        payload=p
                    )
                    is_ok = True
                    if isinstance(action_res, dict) and (action_res.get("status") or "").upper() in ("FAILED", "ERROR"):
                        is_ok = False
                    if is_ok:
                        lifecycle_tracker.update_status(cid, "SUCCESS", result=action_res)
                        lifecycle_tracker.track_success(cid, result=action_res)
                    else:
                        err_act = action_res.get("reason") or action_res.get("error") if isinstance(action_res, dict) else "Action failed"
                        lifecycle_tracker.update_status(cid, "FAILED", error=str(err_act))
                        lifecycle_tracker.track_failure(cid, error=str(err_act))

                    if isinstance(action_res, dict):
                        state_manager.update_state(sess, {
                            "last_resolved_action": res["action"],
                            "action_status": action_res.get("status")
                        })
                    else:
                        state_manager.update_state(sess, {
                            "last_resolved_action": res["action"],
                            "action_status": None
                        })
                    return action_res
                execute_func = run_act
                
            elif resolution["type"] == "navigate_back":
                async def nav_b(s=session, st=state, cid=parallel_command_id):
                    active_app = st.get("active_app")
                    if active_app:
                        await execute("desktop", "close_app", {"domain": st.get("active_domain"), "app": active_app})
                    updates = navigate_back(st)
                    if updates:
                        state_manager.update_state(s, updates)
                    lifecycle_tracker.update_status(cid, "SUCCESS", result={"action": "navigate_back"})
                    lifecycle_tracker.track_success(cid, result={"action": "navigate_back"})
                    return {"status": "success", "action": "navigate_back"}
                execute_func = nav_b
                
            elif resolution["type"] == "navigate_home":
                async def nav_h(s=session, st=state, cid=parallel_command_id):
                    active_app = st.get("active_app")
                    if active_app:
                        await execute("desktop", "close_app", {"domain": st.get("active_domain"), "app": active_app})
                    updates = navigate_home(st)
                    if updates:
                        state_manager.update_state(s, updates)
                    lifecycle_tracker.update_status(cid, "SUCCESS", result={"action": "navigate_home"})
                    lifecycle_tracker.track_success(cid, result={"action": "navigate_home"})
                    return {"status": "success", "action": "navigate_home"}
                execute_func = nav_h
                
            executables.append({
                "cmd": cmd,
                "command_id": parallel_command_id,
                "resolution": resolution,
                "payload": payload,
                "execute_func": execute_func,
                "base_result": result
            })
            
        parallel_results = await parallel_engine.execute_concurrently(executables)
        
        final_results = []
        for pr in parallel_results:
            br = pr.get("base_result", {})
            cid = pr.get("command_id") or br.get("command_id")
            
            if pr.get("status") == "SUCCESS":
                action_res = pr.get("action_res")
                if isinstance(action_res, dict) and "result" in action_res:
                    wrapper_status = (action_res.get("status") or "").upper()
                    inner = action_res.get("result") or {}
                    if wrapper_status == "SUCCESS":
                        if isinstance(inner, dict):
                            inner.setdefault("status", "success")
                            if isinstance(inner["status"], str):
                                inner["status"] = inner["status"].lower()
                            br["action_result"] = inner
                        else:
                            br["action_result"] = {"status": "success", "result": inner}
                    else:
                        err = action_res.get("reason") or (inner.get("message") if isinstance(inner, dict) else None)
                        out = {"status": "failed", "error": err}
                        if isinstance(inner, dict):
                            if "action" in inner:
                                out["action"] = inner["action"]
                            for k, v in inner.items():
                                if k not in out:
                                    out[k] = v
                        br["action_result"] = out
                else:
                    if isinstance(action_res, dict) and "status" in action_res and isinstance(action_res["status"], str):
                        action_res["status"] = action_res["status"].lower()
                    br["action_result"] = action_res
                    
                br["executed"] = True
                
            elif pr.get("status") == "FAILED":
                if br.get("status") != "invalid":
                    br["status"] = "failed"
                br["error"] = pr.get("error", pr.get("conflict"))
                br["executed"] = False
                
            current_state = state_manager.get_state(session)
            if "validation" in br:
                br["validation"] = sequence_validator.refresh(br["validation"], current_state)
                sequence_validator.record(session, br["validation"], state_manager)
            br["state"] = current_state
            if cid:
                lc = lifecycle_tracker.get_lifecycle(cid)
                if lc:
                    br["lifecycle"] = lc.to_dict()
                br["timing"] = lifecycle_tracker.get_execution_timing(cid)
            
            final_results.append(br)
            
        return final_results

    async def process_dependent_workflow(
        self,
        actions: list,
        session: str = "default",
        global_timeout: float = None,
        confidence: float = 1.0,
        source: str = "unknown",
        execution_id: str = None
    ):
        """
        Executes a workflow of dependent actions with synchronized timing controls.
        """
        if not execution_id:
            execution_id = uuid.uuid4().hex

        from core.orchestration.timing_controller import timing_controller, DependentAction

        async def _orchestrator_action_executor(action: DependentAction):
            cmd_str = str(action.command)
            dev_id = action.device_id
            res = await self.process_command(
                command=cmd_str,
                session=session,
                confidence=confidence,
                source=source,
                device_id=dev_id,
                execution_id=execution_id
            )
            if isinstance(res, dict):
                if res.get("status") in ["failed", "invalid"]:
                    err = res.get("error") or (res.get("action_result", {}).get("error") if isinstance(res.get("action_result"), dict) else "Action execution failed")
                    raise RuntimeError(err)
            return res

        return await timing_controller.execute_dependent_actions(
            actions=actions,
            session=session,
            global_timeout=global_timeout,
            execute_fn=_orchestrator_action_executor
        )

ecosystem_orchestrator = EcosystemOrchestrator()

