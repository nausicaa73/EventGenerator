#!/usr/bin/env bash
set -euo pipefail

# Se placer dans le dossier du projet
cd "$(dirname "$0")"

# Lancer le bot avec Python
exec python3 main.py
