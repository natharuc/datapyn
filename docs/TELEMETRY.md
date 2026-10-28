# Telemetria do DataPyn

A telemetria é **opcional e desativada por padrão**. Em **Configurações →
Telemetria**, o usuário escolhe se deseja enviar diagnósticos e o endpoint HTTPS.
O endpoint da distribuição é `https://telemetry.datapyn.com/v1/events`.

O consentimento é local, global para a instalação e independente dos perfis.
Ele não é ativado pela importação de uma configuração PyQt6 ou pela restauração
de um workspace. A configuração fica no diretório Tauri, em
`telemetry_settings.json`, sem alterar arquivos ou atualizadores históricos Qt.

## Campos permitidos

O conector constrói um evento novo a partir de categorias fixas. Ele não tenta
remover segredos de uma mensagem ou traceback e depois enviá-los.

| Campo | Conteúdo |
|---|---|
| `event` | Inicialização, conclusão de execução, recuperação de conexão, erro do runtime ou da interface |
| `version` | Versão Tauri |
| `platform` | Windows, macOS, Linux ou outro |
| `db_type` | Tipo do banco, sem cadastro, servidor, usuário, banco ou schema |
| `status` | Resultado/fase da operação |
| `error_code` | Categoria fixa: transporte, timeout, autenticação, sintaxe, cancelamento, desconhecido ou nenhum |
| `duration_ms` | Duração numérica limitada |
| `attempt` | Número limitado da tentativa de recuperação |
| `rows_bucket` | Faixa de quantidade de linhas, sem conteúdo ou valor de células |

SQL, Python, parâmetros, conteúdo de resultados, mensagens de exceção, nomes de
conexões, endereços de servidores, credenciais, caminhos de arquivos e
identificadores de usuário/instalação não fazem parte do payload. O endpoint
também recusa lotes contendo campos desconhecidos.

## Envio e falhas

- Nenhum HTTP ou thread de envio é iniciado antes do consentimento.
- O envio usa uma thread daemon independente das consultas e da interface.
- A fila existe somente em memória, com até 256 eventos, lotes de até 50 e
  expiração de 24 horas. Eventos antigos são descartados primeiro.
- Lotes com falha têm até três tentativas, com intervalo crescente a partir de
  30 segundos. Não existe envio ao fechar o aplicativo nem espera pela rede na
  saída.
- Desativar ou mudar o endpoint apaga a fila; um evento que começou a ser
  preparado sob o consentimento anterior também é descartado. Um HTTP que já
  estava em andamento não pode ser desfeito.
- Falhas de configuração, serialização, rede ou criação da thread de diagnóstico
  não impedem consultas, entrega de resultados ou inicialização do aplicativo.
- O conector não segue redirecionamentos. O endpoint deve ser HTTPS público,
  sem credenciais, query string ou fragmento.

A entrega é best effort: quedas do aplicativo, eventos descartados e eventuais
reenvios podem alterar contagens. Telemetria não substitui uma trilha de auditoria
de comandos ou a conferência do estado transacional no servidor.

## Coletor Cloudflare

O serviço isolado em `services/telemetry` usa Workers e Analytics Engine. Ele
valida todo o lote antes de escrever pontos no dataset, limita corpo e número de
eventos e aplica um limitador de requisições. O IP é recebido pela infraestrutura
HTTPS e usado somente como chave transitória do limitador; não é escrito no
dataset da aplicação. Logs de aplicação/observabilidade do Worker ficam
desabilitados. Não há endpoint público para ler as métricas nem token Cloudflare
distribuído no desktop.

O dataset `datapyn_telemetry` usa:

- `blob1..blob7`: evento, versão, plataforma, banco, status, categoria de erro e
  faixa de linhas;
- `double1..double2`: duração em ms e tentativa;
- índice: tipo de banco.

Exemplo para consultas autorizadas na SQL API do Analytics Engine:

```sql
SELECT blob2 AS version, blob4 AS database_type, blob5 AS status,
       SUM(_sample_interval) AS estimated_events,
       SUM(double1 * _sample_interval) / SUM(_sample_interval) AS average_ms
FROM datapyn_telemetry
WHERE timestamp > NOW() - INTERVAL '7' DAY
  AND blob1 = 'connection_recovery'
  AND blob2 != 'dev'
GROUP BY version, database_type, status
ORDER BY estimated_events DESC
```

Os limites gratuitos consultados em 28/10/2026 são 100 mil requisições/dia no
[Workers](https://developers.cloudflare.com/workers/platform/pricing/), e 100 mil
pontos/dia mais 10 mil consultas/dia no
[Analytics Engine](https://developers.cloudflare.com/analytics/analytics-engine/pricing/).
O dataset tem [retenção de três meses](https://developers.cloudflare.com/analytics/analytics-engine/limits/).
Os limites são compartilhados pela conta; o serviço deve permanecer no plano
Free para não contratar consumo pago automaticamente. Não há garantia de
capacidade ilimitada ou de preços futuros.

## Publicação e testes

O painel web protegido em `painel.docfis.com` é um serviço separado. Consulte
[TELEMETRY_ADMIN.md](TELEMETRY_ADMIN.md) para identidade, consulta e publicação.

O workflow `telemetry.yml` instala o lock do serviço, roda testes/typecheck e um
dry run, e publica somente a partir de `main`. Usa o secret GitHub
`CLOUDFLARE_API_TOKEN`, restrito à conta do DataPyn e à zona `datapyn.com`.
O deploy descobre a conta pela zona exata e recusa sobrescrever um Worker,
domínio ou registro DNS que pertença a outro serviço.

```powershell
cd C:\nac\datapyn\services\telemetry
npm ci
npm test
npm run typecheck
npm run check
# Na esteira, CLOUDFLARE_API_TOKEN vem do secret; nunca de um arquivo versionado.
npm run deploy
```

Os testes do runtime verificam consentimento, revogação concorrente, limites,
falha de rede/thread e ausência de dados sensíveis. A interface pode ser
verificada com `npm --prefix desktop run test:telemetry-settings`, em português
e inglês, sem acessar o coletor real.
