# Niri Rice V4

Evolução da V3 no Fedora 44, Niri 26.04, Waybar 0.15 e Catppuccin Mocha. O README principal, as preferências GNOME e os outros pacotes Stow são preservados.

## Usar

| Entrada | Ação |
| --- | --- |
| Clique em rede, Bluetooth, volume ou bateria | Central de controle à direita, no monitor ativo |
| `Super+Ctrl+,` | Alternar central de controle |
| `Alt+Tab` / `Alt+Shift+Tab` | Alternador de janelas; repetir percorre a seleção |
| Setas / Tab / Shift+Tab, Enter | Navegar e focar no alternador. Cada janela tem título e workspace próprios. Soltar Alt não confirma; use Enter ou clique. |
| `Super+Shift+C` | Histórico da área de transferência |
| `Super+Ctrl+D` | Spotlight |
| `Super+D` | Fuzzel original, preservado |
| Clique em notificações / `Super+Ctrl+N` | Histórico de notificações |
| Clique direito em notificações / `Super+Shift+N` | Alternar Não Perturbe |
| `Super+N` | Ocultar a notificação flutuante mais recente, mantendo histórico |
| Engrenagem / `Super+,` | Central completa da V3 |
| Relógio | Calendário V3 |
| `Super+Shift+D` | Mostrar/ocultar dock V3 |
| `Super+Shift+W` | Wallpaper V3 |

`Esc` fecha os novos painéis. A área transparente fora deles recebe cliques para fechá-los. Somente o painel visível intercepta entrada. `Super+O` (Overview), `Super+Tab` (workspace anterior), `Super+Espaço` (layout do teclado) e os atalhos anteriores continuam disponíveis.

A dock e seu gerenciador de favoritos continuam sendo os da V3. Existe somente um processo Waybar, com a barra superior e a dock quando habilitada.

## Central de controle

Consulta NetworkManager, BlueZ, WirePlumber/PipeWire, sysfs e a interface D-Bus PowerProfiles já fornecida pelo sistema. Não instala substitutos para esses serviços.

- Wi-Fi mostra SSID/estado e permite ligar/desligar. **Gerenciar** abre o editor do NetworkManager.
- Bluetooth mostra estado e dispositivos conectados no tooltip. **Gerenciar** abre Blueman.
- Saída e microfone têm volume e mute separados. O seletor mostra as saídas de áudio disponíveis; pavucontrol continua acessível.
- Brilho só é oferecido para uma saída interna ativa com dispositivo de backlight. Nesta sessão o HDMI está ativo e eDP está desligado; portanto o controle aparece indisponível. Não há controle DDC de monitores externos.
- Energia mostra bateria e perfil quando disponível. Suspender pede confirmação. Nenhuma política de tampa ou suspensão é alterada.
- Não Perturbe usa o mesmo backend da Waybar. Os botões levam ao histórico e às configurações completas.

Os estados são consultados ao abrir, ao atualizar e após operações. Não existe loop de consultas da central quando ela está fechada.

## Alternador

Usa uma consulta pontual de `niri msg -j windows` e dos workspaces. Ordena pela utilização recente e seleciona inicialmente a próxima janela. Ícones vêm dos arquivos `.desktop` e de `StartupWMClass`; janelas sem correspondência recebem ícone genérico. O foco usa o ID real via Niri IPC, inclusive entre workspaces. Não há captura de previews, simulação X11 nem polling contínuo.

O Overview nativo foi mantido. Uma interface GTK sob demanda permite mostrar títulos, ícones e identificar separadamente várias janelas do mesmo aplicativo.

## Notificações

Foi instalado **SwayNotificationCenter 0.12.6**, disponível nos repositórios oficiais Fedora. Essa versão usa GTK4; seu CSS é validado separadamente do GTK3 da central e da Waybar. O SwayNC fornece agrupamento, ações, horário, remoção individual, limpeza e DND sem implementar outro servidor próprio.

A migração remove Mako apenas das dependências do target Niri. O drop-in e a configuração Mako V3 permanecem para fallback e rollback. `niri-rice-notifications.service` conflita com Mako e para a unidade vendor SwayNC antes de executar o servidor personalizado. Nenhum desses serviços foi habilitado globalmente.

Dois arquivos Stow em `.local/share/dbus-1/services/` direcionam a ativação de Notifications e do painel SwayNC à unidade personalizada. Ela usa `Type=exec` para evitar a disputa entre unidades vendor com o mesmo `BusName`. Em Niri, `notification-server` executa SwayNC com os arquivos específicos do rice; em outras sessões, mantém o fallback Mako original. O GNOME Shell continua sendo o servidor normal da sessão GNOME. Um login real no GNOME ainda precisa ser verificado.

O histórico é volátil: começa com as notificações recebidas após a migração e é perdido ao reiniciar o servidor. As notificações antigas do Mako não foram importadas. Uma verificação a cada minuto limpa o histórico ao ultrapassar 100 itens; também limpa todo o lote a cada hora. Pode haver um excesso temporário entre verificações, e o limite apaga o lote inteiro, pois esta versão do cliente não oferece remoção do item mais antigo do histórico. O botão **Limpar todas** permite apagar antes disso.

O stdout/stderr do servidor não vai para o journal para evitar conteúdo sensível em mensagens de depuração. O systemd ainda registra início, parada e resultado do processo. Nenhum histórico é sincronizado ou gravado em disco pelo rice.

## Clipboard e privacidade

Foi avaliado cliphist 0.7.0, disponível no Fedora. A captura foi implementada com o `wl-paste --watch` existente e SQLite no runtime para limitar tipos de dados e evitar a persistência em disco padrão de outro gerenciador.

- Apenas texto UTF-8, sem imagens nem arquivos.
- Até 40 itens, 16 KiB por item, deduplicados; expiração de 30 minutos, verificada também por timer a cada minuto (pode haver cerca de um minuto adicional).
- Dados em `$XDG_RUNTIME_DIR/niri-rice/clipboard/`, normalmente `/run/user/$UID`, em tmpfs. Diretório 0700, banco e journal 0600. Exclusões usam `secure_delete`; a limpeza compacta o banco.
- A seleção que já existia antes de iniciar a captura é ignorada. Não há sincronização nem gravação de payload nos logs.
- São rejeitados o estado `CLIPBOARD_STATE=sensitive`, MIME hints conhecidos de gerenciadores de senhas e app-ids contendo os padrões configurados.
- **Esses filtros não garantem que senhas nunca sejam capturadas.** Extensões de navegador, cópias em segundo plano e aplicativos sem hints podem passar pelos filtros. Código Python e tmpfs também não oferecem garantia de zerar cada cópia em RAM; o sistema pode ter políticas de swap próprias.
- **Pausar e limpar** para a captura e apaga o histórico. O estado pausado persiste entre logins. O fim da sessão também limpa os itens.
- A interface mostra apenas a primeira linha curta; não coloca o texto completo em tooltips. Selecionar copia e tenta devolver foco à janela anterior.

Comandos: `~/.config/niri/scripts/clipboard-control status|pause|resume|clear`. Preferências mutáveis ficam em `~/.local/state/niri-rice/clipboard.json`, sobre os padrões versionados de `clipboard-defaults.json`. Os máximos aceitos pelo código são 100 itens, 64 KiB e uma hora.

## Spotlight

A implementação GTK foi acrescentada ao `rice-ui` porque permite resultados com ícones e ações por item, sem encadear vários seletores. Fuzzel permanece no atalho original e também pode ser aberto pelo botão do painel.

- Texto comum pesquisa aplicativos, arquivos e projetos. Aplicativos RPM e Flatpak vêm da enumeração Gio das pastas XDG de arquivos `.desktop`.
- `/ nome` restringe a arquivos; **Pasta** abre o diretório que contém o resultado.
- `@ nome` restringe a projetos; Enter abre no VS Code, **Terminal** usa Alacritty com seu perfil Niri, e `☆` marca favoritos. Favoritos e projetos recentes são priorizados.
- `> terminal`, `> arquivos`, `> configurações`, `> controle`, `> bloquear`, `> wallpaper`, `> clipboard` e `> notificações` são ações permitidas. Reiniciar e desligar pedem confirmação. Texto desconhecido não vira comando shell.
- `= 2*(3+4)` calcula e Enter copia. O parser AST aceita apenas números e aritmética, com limites de tamanho e potência. Não usa eval nem chamadas arbitrárias.
- **Pastas pesquisadas** permite adicionar/remover até oito diretórios de arquivos e oito de projetos pela interface. HOME inteiro e `/` são rejeitados.

A descoberta inicial usou os diretórios reais do computador: arquivos em Documentos/Downloads e raízes com marcadores de projetos encontradas em Downloads, Faculdade, dotfiles, estagio_tce e tce. São sugestões iniciais mutáveis, não caminhos codificados como requisitos. Revise a lista conforme sua preferência.

O índice guarda nomes, caminhos e mtimes, sem ler conteúdos. Exclui `.git`, diretórios ocultos, caches, ambientes, dependências, credenciais, backups e nomes/extensões sensíveis por padrão. Não segue symlinks. A atualização reconcilia metadados em segundo plano, com profundidade, número de diretórios e arquivos limitados. A consulta não varre HOME a cada tecla. Atualize pelo botão; não existe indexador contínuo.

Preferências: `~/.local/state/niri-rice/launcher.json`, recentes em `launcher-recent.json`; banco privado em `~/.cache/niri-rice/search.sqlite3`. A primeira indexação encontrou 32.670 entradas, incluindo 66 projetos, em cerca de seis segundos; esses números mudam com os arquivos do usuário.

## Inventário e arquitetura

| Componente | Implementação / serviço |
| --- | --- |
| Aplicativo GTK único sob demanda | `scripts/rice-ui`, iniciado por `settings-hub` em cgroup próprio |
| Widgets e popup compartilhados | `rice_widgets.py` |
| Controles rápidos | `rice_controls.py`, `rice_panels.py` |
| Alternador e clipboard UI | `rice_panels.py` |
| Spotlight e índice | `rice_launcher.py`, `rice_search.py`, `rice-open`, `launcher-index` |
| Captura | `clipboard-store`, `clipboard-control`, `rice_clipboard.py`; `niri-rice-clipboard.service` |
| Expiração do clipboard | `niri-rice-clipboard-prune.timer` e `.service` |
| Servidor de notificações | `notification-server`; `niri-rice-notifications.service` |
| Retenção de notificações | `notification-prune`; `niri-rice-notification-prune.timer` e `.service` |
| Índice sob demanda | `niri-rice-index.service`, sem enable e sem timer |
| Integração Waybar | `waybar.jsonc`, script `notifications`; `waybar-session` e dock V3 preservados |
| Tema | `rice-ui.css`, `swaync.css`, `swaync.json`; paleta da V3 |
| Rollback | `scripts/rice-rollback`, recibo no backup |

Dependências reutilizadas: Python 3, PyGObject, GTK3, GTK layer-shell, GTK4 existente, gtk4-layer-shell instalado com o SwayNC, wl-clipboard, brightnessctl, wpctl/pactl, nmcli, bluetoothctl, Gio/GDBus, systemd, GNU Stow e utilitários V3. A validação de schema usa `python3-jsonschema`, que já estava instalado. A transação oficial instalou SwayNotificationCenter, gtk4-layer-shell e os pacotes de completions Bash/Zsh do SwayNC. Não houve COPR nem instalação de Quickshell ou cliphist.

Os serviços contínuos/timers são associados a `niri-rice.target` e à sessão gráfica. A captura e a indexação têm condição de ambiente Niri. Os popups encerram quando não sobra outra janela da mesma aplicação; a central V3 pode manter a aplicação aberta enquanto estiver em uso.

## Verificação

Executado na sessão Niri/Wayland, monitor HDMI-A-1 Full HD, eDP desligado:

- Validação Niri, scripts Python/Shell, JSON/schema SwayNC, CSS GTK3 e GTK4, launchers desktop, unidades e simulação Stow.
- Central aberta e capturada em tela; mudança de 1% do volume e mute do microfone pelos callbacks GTK, com restauração. Wi-Fi/Bluetooth consultados sem desconectá-los. Perfil energético lido; brilho indisponível corretamente no HDMI.
- Alternador com Firefox, Alacritty, VS Code e Nautilus. Navegação Tab/Enter, ativação de linha, distinção de IDs e foco entre workspaces com uma janela temporária. Clique fora exercitado no handler GTK. Não há ferramenta de injeção de teclas globais instalada; os binds são validados pelo Niri e os handlers foram acionados na sessão gráfica.
- Notificações fictícias: permanência após expiração do popup, dispensa individual, limpeza total, DND e restauração de estado. Reativação por `notify-send` após parar o serviço; servidor único confirmado. Uma chamada bruta Notify imediatamente durante a troca de proprietário D-Bus teve uma corrida transitória; o teste com o cliente normal notify-send concluiu corretamente.
- Clipboard real: captura, duplicatas, busca, cópia, exclusão, pausa e retomada; texto anterior preservado em memória e restaurado ao final. Regressões isoladas verificam MIME/app-id sensíveis fictícios, limites, TTL e permissões.
- Spotlight: Firefox/VS Code, Enter abrindo Alacritty, projeto permitido, configuração de pastas, calculadora e ação de configurações. Arquivo temporário com espaços, aspas, ponto e vírgula e `$()` abriu pelo aplicativo padrão de PNG, Chrome. Não houve interpretação shell.
- Regressões em `niri/.config/niri/tests/test_v4.py`: sete testes offline de segurança e limites, sem usar credenciais reais.
- Simulação do rollback e proteção contra alterações posteriores; restauração real não executada para manter a V4.

Consumo observado após abrir/fechar os painéis: cgroup SwayNC 27.4 MiB, captura wl-paste 0.23 MiB (pico 16.4 MiB durante captura). Em uma janela curta de três segundos sem interação, CPU de um núcleo foi 0.003% e 0.0%, respectivamente. São amostras, não garantias de consumo sob carga. O índice terminou e não deixou processo ativo. Popups fechados não deixaram processo rice-ui ativo. As medições estão em `resources.json` no backup.

Os logs finais não mostram serviços com falha. Permanecem avisos do tray da Waybar sobre itens nm-applet/Cloudflare já registrados e grupos de aceleradores GTK. Há somente uma Waybar; esses avisos não indicam outro servidor de notificações. Os applets e serviços externos não foram substituídos para tentar eliminá-los.

Pendentes por exigirem interrupção ou alteração deliberada: logout/login Niri e GNOME, suspensão, autenticação de bloqueio, desligar/reiniciar, alternar a rede/Bluetooth ativos e brilho com a tela interna ligada. As preferências GNOME foram conferidas sem alterá-las; um login GNOME não foi simulado.

## Atualizar e retornar à V3

Validação: `~/.config/niri/scripts/validate`. Testes offline: `python3 ~/dotfiles/niri/.config/niri/tests/test_v4.py`. A barra recarrega com `systemctl --user restart niri-rice-bar.service`; isso não reinicia a sessão. O servidor pode ser reiniciado com `systemctl --user restart niri-rice-notifications.service`, o que perde o histórico volátil.

Backup anterior à V4: `~/.local/state/niri-rice/backups/2026-10-20-235536-v4/`. Inclui pacote Stow V3 com permissões/symlinks, estado e diff Git, hashes de arquivos pessoais preservados, links, unidades anteriores e preferências V3. O recibo final registra exatamente o que a V4 alterou e seus hashes.

Simular:

```sh
~/.config/niri/scripts/rice-rollback ~/.local/state/niri-rice/backups/2026-10-20-235536-v4
```

Aplicar, depois de revisar a simulação:

```sh
~/.config/niri/scripts/rice-rollback ~/.local/state/niri-rice/backups/2026-10-20-235536-v4 --apply
```

A simulação confere o arquivo de backup e rejeita mudanças posteriores nos arquivos/links afetados. Não existe opção para forçar sua sobrescrita. Ao aplicar, a barra para brevemente, os serviços exclusivos da V4 são parados, apenas os arquivos afetados são restaurados, os novos links são retirados, Stow é simulado/aplicado e Niri é validado. Depois são recarregados os metadados systemd/D-Bus e iniciados Mako e Waybar na sessão Niri.

Favoritos, wallpaper e preferências pessoais atuais são mantidos. Dados de clipboard são limpos ao parar a captura. O índice de nomes e preferências V4 podem permanecer inativos como dados privados do usuário. O pacote SwayNC não é removido; por isso o rollback deixa um pequeno seletor D-Bus Mako no pacote Stow para garantir o servidor original apesar dos dois provedores instalados. Não há reinício do computador, logout, alteração de GNOME nem reset Git.
