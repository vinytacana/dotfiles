
DOTFILES_DIR=~/dotfiles

cd "$DOTFILES_DIR"


STOW_FOLDERS="bash zsh vim nvim alacritty starship btop git"

# Executa o stow para cada uma
for folder in $STOW_FOLDERS; do
    echo "Stowing $folder..."
    stow -D "$folder" # Remove links antigos se existirem
    stow "$folder"
done

echo "your settings have been successfully linked"
