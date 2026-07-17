# CHANGELOG

<!-- version list -->

## v1.53.1 (2026-07-17)

### Bug Fixes

- **schema**: Populate per-block database dropdown on connect
  ([`e21b7ef`](https://github.com/natharuc/datapyn/commit/e21b7efc8119ca06c0e571fa5526ae03002ab7f7))

- **schema**: Populate per-block database dropdown on connect
  ([`c662b41`](https://github.com/natharuc/datapyn/commit/c662b41efced727c9ee5338a4b5ca954d52c2fdc))

### Heuristic

- Merge pull request #145 from natharuc/fix/schema-dropdown-oe-focus-crash-guard
  ([`e21b7ef`](https://github.com/natharuc/datapyn/commit/e21b7efc8119ca06c0e571fa5526ae03002ab7f7))


## v1.53.0 (2026-07-16)

### Bug Fixes

- **connections**: Idle reaper must read is_periodic_active as property
  ([`56a3c7d`](https://github.com/natharuc/datapyn/commit/56a3c7d0ea0afca3eee664848c30d88f7bf5eb30))

- **qt**: Marshal cross-thread signals to prevent Qt6Core crashes.
  ([`db0cb40`](https://github.com/natharuc/datapyn/commit/db0cb40979eb751a4d09e4d02027c7484f2632ea))

- **schema**: Populate block database dropdown after lazy connect
  ([`129c6a3`](https://github.com/natharuc/datapyn/commit/129c6a352c17d410f27d60b1466198661eb4de51))

- **schema,oe**: Block db dropdown + OE focus-load + global crash guard
  ([`0de260c`](https://github.com/natharuc/datapyn/commit/0de260c74413b023c501bf770919a1867012662a))

### Features

- **crash-guard**: Global exception interceptor with GitHub issue reporter
  ([`049c455`](https://github.com/natharuc/datapyn/commit/049c4550716c3c64637cc3958bd225ced3447c33))

- **object-explorer**: Auto-load databases on focus and visibility
  ([`ae5b8a5`](https://github.com/natharuc/datapyn/commit/ae5b8a5905283002813ba9bbd72a033bcdce9897))

### Heuristic

- Merge branch 'fix/application-crashes' into fix/schema-dropdown-oe-focus-crash-guard
  ([`3100cab`](https://github.com/natharuc/datapyn/commit/3100cab731c8967c1569dc921e7d067651a5f0fe))

- Merge pull request #144 from natharuc/fix/schema-dropdown-oe-focus-crash-guard
  ([`0de260c`](https://github.com/natharuc/datapyn/commit/0de260c74413b023c501bf770919a1867012662a))

### Refactoring

- **crash-guard**: Marshal dialog via QueuedConnection signal
  ([`8f7c757`](https://github.com/natharuc/datapyn/commit/8f7c757e469dbe15e5c267b5bb1b62f74551fa90))


## v1.52.0 (2026-07-16)

### Bug Fixes

- **connections**: Start idle reaper only after SessionWidget UI setup
  ([`31ff2e6`](https://github.com/natharuc/datapyn/commit/31ff2e6caba3b5b6f1f74a5629feb4d0bd78da80))

### Features

- **connections**: Close idle SQL Server connections and lazy-load schema
  ([`5f702d4`](https://github.com/natharuc/datapyn/commit/5f702d4e1e97f7388c53333346b480bdc8961660))

- **connections**: Close idle SQL Server connections and lazy-load schema
  ([`c4819ed`](https://github.com/natharuc/datapyn/commit/c4819ed569411fdaff31e005da6d210f14ba3adf))

### Heuristic

- Merge pull request #142 from natharuc/feat/optimize-sleeping-sql-connections
  ([`5f702d4`](https://github.com/natharuc/datapyn/commit/5f702d4e1e97f7388c53333346b480bdc8961660))


## v1.51.0 (2026-07-15)

### Bug Fixes

- **ci**: Guard shared-params refresh and DPW save serialization
  ([`1fb39b2`](https://github.com/natharuc/datapyn/commit/1fb39b24617f9357b1afebcb6f152a0cf6cf0ed1))

### Continuous Integration

- Trigger PR checks
  ([`b8073b5`](https://github.com/natharuc/datapyn/commit/b8073b50bca3f56f7c3d5844be06c8dfc0f24518))

### Features

- **params**: Shared parameter panel at tab footer
  ([`1f4f774`](https://github.com/natharuc/datapyn/commit/1f4f77415fbc48981ccecc06dc29f7745b873a95))

- **params**: Shared tab parameters with {{name}} syntax
  ([`e17ab0b`](https://github.com/natharuc/datapyn/commit/e17ab0b3a9a19ae0a76cf68204ef2ac105c44ffa))

- **ui**: Polish params panel, CSV download options, and tab chrome
  ([`c270c3d`](https://github.com/natharuc/datapyn/commit/c270c3d46171035b51747e8dd652a3a79df952b5))

- **ui**: Polish params panel, CSV download options, and tab chrome
  ([`0065e1e`](https://github.com/natharuc/datapyn/commit/0065e1e9009f20396768b0f7966037fb5ed37423))

### Heuristic

- Merge pull request #140 from natharuc/feat/params-ui-polish-download-csv
  ([`c270c3d`](https://github.com/natharuc/datapyn/commit/c270c3d46171035b51747e8dd652a3a79df952b5))

### Testing

- **params**: Shared tab parameter detection, prep, and persistence
  ([`c293783`](https://github.com/natharuc/datapyn/commit/c293783726079943fdc7e8fe9e4590e8ca8db0e5))


## v1.50.0 (2026-07-10)

### Bug Fixes

- **results**: Apply grid prepare when viewer was never shown
  ([`083b677`](https://github.com/natharuc/datapyn/commit/083b677cc11e86c19eafecdf84545251e0cd9ef8))

- **results**: Apply grid prepare when viewer was never shown
  ([`58182b0`](https://github.com/natharuc/datapyn/commit/58182b04415df8a14ba782597099b5d0cbe0f7b5))

- **security**: Stop logging notification credential key names
  ([`710cf52`](https://github.com/natharuc/datapyn/commit/710cf52ec27dbcb7bc083bd55034e71b039418f0))

### Features

- **ui**: Tab-close UX, typing-freeze fixes, and related polish
  ([`5702631`](https://github.com/natharuc/datapyn/commit/57026313d504d010aee989efdf0f0f2ec0441d71))

- **ui**: Tab-close UX, typing-freeze fixes, and related polish
  ([`3dcc33e`](https://github.com/natharuc/datapyn/commit/3dcc33ee5f09ce72ab96d342aa280ff7dda0586b))

### Heuristic

- Merge pull request #136 from natharuc/feat/tab-close-ux-typing-freeze
  ([`5702631`](https://github.com/natharuc/datapyn/commit/57026313d504d010aee989efdf0f0f2ec0441d71))

- Merge pull request #137 from natharuc/fix/results-viewer-defer-grid-ci
  ([`083b677`](https://github.com/natharuc/datapyn/commit/083b677cc11e86c19eafecdf84545251e0cd9ef8))


## v1.49.0 (2026-07-06)

### Features

- **download**: Streaming export, progress bars, error surfacing, parquet null fix
  ([`90d734d`](https://github.com/natharuc/datapyn/commit/90d734dd0f7add92057033e71a80d6f660a57efa))

- **download**: Streaming export, progress bars, error surfacing, parquet null fix
  ([`3d38dc3`](https://github.com/natharuc/datapyn/commit/3d38dc3d218b50bbf79a5d3e2a6f33174f203611))

### Heuristic

- Merge pull request #135 from natharuc/fix/download-error-parquet-reveal
  ([`90d734d`](https://github.com/natharuc/datapyn/commit/90d734dd0f7add92057033e71a80d6f660a57efa))


## v1.48.0 (2026-06-29)

### Features

- Melhoria em digitação, removendo congelamentos
  ([`0ce8028`](https://github.com/natharuc/datapyn/commit/0ce80285f27fb1d156d61801582333ece2297bdf))

- Melhoria em digitação, removendo congelamentos
  ([`08a507b`](https://github.com/natharuc/datapyn/commit/08a507b9f70110866aa531472c911d7323fca6a5))

### Heuristic

- Merge pull request #134 from natharuc/feature/feature-dpw-file
  ([`0ce8028`](https://github.com/natharuc/datapyn/commit/0ce80285f27fb1d156d61801582333ece2297bdf))


## v1.47.0 (2026-06-26)

### Features

- Instalador default dpw
  ([`b6daa69`](https://github.com/natharuc/datapyn/commit/b6daa696e26ce4def247866a246ce9009afdd5da))

- Instalador default dpw
  ([`0acda62`](https://github.com/natharuc/datapyn/commit/0acda624b47a4373a8b4874611e2bf82dc93a0f8))

### Heuristic

- Merge pull request #133 from natharuc/feature/feature-dpw-file
  ([`b6daa69`](https://github.com/natharuc/datapyn/commit/b6daa696e26ce4def247866a246ce9009afdd5da))


## v1.46.1 (2026-06-22)

### Bug Fixes

- Resolvendo atualização automatica
  ([`9053449`](https://github.com/natharuc/datapyn/commit/9053449d4f658d8379f47210620bd67ff8c6c46c))

- Resolvendo atualização automatica
  ([`a372a93`](https://github.com/natharuc/datapyn/commit/a372a93a1e05db0a98fb6076756ae05ab4112a8d))

### Heuristic

- Merge pull request #132 from natharuc/bug/bug-update
  ([`9053449`](https://github.com/natharuc/datapyn/commit/9053449d4f658d8379f47210620bd67ff8c6c46c))


## v1.46.0 (2026-06-20)

### Features

- Ajuste em testes e audit
  ([`b99a728`](https://github.com/natharuc/datapyn/commit/b99a728edd301e40f1c55ceaebdd5e5070fed87a))

- Melhorando consistencia em cancelamento de execuções
  ([`6ec4cab`](https://github.com/natharuc/datapyn/commit/6ec4cab6f0c8d85830758c406141ccf09cd3b48c))

- Melhorando consistencia em cancelamento de execuções
  ([`620e5aa`](https://github.com/natharuc/datapyn/commit/620e5aa7408ab309b7da62fd493e079c9f94f00a))

### Heuristic

- Merge pull request #131 from natharuc/feat/keep-last-result
  ([`6ec4cab`](https://github.com/natharuc/datapyn/commit/6ec4cab6f0c8d85830758c406141ccf09cd3b48c))


## v1.45.0 (2026-06-13)

### Bug Fixes

- **ci**: Emit one test path per line for shard mapfile
  ([`f69cf31`](https://github.com/natharuc/datapyn/commit/f69cf314f18f9e4f822176553ad253ca58e0e804))

- **tests**: Silent python namespace and get_context JSON on CI
  ([`06ee7e4`](https://github.com/natharuc/datapyn/commit/06ee7e4b68973c3c92bc55c971996cd7539c34e1))

### Features

- Correção de bugs
  ([`9133ad2`](https://github.com/natharuc/datapyn/commit/9133ad24a38801a5a8cfe57318f04006684eb2bf))

- Melhoria em execução de testes
  ([`2cbde4a`](https://github.com/natharuc/datapyn/commit/2cbde4ada8160b296dbf7fed5c3985caf752396b))

### Heuristic

- Merge pull request #130 from natharuc/feat/keep-last-result
  ([`db89de5`](https://github.com/natharuc/datapyn/commit/db89de554fd6cd8142ff3d7ff971e401e45348dc))

- Merge(main): resolve version and changelog conflicts
  ([`4bf7d6e`](https://github.com/natharuc/datapyn/commit/4bf7d6ec45d2e526e5ab6402f4434f638e48c889))


## v1.44.0 (2026-06-12)

### Features

- Ajuste em testes
  ([`03772ff`](https://github.com/natharuc/datapyn/commit/03772ffd4c24569011ca67760b9ce1b7edf7853f))

- Ajuste em testes
  ([`9d20f22`](https://github.com/natharuc/datapyn/commit/9d20f2275d25a3f7375956c56f347a0b9d04904d))

- Estabilização de usabilidade e fluidez
  ([`3d38347`](https://github.com/natharuc/datapyn/commit/3d38347af175a52794f463d72e10adb92bb3e419))

### Heuristic

- Merge branch 'main' of github-nac:natharuc/datapyn into feat/keep-last-result
  ([`8352f6a`](https://github.com/natharuc/datapyn/commit/8352f6abccf6aaac73edcead2ce6877c57084244))

- Merge pull request #129 from natharuc/feat/keep-last-result
  ([`1538325`](https://github.com/natharuc/datapyn/commit/1538325f412058e9711839491bf3c4805b7f423b))

## v1.43.0 (2026-06-10)

### Bug Fixes

- Melhoria em travamento do UI e otimização de cargas
  ([`9a6bad5`](https://github.com/natharuc/datapyn/commit/9a6bad571a68f73c75656de04b00458f8a91da98))

### Features

- Ajuste em testes
  ([`a46d71c`](https://github.com/natharuc/datapyn/commit/a46d71cb3f8fb2314b9036a5bfaf37cc7f2dafdb))

- Melhoria copilot e performance
  ([`5b0a70f`](https://github.com/natharuc/datapyn/commit/5b0a70f22ca4f92a91b6724dd75c82b9953e56a4))

- Salvar e restaurar variaveis de sessoes em parquet
  ([`6dbafe7`](https://github.com/natharuc/datapyn/commit/6dbafe7bcb561099c5481e7eb6e267886b85f34e))

### Heuristic

- Merge pull request #128 from natharuc/feat/keep-last-result
  ([`9a18d5f`](https://github.com/natharuc/datapyn/commit/9a18d5fc17a8b35c8a88d62b58b38d02ef9561e3))


## v1.42.4 (2026-06-06)

### Heuristic

- Merge pull request #127 from natharuc/cursor/pynia
  ([`89a427b`](https://github.com/natharuc/datapyn/commit/89a427bf1c100a933288ae86b474fc9b07e6ac36))

### Testing

- Melhorias em UX
  ([`89a427b`](https://github.com/natharuc/datapyn/commit/89a427bf1c100a933288ae86b474fc9b07e6ac36))

- Melhorias em UX
  ([`886686a`](https://github.com/natharuc/datapyn/commit/886686a9eec428733576e49db272b0fc10ad86cf))

- Melhorias em UX
  ([`e210d2c`](https://github.com/natharuc/datapyn/commit/e210d2c9731fc890cfec4a8b481b95330c5f7124))


## v1.42.3 (2026-06-06)

### Heuristic

- Merge pull request #126 from natharuc/cursor/pynia
  ([`cf6950e`](https://github.com/natharuc/datapyn/commit/cf6950e0d816989632202dc7a6c7caade37f9b10))

### Testing

- Ajuste em testes
  ([`cf6950e`](https://github.com/natharuc/datapyn/commit/cf6950e0d816989632202dc7a6c7caade37f9b10))

- Ajuste em testes
  ([`2623799`](https://github.com/natharuc/datapyn/commit/262379955d4d440c82be1654580c8ec8e56e0e98))


## v1.42.2 (2026-06-06)

### Heuristic

- Merge pull request #125 from natharuc/cursor/pynia
  ([`126ebef`](https://github.com/natharuc/datapyn/commit/126ebef419eb88f1f644afe90903a5935fa2a18e))

### Testing

- Ajuste em testes
  ([`250b14e`](https://github.com/natharuc/datapyn/commit/250b14e835d97cb1c9251901e021ed4a6ec5cab2))

- Ajuste em testes
  ([`addf8ab`](https://github.com/natharuc/datapyn/commit/addf8ab0810f7fbef5e6f5743960d2b4f1d39280))

- Ajuste em testes
  ([`1f87551`](https://github.com/natharuc/datapyn/commit/1f8755103dc7b6abea88608af52f78bab679e55c))


## v1.42.1 (2026-06-05)

### Heuristic

- Merge pull request #124 from natharuc/cursor/pynia
  ([`da3bfe6`](https://github.com/natharuc/datapyn/commit/da3bfe687b634b9f7bf05e7b62176907e7521ba8))

### Testing

- Ajuste em testes
  ([`da3bfe6`](https://github.com/natharuc/datapyn/commit/da3bfe687b634b9f7bf05e7b62176907e7521ba8))

- Ajuste em testes
  ([`da59182`](https://github.com/natharuc/datapyn/commit/da5918227226a432a7aa7e9b55d77850a163e019))


## v1.42.0 (2026-06-05)

### Features

- Padronizacoes de telas e janelas
  ([`6a47731`](https://github.com/natharuc/datapyn/commit/6a47731068a247d9ed691046acb2055f27d19f80))

### Heuristic

- Merge branch 'main' of github-nac:natharuc/datapyn into cursor/pynia
  ([`2064518`](https://github.com/natharuc/datapyn/commit/2064518fab94b75219daaf57846ab2b3e43ce3b2))

- Merge pull request #123 from natharuc/cursor/pynia
  ([`6a47731`](https://github.com/natharuc/datapyn/commit/6a47731068a247d9ed691046acb2055f27d19f80))

### Testing

- Ajuste em testes
  ([`4e33fa7`](https://github.com/natharuc/datapyn/commit/4e33fa740f932d732c4259519c3a762e0e8a0563))


## v1.41.0 (2026-06-05)

### Features

- Padronizacoes de telas e janelas
  ([`ddab1dd`](https://github.com/natharuc/datapyn/commit/ddab1dd926f73de519539588f507f16430483870))

- Padronizacoes de telas e janelas
  ([`1e83712`](https://github.com/natharuc/datapyn/commit/1e83712350ffdde3d580952cc3ec435e1048e229))

- Padronizacoes de telas e janelas
  ([`ea90e99`](https://github.com/natharuc/datapyn/commit/ea90e9978914c63e29d2ee1d9801f0633a9bb194))

### Heuristic

- Merge pull request #122 from natharuc/cursor/pynia
  ([`ddab1dd`](https://github.com/natharuc/datapyn/commit/ddab1dd926f73de519539588f507f16430483870))


## v1.40.0 (2026-06-04)

### Features

- Novo instalador e ajuste em splash scren
  ([`089864f`](https://github.com/natharuc/datapyn/commit/089864fe8a584bdf2f77fb6e3315b710385f9e56))

- Novo instalador e ajuste em splash scren
  ([`d5db92e`](https://github.com/natharuc/datapyn/commit/d5db92ec9f6127e9be7022e227a6c4c1e1d5a741))

### Heuristic

- Merge pull request #121 from natharuc/cursor/pynia
  ([`089864f`](https://github.com/natharuc/datapyn/commit/089864fe8a584bdf2f77fb6e3315b710385f9e56))


## v1.39.0 (2026-06-04)

### Features

- Novo instalador e ajuste em splash scren
  ([`d353185`](https://github.com/natharuc/datapyn/commit/d353185435138ca50654d08ddd9661983ce0c9eb))

- Novo instalador e ajuste em splash scren
  ([`56a4896`](https://github.com/natharuc/datapyn/commit/56a489609e6e1569732f6ba90d8207b2892883ca))

### Heuristic

- Merge pull request #120 from natharuc/cursor/pynia
  ([`d353185`](https://github.com/natharuc/datapyn/commit/d353185435138ca50654d08ddd9661983ce0c9eb))


## v1.38.0 (2026-06-04)

### Features

- **installer**: Replace MSI with ZIP setup and in-app updates
  ([`7f82d74`](https://github.com/natharuc/datapyn/commit/7f82d747268476273315f110dec790b83abc9d2b))

- **installer**: Replace MSI with ZIP setup and in-app updates
  ([`d5a34d6`](https://github.com/natharuc/datapyn/commit/d5a34d689fe933f293813029b1b9adcc82b25cca))

### Heuristic

- Merge pull request #118 from natharuc/cursor/pynia
  ([`7f82d74`](https://github.com/natharuc/datapyn/commit/7f82d747268476273315f110dec790b83abc9d2b))

- Merge pull request #119 from natharuc/cursor/pynia
  ([`fd43556`](https://github.com/natharuc/datapyn/commit/fd43556eb3eaa7038e66b684d90620e4b0b5152b))


## v1.37.0 (2026-06-04)

### Bug Fixes

- Ajuste em testes
  ([`05e2652`](https://github.com/natharuc/datapyn/commit/05e265282159577881e125a0eed5d834bac6dd3d))

- Readme
  ([`ecc479a`](https://github.com/natharuc/datapyn/commit/ecc479acc58c6a9c02c03f30f6e5529a9c3d3e38))

- **execution**: Cancel SQL on worker thread to avoid UI freeze
  ([`c45072f`](https://github.com/natharuc/datapyn/commit/c45072fe2555e9146cd0815afdc801df436e767a))

- **execution**: Initialize _sql_worker before Databricks DB switch retry
  ([`14edc40`](https://github.com/natharuc/datapyn/commit/14edc40c0bff54b79dcfda5907243f114fcfc190))

- **execution**: Run SQL for current editor selection, not stale cache
  ([`70b0094`](https://github.com/natharuc/datapyn/commit/70b00949ec28afb42bc1fcd73a674644fe54ece7))

- **pynia**: Add BlockEditor.set_pynia_client and chat integration tests
  ([`0ff5a79`](https://github.com/natharuc/datapyn/commit/0ff5a79ec625a8ba6226fc99e431cf58adb45e18))

- **pynia**: Fix Copilot SDK auth init and auto-login on open
  ([`c36eb14`](https://github.com/natharuc/datapyn/commit/c36eb1454721c4a487abca582584bdf1e41a15bb))

- **pynia**: Recover stuck chat turns after errors or cancel
  ([`52d61b2`](https://github.com/natharuc/datapyn/commit/52d61b2f051bba15561409e89314e8244754eb91))

- **pynia**: Stop chat tool loops and stuck running UI
  ([`cf84b23`](https://github.com/natharuc/datapyn/commit/cf84b23bff39e064927e23a930560d8f00229e82))

- **pynia**: Stop inspect loops and stuck running tools in Copilot
  ([`d6bedb2`](https://github.com/natharuc/datapyn/commit/d6bedb276f8f22a3064b9f44783e6a247cd6170d))

- **pynia**: Unblock Copilot tool UI stuck on running forever
  ([`219968d`](https://github.com/natharuc/datapyn/commit/219968d433e030f5582053f9262e8c4c5aeb4c15))

- **tests**: Align Pynia, charts, and tab paint tests with current UI
  ([`956ad1c`](https://github.com/natharuc/datapyn/commit/956ad1cd228b09eb41115501f37a7722ce35bca6))

### Features

- Cross-database SQL autocomplete, Monaco UX, and editor improvements
  ([`6bf2cad`](https://github.com/natharuc/datapyn/commit/6bf2cad011e84f94cd50ba10f68a7811d84c9be8))

- Integrate official Pynia logo across the UI
  ([`c3a672c`](https://github.com/natharuc/datapyn/commit/c3a672c89fbe76aee96dc931ad3b98ee29fa4810))

- Melhorias
  ([`a46efff`](https://github.com/natharuc/datapyn/commit/a46efffb48956697fdcfba07b8868f83b0abb742))

- Melhorias gerais
  ([`1aeee4e`](https://github.com/natharuc/datapyn/commit/1aeee4e04ab7ba898ed6a1c7e472d4d4c9676f29))

- **pynia**: Add multi-provider AI agent with LLM connectors
  ([`99914d8`](https://github.com/natharuc/datapyn/commit/99914d89e6064978834f872798756499e6e55428))

- **pynia**: Add parallel explore subagents and higher read-only limits
  ([`f5aaa62`](https://github.com/natharuc/datapyn/commit/f5aaa62212654a4d04e857352ebd8f0f25f5a69d))

- **pynia**: Anchor chat on focused block and speed up tool rounds
  ([`c28c195`](https://github.com/natharuc/datapyn/commit/c28c1958833e6ee1993d253366c99314838101ab))

- **pynia**: Compact chat UX like Cursor (single activity line)
  ([`fac88b5`](https://github.com/natharuc/datapyn/commit/fac88b52aa6b88ef963bfc2f46fff9f2248a3247))

- **pynia**: Consolidate agent tools into nine datapyn_* APIs
  ([`ae56410`](https://github.com/natharuc/datapyn/commit/ae56410a6639b9a0537e5e2eff1b35f880b1cdfa))

- **pynia**: Fluid agent progress UI with timeline and block labels
  ([`294549a`](https://github.com/natharuc/datapyn/commit/294549ac8409fb1ce65d96f34457a5483c351bf9))

- **pynia**: Multi-provider agent, UX, and execution fixes
  ([`78e893a`](https://github.com/natharuc/datapyn/commit/78e893a9f6fa7379c803e4e4088226a2f7ceaee5))

- **pynia**: Native agent identity, faster tools, and UI cleanup
  ([`e144860`](https://github.com/natharuc/datapyn/commit/e1448605fe538a4152aa8c6cbd3172837d28adee))

- **pynia**: Native inline autocomplete and remove Copilot settings tab
  ([`cc609ec`](https://github.com/natharuc/datapyn/commit/cc609ecec3b54f1131dd7a1b916eeb2e27632efe))

- **pynia**: Persist last chat model per provider
  ([`d9fc218`](https://github.com/natharuc/datapyn/commit/d9fc21898921257dfcc4031d064197a9b74f8e14))

- **pynia**: Rebrand chat UI and show per-provider limits
  ([`75439a2`](https://github.com/natharuc/datapyn/commit/75439a2c577c4d1937e6a72f5e481d22eeec3277))

- **pynia**: Sequential thinking UI and system prompt standard
  ([`27262f1`](https://github.com/natharuc/datapyn/commit/27262f14b7b3e9a3d8c1e707fdc67b3dbc0f807f))

- **pynia**: Session intelligence, block summaries, and smarter subagents
  ([`a3d83d8`](https://github.com/natharuc/datapyn/commit/a3d83d8212a06799b05cfc2784e257bf9644af56))

- **pynia**: Show focused block as chat attachment chip
  ([`999acca`](https://github.com/natharuc/datapyn/commit/999accad8339244f00156b69db3b8ea77439b159))

### Heuristic

- Merge pull request #115 from natharuc/cursor/pynia
  ([`78e893a`](https://github.com/natharuc/datapyn/commit/78e893a9f6fa7379c803e4e4088226a2f7ceaee5))

- Merge pull request #117 from natharuc/cursor/pynia
  ([`8b5d3ab`](https://github.com/natharuc/datapyn/commit/8b5d3abb2e456007eb2e3183bff046f60447a730))


## v1.36.1 (2026-06-02)

### Documentation

- **agents**: Add Cursor Cloud development instructions
  ([`e22b2bb`](https://github.com/natharuc/datapyn/commit/e22b2bb8fb130e99f200041aa9f815bd55c1221b))

- **agents**: Add Cursor Cloud development instructions
  ([`3209838`](https://github.com/natharuc/datapyn/commit/3209838a30e7fdd402d0020a9cea8ca8131ff6b4))

### Heuristic

- Merge pull request #110 from natharuc/cursor/cloud-dev-env-setup-1c49
  ([`e22b2bb`](https://github.com/natharuc/datapyn/commit/e22b2bb8fb130e99f200041aa9f815bd55c1221b))


## v1.36.0 (2026-06-02)

### Bug Fixes

- Melhoria em integração com cli
  ([`b072dfb`](https://github.com/natharuc/datapyn/commit/b072dfb97b0189f188401790287d5a9613f45ab7))

- **release**: Add DataPyn commit parser and PSR fallback for MSI
  ([`7feba5b`](https://github.com/natharuc/datapyn/commit/7feba5bdfd9aeb10fc2e49208f14bba5cae86a66))

- **release**: Semantic-release parser and MSI fallback on main
  ([`4bd39fc`](https://github.com/natharuc/datapyn/commit/4bd39fc06fd73793ea57f7ba09b9fff3ab862207))

### Continuous Integration

- **release**: Fail workflow when MSI is skipped on main
  ([`15445f7`](https://github.com/natharuc/datapyn/commit/15445f73e7ecdb33056b9bfcbbddbf98ce352363))

### Features

- Melhoria em integração com copilot
  ([`044667e`](https://github.com/natharuc/datapyn/commit/044667e03e005cbe5b21932bafb25d3444585751))

- Melhoria em integração com copilot
  ([`19ee27c`](https://github.com/natharuc/datapyn/commit/19ee27ccf63606a3dbddf48c1caca72776c5d6e7))

### Heuristic

- Merge pull request #108 from natharuc/ci/fail-when-msi-skipped
  ([`4bd39fc`](https://github.com/natharuc/datapyn/commit/4bd39fc06fd73793ea57f7ba09b9fff3ab862207))

- Merge pull request #109 from natharuc/ci/fail-when-msi-skipped
  ([`044667e`](https://github.com/natharuc/datapyn/commit/044667e03e005cbe5b21932bafb25d3444585751))


## v1.35.1 (2026-06-02)

### Continuous Integration

- Add agent rules for Conventional Commits and improve PSR workflow
  ([`f26666d`](https://github.com/natharuc/datapyn/commit/f26666dcdb94211191d45d10c162cdbea5b21ace))


## v1.35.0 (2026-05-30)

### Bug Fixes

- **security**: Stop logging Copilot model IDs and names in clear text.
  ([`a0d7713`](https://github.com/natharuc/datapyn/commit/a0d771390abfff1d383e505e7be655cf7ac82a73))

### Features

- Ship full WebView Copilot chat with image attachments and session persistence.
  ([`d455719`](https://github.com/natharuc/datapyn/commit/d45571988819a7ca7c1986805c86178aff2ca3e6))


## v1.34.0 (2026-05-29)

### Features

- Improve Copilot chat
  ([`0f2866d`](https://github.com/natharuc/datapyn/commit/0f2866d7a5fc17ce1b2c42be098fe1b1627b2e0f))


## v1.33.0 (2026-05-29)

### Features

- Melhora resultados SQL, charts e zoom
  ([`960a5d4`](https://github.com/natharuc/datapyn/commit/960a5d4718325c280200b509e49921c89bf3990b))


## v1.32.1 (2026-05-22)


## v1.32.0 (2026-05-18)

### Bug Fixes

- Limitar autocomplete SQL ao banco ativo
  ([`2b3ed76`](https://github.com/natharuc/datapyn/commit/2b3ed76e2e3bb924b61abf8e85a00a34ea2fc6ac))


## v1.31.0 (2026-05-16)

### Bug Fixes

- Restore saved connections asynchronously on startup
  ([`e284a97`](https://github.com/natharuc/datapyn/commit/e284a9709e88c050ad1e3d004d319d249527fed0))

### Features

- Add custom SQL parameter workflow
  ([`4752d09`](https://github.com/natharuc/datapyn/commit/4752d09f475630dedea5c83920f1b5ee1ccfe781))


## v1.30.2 (2026-05-16)

### Bug Fixes

- Stabilize object explorer lazy loading across databases
  ([`a7603d3`](https://github.com/natharuc/datapyn/commit/a7603d3a579c17652b3e0ff31a1e4029019d86f0))


## v1.30.1 (2026-05-15)

### Bug Fixes

- Unify databricks context and stabilize monaco updates
  ([`13f7480`](https://github.com/natharuc/datapyn/commit/13f74802c8051f69cb47989bfdd89aadf985969f))


## v1.30.0 (2026-05-14)

### Features

- Entity info for routines/triggers, smarter SQL autocomplete with routines
  ([`0934bf1`](https://github.com/natharuc/datapyn/commit/0934bf1b71bf7f08012de410f2d7e7429b930feb))

- Improve Copilot chat flow and stabilize Qt lifecycle
  ([`1b35fd5`](https://github.com/natharuc/datapyn/commit/1b35fd5ef73288a47731b771643c3cf4d052b377))


## v1.29.2 (2026-04-27)

### Bug Fixes

- Refine per-tab notification delivery
  ([`168e0b5`](https://github.com/natharuc/datapyn/commit/168e0b5f7a4aa7a56cd4b03b229dbd0a874a0150))


## v1.29.1 (2026-04-27)

### Bug Fixes

- Support python results in tab notifications
  ([`2cdd644`](https://github.com/natharuc/datapyn/commit/2cdd6440643939cfae733aef1d989c5ff52a009c))


## v1.29.0 (2026-04-21)

### Features

- Output panel interativo com navegacao por linha e coluna
  ([`4754fc9`](https://github.com/natharuc/datapyn/commit/4754fc978ba999aec90ed91e0f91dcdb1770e5ee))


## v1.28.0 (2026-04-20)

### Features

- Per-tab custom notifications with result access and color picker
  ([`9406089`](https://github.com/natharuc/datapyn/commit/9406089ee798712be98067bd42fae92b301b2450))


## v1.27.0 (2026-04-20)

### Bug Fixes

- Import ToastManager em _execution.py (notificacoes quebradas)
  ([`a59d3ea`](https://github.com/natharuc/datapyn/commit/a59d3ea602633ec5718afbdec0a01b60e7c8d335))

- Notificacoes sempre exibidas apos execucao
  ([`2c7c63c`](https://github.com/natharuc/datapyn/commit/2c7c63caf82017ab44bf148017e99524b5bd470a))

### Features

- Notification config + settings dialog refactor
  ([`883173c`](https://github.com/natharuc/datapyn/commit/883173c7ce5cab32c2771ca013e126389859dd60))


## v1.26.0 (2026-04-20)

### Bug Fixes

- Import Qt em _connections.py (NameError na troca de banco)
  ([`5b6c3bc`](https://github.com/natharuc/datapyn/commit/5b6c3bc5290b59eca672c4c05bb677baf4ed04e6))

- Invalidar cache de schema ao trocar banco via USE
  ([`46daa65`](https://github.com/natharuc/datapyn/commit/46daa65985eb5f7f934202d903c1784c47fd1f20))

- NameError SessionWidget em _connections + USE db intellisense
  ([`9dedac0`](https://github.com/natharuc/datapyn/commit/9dedac01ee017eb4006aa1d2fda300f35fea61f5))

- Preservar tempo de execucao quando set_running(False) chamado 2x
  ([`41d1735`](https://github.com/natharuc/datapyn/commit/41d17357cc52d3156b2bcc944d615ec896480c68))

### Features

- Manter tempo de execucao visivel apos query terminar
  ([`8d121d7`](https://github.com/natharuc/datapyn/commit/8d121d709dccc7f8a39e223800531027c4ba17f0))

- Mostrar icone check verde no bloco apos execucao
  ([`4600db2`](https://github.com/natharuc/datapyn/commit/4600db25d6ec4557a929219188e8dbaa619a4dd1))


## v1.25.0 (2026-04-19)

### Bug Fixes

- Correct pyproject.toml path after main_window package refactor
  ([`d5baa6b`](https://github.com/natharuc/datapyn/commit/d5baa6ba006fe0aeb59dd13cd4ea3af67ebf7711))

### Features

- Import/export conexoes + polish tab buttons
  ([`843e2f3`](https://github.com/natharuc/datapyn/commit/843e2f320b1ee4083a822c0dbc73117353709636))

- Per-tab context, periodic timer, Copilot isolation, insert code, refactor main_window
  ([`b6377fa`](https://github.com/natharuc/datapyn/commit/b6377fa60e2dd71025177d5c4102f24b31690776))


## v1.24.0 (2026-04-17)

### Features

- Add Open Recent submenu to File menu
  ([`d0e29a2`](https://github.com/natharuc/datapyn/commit/d0e29a22a674abaa791f1f7f4811195ed6234626))


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
