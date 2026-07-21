"""Tests for `aureon-agent skills list` (cmd_skills_list) + SkillLoader path."""
import asyncio

from skill_loader import SkillLoader

SKILL_MD = """---
name: {name}
description: {desc}
---
Body for {name}.
"""


def _make_skills(root, specs):
    for name, desc in specs:
        d = root / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(SKILL_MD.format(name=name, desc=desc))


def test_get_active_skills_includes_path(tmp_path):
    _make_skills(tmp_path, [("caveman", "compressed talk"), ("notion", "notion ops")])
    loader = SkillLoader(str(tmp_path))
    asyncio.run(loader.load())
    active = loader.get_active_skills()

    assert {s["name"] for s in active} == {"caveman", "notion"}
    for s in active:
        assert s["path"].endswith(s["name"])
        assert s["description"]


def test_cmd_skills_list_prints_all(tmp_path, monkeypatch, capsys):
    from aureon_agent import __main__ as m

    names = ["caveman", "homelab-deploy", "homelab-health", "homelab-scaffold",
             "nano-banana-pro", "notion", "openclaw-health", "project-init"]
    _make_skills(tmp_path, [(n, f"desc for {n}") for n in names])

    # Point cmd_skills_list at the temp skills dir by faking the resolved path.
    import os
    real_join = os.path.join

    def fake_join(*parts):
        if parts[-2:] == ("workspace", "skills"):
            return str(tmp_path)
        return real_join(*parts)

    monkeypatch.setattr(m.os.path, "join", fake_join)
    m.cmd_skills_list(None)

    out = capsys.readouterr().out
    assert "Doctrine Skills (8)" in out
    for n in names:
        # Rich may wrap long names; check the distinctive prefix survives
        assert n.split("-")[0] in out


def test_cmd_skills_list_empty(tmp_path, monkeypatch, capsys):
    from aureon_agent import __main__ as m
    import os
    real_join = os.path.join

    def fake_join(*parts):
        if parts[-2:] == ("workspace", "skills"):
            return str(tmp_path / "empty")
        return real_join(*parts)

    monkeypatch.setattr(m.os.path, "join", fake_join)
    m.cmd_skills_list(None)
    assert "No skills loaded" in capsys.readouterr().out
