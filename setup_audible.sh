#!/usr/bin/env bash
# Set up audible-cli to export your Audible library.
# Run this YOURSELF — it prompts for your Amazon/Audible login and I never see credentials.
#
#   bash setup_audible.sh
#
# After logging in, it exports your full library to audible_library.csv
# (title/author columns), then imports it into books.db via recommend.py.
set -euo pipefail
cd "$(dirname "$0")"

pip install --quiet audible audible-cli 2>/dev/null || pip install --user --quiet audible audible-cli

if [ -f "$HOME/.audible/config.toml" ]; then
  echo "==> Existing audible config found — skipping audible-quickstart."
else
  echo "==> Now running audible-quickstart (you will enter your login in the prompt)."
  audible-quickstart
fi

# columns include Title, Author, Series (the exporter decides the set; no --fields option)
audible library export -f csv -o audible_library.csv

.venv/bin/python recommend.py import-audible audible_library.csv
