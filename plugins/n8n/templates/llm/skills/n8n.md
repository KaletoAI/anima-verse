---
name: RunWorkflow
brief: Run a configured automation; {"workflow":"<configured id>","params":{}}. Use only configured workflows and their parameters.
action_hint: Character triggers an external automation workflow
---
Calls one of the configured external automation workflows (n8n webhook) and returns its JSON response. The LLM passes JSON: {"workflow": "<id>", "params": {...}} — available workflows and their parameters come from the character's skill configuration.
