import logging
import asyncio
from typing import Union
from core.plugin_manager.manager import execute
from core.state.state_manager import state_manager
from core.routing.rule_router import resolve_command, navigate_back, navigate_home
from core.navigation.sequence_validator import sequence_validator
from core.managers.retry_manager import retry_manager
from core.orchestration.parallel_engine import parallel_engine
from core.managers.async_task_manager import async_task_manager
from core.managers.resource_lock_manager import resource_lock_manager
from core.managers.lifecycle_tracker import lifecycle_tracker, CommandLifecycleStage
from core.managers.domain_handler import domain_handler

logger = logging.getLogger("orchestrator")

class EcosystemOrchestrator:
    async def process_command(
        self,
        command: Union[str, list],
        session: str = "default",
        confidence: float = 1.0,
        source: str = "unknown",
        device_id: Optional[str] = None,
        command_id: Optional[str] = None
    ):
        if isinstance(command, list):
            logger.info(f"[ORCHESTRATOR] PARALLEL COMMANDS INPUT: {command}")
            return await self._process_parallel(command, session, confidence, source, device_id)
        
        logger.info(f"[ORCHESTRATOR] COMMAND INPUT: {command}")
        
        # Track CREATED
        cmd_raw_str = str(command)
        rec = lifecycle_tracker.create_command(
            command=cmd_raw_str,
            session_id=session,
            command_id=command_id,
            metadata={"confidence": confidence, "source": source, "device_id": device_id}
        )
        command_id = rec.command_id
        
        # Track VALIDATING
        lifecycle_tracker.track_validating(command_id)
        
        try:
            from core.validation.command_normalizer import normalize_command
            cmd = normalize_command(command)
        except ImportError:
            cmd = command.upper()
            
        logger.info(f"[ORCHESTRATOR] COMMAND PARSED: {cmd}")
        state = state_manager.get_state(session)
        
        validation = sequence_validator.validate(cmd, state)
        logger.info(f"[ORCHESTRATOR] COMMAND VALIDATED: {validation['is_valid']}")
        
        state_manager.add_command(session, cmd, command_id=command_id)
        sequence_validator.record(session, validation, state_manager)
        
        if not validation["is_valid"]:
            rejection_reason = validation.get("rejection_reason", "Invalid command sequence")
            lifecycle_tracker.track_validation(command_id, is_valid=False, reason=rejection_reason)
            lifecycle_tracker.track_failed(command_id, error=rejection_reason, error_code="INVALID_SEQUENCE")
            return {
                "status": "invalid",
                "resolved": {"type": "no_action"},
                "executed": False,
                "validation": validation,
                "state": state_manager.get_state(session),
                "command_id": command_id,
                "lifecycle_stage": rec.current_stage.value,
                "lifecycle": rec.to_dict(),
            }
            
        lifecycle_tracker.track_validation(command_id, is_valid=True)
            
        resolution = resolve_command(cmd, state)
        r_domain = resolution.get("domain") or state.get("active_domain") or "N/A"
        r_app = resolution.get("app") or state.get("active_app") or "N/A"
        r_op = resolution.get("action") or resolution.get("type") or "N/A"
        
        print("\n========== COMMAND ROUTER ==========")
        print(f"Command     : {cmd}")
        print(f"Domain      : {r_domain}")
        print(f"Application : {r_app}")
        print(f"Operation   : {r_op}")
        print("=====================================\n")
        
        result = {
            "status": "success",
            "resolved": resolution,
            "executed": False,
            "validation": validation,
            "command_id": command_id,
        }
        
        if resolution["type"] == "transition":
            target_desc = f"{resolution.get('domain', '')}:{resolution.get('app', '')} [L{resolution.get('level', '')}]"
            lifecycle_tracker.track_execution_started(command_id, target=target_desc)
            state_manager.update_state(session, {
                "current_level": resolution["level"],
                "active_domain": resolution["domain"],
                "active_app": resolution["app"],
                "last_resolved_action": None
            })
            lifecycle_tracker.track_success(command_id, result={"type": "transition", "action": "transition", "domain": resolution["domain"], "app": resolution["app"]})
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
                "source": source
            }
            
            if plugin_id == "iot":
                if not device_id:
                    err_msg = "Missing device_id: Validation Error: device_id is required for IoT actions"
                    lifecycle_tracker.track_failed(command_id, error=err_msg, error_code="MISSING_DEVICE_ID")
                    result["action_result"] = {"status": "failed", "error": err_msg}
                    result["lifecycle_stage"] = rec.current_stage.value
                    result["lifecycle"] = rec.to_dict()
                    return result
                payload["device_id"] = device_id
                
            lifecycle_tracker.track_queued(command_id, priority=resolution.get("priority", "NORMAL"))
            
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
                
            if plugin_id == "iot" and device_id:
                resource_id = f"device:{device_id}"
            else:
                resource_id = f"resource:{resolution['domain']}:{resolution['app']}"

            async def run_action():
                target_str = f"{resolution['domain']}:{resolution['app']}:{resolution['action']}"
                lifecycle_tracker.track_execution_started(command_id, target=target_str)
                async with resource_lock_manager.lock(resource_id, owner=session):
                    action_res = await domain_handler.handle(
                        plugin_id=plugin_id,
                        command=resolution["action"],
                        payload=payload,
                        session=session,
                        device_id=device_id,
                        state_updater_cb=state_updater_cb,
                        func=execute
                    )
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
                    if wrapper_status == "SUCCESS":
                        if isinstance(inner, dict):
                            inner.setdefault("status", "success")
                            if isinstance(inner["status"], str):
                                inner["status"] = inner["status"].lower()
                            result["action_result"] = inner
                        else:
                            result["action_result"] = {"status": "success", "result": inner}
                        lifecycle_tracker.track_execution_completed(command_id, success=True, result=result["action_result"])
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
                        lifecycle_tracker.track_execution_completed(command_id, success=False, result=out, error=err)
                else:
                    if isinstance(action_res, dict) and "status" in action_res and isinstance(action_res["status"], str):
                        action_res["status"] = action_res["status"].lower()
                    result["action_result"] = action_res
                    is_ok = isinstance(action_res, dict) and action_res.get("status") in ("success", "ok")
                    lifecycle_tracker.track_execution_completed(command_id, success=is_ok, result=action_res)
            else:
                async def run_and_track():
                    try:
                        res = await run_action()
                        lifecycle_tracker.track_execution_completed(command_id, success=True, result=res)
                    except Exception as ex:
                        lifecycle_tracker.track_execution_completed(command_id, success=False, error=str(ex))
                async_task_manager.submit(run_and_track())
                
            result["executed"] = True

        elif resolution["type"] == "navigate_back":
            lifecycle_tracker.track_execution_started(command_id, target="NAVIGATE_BACK")
            active_app = state.get("active_app")
            if active_app:
                await execute("desktop", "close_app", {"domain": state.get("active_domain"), "app": active_app})
            updates = navigate_back(state)
            if updates:
                state_manager.update_state(session, updates)
            lifecycle_tracker.track_success(command_id, result={"action": "navigate_back", "updates": updates})
        elif resolution["type"] == "navigate_home":
            lifecycle_tracker.track_execution_started(command_id, target="NAVIGATE_HOME")
            active_app = state.get("active_app")
            if active_app:
                await execute("desktop", "close_app", {"domain": state.get("active_domain"), "app": active_app})
            updates = navigate_home(state)
            if updates:
                state_manager.update_state(session, updates)
            lifecycle_tracker.track_success(command_id, result={"action": "navigate_home", "updates": updates})
        else:
            result["status"] = "no_action"
            lifecycle_tracker.track_success(command_id, result={"action": "no_action"})
            
        current_state = state_manager.get_state(session)
        validation = sequence_validator.refresh(validation, current_state)
        sequence_validator.record(session, validation, state_manager)
        result["validation"] = validation
        result["state"] = current_state
        result["lifecycle_stage"] = rec.current_stage.value
        result["lifecycle"] = rec.to_dict()
        return result

    async def _process_parallel(self, commands: list, session: str, confidence: float, source: str, device_id: str):
        try:
            from core.validation.command_normalizer import normalize_command
        except ImportError:
            normalize_command = lambda c: c.upper()
            
        executables = []
        for cmd_raw in commands:
            cmd = normalize_command(cmd_raw)
            rec = lifecycle_tracker.create_command(
                command=cmd,
                session_id=session,
                metadata={"confidence": confidence, "source": source, "device_id": device_id, "parallel": True}
            )
            command_id = rec.command_id
            lifecycle_tracker.track_validating(command_id)

            state = state_manager.get_state(session)
            validation = sequence_validator.validate(cmd, state)
            
            state_manager.add_command(session, cmd, command_id=command_id)
            sequence_validator.record(session, validation, state_manager)
            
            if not validation["is_valid"]:
                rejection_reason = validation.get("rejection_reason", "Invalid command sequence")
                lifecycle_tracker.track_validation(command_id, is_valid=False, reason=rejection_reason)
                lifecycle_tracker.track_failed(command_id, error=rejection_reason, error_code="INVALID_SEQUENCE")
                executables.append({
                    "cmd": cmd,
                    "command_id": command_id,
                    "resolution": {"type": "invalid"},
                    "conflict": "Invalid command sequence",
                    "validation": validation,
                    "status": "FAILED",
                    "error": "Invalid command sequence",
                    "base_result": {
                        "status": "invalid",
                        "resolved": {"type": "no_action"},
                        "executed": False,
                        "validation": validation,
                        "state": state_manager.get_state(session),
                        "command_id": command_id,
                        "lifecycle_stage": rec.current_stage.value,
                        "lifecycle": rec.to_dict(),
                    }
                })
                continue
                
            lifecycle_tracker.track_validation(command_id, is_valid=True)
            resolution = resolve_command(cmd, state)
            result = {
                "status": "success",
                "resolved": resolution,
                "executed": False,
                "validation": validation,
                "command_id": command_id,
            }
            
            execute_func = None
            payload = {}
            
            if resolution["type"] == "transition":
                async def trans_func(r=resolution, s=session, cid=command_id):
                    lifecycle_tracker.track_execution_started(cid, target=f"{r.get('domain')}:{r.get('app')}")
                    state_manager.update_state(s, {
                        "current_level": r["level"],
                        "active_domain": r["domain"],
                        "active_app": r["app"],
                        "last_resolved_action": None
                    })
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
                    "source": source
                }
                if plugin_id == "iot":
                    if not device_id:
                        err_msg = "Validation Error: device_id is required for IoT actions"
                        lifecycle_tracker.track_failed(command_id, error=err_msg, error_code="MISSING_DEVICE_ID")
                        executables.append({
                            "cmd": cmd,
                            "command_id": command_id,
                            "resolution": resolution,
                            "conflict": "Missing device_id",
                            "status": "FAILED",
                            "error": err_msg,
                            "base_result": result
                        })
                        continue
                    payload["device_id"] = device_id
                    
                lifecycle_tracker.track_queued(command_id, priority=resolution.get("priority", "NORMAL"))

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
                
                async def run_act(pid=plugin_id, res=resolution, p=payload, cb=make_state_updater(resolution, session), sess=session, cid=command_id):
                    lifecycle_tracker.track_execution_started(cid, target=f"{res['domain']}:{res['app']}:{res['action']}")
                    action_res = await domain_handler.handle(
                        plugin_id=pid,
                        command=res["action"],
                        payload=p,
                        session=sess,
                        device_id=device_id,
                        state_updater_cb=cb,
                        func=execute
                    )
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
                async def nav_b(s=session, st=state, cid=command_id):
                    lifecycle_tracker.track_execution_started(cid, target="NAVIGATE_BACK")
                    active_app = st.get("active_app")
                    if active_app:
                        await execute("desktop", "close_app", {"domain": st.get("active_domain"), "app": active_app})
                    updates = navigate_back(st)
                    if updates:
                        state_manager.update_state(s, updates)
                    lifecycle_tracker.track_success(cid, result={"action": "navigate_back"})
                    return {"status": "success", "action": "navigate_back"}
                execute_func = nav_b
                
            elif resolution["type"] == "navigate_home":
                async def nav_h(s=session, st=state, cid=command_id):
                    lifecycle_tracker.track_execution_started(cid, target="NAVIGATE_HOME")
                    active_app = st.get("active_app")
                    if active_app:
                        await execute("desktop", "close_app", {"domain": st.get("active_domain"), "app": active_app})
                    updates = navigate_home(st)
                    if updates:
                        state_manager.update_state(s, updates)
                    lifecycle_tracker.track_success(cid, result={"action": "navigate_home"})
                    return {"status": "success", "action": "navigate_home"}
                execute_func = nav_h
                
            executables.append({
                "cmd": cmd,
                "command_id": command_id,
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
                        if cid:
                            lifecycle_tracker.track_execution_completed(cid, success=True, result=br["action_result"])
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
                        if cid:
                            lifecycle_tracker.track_execution_completed(cid, success=False, result=out, error=err)
                else:
                    if isinstance(action_res, dict) and "status" in action_res and isinstance(action_res["status"], str):
                        action_res["status"] = action_res["status"].lower()
                    br["action_result"] = action_res
                    if cid:
                        is_ok = isinstance(action_res, dict) and action_res.get("status") in ("success", "ok")
                        lifecycle_tracker.track_execution_completed(cid, success=is_ok, result=action_res)
                    
                br["executed"] = True
                
            elif pr.get("status") == "FAILED":
                if br.get("status") != "invalid":
                    br["status"] = "failed"
                br["error"] = pr.get("error", pr.get("conflict"))
                br["executed"] = False
                if cid:
                    lifecycle_tracker.track_failed(cid, error=br["error"])
                
            current_state = state_manager.get_state(session)
            if "validation" in br:
                br["validation"] = sequence_validator.refresh(br["validation"], current_state)
                sequence_validator.record(session, br["validation"], state_manager)
            br["state"] = current_state
            if cid:
                rec = lifecycle_tracker.get_record(cid)
                if rec:
                    br["lifecycle_stage"] = rec.current_stage.value
                    br["lifecycle"] = rec.to_dict()
            
            final_results.append(br)
            
        return final_results

    async def process_dependent_workflow(
        self,
        actions: list,
        session: str = "default",
        global_timeout: float = None,
        confidence: float = 1.0,
        source: str = "unknown"
    ):
        """
        Executes a workflow of dependent actions with synchronized timing controls.
        """
        from core.orchestration.timing_controller import timing_controller, DependentAction

        async def _orchestrator_action_executor(action: DependentAction):
            cmd_str = str(action.command)
            dev_id = action.device_id
            res = await self.process_command(
                command=cmd_str,
                session=session,
                confidence=confidence,
                source=source,
                device_id=dev_id
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

