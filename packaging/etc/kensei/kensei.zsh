# Kensei shell — zsh + ghost autocomplete + low-tech branding.
# Se carga desde $KENSEI_ZDOTDIR/.zshrc cuando ejecutás `kensei`.

export KENSEI_PREFIX="${KENSEI_PREFIX:-/usr/local}"
export KENSEI_CLI="${KENSEI_CLI:-$KENSEI_PREFIX/bin/kensei-cli}"
export KENSEI_MODEL="${KENSEI_MODEL:-kensei}"
export PATH="$HOME/.local/bin:$PATH"

HISTFILE="${XDG_STATE_HOME:-$HOME/.local/state}/kensei/history"
mkdir -p "${HISTFILE:h}"
HISTSIZE=20000
SAVEHIST=20000
setopt HIST_IGNORE_DUPS HIST_IGNORE_SPACE SHARE_HISTORY INC_APPEND_HISTORY

autoload -Uz compinit
compinit -C
zstyle ':completion:*' menu select
zstyle ':completion:*' matcher-list 'm:{a-zA-Z}={A-Za-z}'

# zsh-autosuggestions: sugerencia fantasma desde historial + completion.
for candidate in \
  /usr/share/zsh/plugins/zsh-autosuggestions/zsh-autosuggestions.zsh \
  /usr/share/zsh-autosuggestions/zsh-autosuggestions.zsh; do
  if [[ -r "$candidate" ]]; then
    source "$candidate"
    ZSH_AUTOSUGGEST_HIGHLIGHT_STYLE='fg=240'
    ZSH_AUTOSUGGEST_STRATEGY=(history completion)
    ZSH_AUTOSUGGEST_BUFFER_MAX_SIZE=60
    break
  fi
done

# Tab: acepta el fantasma si existe; si no, completa rutas normalmente.
_kensei_tab() {
  if (( $+widgets[autosuggest-accept] )) && [[ -n "$POSTDISPLAY" ]]; then
    zle autosuggest-accept
  else
    zle expand-or-complete
  fi
}
if [[ -o interactive ]]; then
  zle -N _kensei_tab
  bindkey '^I' _kensei_tab
fi

# Prompt low-tech.
if [[ ${EUID} -eq 0 ]]; then
  PROMPT='%F{red}root%f %F{240}kensei›%f '
else
  PROMPT='%F{green}kensei%f %F{240}›%f '
fi
RPROMPT='%F{240}%n@%m%f'
unsetopt PROMPT_SP 2>/dev/null || true

_kensei_scope() {
  local file="${XDG_CONFIG_HOME:-$HOME/.config}/kensei/scope.yaml"
  if [[ -r "$file" ]] && grep -qE '^authorized:[[:space:]]*true' "$file" 2>/dev/null; then
    print "active"
  else
    print "unset"
  fi
}

_kensei_banner() {
  emulate -L zsh
  [[ -o interactive ]] || return
  [[ -z "${KENSEI_BANNER_SHOWN:-}" ]] || return
  export KENSEI_BANNER_SHOWN=1
  local scope logo
  scope="$(_kensei_scope)"
  logo="$KENSEI_PREFIX/share/kensei/logo.txt"
  print
  if [[ -r "$logo" ]]; then
    if [[ -z "${KENSEI_NO_ANIM:-}" ]] && command -v tte >/dev/null 2>&1; then
      tte print --print-speed 12 --final-gradient-stops eda000 --final-gradient-steps 1 \
        < "$logo" 2>/dev/null || cat "$logo"
    else
      cat "$logo"
    fi
  elif [[ -z "${KENSEI_NO_ANIM:-}" ]] && command -v tte >/dev/null 2>&1; then
    print -n "KENSEI" | tte decrypt 2>/dev/null || print -P "%F{green}KENSEI%f %F{240}// RONIN%f"
  else
    print -P "%F{green}KENSEI%f %F{240}// RONIN%f"
  fi
  print -P "%F{240}────────────────────────────────────────────────────%f"
  print -P "%F{240}model%f $KENSEI_MODEL   %F{240}scope%f $scope   %F{240}user%f $USER"
  if [[ "${KENSEI_ROOT:-0}" == "1" || ${EUID} -eq 0 ]]; then
    print -P "%F{red}ROOT SHELL%f %F{240}— el guard sigue activo; confirmá cada paso%f"
  else
    print -P "%F{240}terminal-native security operator — 'kensei --help'%f"
  fi
  print
}

_kensei_banner

# kensei <prompt>  -> una respuesta (dry-run, no ejecuta)
# kensei --auto <prompt> -> agente con human-in-the-loop
# kensei           -> chat interactivo con confirmación
kensei() {
  emulate -L zsh
  local cli="$KENSEI_CLI"
  local model="$KENSEI_MODEL"

  if (( $# == 0 )); then
    "$cli" chat --model "$model" --execute --allow-code-blocks
    return $?
  fi

  case "$1" in
    --auto)
      shift
      local prompt
      if (( $# == 0 )); then
        print -n "kensei(auto)› "
        read -r prompt || return 1
      else
        prompt="$*"
      fi
      [[ -n "$prompt" ]] || return 1
      "$cli" auto "$prompt" --model "$model" --allow-code-blocks
      ;;
    --help|-h)
      "$cli" --help
      ;;
    --version)
      "$cli" --version
      ;;
    *)
      "$cli" ask "$*" --model "$model" --allow-code-blocks
      ;;
  esac
}

# Atajos de baja tecnología.
alias ll='ls -lah'
alias la='ls -lah'
alias ..='cd ..'
alias ...='cd ../..'
alias kk='kensei'

# zsh-syntax-highlighting al final.
for candidate in \
  /usr/share/zsh/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh \
  /usr/share/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh; do
  if [[ -r "$candidate" ]]; then
    source "$candidate"
    break
  fi
done
