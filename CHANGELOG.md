# CHANGELOG

<!-- version list -->

## v1.8.1 (2026-02-20)

### Bug Fixes

- Consertar shift enter impossivel de bindar nos atalhos.
  ([`4d82a2c`](https://github.com/natharuc/datapyn/commit/4d82a2cb50bf0e3362bde93648f4fe9ba76a6de6))


## v1.8.0 (2026-02-19)

### Chores

- Limpar pasta raiz do projeto
  ([`e34f1d1`](https://github.com/natharuc/datapyn/commit/e34f1d175d3ff3a5dc3702578bbb02e131a9e7da))

### Features

- **database**: Adiciona suporte a LocalDB com autenticação automática
  ([`edfe10f`](https://github.com/natharuc/datapyn/commit/edfe10fbeaa87d1b4b18861ed0b28d6229300277))


## v1.7.0 (2026-02-17)

### Features

- Isolamento de paineis por sessao, grid fluido com limitador de linhas
  ([`3d7aa62`](https://github.com/natharuc/datapyn/commit/3d7aa626237a0d18148ede42ef079daaf6f4c5c7))


## v1.6.0 (2026-02-17)

### Bug Fixes

- Auth via Basic header em vez de URL, corrigir QThread jedi crash
  ([`a6d9cb0`](https://github.com/natharuc/datapyn/commit/a6d9cb0903c6a14f8b90373f0751f30071608fe3))

- Busca de pacotes exibia resultados falsos em sources privadas
  ([`3d53334`](https://github.com/natharuc/datapyn/commit/3d53334627b5d2af45ebfaf04e69718d382ded66))

- Corrigir get_colors -> get_app_colors em _AddSourceDialog
  ([`03f70a6`](https://github.com/natharuc/datapyn/commit/03f70a62ee35b4b47f88762aff476210f1692677))

- Drag-drop conexao nao muda conexao da aba existente
  ([`03111f0`](https://github.com/natharuc/datapyn/commit/03111f0989b8b61f71c978e71701479de830bc34))

- PackageManager usa uv em vez de pip
  ([`e640ea6`](https://github.com/natharuc/datapyn/commit/e640ea64ed7940741c45ad6bbe7cb2ddc406b133))

- Pesquisa de pacotes verifica PyPI + extra sources antes de exibir
  ([`9d19d50`](https://github.com/natharuc/datapyn/commit/9d19d50efdd42ddeaa01e8f3f0dd82dd9d15ae29))

- QThread crash no jedi autocomplete ao abrir bloco Python
  ([`a042a50`](https://github.com/natharuc/datapyn/commit/a042a50f61f070c800ee1b99e225dddcea28f0fa))

- Race condition no _cleanup do jedi_completer
  ([`4f9ac49`](https://github.com/natharuc/datapyn/commit/4f9ac4975bcb5b05c8d388a25213c42a51442503))

- Regex de file links nao casava com URLs PEP 503 com hash fragment
  ([`1773bcc`](https://github.com/natharuc/datapyn/commit/1773bccadc4d349147cd4d726ccdfaca502b1f66))

- Remover --python flag do uv pip (argumento invalido)
  ([`b500d0d`](https://github.com/natharuc/datapyn/commit/b500d0d8984e60c149cd67fe272333d19a85fc76))

- SQL autocomplete case-insensitive
  ([`ef08b49`](https://github.com/natharuc/datapyn/commit/ef08b49a3089320b25abef79e9d22bbc11105798))

- SQL autocomplete preserva case real de tabelas/colunas
  ([`99b9ac0`](https://github.com/natharuc/datapyn/commit/99b9ac0e6fc9d99571e46377f8c188c87b0a1adf))

- **ci**: Grep versao casava 2 linhas no pyproject.toml
  ([`ee7f41a`](https://github.com/natharuc/datapyn/commit/ee7f41a3613af7aa491c13826148cd8cf7a1c8fd))

### Features

- Autenticacao para fontes privadas de pacotes (Azure DevOps, Artifactory)
  ([`b7d40f7`](https://github.com/natharuc/datapyn/commit/b7d40f75a1c7e2ad66de35db9a9a6a656f46e1a1))

- Drag-drop conexao cria bloco SQL, seletor de banco por bloco
  ([`c344ee3`](https://github.com/natharuc/datapyn/commit/c344ee3ab55d2caea743dc5ae98afe3fd94dcf63))

- Jedi autocomplete, package sources, database switch propagation
  ([`f965d4d`](https://github.com/natharuc/datapyn/commit/f965d4dd9ef29d40da7a88ef807bba215e6a21f9))

- Jedi autocomplete, package sources, database switch propagation
  ([`0cf1388`](https://github.com/natharuc/datapyn/commit/0cf13881168608b7b9817eb058af026c0d76df5e))

- Persistencia de layout dock widgets entre reinicializacoes
  ([`ed295ca`](https://github.com/natharuc/datapyn/commit/ed295cadcf91be5fb9dd39cfdfe2e0199c43b32d))

- SqlAutoCompleteService - autocomplete SQL contextual
  ([`db3673e`](https://github.com/natharuc/datapyn/commit/db3673efae205b3a6352d3546e6abe20796b9985))


## v1.5.1 (2026-02-16)

### Refactoring

- Remove Monaco Editor, fix splash screen e build
  ([`73b7fe2`](https://github.com/natharuc/datapyn/commit/73b7fe292bf419087a9ec5c75047288eb0d97585))


## v1.5.0 (2026-02-16)

### Bug Fixes

- MSI build - XSLT ComponentRef removal and include language files
  ([`874438d`](https://github.com/natharuc/datapyn/commit/874438d3ec1775c9344b8b5d873c195fb3dfb2f3))

### Features

- Installer BMPs with DataPyn logo and simplified CI workflow
  ([`1d3c840`](https://github.com/natharuc/datapyn/commit/1d3c840e1f349c2f8d30c87a8bcbe31f4f009045))


## v1.4.0 (2026-02-16)

### Continuous Integration

- Ignore test files that require real database connections
  ([`f521ab1`](https://github.com/natharuc/datapyn/commit/f521ab18947b2ac77a4624480c757911680eef5f))

### Documentation

- Add translation tracking plan for en-US migration
  ([`00e96c3`](https://github.com/natharuc/datapyn/commit/00e96c3d1736d9925b8925a5f19124521fb0c877))

### Features

- Ajuste em geraçã de msi
  ([`2333baa`](https://github.com/natharuc/datapyn/commit/2333baa15941bb11894eeab6a9f0663e05527eab))

- Ajuste em geraçã de msi
  ([`fe4c288`](https://github.com/natharuc/datapyn/commit/fe4c28815627ffc754cb031cd442ddb4c201abd9))

- English interface
  ([`484080f`](https://github.com/natharuc/datapyn/commit/484080f05b67a39b8063f0a0b6687cecd7d643b5))

- I18n system with JSON translations and language selector
  ([`d1c0ba9`](https://github.com/natharuc/datapyn/commit/d1c0ba92683ef439bbf7be0eee754a8706d510c2))


## v1.3.0 (2026-02-15)

### Bug Fixes

- Adicionar logger em main_window.py para evitar NameError
  ([`ae35e0b`](https://github.com/natharuc/datapyn/commit/ae35e0b9c864c88fcef6463ae09f220de3bffc9d))

### Features

- Ajuste em build de msi
  ([`ac17936`](https://github.com/natharuc/datapyn/commit/ac17936e191180f750c45f59ff5fb3883be82ae6))


## v1.2.0 (2026-02-14)

### Bug Fixes

- Address code review feedback
  ([`9e819bf`](https://github.com/natharuc/datapyn/commit/9e819bfa3fd96cf376a51f3bd2c13b90d75346b9))

### Documentation

- Improve clarity of XSLT transform comment in workflow
  ([`2bba750`](https://github.com/natharuc/datapyn/commit/2bba750ed22fe45c17bd7d51ffa1f588c09a8c60))

### Features

- Add additional MSI optimizations and comprehensive documentation
  ([`1fbce6e`](https://github.com/natharuc/datapyn/commit/1fbce6ec8e681b3279ba4a112004319bc01e5547))

- Optimize MSI size by excluding unnecessary files and improving compression
  ([`b66748b`](https://github.com/natharuc/datapyn/commit/b66748b68a46d100196656961cd123eac8338c34))


## v1.1.8 (2026-02-14)

### Bug Fixes

- Ajuste em falha ao abrir tela de versao
  ([`69af77e`](https://github.com/natharuc/datapyn/commit/69af77e0e19f51acce513bd007e58ebaa9388a0f))


## v1.1.7 (2026-02-13)

### Bug Fixes

- **ci**: Disable Microsoft apt repos returning 403
  ([`a273e16`](https://github.com/natharuc/datapyn/commit/a273e16ffb326ac6abebf6df960fbc411ff35e91))


## v1.1.6 (2026-02-13)

### Bug Fixes

- **ci**: Retry automatico em crash SIGABRT do QWebEngine durante testes
  ([`e028939`](https://github.com/natharuc/datapyn/commit/e02893993c5011b8ddf39b05e667395df652219b))


## v1.1.5 (2026-02-13)

### Bug Fixes

- Loading infinito na verificacao de atualizacao
  ([`a9b8c0c`](https://github.com/natharuc/datapyn/commit/a9b8c0c4cea220faf84c718769bc0a61dfc48208))

- **test**: Usar tempdir real no teste de install_update (cross-platform)
  ([`e0139af`](https://github.com/natharuc/datapyn/commit/e0139afc2ff0ae9463f36d19dc40874a46eafc58))


## v1.1.4 (2026-02-13)

### Bug Fixes

- **installer**: Sanitizar versao para formato MSI valido (x.x.x.x)
  ([`71c58f3`](https://github.com/natharuc/datapyn/commit/71c58f3192cb51b3d0fbf64dc68e812fdd2b64ab))

- **installer**: Suprimir ICE38 e ICE60 para bundles PyInstaller per-user
  ([`13885c1`](https://github.com/natharuc/datapyn/commit/13885c1e9b0220cf7d94c4c9f272efdf30f669e2))

- **installer**: Suprimir ICE64 para diretórios em user profile
  ([`d3200d5`](https://github.com/natharuc/datapyn/commit/d3200d566b8b6285bf8e36b53391de75c7b114cd))

- **installer**: Suprimir ICE91 (esperado para per-user)
  ([`0bc11cf`](https://github.com/natharuc/datapyn/commit/0bc11cf94638a50375022ef47658e59640e4c9f5))

- **installer**: Suprimir warnings HEAT5150 de SelfReg
  ([`0c15b20`](https://github.com/natharuc/datapyn/commit/0c15b20054f76a9a8a68838519d374e532f22f29))


## v1.1.3 (2026-02-13)

### Bug Fixes

- **installer**: Copiar assets para dist/scripts onde WiX espera
  ([`b54ba6d`](https://github.com/natharuc/datapyn/commit/b54ba6d2d61e37db9621337cc09a9105c87738e8))


## v1.1.2 (2026-02-13)

### Bug Fixes

- **installer**: Corrigir MSI - textos, assinatura e permissoes
  ([`634bf60`](https://github.com/natharuc/datapyn/commit/634bf60175e8aa4c03a55602204c8033cdfcc855))


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
