# Configurações entre PyQt6 e Tauri

O formato público de conexões continua sendo o JSON usado pelo PyQt6. O banco SQLite das sessões é privado e não substitui esse JSON nem o formato `.dpw`.

## JSON de conexões

Em **Gerenciar conexões**, importar aceita os formatos legados plano e agrupado. Exportar produz o formato agrupado do PyQt6, com `connections` e `groups`:

```json
{
  "connections": {
    "Produção": {
      "Principal": {
        "db_type": "sqlserver", "host": "servidor", "port": 1433,
        "database": "dados", "username": "usuario",
        "use_windows_auth": false, "trust_server_certificate": false
      }
    },
    "Grupo vazio": {}
  },
  "groups": {
    "Produção": {"color": "#5179ef", "parent": "Servidores"},
    "Grupo vazio": {"color": "", "parent": null}
  }
}
```

- A identidade é `(grupo, nome)`, diferenciando maiúsculas e minúsculas, como no `ConnectionManager` original. Reimportar atualiza essa conexão, preservando seu ID interno. Não renomeia conflitos automaticamente.
- Conexões homônimas em grupos distintos continuam distintas. Grupos vazios, cores, hierarquia, schema, campos de autenticação e extensões desconhecidas são preservados.
- Senhas não são exportadas nem importadas do JSON público, seguindo o diálogo original. Credenciais existentes ficam no cofre; importação não solicita nem grava passwords recebidos no JSON.
- CRUD de grupos exige nomes globalmente únicos, pois o formato PyQt6 identifica grupos pelo nome. Catálogos de previews anteriores com homônimos sob pais distintos precisam de renomeação para esse formato. Exportar com `format: "tauri"` mantém o backup interno desses catálogos; não é o arquivo para importar no PyQt6.

A compatibilidade é verificada com as funções reais `export_connections`, `validate_import_json`, `apply_import`, o loader `ConnectionManager` e fixtures sintéticas. Os testes não acessam credenciais ou configurações pessoais.

No build Windows final, o perfil de aceite reabriu automaticamente e executou seus blocos Python. O diálogo CSV exibiu os valores importados: vírgula no separador e no decimal, Windows 1252, cabeçalhos desabilitados e abertura de pasta desabilitada.

## Transferir a pasta de configurações

Em **Configurações → Importar e exportar**, selecionar uma pasta mostra os arquivos e avisos antes de aplicar. Um token de revisão invalida a confirmação se a origem ou o catálogo mudar. Importação tem rollback de arquivos em caso de falha; exportação requer uma pasta vazia.

Arquivos de configuração JSON/INI, `shortcuts.json` e `PyniaSettings.ini` usam a representação original. Atalhos traduzem nomes de ações e `Return`/`Enter` entre os dois frontends, sem mudar o arquivo esperado pelo `ShortcutManager`. Valores e linhas Qt desconhecidos são preservados, incluindo variantes binárias e geometria, exceto credenciais reconhecidas.

Os arquivos originais importados ficam em `.pyqt-configuration`, dentro do perfil. A exportação atualiza os campos conhecidos com os valores aplicados no Tauri e conserva as extensões. Preferências exclusivas do Tauri ficam em `tauri-settings.json`, que o PyQt6 pode ignorar. Configurações de notificações e snapshots são convertidas para os serviços equivalentes.

Defaults CSV (separador, decimal, encoding, cabeçalhos e abertura da pasta) e de cópia (separador e texto de valores nulos) passam a ser usados nos documentos sem override explícito. Downloads SQL diretos também recebem essas opções. Fontes de pacotes sem credenciais são transferidas para o serviço de pacotes, sem instalar nada durante a importação.

O agente padrão e as preferências de modelo/reasoning da Pynia são usados em conversas novas, somente quando o agente anuncia a opção. Conversas ACP existentes conservam sua configuração. Valores Qt desconhecidos e a geometria binária permanecem disponíveis para retornar ao PyQt6; o Tauri usa seus componentes e layout próprios.

Sessões, bancos de recuperação, caches, resultados, credenciais, registros de workspaces e diretórios de pacotes ficam fora dessa transferência. `MainWindow.ini` e `DockingLayout.ini` conservam o layout Qt binário para o PyQt6; importar mostra o aviso de que essa geometria não pode ser convertida diretamente para Dockview. O Tauri grava os nove docks e a geometria de sua janela principal nos metadados privados `layout.docking`/`layout.mainWindow` do perfil. Reorganizar esses painéis não modifica os bytes Qt arquivados nem acrescenta estruturas Dockview ao formato de configuração do PyQt6.

## Preferências globais do PyQt6

No Windows, copiar a pasta de workspace não copia os valores globais de `QSettings`: eles ficam no Registro do Windows. Para transferi-los, o helper usa o codec real do Qt, preservando `QByteArray`, listas, tipos e chaves desconhecidas. Ele é executado explicitamente no ambiente Python da versão PyQt6 e não faz parte do runtime Tauri.

Para acrescentar as preferências globais a uma cópia da pasta legada, escolha uma pasta que ainda não contenha os arquivos globais:

```powershell
uv run python scripts/tauri/transfer_pyqt_settings.py export --folder C:\backup\datapyn-config
```

Depois, importe essa pasta na tela de configurações do Tauri. Para aplicar os INI exportados pelo Tauri ao PyQt6, use:

```powershell
uv run python scripts/tauri/transfer_pyqt_settings.py import --folder C:\backup\datapyn-config
```

O segundo comando altera as preferências globais do PyQt6 nesta máquina. Execute com o aplicativo legado fechado. A pasta de conexões/atalhos continua sendo selecionada pelo workspace do PyQt6. Categorias: `DataPyn`, `MainWindow`, `DockingLayout`, `CSVExport`, `ExportSettings`, `PackageManager`. Credenciais e a lista global de workspaces não são transferidas. A configuração opaca `sources_v2` do PackageManager é omitida pelo importador Qt-free; URLs sem credenciais podem ser transferidas por `extra_index_urls`.

## Sessões

As sessões são restauradas automaticamente com abas, blocos, ordem, foco, cursor, scroll, layout, preferências e atalhos. O layout inclui posição/ordem dos docks, abas selecionadas, dimensões e painéis ocultos, flutuantes ou destacados. A geometria nativa é restaurada na abertura e adaptada aos monitores disponíveis. O salvamento é incremental, transacional e separado da troca pública de configurações. Consulte [TAURI_SESSION_PERSISTENCE.md](TAURI_SESSION_PERSISTENCE.md) para migração, recuperação, limites e evidência de desempenho.
