# CHANGELOG

<!-- version list -->

## v1.1.1 (2026-02-13)

### Bug Fixes

- Use uv run for pyinstaller and add missing system dependencies to Linux release workflow
  ([`1c71260`](https://github.com/natharuc/datapyn/commit/1c71260ba0ee6a8892672a22de85105e4c2cab5a))


## v1.1.0 (2026-02-12)

### Bug Fixes

- _rebuild_apis trata tables/columns como dicts do schema_service
  ([`fdc1238`](https://github.com/natharuc/datapyn/commit/fdc12387b5000685ddb894042a1d301b220c3e01))

- Add native tls
  ([`13742cc`](https://github.com/natharuc/datapyn/commit/13742ccd0570facbf71b51c1c7a91f3206496372))

- Cancelar teste conexao, editor lento, atalhos find/replace
  ([`4bcb602`](https://github.com/natharuc/datapyn/commit/4bcb602efa8fc96dbfef31c99052b6293af301f1))

- Correcoes para build PyInstaller (Monaco, mariadb, package manager)
  ([`c31f732`](https://github.com/natharuc/datapyn/commit/c31f732d76ee3e59187bbafb3ff1fffbb252a3e8))

- Corrigir testes lentos/travando e atualizar README para uv
  ([`f2d450d`](https://github.com/natharuc/datapyn/commit/f2d450dba18f48e3bf418b68095e18863fb56cc2))

- Interceptar ShortcutOverride em vez de keyPressEvent
  ([`3fa7fdc`](https://github.com/natharuc/datapyn/commit/3fa7fdcc83f66e672249b329d7ce43aadc44e41c))

- KeyboardModifier.value para QKeySequence no PyQt6
  ([`55c62ff`](https://github.com/natharuc/datapyn/commit/55c62ff2638e09d39ec25968bb83f08e9b638397))

- QThread destroyed while still running
  ([`1213b41`](https://github.com/natharuc/datapyn/commit/1213b41788f7932e0d24e8b5b7d1c3cf6f06ab89))

- Remover add do pyinstaller no script de build
  ([`79792a2`](https://github.com/natharuc/datapyn/commit/79792a20f39d227b0831472a1361341a8c466723))

- **ci**: Corrigir crash SIGABRT e falhas de ODBC no CI
  ([`dd88f69`](https://github.com/natharuc/datapyn/commit/dd88f69bea099a3981d6c622492677193e88c404))

- **ci**: Mock ODBC em test_system_api + tratar SIGSEGV no cleanup do QWebEngine
  ([`4b4fa93`](https://github.com/natharuc/datapyn/commit/4b4fa93d6bf8644113034eb7d26170d899854be6))

- **ci**: Usar uv run pytest no workflow
  ([`8c14a6b`](https://github.com/natharuc/datapyn/commit/8c14a6b516ad4e61a6f92c5e2a7ccefddfc4bccc))

### Features

- Add GitHub Actions workflow for building Linux installers
  ([`775f2bf`](https://github.com/natharuc/datapyn/commit/775f2bfd86182180bf5347fddb239c181520d441))

- Add Linux desktop entry and post-install scripts
  ([`775f2bf`](https://github.com/natharuc/datapyn/commit/775f2bfd86182180bf5347fddb239c181520d441))

- Add WiX installer script for Windows
  ([`775f2bf`](https://github.com/natharuc/datapyn/commit/775f2bfd86182180bf5347fddb239c181520d441))

- Formatacao de codigo com Ctrl+Shift+F (configuravel)
  ([`0f27457`](https://github.com/natharuc/datapyn/commit/0f2745724cfed61b0f5a2483430ec3b802fc5ae7))

- Spinner animado na aba + fix conflito atalhos editor/app
  ([`476f0d1`](https://github.com/natharuc/datapyn/commit/476f0d1111d5869684c621854064cd8537cbc245))

- Substituir Monaco Editor por QScintilla com Find/Replace nativo
  ([`972583c`](https://github.com/natharuc/datapyn/commit/972583cf5d9917d2dfb402b189522461decf1edc))

- Variaveis DB no painel, dialogo importacao, fastexcel, context menu, autocomplete
  ([`494464c`](https://github.com/natharuc/datapyn/commit/494464ce999f65661ca2189c3c1a644b13f2e698))

- **connection**: Corrige conexões com bancos de dados e adiciona opção de confiar no certificado do
  servidor quando sql server
  ([`445e9f6`](https://github.com/natharuc/datapyn/commit/445e9f6ae682b883fd9d1a9fc115fc62617aaa27))

### Performance Improvements

- Eliminar SELECT 1 na thread principal e otimizar event loop
  ([`e1a707a`](https://github.com/natharuc/datapyn/commit/e1a707a4f7134150b516438f7d646bed00337086))

- Otimizar CodeEditor - eliminar rebuilds redundantes e folding
  ([`496c844`](https://github.com/natharuc/datapyn/commit/496c844b21ecf7cfc13e87e47bf0e7088faa2abd))

### Refactoring

- Atalhos 100% dinamicos - sem ifs hardcoded no editor
  ([`cdd0e40`](https://github.com/natharuc/datapyn/commit/cdd0e40f9c30553d92c1a1032e8bf175852417c6))

- Atalhos usam prioridade dinamica app>editor
  ([`1b9cd83`](https://github.com/natharuc/datapyn/commit/1b9cd83ef202e12510d905fad0f28b4848889931))

- Migrate project to use UV package manager
  ([`9f679c4`](https://github.com/natharuc/datapyn/commit/9f679c42e5c3f0ff3abc41afe473f005fa54c782))

- Notificacoes cross-platform via QSystemTrayIcon
  ([`3d350b6`](https://github.com/natharuc/datapyn/commit/3d350b6fb4a8f6dee46c3ff638ebda7b2155d66e))


## v1.0.0 (2026-02-08)

- Initial Release
