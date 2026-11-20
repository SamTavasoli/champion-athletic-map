# Shared model integration

We use OllamaClient(root, contracts_directory) from src/champion_athletic_map/llm.py.
generate(public_record, instructions, call_id, planner_version=1) uses no reference packet.
Versions 2–4 require reference_packet=packet and share the same public input and packet for a matched case.
Use a stable, unique call ID for each logical request. Completed matching calls reuse their saved result.
Unknown transport outcomes block new submissions; there are no automatic repair generations.
The shared public schema validates inputs. Only the input object enters a model message;
wrapper identifiers and private study annotations stay outside the model context.

The current common policy uses native JSON schema output. All four final-response paths use the same policy.
The original local validator remains authoritative. Raw replies are saved before validation, beside the original input.
The backend renders each complete prompt before generation. Counting includes role formatting and output reserves.
Packet limits alone do not establish complete-request capacity. Step 31 confirms final operating limits.

The current saved response passed format and budget checks but returned outside_scope for an in-scope calendar request.
It did not demonstrate a successful weekly calendar. Earlier plain-JSON clarification and reference examples remain historical evidence;
they do not verify reference-supported generation under the current schema configuration.
The original emoji-copying failure is also retained. These are development examples, not accepted study cases or benchmark results.
Steps 25–28 develop planner behavior; representative workflow capacity and operational readiness remain pending.
