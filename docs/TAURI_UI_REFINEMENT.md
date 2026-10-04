# Revisão da interface Tauri

Correções de 04/10/2026 na branch `codex/tauri-migration`:

- Splash e interface com superfícies planas, cores discretas e labels funcionais. Removidos slogans, textos decorativos, status duplicados e instruções permanentes em estados vazios.
- Cabeçalho dos blocos com linguagem, nome, conexão SQL e execução. Ações secundárias ficam no menu; database/schema aparecem ao abrir os detalhes de conexão. Estados de fila, execução, erro e cancelamento permanecem visíveis.
- Diagnósticos válidos não adicionam uma barra a cada bloco. Erros, avisos e limitações continuam no editor e no painel de diagnóstico.
- Menus de conexões e blocos usam portal na janela de origem, posição limitada ao viewport, navegação por teclado e fechamento por Escape/clique externo. Não acionam atalhos do aplicativo nem propagam cliques para o cabeçalho do bloco.
- Modais compartilham foco e portal, com espaçamento, campos e botões adaptáveis. Ajuda técnica fica recolhida; campos desabilitados por fieldset saem da navegação por Tab.
- Blocos e toolbar se adaptam à largura disponível. Menus do Monaco continuam fora do recorte dos docks. Removidos estilos antigos de gráficos que conflitavam com o componente atual.

O autocomplete e os avisos por aba estão documentados em [TAURI_AUTOCOMPLETE.md](TAURI_AUTOCOMPLETE.md) e [TAURI_NOTIFICATIONS.md](TAURI_NOTIFICATIONS.md).

As suítes finais passaram por 624 testes frontend e 737 testes runtime; TypeScript, Ruff, build Tauri de produção e os três smokes do runtime congelado passaram. O pacote final inclui o tratamento de strings PostgreSQL. O teste visual foi interrompido a pedido do usuário após observar a janela principal; menus, modais e tamanhos menores exigem conferência visual posterior. Nenhum dado de perfil real foi usado nos testes.

No benchmark final do sidecar distribuído, com 10 amostras e catálogo SQLite privado, o RPC SQL aquecido teve mediana de 0,387 ms e p95 de 0,568 ms; Python teve mediana de 0,277 ms e p95 de 0,728 ms. O primeiro carregamento do catálogo levou 38,336 ms. São medidas do runtime local, não uma garantia de latência da interface ou de servidores externos.
