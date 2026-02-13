# Sistema de Auto-Update do DataPyn

## Visão Geral

O DataPyn possui um sistema integrado de auto-atualização que verifica automaticamente por novas versões no GitHub e permite que os usuários atualizem a aplicação com um simples clique.

## Características

### Verificação Automática
- Ao iniciar o DataPyn, o sistema verifica automaticamente por atualizações após 5 segundos
- A verificação é feita silenciosamente em background
- Não interfere com o uso normal da aplicação

### Verificação Manual
- Acesse **Ajuda → Verificar Atualizações** no menu principal
- O sistema verificará imediatamente por novas versões
- Mostra uma mensagem informativa se já estiver na versão mais recente

### Notificações
Quando uma nova versão está disponível, o DataPyn:
1. Exibe uma notificação na barra de status
2. Mostra um diálogo com informações sobre a nova versão:
   - Número da versão atual e nova
   - Notas da release (changelog)
   - Botões para baixar ou adiar a atualização

### Download e Instalação
Se o usuário escolher atualizar:
1. O instalador MSI é baixado automaticamente
2. Uma barra de progresso mostra o andamento do download
3. Ao concluir, o usuário pode optar por instalar imediatamente
4. A instalação fecha o DataPyn e executa o instalador MSI
5. Após a instalação, o usuário pode reiniciar o DataPyn na nova versão

## Configurações

### Habilitar/Desabilitar Auto-Update
Acesse **Ferramentas → Ativar Auto-Update** no menu principal para ativar ou desativar a verificação automática.

- ✓ Marcado: Auto-update ativado (padrão)
- ☐ Desmarcado: Verificação automática desabilitada (ainda pode verificar manualmente)

## Segurança

### Verificação de Origem
- Todas as atualizações são obtidas exclusivamente do repositório oficial do GitHub
- O sistema verifica apenas releases publicadas oficialmente
- URLs de download são validadas antes do download

### Instalação Segura
- Utiliza o Windows Installer (msiexec) para instalar atualizações
- Instalação em modo passivo (sem interação complexa)
- Não reinicia o sistema automaticamente

### Privacidade
- Apenas consulta a API pública do GitHub
- Não envia dados do usuário ou telemetria
- Configurações de auto-update são armazenadas localmente

## Como Funciona Internamente

### Componentes

#### 1. AutoUpdateService
Serviço principal que gerencia o ciclo de vida de atualizações:
- Verifica versões disponíveis
- Coordena download e instalação
- Gerencia configurações de auto-update

#### 2. UpdateChecker
Worker em background que:
- Consulta a API do GitHub para obter a última release
- Compara versões usando semantic versioning
- Emite sinais quando há atualizações disponíveis

#### 3. UpdateDownloader
Worker em background que:
- Baixa o instalador MSI
- Reporta progresso do download
- Salva o arquivo em diretório temporário

#### 4. UpdateDialog
Interface gráfica que:
- Exibe informações sobre a nova versão
- Mostra notas da release em Markdown
- Permite que o usuário escolha baixar ou adiar

#### 5. UpdateDownloadDialog
Diálogo de progresso que:
- Mostra barra de progresso do download
- Exibe status atual do download
- Informa sobre conclusão ou erros

### Fluxo de Atualização

```
Iniciar DataPyn
    ↓
Timer (5s)
    ↓
Verificar Auto-Update Habilitado? → Não → Fim
    ↓ Sim
UpdateChecker (Background)
    ↓
Consultar GitHub API
    ↓
Nova Versão? → Não → Fim (Silencioso)
    ↓ Sim
UpdateDialog
    ↓
Usuário Aceita? → Não → Fim
    ↓ Sim
UpdateDownloader (Background)
    ↓
Download Completo?
    ↓ Sim
Oferecer Instalação
    ↓
Usuário Aceita? → Não → Manter MSI em Temp
    ↓ Sim
Executar msiexec
    ↓
Fechar DataPyn
    ↓
Instalador Atualiza Aplicação
    ↓
Usuário Reinicia DataPyn
    ↓
Nova Versão Instalada ✓
```

## API do GitHub

O sistema utiliza a API pública do GitHub:

```
GET https://api.github.com/repos/{owner}/{repo}/releases/latest
```

Resposta esperada:
```json
{
  "tag_name": "v1.2.0",
  "body": "Release notes in Markdown",
  "assets": [
    {
      "name": "DataPyn-1.2.0-windows.msi",
      "browser_download_url": "https://github.com/.../DataPyn-1.2.0-windows.msi"
    }
  ]
}
```

## Comparação de Versões

O sistema usa **Semantic Versioning** (semver) para comparar versões:
- Formato: `MAJOR.MINOR.PATCH` (ex: `1.2.3`)
- Compara numericamente cada componente
- Ignora sufixos como `-alpha`, `-beta`, `-dryrun`

Exemplos:
- `1.2.0` > `1.1.9` (minor incrementado)
- `2.0.0` > `1.9.9` (major incrementado)
- `1.2.1` > `1.2.0` (patch incrementado)
- `1.2.0-beta` é tratado como `1.2.0` para comparação

## Tratamento de Erros

### Erros de Rede
- Timeout: 10 segundos para verificação, 30 segundos para download
- Falhas são registradas em log
- Usuário é notificado apenas em verificações manuais

### Erros de Download
- Se o download falhar, o usuário é notificado
- Arquivo parcial é descartado
- Usuário pode tentar novamente

### Erros de Instalação
- Se o instalador não puder ser executado, erro é exibido
- Arquivo MSI permanece disponível para instalação manual

## Limitações

### Plataforma
- Atualmente suporta apenas Windows (instaladores MSI)
- Outras plataformas requerem instalação manual

### Requisitos
- Conexão com internet
- Acesso à API do GitHub (não bloqueada por firewall)
- Permissões para executar instaladores MSI

## Desenvolvimento

### Testes
Execute os testes do auto-update:
```bash
uv run pytest tests/test_auto_update_service.py -v
```

### Estrutura de Arquivos
```
source/src/services/
  └── auto_update_service.py    # Lógica de verificação e download

source/src/ui/dialogs/
  └── update_dialog.py           # Interfaces de usuário

tests/
  └── test_auto_update_service.py  # Testes unitários
```

## Configurações Avançadas

### Modificar Repositório de Origem
Por padrão, o sistema verifica atualizações em `natharuc/datapyn`. Para alterar:

```python
# Em main_window.py, ao inicializar AutoUpdateService:
self.auto_update_service = AutoUpdateService(
    self._current_version,
    repo_owner="seu-usuario",
    repo_name="seu-repositorio"
)
```

### Desabilitar Verificação Automática por Padrão
Edite `auto_update_service.py`:

```python
def is_auto_update_enabled(self) -> bool:
    return self.settings.value("auto_update/enabled", False, type=bool)  # False = desabilitado
```

## Referências

- [GitHub Releases API](https://docs.github.com/en/rest/releases/releases)
- [Semantic Versioning](https://semver.org/)
- [Windows Installer (msiexec)](https://docs.microsoft.com/en-us/windows-server/administration/windows-commands/msiexec)
