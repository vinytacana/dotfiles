eval "$(starship init zsh)"


if [[ $- == *i* ]]; then
  fastfetch
fi

HISTFILE=~/.zsh_history
HISTSIZE=10000
SAVEHIST=10000
setopt INC_APPEND_HISTORY
setopt HIST_IGNORE_DUPS
setopt HIST_FIND_NO_DUPS
setopt SHARE_HISTORY


autoload -Uz up-line-or-beginning-search
autoload -Uz down-line-or-beginning-search
zle -N up-line-or-beginning-search
zle -N down-line-or-beginning-search
bindkey "^[[A" up-line-or-beginning-search
bindkey "^[[B" down-line-or-beginning-search

# Atalhos úteis
if command -v eza >/dev/null 2>&1; then
    alias ls='eza --icons'
    alias ll='eza -lah --icons'
    alias la='eza -a --icons'
    alias lt='eza --tree --icons'
fi

if command -v bat >/dev/null 2>&1; then
    alias cat='bat'
fi

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

# >>> conda initialize >>>
# !! Contents within this block are managed by 'conda init' !!
__conda_setup="$('/home/viny/anaconda3/bin/conda' 'shell.zsh' 'hook' 2> /dev/null)"
if [ $? -eq 0 ]; then
    eval "$__conda_setup"
else
    if [ -f "/home/viny/anaconda3/etc/profile.d/conda.sh" ]; then
        . "/home/viny/anaconda3/etc/profile.d/conda.sh"
    else
        export PATH="/home/viny/anaconda3/bin:$PATH"
    fi
fi
unset __conda_setup
# <<< conda initialize <<<
