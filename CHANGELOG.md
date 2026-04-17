# CHANGELOG

<!-- version list -->

## v1.23.0 (2026-04-17)

### Features

- Run timer, DELIMITER-aware SQL split, OE improvements, configurable shortcuts
  ([`2b14ec2`](https://github.com/natharuc/datapyn/commit/2b14ec2473bdd6f5d32f5a9c778aead666fe863d))


## v1.22.0 (2026-04-15)

### Bug Fixes

- **ci**: Remover cache pip e adicionar fallback para WiX path
  ([`7931a4c`](https://github.com/natharuc/datapyn/commit/7931a4cd73882b14ba9a7479572a770bc0820c17))

### Features

- Toggle ativo/inativo nos blocos de codigo
  ([`fbed70b`](https://github.com/natharuc/datapyn/commit/fbed70b36ca3eb1632e227c18687620c3c4d463c))


## v1.21.2 (2026-04-14)

### Bug Fixes

- Retry automatico quando OAuth token do Databricks expira
  ([`09e57b3`](https://github.com/natharuc/datapyn/commit/09e57b38f8dc2b45741145fbb8219b3ce91c3da5))


## v1.21.1 (2026-04-13)

### Bug Fixes

- Suporte correto a GO como separador de batches SQL Server
  ([`66b8507`](https://github.com/natharuc/datapyn/commit/66b850762a4607ed617ea882e247098eac000d95))


## v1.21.0 (2026-04-12)

### Features

- Copilot identifica blocos por nome + system prompt melhorado
  ([`15c74f4`](https://github.com/natharuc/datapyn/commit/15c74f49d3c9b18d4e0009f9459c983d63dc413d))

- Maximizar bloco (focus mode) + CTRL+C copia selecao no grid
  ([`1f98f7e`](https://github.com/natharuc/datapyn/commit/1f98f7ebda7fdf0fe5d1d05580916db3bc684fc4))


## v1.20.0 (2026-04-08)

### Features

- **variables-panel**: Add "Show in results" action for DataFrame/Series
  ([`e27e6d8`](https://github.com/natharuc/datapyn/commit/e27e6d8dbb6ebff20edc5fd616e40e35790c22ee))


## v1.19.0 (2026-03-11)

### Features

- **package-manager**: Add support for virtual environment management
  ([`b7e1bca`](https://github.com/natharuc/datapyn/commit/b7e1bca01f53dda15caffffad415a36995acad3c))


## v1.18.0 (2026-03-10)

### Bug Fixes

- Improve edit_block_lines validation and performance
  ([`c7c29d1`](https://github.com/natharuc/datapyn/commit/c7c29d18b53b9c83fc30ae668b96d342ae846692))

### Features

- Add new MCP tools and improve Copilot integration
  ([`4835dbf`](https://github.com/natharuc/datapyn/commit/4835dbf2ad190ab36bfdd48941fd396c782bace1))

- Contador de tempo em blocos, remover eval/run-shell, fix WMI hang
  ([`b4dc950`](https://github.com/natharuc/datapyn/commit/b4dc95070ba459915f92cc5d77a968c45f289f6c))


## v1.17.0 (2026-02-26)

### Features

- **oe**: Isolamento per-session do cache de schema
  ([`2b37d45`](https://github.com/natharuc/datapyn/commit/2b37d4540be2c000d81c10859b080c2ffb6e9cac))


## v1.16.0 (2026-02-26)

### Bug Fixes

- **oe**: Isolar Object Explorer por sessao
  ([`4dae634`](https://github.com/natharuc/datapyn/commit/4dae634394c7f009a4c9d9811a6cc6ad0e48a16e))

### Features

- **oe**: Integracao Object Explorer com conexoes per-block
  ([`57f931d`](https://github.com/natharuc/datapyn/commit/57f931d795e7a35d7d0279cefefe3c6ee706f390))


## v1.15.0 (2026-02-25)


## v1.14.0 (2026-02-25)

### Bug Fixes

- Force_completion usava _request_counter inexistente
  ([`7d66c4b`](https://github.com/natharuc/datapyn/commit/7d66c4bd1faf27ce93df43dc6edc40e057eb716f))

- LSP auth status 'OK' nao era reconhecido como autenticado
  ([`be3524c`](https://github.com/natharuc/datapyn/commit/be3524c187b75340a65110d1fb48635e55dd2141))

- Permitir autocomplete ao quebrar linha
  ([`9c76808`](https://github.com/natharuc/datapyn/commit/9c768082fddb2b9c31fce804931ea2ed1b636c35))

- Usar getCompletions para completions multi-linha
  ([`154fcdf`](https://github.com/natharuc/datapyn/commit/154fcdf6243bf28c632b3f6f7ad74dc32e011b13))

- Workspace switch e auto update service cleanup
  ([`6c81985`](https://github.com/natharuc/datapyn/commit/6c81985b5930bcd2bcb129b0bea1097abd6f4cd1))

### Features

- Workspace name prefix no titulo da janela
  ([`b08429f`](https://github.com/natharuc/datapyn/commit/b08429ff5c74932f9441d730c3d4123216bc5ad9))

- Workspace switch dialog e force autocomplete (Ctrl+.)
  ([`b630991`](https://github.com/natharuc/datapyn/commit/b6309913f336c3833ff4ed1b27746d361cdd8904))

- **copilot**: Auth service + workspace improvements
  ([`a56576a`](https://github.com/natharuc/datapyn/commit/a56576af6db783135565cd5bbc76cdcc0626f476))

- **copilot**: Implement getPanelCompletions for multi-line suggestions
  ([`6805110`](https://github.com/natharuc/datapyn/commit/6805110b04b47eda4bd5d691e6ac11a346f6b8e3))

- **sql**: Autocomplete SSMS-style + blocos SQL maiores
  ([`8496f54`](https://github.com/natharuc/datapyn/commit/8496f541b6d5b25a8afe4629bdb8b0c5b363f376))

- **ux**: Ask confirmation before closing unsaved tab
  ([`3444ca2`](https://github.com/natharuc/datapyn/commit/3444ca20af683cf920b5260259c8dabbca6b2ba3))


## v1.13.0 (2026-02-24)

### Features

- **ui**: Modern theme overhaul with blue accent and Inter font
  ([`bb1d3c6`](https://github.com/natharuc/datapyn/commit/bb1d3c621732208cc87e824285fc51481891adae))

- **ui**: Polish visual com fonte Ubuntu, dropdowns e status
  ([`0810de5`](https://github.com/natharuc/datapyn/commit/0810de58111abed91af58c5a0b86b11fe4991ef2))


## v1.12.1 (2026-02-22)

### Bug Fixes

- Esconde janelas CMD dos subprocessos no Windows
  ([`dba559f`](https://github.com/natharuc/datapyn/commit/dba559f1324d6f89514e3c44ff2764dd17e8fe61))

- MSI install - HTML templates e Copilot CLI
  ([`1f98e1b`](https://github.com/natharuc/datapyn/commit/1f98e1b04380689c9b18a24ba74f58893feecd21))

### Chores

- Atualiza copilot-instructions.md
  ([`ef176f8`](https://github.com/natharuc/datapyn/commit/ef176f8320d174a1bad44078d2622fd9b3c68dde))


## v1.12.0 (2026-02-22)


## v1.11.0 (2026-02-22)

### Bug Fixes

- Adiciona __init__.py faltando (copilot + monaco)
  ([`457a788`](https://github.com/natharuc/datapyn/commit/457a788011e7df7b82ac58fdb6a8ca5d7420550d))

- Chat message widget vertical sizing for long messages
  ([`7c4c942`](https://github.com/natharuc/datapyn/commit/7c4c942b66d605581ab8e9785094f2aa4ae4f6ec))

- Chat panel - center welcome label, messages fill available width
  ([`4a31378`](https://github.com/natharuc/datapyn/commit/4a31378d1ffe3be2cdb876dd3d7de63162f6439f))

- Chat panel layout - no horizontal scroll, proper message alignment
  ([`4768a7b`](https://github.com/natharuc/datapyn/commit/4768a7bce55eac240523ab2a9fc68db8e1a71e1b))

- Code review improvements - security and resource management
  ([`d66e602`](https://github.com/natharuc/datapyn/commit/d66e602ab8aa8e3432683501db3f8788578d112c))

- Corrige imports e ignora testes WebEngine no CI
  ([`2006f3e`](https://github.com/natharuc/datapyn/commit/2006f3e27db1f55905c2281899c7df8374eee2aa))

- Corrige pythonpath para CI - remove source/src duplicado
  ([`be5f2be`](https://github.com/natharuc/datapyn/commit/be5f2bea90cd188d8d1665a48b820ba37b5e60f6))

- Guard against deleted C++ object in copilot_output_panel
  ([`f3d094e`](https://github.com/natharuc/datapyn/commit/f3d094e0125b32bfa7586606d3f3a2fcd983ccf8))

- Imports defensivos para copilot em ambiente CI headless
  ([`55b0020`](https://github.com/natharuc/datapyn/commit/55b0020602148725b0c1b3baad383036b28aad22))

- Make Monaco imports defensive for CI/headless environments
  ([`197d9c0`](https://github.com/natharuc/datapyn/commit/197d9c099ebb3fdd2fc179ba277fec1de3d0e46f))

- Only ignore generated report PNGs in root
  ([`d027350`](https://github.com/natharuc/datapyn/commit/d0273501a10524954da1e2a245b8029a82b93e06))

- Remove duplicate _delete_session method causing TypeError
  ([`23cf4a4`](https://github.com/natharuc/datapyn/commit/23cf4a4673ed497ddc2f6b988524fc27a9e49ccb))

- Remove skipped tests and fix test_settings_dialog
  ([`078591a`](https://github.com/natharuc/datapyn/commit/078591a10942aad8ae4ba88fb40cd3cdf77d9633))

- Rodar todos testes na CI - remove ignores, fixa API Monaco
  ([`3a072b1`](https://github.com/natharuc/datapyn/commit/3a072b1097af235f44abdda07801b8db55489f53))

- Use get_connection_config instead of get_config
  ([`311e69a`](https://github.com/natharuc/datapyn/commit/311e69ab2732c3f9554627cc662b0343ae44a166))

- **chat**: Improve tool group scrolling and visibility
  ([`e1d8276`](https://github.com/natharuc/datapyn/commit/e1d8276e5267587cb537d40bb8c60bc9265de9b1))

- **chat**: Set dark background on WebView before load to prevent white flash
  ([`36161b8`](https://github.com/natharuc/datapyn/commit/36161b84258d5531434d100b17052cbd3b0b49d1))

- **test**: Wait for QTimer.singleShot in test_new_session_captures_previous_connection
  ([`f907c04`](https://github.com/natharuc/datapyn/commit/f907c044546f2ce290a76fc7c27f692f59d4f182))

### Chores

- Add test output files to gitignore
  ([`f7875cd`](https://github.com/natharuc/datapyn/commit/f7875cdada871eb479c79bf97552c7351933ee2c))

- Ignore png files
  ([`1d07f83`](https://github.com/natharuc/datapyn/commit/1d07f83bb4bff9993b6fbdf328510f65e3e4ede7))

- Remove accidental image file
  ([`d73003d`](https://github.com/natharuc/datapyn/commit/d73003ddfb9204581a9d6f0b68731bfecee7bad1))

- Remove accidentally committed image
  ([`fff13f4`](https://github.com/natharuc/datapyn/commit/fff13f4e85e6a0c287281849b436d2acbf591714))

### Features

- Add Copilot SDK integration - MCP server, client, and chat panel
  ([`9916a94`](https://github.com/natharuc/datapyn/commit/9916a947e173898e343cb5899c5f14792e68bbef))

- Add stop button, get_execution_results and notify_user tools
  ([`e62fb84`](https://github.com/natharuc/datapyn/commit/e62fb84f8ab1ee7a752d7ec22a5c02951c3ec626))

- Improve Copilot integration with block naming
  ([`151dec9`](https://github.com/natharuc/datapyn/commit/151dec99fffc745d08b4de02c54035d99da8373b))

- Monaco Editor integration with Copilot LSP
  ([`3af0830`](https://github.com/natharuc/datapyn/commit/3af08306be6d690831591de8b6e593bc84b15353))

- **chat**: Group tool calls in collapsible container
  ([`8e32042`](https://github.com/natharuc/datapyn/commit/8e3204233660412e41c07cf9e282b69cc78644a1))

- **copilot**: Melhorias na UI - menu usuario, delete sessoes, usage label
  ([`65db95d`](https://github.com/natharuc/datapyn/commit/65db95db0d0da3ba091451681fdea27278f77cf3))

- **deps**: Add GitHub Copilot SDK for integration support (not completed yet)
  ([`2a40a24`](https://github.com/natharuc/datapyn/commit/2a40a24f22281e31a4634da37c0bac7ff64baa22))

### Performance Improvements

- Fix UI stutter when dragging window
  ([`99ef098`](https://github.com/natharuc/datapyn/commit/99ef098c2f17d9435a565ab38271133e221245f5))

### Refactoring

- Address code review feedback
  ([`6022a35`](https://github.com/natharuc/datapyn/commit/6022a3507dd61285d33f8bcca507915c25648b44))

- Replace PyQt chat widgets with WebView-based implementation
  ([`be5b4a5`](https://github.com/natharuc/datapyn/commit/be5b4a50b50dd1023534a9614eb5612d031545bb))

### Testing

- Add comprehensive tests for Copilot integration (41 tests)
  ([`32a8893`](https://github.com/natharuc/datapyn/commit/32a8893849def6d2cf1bd215d943c827795881e2))


## v1.10.0 (2026-02-20)

### Features

- **dependencies**: Add new libraries for Databricks and SQL compatibility
  ([`e82432d`](https://github.com/natharuc/datapyn/commit/e82432d77b4e732dfba1ba185479cfc24409bb46))


## v1.9.0 (2026-02-20)

### Bug Fixes

- Remove cross-syntax tests (feature removed)
  ([`2ef311b`](https://github.com/natharuc/datapyn/commit/2ef311bd3424fe3fa90c20b05de332e0b3e93be2))

- UX improvements and bug fixes
  ([`0e03bfc`](https://github.com/natharuc/datapyn/commit/0e03bfc41732131c09ed78ddd31b631513388439))

### Features

- Databricks connector finalizado
  ([`3bbf6ea`](https://github.com/natharuc/datapyn/commit/3bbf6ea82acd1ab5ba2626a6b7ec177f72a73f47))

- **ui**: Modernizacao visual - design mais limpo e web-like
  ([`480078b`](https://github.com/natharuc/datapyn/commit/480078bdcf28aba7aa699738eb695eb234d10083))


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
