# Revisão da interface Tauri

Correções de 04/10/2026 na branch `codex/tauri-migration`:

- Splash e interface com superfícies planas, cores discretas e labels funcionais. Removidos slogans, textos decorativos, status duplicados e instruções permanentes em estados vazios.
- Cabeçalho dos blocos com linguagem, nome, conexão SQL, banco/schema e execução. Banco/schema usam seletores pesquisáveis no próprio cabeçalho; ações secundárias ficam no menu. Estados de fila, execução, erro e cancelamento permanecem visíveis.
- Diagnósticos válidos não adicionam uma barra a cada bloco. Erros, avisos e limitações continuam no editor e no painel de diagnóstico.
- Menus de conexões e blocos usam portal na janela de origem, posição limitada ao viewport, navegação por teclado e fechamento por Escape/clique externo. Não acionam atalhos do aplicativo nem propagam cliques para o cabeçalho do bloco.
- Modais compartilham foco e portal, com espaçamento, campos e botões adaptáveis. Ajuda técnica fica recolhida; campos desabilitados por fieldset saem da navegação por Tab.
- Blocos e toolbar se adaptam à largura disponível. Menus do Monaco continuam fora do recorte dos docks. Removidos estilos antigos de gráficos que conflitavam com o componente atual.

O autocomplete e os avisos por aba estão documentados em [TAURI_AUTOCOMPLETE.md](TAURI_AUTOCOMPLETE.md) e [TAURI_NOTIFICATIONS.md](TAURI_NOTIFICATIONS.md).

## Abertura de conexão e topo dos blocos — 05/10/2026

A aba em abertura mostra um spinner durante a preparação da sessão e a autenticação do banco. O painel da análise informa `Preparando sessão…` ou `Conectando e autenticando…`, com o nome da conexão. Uma falha substitui o mesmo aviso pelo erro e pela ação de nova tentativa; a indicação permanece na aba de origem ao trocar de análise. Não depende da barra de status global. A autenticação fica pendente até a resposta do driver, inclusive no login OAuth.

Execuções e buscas de metadados aguardam o término da abertura. Repetir a abertura da mesma conexão reutiliza a solicitação pendente; outra conexão na mesma aba é recusada enquanto isso. Fechar a aba ou trocar de workspace invalida a resposta tardia. O erro de conexão SQL não impede executar Python na sessão já criada.

Executar agora fica à esquerda do cabeçalho, junto ao arraste, recolhimento e linguagem, conforme o fluxo PyQt6. Nome, conexão, banco/schema e ações ficam no grupo seguinte. Em painéis estreitos, esse grupo quebra para uma segunda linha sem esconder os controles principais. O botão continua executando somente a seleção quando ela existe.

A fixture de estilos cobre também preparação, autenticação, erro longo e estado pronto: 48 verificações de estado nos 12 cenários de tema/tamanho/fonte, com nova tentativa por teclado, contraste e ausência de overflow. Testes do controller usam autenticação adiada para verificar isolamento, erros, retry e respostas tardias, sem usar bancos do usuário.

Aceite final de 05/10: 773 testes frontend, 777 runtime, 36 Rust, 65 cenários Monaco headless e 12 cenários de tema passaram. TypeScript, Ruff, build Tauri de produção e os três smokes do runtime congelado passaram; a ponte nativa também foi testada em release com esse sidecar. O pacote atualizado está em `build/tauri-preview-current/`, com frontend e runtime recompilados. Os testes usaram dados sintéticos e SQLite temporário, sem operar o desktop ou conectar a servidores privados.

## Tema e buscas

As superfícies, textos, foco, bordas e estados agora vêm de `desktop/src/theme.css`. Abas ativas, a faixa de resultados, botões de novos blocos, Explorer, menus, modais e Pynia deixam de depender de cores escuras fixas. O tema claro conserva o contraste dos textos e botões de execução.

Os campos compostos de pesquisa têm uma única borda e superfície no contêiner. Seus inputs internos são transparentes, sem padding ou borda duplicados; `:focus-within` destaca o campo inteiro. A correção cobre conexões, objetos, variáveis, arquivos de variáveis, resultados e banco/schema.

Pynia usa símbolos locais de Claude, Cursor, GitHub Copilot e Codex, com variantes para cada tema e proporções preservadas. Codex usa sua marca atual com flor e terminal. As fontes dos arquivos estão em [agents/README.md](../desktop/src/assets/agents/README.md); somente integrações desconhecidas usam um ícone genérico.

`npm --prefix desktop run test:theme` exercita os estilos de produção em uma fixture isolada, sem abrir janelas do aplicativo. Os 12 cenários cobrem claro/escuro, larguras de 320/720/1280 pixels e fontes Ubuntu 12/Consolas 16. Verificam contraste mínimo de 4,5 para textos e placeholders, ausência de overflow nos painéis, foco das buscas e carregamento/seleção das variantes dos logos. Isso não substitui uma conferência de todas as telas com dados e tamanhos reais do usuário.

Na revisão de 04/10, as suítes passaram por 624 testes frontend e 737 testes runtime; TypeScript, Ruff, build Tauri de produção e os três smokes do runtime congelado passaram. O pacote incluiu o tratamento de strings PostgreSQL. O teste visual foi interrompido a pedido do usuário após observar a janela principal. Nenhum dado de perfil real foi usado nos testes.

No benchmark final do sidecar distribuído, com 10 amostras e catálogo SQLite privado, o RPC SQL aquecido teve mediana de 0,387 ms e p95 de 0,568 ms; Python teve mediana de 0,277 ms e p95 de 0,728 ms. O primeiro carregamento do catálogo levou 38,336 ms. São medidas do runtime local, não uma garantia de latência da interface ou de servidores externos.
