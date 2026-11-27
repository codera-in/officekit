#!/bin/sh
# Copies the git-ignored local files (house rules, skills, infra settings) from the main checkout
# into a new workspace. Safe to run again: it never overwrites what is already there.
# .claude/ is copied selectively: it also holds Claude Code's own worktrees (gigabytes) and
# personal settings, which must stay in the main checkout.
set -eu

root="${SUPERSET_ROOT_PATH:-}"
if [ -z "$root" ] || [ "$root" = "$PWD" ]; then
  exit 0
fi

for item in .claude/se-rules .agents skills-lock.json PITFALLS.md docs/PITFALLS.md infra.env; do
  if [ -e "$root/$item" ] && [ ! -e "$item" ]; then
    mkdir -p "$(dirname "$item")"
    cp -R "$root/$item" "$item"
    echo "copied $item from the main checkout"
  fi
done
