import sys
import os
import shutil
import tempfile
import asyncio
from pathlib import Path

# Add EverMind Raven code to path
RAVEN_CODE_PATH = "/library/repos/EverMind-AI_raven/code"
if RAVEN_CODE_PATH not in sys.path:
    sys.path.insert(0, RAVEN_CODE_PATH)

# Import hooks and context
from raven.eval_engine.hooks.before_iteration_hook import BeforeIterationHook
from raven.eval_engine.hooks.tool_audit_hook import ToolAuditHook
from raven.eval_engine.config import EvalEngineConfig
from raven.agent.hook.base import AgentHookContext

async def run_hook_tests():
    print("=== TESTING EVAL ENGINE HOOKS ===")
    
    # 1. BeforeIterationHook
    config = EvalEngineConfig(
        enabled=True,
        on_iteration_gate=True,
        max_iteration_tokens=100
    )
    hook = BeforeIterationHook(config)
    
    # Toy messages (under budget)
    under_messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
    ctx_under = AgentHookContext(
        session_key="test_session",
        messages=under_messages,
        iteration=1
    )
    decision_under = await hook.before_iteration(ctx_under)
    print(f"BeforeIterationHook (under budget): pass_through={decision_under.pass_through}, short_circuit_result={decision_under.short_circuit_result}, notes={decision_under.notes}")
    
    # Toy messages (over budget)
    over_messages = [{"role": "user", "content": "a" * 300}, {"role": "assistant", "content": "b" * 300}]
    ctx_over = AgentHookContext(
        session_key="test_session",
        messages=over_messages,
        iteration=2
    )
    decision_over = await hook.before_iteration(ctx_over)
    print(f"BeforeIterationHook (over budget): pass_through={decision_over.pass_through}, short_circuit_result={decision_over.short_circuit_result}, notes={decision_over.notes}")

    # 2. ToolAuditHook
    config_tool = EvalEngineConfig(
        enabled=True,
        on_tool_audit=True,
        tool_denylist=["rm_rf", "eval_unsafe"]
    )
    tool_hook = ToolAuditHook(config_tool)
    
    # Safe response
    response_safe = {
        "tool_calls": [
            {"name": "read_file", "arguments": {"path": "foo.txt"}}
        ]
    }
    ctx_safe = AgentHookContext(
        session_key="test_session",
        response=response_safe
    )
    decision_safe = await tool_hook.before_execute_tools(ctx_safe)
    print(f"ToolAuditHook (safe tools): pass_through={decision_safe.pass_through}, short_circuit_result={decision_safe.short_circuit_result}, notes={decision_safe.notes}")
    
    # Offending response
    response_unsafe = {
        "tool_calls": [
            {"name": "read_file", "arguments": {"path": "foo.txt"}},
            {"name": "rm_rf", "arguments": {"path": "/"}}
        ]
    }
    ctx_unsafe = AgentHookContext(
        session_key="test_session",
        response=response_unsafe
    )
    decision_unsafe = await tool_hook.before_execute_tools(ctx_unsafe)
    print(f"ToolAuditHook (unsafe tools): pass_through={decision_unsafe.pass_through}, short_circuit_result={decision_unsafe.short_circuit_result}, notes={decision_unsafe.notes}")

def run_evolver_analysis_tests():
    print("\n=== TESTING EVOLVER ANALYSIS MODULES ===")
    
    # Create a temporary directory structure mimicking trials
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        # We need task_ids: task_a, task_b
        # Directory names format: {task_id}__{suffix}
        # Under each directory: result.json and verifier/reward.txt
        
        tasks_data = {
            "task_a__attempt1": {"reward": "1.0", "passed": True, "exit": "passed", "turns": 2, "tools": True, "docker_errors": 0},
            "task_a__attempt2": {"reward": "1.0", "passed": True, "exit": "passed", "turns": 3, "tools": True, "docker_errors": 0},
            "task_a__attempt3": {"reward": "1.0", "passed": True, "exit": "passed", "turns": 2, "tools": True, "docker_errors": 0},
            
            "task_b__attempt1": {"reward": "0.0", "passed": False, "exit": "failed_verifier", "turns": 5, "tools": True, "docker_errors": 0},
            "task_b__attempt2": {"reward": "1.0", "passed": True, "exit": "passed", "turns": 4, "tools": True, "docker_errors": 0},
            "task_b__attempt3": {"reward": "0.0", "passed": False, "exit": "AgentTimeoutError", "turns": 10, "tools": True, "docker_errors": 1},
        }
        
        for name, data in tasks_data.items():
            trial_dir = tmp_path / name
            trial_dir.mkdir()
            
            # Write result.json
            res_content = {
                "trial_id": name,
                "exception_info": {
                    "exception_type": data["exit"] if "Error" in data["exit"] else None,
                    "exception_traceback": "docker.errors.DockerException" if data["docker_errors"] > 0 else ""
                }
            }
            (trial_dir / "result.json").write_text(json.dumps(res_content))
            
            # Write verifier/reward.txt
            v_dir = trial_dir / "verifier"
            v_dir.mkdir()
            (v_dir / "reward.txt").write_text(data["reward"])
            
            # Write agent/workspace/sessions/tb2-task.jsonl
            sess_dir = trial_dir / "agent" / "workspace" / "sessions"
            sess_dir.mkdir(parents=True)
            
            # Write session file with some assistant and tool messages
            session_lines = [
                json.dumps({"role": "user", "content": "Please do the task"}),
            ]
            for i in range(data["turns"]):
                session_lines.append(json.dumps({
                    "role": "assistant",
                    "content": f"Thinking step {i}",
                    "tool_calls": [{"name": "some_tool"}] if data["tools"] else []
                }))
                if data["tools"]:
                    session_lines.append(json.dumps({
                        "role": "tool",
                        "content": "container not running" if data["docker_errors"] > 0 and i == 0 else "tool output"
                    }))
            
            (sess_dir / "tb2-task.jsonl").write_text("\n".join(session_lines) + "\n")
            
        # Now import the stability bucket and proxy features modules
        from raven.evolver.analysis.stability_bucket import compute_stability, bucket_counts
        from raven.evolver.analysis.proxy_features import extract_features, extract_trial_dir
        from raven.evolver.analysis.trial_pool import build_trial_pool
        
        # Test compute_stability
        stability = compute_stability(tmp_path)
        print("Task Stability Results:")
        for task_id, ts in stability.items():
            print(f"  Task: {task_id}, Attempts: {ts.attempts}, Passes: {ts.passes}, Bucket: {ts.bucket.value}")
        
        print("Bucket Counts:")
        counts = bucket_counts(stability.values())
        for bucket, count in counts.items():
            print(f"  {bucket.value}: {count}")
            
        # Test extract_features on one of the trials
        print("\nProxy Features for task_b__attempt3:")
        feat = extract_features(tmp_path / "task_b__attempt3")
        print(f"  Trial ID: {feat.trial_id}")
        print(f"  Task ID: {feat.task_id}")
        print(f"  Turn Count: {feat.turn_count}")
        print(f"  Final Exit Status: {feat.final_exit_status.value}")
        print(f"  Has Tool Calls: {feat.has_tool_calls_ever}")
        print(f"  Assistant Text Length Avg: {feat.assistant_text_length_avg}")
        print(f"  Docker Error Count: {feat.docker_error_count}")
        
        # Test build_trial_pool
        print("\nUnified Trial Pool Objects:")
        trials = build_trial_pool(tmp_path)
        for t in trials:
            print(f"  Trial ID: {t.trial_id}, Task ID: {t.task_id}, Attempt: {t.attempt}, Passed: {t.passed}, Stability: {t.stability.value}, Proxy Features: {t.proxy_features}")

import json
if __name__ == "__main__":
    asyncio.run(run_hook_tests())
    run_evolver_analysis_tests()
