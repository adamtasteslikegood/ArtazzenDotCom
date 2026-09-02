#!/usr/bin/env python3
"""Generate AGENTS.md by flattening CLAUDE.md and its ``@`` imports.

``CLAUDE.md`` uses ``@path`` lines to pull in shared guidance. Some agent
tools read ``AGENTS.md`` and do not understand that syntax, so this script
resolves every import into a single self-contained document.

``AGENTS.md`` is the *output* of this script and must never be an input:
importing it would inline the previous generation into the next one, which is
how the file previously ended up containing two full copies of the chain.
``_resolve`` guards against that by tracking every file it has already
inlined.

Usage::

    python scripts/generate_agents_md.py           # write AGENTS.md
    python scripts/generate_agents_md.py --check    # exit 1 if stale
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINT = REPO_ROOT / "CLAUDE.md"
OUTPUT = REPO_ROOT / "AGENTS.md"

BANNER = (
    "<!-- GENERATED FILE - DO NOT EDIT.\n"
    "     Produced by scripts/generate_agents_md.py from CLAUDE.md and its\n"
    "     @-imports. Edit those source files and re-run the script instead. -->\n"
    "\n"
    "# AGENTS.md - ArtazzenDotCom\n"
    "\n"
    "> Flattened, self-contained copy of `CLAUDE.md` and the files it imports,\n"
    "> for agent tools that do not support `@`-import syntax.\n"
    "> `CLAUDE.md` remains the source of truth.\n"
)

# The entrypoint's own H1 is replaced by the generated title above, so the
# document is not titled "CLAUDE.md" while living at AGENTS.md.
ENTRYPOINT_TITLE_PREFIX = "# CLAUDE.md"


def _resolve(path: Path, seen: set[Path]) -> list[str]:
    """Return the lines of ``path`` with ``@import`` lines expanded."""
    resolved = path.resolve()
    if resolved in seen:
        logger.warning("skipping already-inlined file: %s", path)
        return []
    seen.add(resolved)

    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        # An import is a line that is *only* an @path reference.
        if stripped.startswith("@") and len(stripped.split()) == 1:
            target = REPO_ROOT / stripped[1:]
            if not target.is_file():
                logger.warning("import target not found, keeping literal: %s", stripped)
                out.append(line)
                continue
            rel = target.relative_to(REPO_ROOT)
            out.append(f"<!-- Inlined from {rel} -->")
            out.append("")
            out.extend(_resolve(target, seen))
            out.append("")
            out.append(f"<!-- End of {rel} -->")
        else:
            out.append(line)
    return out


def render() -> str:
    if not ENTRYPOINT.is_file():
        raise SystemExit(f"missing entrypoint: {ENTRYPOINT}")
    # Seed `seen` with the output path so AGENTS.md can never inline itself.
    body = _resolve(ENTRYPOINT, seen={OUTPUT.resolve()})
    if body and body[0].startswith(ENTRYPOINT_TITLE_PREFIX):
        body = body[1:]
    text = BANNER + "\n" + "\n".join(body).rstrip() + "\n"
    # Collapse runs of blank lines left behind by import expansion.
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify AGENTS.md is up to date instead of rewriting it",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    rendered = render()
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.is_file() else ""
        if current != rendered:
            logger.error("AGENTS.md is out of date; run scripts/generate_agents_md.py")
            return 1
        logger.info("AGENTS.md is up to date")
        return 0

    OUTPUT.write_text(rendered, encoding="utf-8")
    logger.info("wrote %s (%d lines)", OUTPUT.name, rendered.count("\n"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
