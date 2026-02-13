# Assinatura de Codigo para o MSI do DataPyn

Este documento explica como configurar a assinatura de codigo para o instalador MSI do DataPyn.

## Por que assinar o MSI?

Instaladores nao assinados sao frequentemente detectados como ameacas pelo Windows Defender e outros antivirus. A assinatura de codigo:

1. Confirma a identidade do publicador
2. Garante que o arquivo nao foi alterado
3. Evita avisos de "editor desconhecido" do Windows
4. Reduz deteccoes de falso positivo por antivirus

## Tipos de Certificados

### Certificado EV (Extended Validation)

- **Recomendado para distribuicao publica**
- Requer validacao rigorosa da identidade da empresa
- Custo: $300-500/ano
- Provedores: DigiCert, Sectigo, GlobalSign

### Certificado OV (Organization Validation)

- Validacao menos rigorosa
- Custo: $70-200/ano
- Pode levar mais tempo para construir reputacao no SmartScreen

### Certificado Self-Signed (apenas para testes)

- Gratuito
- **NAO recomendado para distribuicao** - nao resolve o problema de deteccao

## Configurando a Assinatura no GitHub Actions

### 1. Obter um Certificado de Code Signing

Compre um certificado de code signing de uma CA confiavel. Voce recebera um arquivo .pfx ou .p12.

### 2. Converter para Base64

```powershell
# No PowerShell
$pfxBytes = [System.IO.File]::ReadAllBytes("seu-certificado.pfx")
$base64 = [Convert]::ToBase64String($pfxBytes)
$base64 | Set-Clipboard  # Copia para a area de transferencia
```

### 3. Adicionar Secrets no GitHub

Va em: Repository > Settings > Secrets and variables > Actions

Adicione dois secrets:

| Secret Name | Valor |
|-------------|-------|
| `CODE_SIGNING_CERT_BASE64` | O certificado em base64 (do passo 2) |
| `CODE_SIGNING_CERT_PASSWORD` | A senha do arquivo PFX |

### 4. Pronto!

O workflow de release ira automaticamente:
1. Decodificar o certificado
2. Assinar o MSI com timestamp
3. Limpar o certificado temporario

## Verificando a Assinatura

Apos baixar o MSI assinado:

```powershell
# Verificar assinatura
Get-AuthenticodeSignature "DataPyn-*.msi"
```

Deve mostrar `Status: Valid` e o nome do certificado.

## Alternativa: Azure Trusted Signing (preview)

A Microsoft oferece um servico de assinatura na nuvem que nao requer certificado local:
https://learn.microsoft.com/en-us/azure/trusted-signing/

## Solucao Temporaria (sem certificado)

Enquanto nao tiver um certificado:

1. O MSI funcionara, mas mostrara avisos
2. Usuarios podem clicar em "More info" > "Run anyway"
3. Considere distribuir tambem um ZIP portatil como alternativa
