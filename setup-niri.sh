#!/bin/sh
# Integra somente o pacote novo, sem o unstow geral do setup.sh histórico.
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
niri validate --config "$repo/niri/.config/niri/config.kdl"
stow --simulate --no-folding --verbose --dir="$repo" --target="$HOME" niri
stow --no-folding --verbose --dir="$repo" --target="$HOME" niri
systemctl --user daemon-reload
printf '%s\n' 'Pronto. Selecione Niri no GDM quando encerrar sua sessão.'
