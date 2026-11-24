// SPDX-License-Identifier: AGPL-3.0-only
// Ganjalf: parsing for the todo_write card (tool-ui-todo.tsx).

export type TodoItem = { content: string; status: string; activeForm?: string };

/** The list the model sent, tolerating a JSON string and dropping malformed items. */
export function todoItems(raw: unknown): TodoItem[] {
  let value = raw;
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch {
      return [];
    }
  }
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const record = item as Record<string, unknown>;
    const content = typeof record.content === "string" ? record.content.trim() : "";
    if (!content) return [];
    const status = typeof record.status === "string" ? record.status : "pending";
    const activeForm = typeof record.activeForm === "string" ? record.activeForm : undefined;
    return [{ content, status, activeForm }];
  });
}

/** "3/7 · Adding the camera": progress and the step under way, for the collapsed card. */
export function todoSummary(items: TodoItem[]): string {
  const done = items.filter((item) => item.status === "completed").length;
  const current = items.find((item) => item.status === "in_progress");
  const step = current ? ` · ${current.activeForm || current.content}` : "";
  return `${done}/${items.length}${step}`;
}
