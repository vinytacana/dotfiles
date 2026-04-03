# Created by newuser for 5.9
# >>> INÍCIO DO ZSHRC BONITÃO <<<

# Starship prompt
eval "$(starship init zsh)"

# Mostrar Fastfetch SOMENTE quando for um terminal interativo (não scripts)
if [[ $- == *i* ]]; then
  fastfetch
fi

# Histórico com timestamp
HISTFILE=~/.zsh_history
HISTSIZE=10000
SAVEHIST=10000
setopt INC_APPEND_HISTORY
setopt HIST_IGNORE_DUPS
setopt HIST_FIND_NO_DUPS
setopt SHARE_HISTORY

# Autocompletar com seta pra cima
autoload -Uz up-line-or-beginning-search
autoload -Uz down-line-or-beginning-search
zle -N up-line-or-beginning-search
zle -N down-line-or-beginning-search
bindkey "^[[A" up-line-or-beginning-search
bindkey "^[[B" down-line-or-beginning-search

# Atalhos úteis
alias ls='eza --icons'
alias ll='eza -lah --icons'
alias la='eza -a --icons'
alias lt='eza --tree --icons'
alias cat='bat' # (If installed later)
alias gs='git status'
alias ga='git add .'
alias gc='git commit -m'
alias gco='git checkout'
alias update='sudo dnf update'
alias cls='clear'

# Source local config if exists
if [ -f ~/.zshrc_local ]; then
    source ~/.zshrc_local
fi

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion
export PATH="$HOME/.local/bin:$PATH"
