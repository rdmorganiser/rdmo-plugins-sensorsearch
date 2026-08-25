#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 RDMO Community and individual contributors
# SPDX-License-Identifier: Apache-2.0

# Generate a reviewable, chronological evidence table for docs/development-history.md.
# Usage: testing/tools/generate_development_commit_inventory.sh [repository-path]
set -euo pipefail

repository_path="${1:-.}"
git -C "$repository_path" rev-parse --is-inside-work-tree >/dev/null

category_for() {
    local subject="$1"
    local paths="$2"

    if [[ "$paths" == *"rdmo_sensorsearch/config_models/"* ]] || [[ "$subject" == *"config"* ]] || [[ "$subject" == *"refactor"* ]]; then
        printf '%s' 'Architecture/configuration'
    elif [[ "$paths" == *"rdmo_sensorsearch/signals/"* ]] || [[ "$paths" == *"rdmo_sensorsearch/workflows/"* ]] || [[ "$paths" == *"rdmo_sensorsearch/persistence/"* ]] || [[ "$paths" == *"rdmo_sensorsearch/services/"* ]]; then
        printf '%s' 'Synchronization workflow'
    elif [[ "$paths" == *"rdmo_sensorsearch/providers/"* ]] || [[ "$paths" == *"rdmo_sensorsearch/handlers/"* ]]; then
        printf '%s' 'Backend integration/search'
    elif [[ "$paths" == *"testing/"* ]] || [[ "$paths" == *"docs/"* ]] || [[ "$paths" == *"README"* ]]; then
        printf '%s' 'Documentation/test coverage'
    elif [[ "$paths" == *"pyproject.toml"* ]] || [[ "$paths" == *"setup.py"* ]]; then
        printf '%s' 'Build/release'
    elif [[ "$paths" == *"xml/"* ]] || [[ "$paths" == *"catalog"* ]]; then
        printf '%s' 'Catalog/editor experience'
    else
        printf '%s' 'General maintenance'
    fi
}

printf '%s\n\n' '# Development commit inventory'
printf '%s\n\n' 'Generated from Git history. Categories are mechanical review aids; inspect the linked diff before citing a commit as evidence of a design decision.'
printf '%s\n' '| Commit | Date | Category | Subject | Changed paths |'
printf '%s\n' '| --- | --- | --- | --- | --- |'

while IFS=$'\x1f' read -r commit_hash short_hash commit_date subject; do
    changed_paths=$(git -C "$repository_path" diff-tree --root --no-commit-id --name-only -r "$commit_hash" | tr '\n' '\034')
    changed_paths=${changed_paths//$'\034'/, }
    changed_paths=${changed_paths%, }
    changed_paths=${changed_paths:-'(no file changes)'}
    changed_paths=${changed_paths//|/\\|}
    subject=${subject//|/\\|}
    category=$(category_for "$subject" "$changed_paths")
    printf '| [`%s`](https://github.com/rdmorganiser/rdmo-plugins-sensorsearch/commit/%s) | %s | %s | %s | `%s` |\n' \
        "$short_hash" "$commit_hash" "$commit_date" "$category" "$subject" "$changed_paths"
done < <(git -C "$repository_path" log --reverse --date=short --format='%H%x1f%h%x1f%ad%x1f%s')
