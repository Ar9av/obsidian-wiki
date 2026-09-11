"""Staged-write promotion: inventory, promote, discard, and the conflict path."""

from __future__ import annotations

import pytest

from obsidian_wiki.staging import (
    StagingConflict,
    StagingError,
    discard,
    list_staged,
    log_decisions,
    promote,
    revision,
)


def write(vault, rel, body):
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def vault(tmp_path):
    write(tmp_path, "concepts/live.md", "---\ntitle: Live\n---\n\noriginal\n")
    write(tmp_path, "_staging/concepts/live.md", "---\ntitle: Live\n---\n\nrevised\n")
    write(tmp_path, "_staging/concepts/fresh.md", "---\ntitle: Fresh\n---\n\nbrand new\n")
    write(tmp_path, "_staging/concepts/live.patch.md", "+ added\n- removed\n")
    return tmp_path


def test_listing_classifies_new_update_and_patch(vault):
    by_staged = {e.staged_path: e for e in list_staged(vault)}
    assert by_staged["_staging/concepts/fresh.md"].kind == "new"
    assert by_staged["_staging/concepts/live.md"].kind == "update"

    patch = by_staged["_staging/concepts/live.patch.md"]
    assert patch.kind == "patch"
    # A patch targets the page it is named after, with the .patch infix dropped.
    assert patch.live_path == "concepts/live.md"


def test_listing_pins_both_revisions(vault):
    entries = {e.staged_path: e for e in list_staged(vault)}
    update = entries["_staging/concepts/live.md"]
    assert update.staged_revision == revision(vault / "_staging/concepts/live.md")
    assert update.live_revision == revision(vault / "concepts/live.md")
    # There is no live page for a new one, and that absence is itself the revision.
    assert entries["_staging/concepts/fresh.md"].live_revision is None


def test_empty_staging_lists_nothing(tmp_path):
    assert list_staged(tmp_path) == []


def test_promoting_a_new_page_moves_it_live(vault):
    result = promote(vault, "concepts/fresh.md")
    assert result["kind"] == "new"
    assert (vault / "concepts/fresh.md").read_text(encoding="utf-8") == (
        "---\ntitle: Fresh\n---\n\nbrand new\n"
    )
    assert not (vault / "_staging/concepts/fresh.md").exists()


def test_promoting_an_update_replaces_the_live_page(vault):
    assert promote(vault, "concepts/live.md")["kind"] == "update"
    assert "revised" in (vault / "concepts/live.md").read_text(encoding="utf-8")


def test_promotion_preserves_arbitrary_frontmatter_byte_for_byte(vault):
    staged = write(
        vault,
        "_staging/references/odd.md",
        "---\ntitle: Odd\nhouse_style: {a: 1}\ntags: [x, y]\n---\n\nbody  with   spacing\n",
    )
    original = staged.read_bytes()
    promote(vault, "references/odd.md")
    # A rename, not a rewrite: nothing normalises frontmatter, prose or links.
    assert (vault / "references/odd.md").read_bytes() == original


def test_promotion_accepts_either_path_spelling(vault):
    promote(vault, "_staging/concepts/fresh.md")
    assert (vault / "concepts/fresh.md").is_file()


def test_promotion_refuses_a_patch(vault):
    with pytest.raises(StagingError, match="is a patch"):
        promote(vault, "concepts/live.patch.md")
    assert (vault / "_staging/concepts/live.patch.md").is_file()


def test_promotion_refuses_when_the_live_page_moved_on(vault):
    reviewed = revision(vault / "concepts/live.md")
    # An agent rewrites the live page while a human is still reading the diff.
    write(vault, "concepts/live.md", "---\ntitle: Live\n---\n\nagent wrote this\n")

    with pytest.raises(StagingConflict, match="changed since it was reviewed"):
        promote(vault, "concepts/live.md", expected_live_revision=reviewed)

    assert "agent wrote this" in (vault / "concepts/live.md").read_text(encoding="utf-8")
    assert (vault / "_staging/concepts/live.md").is_file()


def test_promotion_refuses_when_the_staged_file_moved_on(vault):
    reviewed = revision(vault / "_staging/concepts/fresh.md")
    write(vault, "_staging/concepts/fresh.md", "---\ntitle: Fresh\n---\n\nrestaged\n")

    with pytest.raises(StagingConflict):
        promote(vault, "concepts/fresh.md", expected_staged_revision=reviewed)
    assert not (vault / "concepts/fresh.md").exists()


def test_pin_live_absent_catches_a_page_that_appeared(vault):
    """A bare expected_live_revision=None cannot say "there was no page"."""
    write(vault, "concepts/fresh.md", "---\ntitle: Fresh\n---\n\nsomeone got there first\n")

    with pytest.raises(StagingConflict, match="was created since"):
        promote(vault, "concepts/fresh.md", pin_live_absent=True)
    assert "got there first" in (vault / "concepts/fresh.md").read_text(encoding="utf-8")


def test_matching_revisions_promote_normally(vault):
    # Keyed by staged path: a page and its patch share one live_path.
    entry = {e.staged_path: e for e in list_staged(vault)}["_staging/concepts/live.md"]
    promote(
        vault,
        entry.staged_path,
        expected_staged_revision=entry.staged_revision,
        expected_live_revision=entry.live_revision,
    )
    assert "revised" in (vault / "concepts/live.md").read_text(encoding="utf-8")


def test_discard_moves_the_file_to_raw(vault):
    result = discard(vault, "concepts/fresh.md")
    assert result["raw_path"] == "_raw/rejected-concepts-fresh.md"
    assert "brand new" in (vault / result["raw_path"]).read_text(encoding="utf-8")
    assert not (vault / "_staging/concepts/fresh.md").exists()


def test_discarding_a_patch_is_labelled_as_one(vault):
    assert discard(vault, "concepts/live.patch.md")["raw_path"] == (
        "_raw/rejected-patch-concepts-live.md"
    )


def test_a_second_rejection_does_not_clobber_the_first(vault):
    discard(vault, "concepts/fresh.md")
    write(vault, "_staging/concepts/fresh.md", "---\ntitle: Fresh\n---\n\nsecond attempt\n")

    assert discard(vault, "concepts/fresh.md")["raw_path"] == "_raw/rejected-concepts-fresh-2.md"
    assert "brand new" in (vault / "_raw/rejected-concepts-fresh.md").read_text(encoding="utf-8")


def test_emptied_staging_directories_are_pruned(vault):
    for rel in ("concepts/live.md", "concepts/fresh.md"):
        promote(vault, rel)
    discard(vault, "concepts/live.patch.md")
    assert not (vault / "_staging/concepts").exists()


def test_a_traversing_path_is_refused_outright(vault):
    with pytest.raises(StagingError, match="escapes the vault"):
        promote(vault, "../../etc/passwd")


@pytest.mark.parametrize("rel", ["/etc/passwd", "concepts/absent.md"])
def test_odd_but_contained_paths_fail_as_missing(vault, rel):
    """Anchoring under _staging/ and stripping a leading slash contains these."""
    with pytest.raises(StagingError, match="no staged file"):
        promote(vault, rel)


@pytest.mark.parametrize(
    "rel",
    ["../concepts/live.md", "_staging/../concepts/live.md", "concepts/../../escape.md"],
)
def test_a_live_page_cannot_be_promoted_as_if_it_were_staged(vault, rel):
    """Inside the vault is not enough — `..` reaches live pages from _staging/."""
    with pytest.raises(StagingError, match="not under _staging/"):
        promote(vault, rel)
    with pytest.raises(StagingError, match="not under _staging/"):
        discard(vault, rel)
    assert (vault / "concepts/live.md").read_text(encoding="utf-8").endswith("original\n")


def test_missing_staged_file_is_reported(vault):
    with pytest.raises(StagingError, match="no staged file"):
        promote(vault, "concepts/absent.md")


def test_log_records_one_line_per_batch(vault):
    log_decisions(vault, [promote(vault, "concepts/fresh.md"), discard(vault, "concepts/live.md")])
    assert "STAGE_COMMIT accepted=1 rejected=1" in (vault / "log.md").read_text(encoding="utf-8")


def test_log_is_silent_when_nothing_happened(vault):
    log_decisions(vault, [])
    assert not (vault / "log.md").exists()
