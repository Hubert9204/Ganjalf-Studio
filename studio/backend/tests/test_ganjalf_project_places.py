"""Ganjalf: a project remembers where its chats wrote outside the project folder."""

from core.inference import project_places, tools


def _project(monkeypatch, tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    monkeypatch.setattr(tools, "_get_workdir", lambda session_id = None: str(folder))
    return folder


def test_a_write_outside_the_project_is_told_to_the_next_chat(monkeypatch, tmp_path):
    _project(monkeypatch, tmp_path)
    app = tmp_path / "expense-split"
    (app / "public").mkdir(parents = True)
    out = tools.execute_tool(
        "edit_file",
        {
            "path": str(app / "public" / "index.html"),
            "edits": [{"old_string": "", "new_string": "<p>x</p>\n"}],
        },
        session_id = "project-abc",
        disable_sandbox = True,
    )
    assert out.startswith("Created")
    tools.execute_tool(
        "edit_file",
        {"path": str(app / "server.js"), "edits": [{"old_string": "", "new_string": "1\n"}]},
        session_id = "project-abc",
        disable_sandbox = True,
    )
    note = project_places.places_note("project-abc")
    assert str(app) in note and str(app / "public") not in note  # one place, not two
    assert "look there first" in note


def test_inside_the_project_or_outside_a_project_nothing_is_noted(monkeypatch, tmp_path):
    folder = _project(monkeypatch, tmp_path)
    project_places.note_write("project-abc", str(folder / "src" / "a.ts"))
    assert project_places.places_note("project-abc") == ""
    project_places.note_write("chat-1", str(tmp_path / "elsewhere" / "a.ts"))
    assert project_places.places_note("chat-1") == ""


def test_the_prompt_carries_it_for_code_tools(monkeypatch, tmp_path):
    import routes.inference as routes

    _project(monkeypatch, tmp_path)
    app = tmp_path / "app"
    app.mkdir()
    project_places.note_write("project-p", str(app / "server.js"))
    terminal = {"type": "function", "function": {"name": "terminal", "parameters": {}}}
    text = routes._build_tool_action_nudge(tools = [terminal], model_name = "m", session_id = "project-p")
    assert str(app) in text
    assert str(app) not in routes._build_tool_action_nudge(tools = [terminal], model_name = "m")
