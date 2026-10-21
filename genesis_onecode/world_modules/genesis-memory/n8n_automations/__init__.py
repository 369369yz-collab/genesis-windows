"""n8n automations for genesis-memory.

Wired + working: workflows are executed via n8n_runner, not just stored.
"""
from pathlib import Path
from .registry import REGISTRY
from .n8n_runner import run_workflow, validate_workflow, MockLLM, SlotError

_WF_DIR = Path(__file__).parent / 'workflows'

def list_workflows():
    """Return {workflow_id: metadata}."""
    return dict(REGISTRY)

def get_workflow(workflow_id):
    """Load a workflow JSON by id."""
    import json
    p = _WF_DIR / f'{workflow_id}.json'
    raw = json.loads(p.read_text(encoding='utf-8'))
    return raw.get('workflow', raw)

def run_automation(workflow_id, **kwargs):
    """Run a workflow by id. kwargs -> run_workflow (llm, http_transport, ...)."""
    wf = get_workflow(workflow_id)
    return run_workflow(wf, **kwargs)
