# Guia de Geracao do Instalador MSI

## Visao Geral

Este documento descreve o processo de geracao do instalador MSI do DataPyn usando cx_Freeze.

## Pre-requisitos

### Windows
- Python 3.8 ou superior
- Ambiente virtual ativado (`.venv`)
- Visual C++ Redistributable (geralmente ja instalado no Windows)

### Dependencias de Build
Instale as dependencias de build:
```bash
pip install -r requirements-build.txt
```

Ou instale manualmente:
```bash
pip install cx_Freeze>=7.0.0
pip install pyinstaller>=6.0.0
```

## Opcoes de Build

### 1. Build Interativo (Recomendado)
Execute o script principal de build e escolha a opcao desejada:
```bash
scripts\build.bat
```

Menu de opcoes:
1. EXE (PyInstaller - rapido, ~3-5 minutos)
2. MSI Installer (cx_Freeze - completo, ~10-15 minutos)
3. Ambos (EXE + MSI)

### 2. Build Direto do MSI
Para gerar apenas o instalador MSI:
```bash
scripts\build_msi.bat
```

### 3. Build Direto do EXE
Para gerar apenas o executavel:
```bash
scripts\build_exe.bat
```

## Estrutura do Instalador MSI

### Configuracao
O instalador e configurado via `scripts/setup_msi.py`:

```python
build_exe_options = {
    "packages": [...],      # Pacotes Python incluidos
    "excludes": [...],      # Pacotes excluidos (reduz tamanho)
    "include_files": [...], # Arquivos de assets
    "optimize": 2,          # Nivel de otimizacao
}

bdist_msi_options = {
    "upgrade_code": "...",              # GUID unico do produto
    "add_to_path": False,               # Nao adiciona ao PATH
    "initial_target_dir": "...",        # Diretorio de instalacao padrao
    "install_icon": "...",              # Icone do instalador
}
```

### Arquivos Incluidos
O instalador MSI inclui:
- Executavel principal (`DataPyn.exe`)
- Todas as bibliotecas Python necessarias
- Assets (icones, estilos, etc.)
- Monaco Editor (editor de codigo web)
- Dependencias nativas (Qt, bancos de dados, etc.)

## Localizacao dos Arquivos Gerados

### EXE (PyInstaller)
```
dist/
└── DataPyn/
    ├── DataPyn.exe         # Executavel principal
    ├── _internal/          # Bibliotecas e dependencias
    └── ...
```

### MSI (cx_Freeze)
```
dist/
└── DataPyn-1.0.0-win64.msi  # Instalador
```

## Testando o Instalador

### 1. Instalacao
- Execute o arquivo `.msi`
- Siga o assistente de instalacao
- O DataPyn sera instalado em `C:\Program Files\DataPyn\`
- Um atalho sera criado no Menu Iniciar

### 2. Verificacao
- Abra o DataPyn pelo Menu Iniciar
- Teste as funcionalidades principais:
  - Criar nova conexao com banco de dados
  - Executar consulta SQL
  - Executar codigo Python
  - Exportar resultados
  - Salvar/carregar workspace

### 3. Desinstalacao
- Painel de Controle > Programas > Desinstalar um programa
- Selecione "DataPyn" e clique em "Desinstalar"

## Troubleshooting

### Erro: "Microsoft Visual C++ Redistributable nao encontrado"
**Solucao**: Instale o Visual C++ Redistributable mais recente:
- [Download Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe)

### Erro: "cx_Freeze nao encontrado"
**Solucao**: Instale cx_Freeze:
```bash
pip install cx_Freeze
```

### Build MSI muito lento
**Causa**: cx_Freeze compila e empacota todas as dependencias.
**Solucao**: Use o build EXE (PyInstaller) para desenvolvimento rapido e MSI apenas para releases.

### Instalador muito grande (>500MB)
**Causa**: Muitos pacotes incluidos.
**Solucao**: Adicione mais pacotes a lista `excludes` em `setup_msi.py`.

### Erro de permissao durante instalacao
**Solucao**: Execute o instalador como Administrador (botao direito > Executar como administrador).

## Personalizacao

### Alterar Diretorio de Instalacao Padrao
Edite `scripts/setup_msi.py`:
```python
bdist_msi_options = {
    ...
    "initial_target_dir": r"[ProgramFilesFolder]\MeuDiretorio",
    ...
}
```

### Alterar GUID do Produto
O GUID atual do DataPyn e `{550CD338-127B-4152-A131-C0E375667D77}`.

Para uma nova versao major, voce pode alterar o `upgrade_code`:
```python
bdist_msi_options = {
    ...
    "upgrade_code": "{NOVO-GUID-AQUI}",
    ...
}
```

**IMPORTANTE**: 
- Use o mesmo GUID para permitir atualizacoes automaticas entre versoes
- Gere um novo GUID apenas para releases incompativeis que nao devem atualizar versoes antigas
- Para gerar um novo GUID: `python -c "import uuid; print('{' + str(uuid.uuid4()).upper() + '}')"`

### Adicionar/Remover Pacotes
Edite `scripts/setup_msi.py`:
```python
build_exe_options = {
    "packages": [
        "PyQt6",
        "pandas",
        # Adicione novos pacotes aqui
    ],
    "excludes": [
        "tkinter",
        # Adicione pacotes a excluir aqui
    ],
}
```

## Distribuicao

### GitHub Releases
1. Crie um release no GitHub
2. Faca upload do arquivo `.msi`
3. Usuarios poderao baixar e instalar diretamente

### Assinatura Digital
Para producao, recomenda-se assinar o instalador:
```bash
signtool sign /f certificado.pfx /p senha DataPyn-1.0.0-win64.msi
```

## Comparacao: EXE vs MSI

| Aspecto | EXE (PyInstaller) | MSI (cx_Freeze) |
|---------|-------------------|-----------------|
| Tempo de build | 3-5 minutos | 10-15 minutos |
| Tamanho | ~200-300 MB | ~250-350 MB |
| Instalacao | Pasta ZIP | Instalador Windows |
| Desinstalacao | Manual | Painel de Controle |
| Atualizacoes | Manual | Automatica (MSI) |
| Menu Iniciar | Nao | Sim |
| Uso | Desenvolvimento/Teste | Distribuicao final |

## Recomendacoes

- **Desenvolvimento**: Use build EXE para testes rapidos
- **Releases**: Use build MSI para distribuicao aos usuarios
- **CI/CD**: Configure o build MSI no pipeline de release
- **Versionamento**: Atualize a versao em `pyproject.toml` antes do build

## Referencias

- [cx_Freeze Documentation](https://cx-freeze.readthedocs.io/)
- [PyInstaller Documentation](https://pyinstaller.org/)
- [Windows Installer (MSI) Guide](https://docs.microsoft.com/windows/win32/msi/)
