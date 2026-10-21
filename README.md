# Dotfiles

Personal configuration managed with **GNU Stow**.

## Setup

Clone this repository to `~/dotfiles`, install GNU Stow, then run:

```sh
cd ~/dotfiles
./setup.sh
```

Packages: Bash, Zsh, Vim, Neovim, Alacritty, Starship, btop and Git.

## Niri + Catppuccin Mocha

Optional Fedora 44 session with Waybar, Fuzzel, Mako, Swaybg, Swaylock and
XWayland Satellite. GNOME remains available. The Niri Alacritty profile imports
existing preferences and applies its own colors, opacity and padding.

```sh
sudo dnf install stow niri waybar fuzzel mako swaybg swaylock swayidle xwayland-satellite alacritty zsh nautilus btop pavucontrol network-manager-applet blueman mate-polkit brightnessctl wl-clipboard xdg-desktop-portal-gnome xdg-desktop-portal-gtk
cd ~/dotfiles
stow --simulate alacritty
stow alacritty
./setup-niri.sh
~/.config/niri/scripts/validate
```
Uses UbuntuMono Nerd Font. Configurations live in `niri/.config/niri`; session
services live in `niri/.config/systemd/user`. Stow uses `--no-folding` so systemd
loads the Mako drop-in correctly. Select **Niri** in the GDM session menu.

Locks after 5 minutes; turns displays off after 10. Configuration validation passes;
screen sharing, X11 apps, lock/unlock and suspend still need testing inside Niri.
