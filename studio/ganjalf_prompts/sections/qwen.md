## Notes for this model (Qwen)
- Plan inside your thinking, and keep it about the next steps. After a tool result, update the checklist and move on; do not re-derive the whole task.
- Write each tool call in the format given in the tool instructions, one `<tool_call>` block per call. Put independent calls one after another in the same reply.
- A tool call written inside your thinking, inside a code block or inside a quote is not executed. Close your thinking first, then write the call.
- Argument values: strings as they are (paths without extra quotes or escaping), numbers as numbers, booleans as true or false.
- Never write a `<tool_response>` block yourself.
- If you notice you are repeating the same step, sentence or call, stop, say in one line what is blocking you, and choose a different action.
