# Painel administrativo de telemetria

O serviço `services/telemetry-admin` publica o painel em **painel.docfis.com**.
Interface e API são protegidas pelo mesmo aplicativo Cloudflare Access. O
coletor `telemetry.datapyn.com/v1/events` continua público e independente.
Não é necessário publicar outra versão desktop.

## Dados e consulta

O painel oferece filtros de período (24 horas, 7, 30 ou 90 dias), versão,
plataforma e tipo de banco; indicadores de execução, falha, duração e recuperação;
série temporal; distribuições; e até 100 pontos amostrados recentes. A versão
`dev` é excluída. A tabela contém apenas os campos permitidos em
[TELEMETRY.md](TELEMETRY.md), sem SQL, servidores, usuários ou mensagens de erro.

O backend usa o [Analytics SQL binding](https://developers.cloudflare.com/analytics/sql-api/workers-binding/)
com escopo automático da conta e o dataset fixo
`events.analyticsEngine.datapyn_telemetry`. Não há token de leitura no navegador
nem endpoint que aceite SQL do cliente. Os filtros são validados e enviados como
parâmetros a quatro consultas fixas. A API aceita também `start` e `end` em ISO
UTC, limitados aos últimos 90 dias.

A nova [SQL API aplica os pesos de amostragem automaticamente em COUNT, SUM e AVG](https://developers.cloudflare.com/analytics/sql-api/sql-reference/functions/).
Multiplicar novamente por `_sample_interval` produziria contagens incorretas;
essa multiplicação continua necessária apenas no endpoint legado usado nos
exemplos de TELEMETRY.md. Duração média é o total ponderado dividido pelas
execuções ponderadas. Recuperação considera os resultados finais, sem contar as
fases intermediárias como novas recuperações. Contagens são estimativas; não há
identificador que permita calcular pessoas, instalações ou sessões únicas.

O schema real foi confirmado pelo diagnóstico: `sampleInterval` fornece o peso
individual, exibido como `sampleWeight`. A tabela é uma amostra, não uma trilha
completa. Respostas são reaproveitadas internamente por
até 60 segundos, sempre depois da autenticação; o navegador recebe `no-store`.
Logs e observabilidade bruta do Worker permanecem desativados.

## Identidade e segurança

A implantação usa OTP do Access e libera apenas os endereços configurados no
secret `TELEMETRY_ADMIN_EMAILS`. Cada endereço deve ser autorizado explicitamente.
O código por e-mail é uma [opção nativa do Access](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/one-time-pin/).
Google, Microsoft e outros provedores podem ser integrados separadamente.
Cloudflare também dispõe de [um IdP próprio](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/cloudflare/),
que precisa ser configurado; ter uma conta do dashboard não define sozinho a
política de acesso ao painel.

O deploy cria/reutiliza um aplicativo self-hosted para o hostname inteiro. Uma
configuração existente divergente é recusada para não alterar permissões de
outro serviço. O Worker verifica criptograficamente assinatura RS256, emissor,
audience e expiração de `Cf-Access-Jwt-Assertion` antes de servir qualquer HTML,
asset, health ou consulta. Configuração ausente bloqueia o acesso.

`workers_dev` e URLs de preview ficam desativados, e o Worker também recusa
qualquer hostname diferente de `painel.docfis.com`, impedindo contorno pelo
endereço alternativo. O binding de assets usa `run_worker_first: true` para que
arquivos estáticos também passem pela verificação.

## Preparação e publicação

1. Confirme que **docfis.com** está ativa na conta da telemetria
   `10d97e9bda1dd76cde34ad2f54c8c37e`. Custom Domains precisam de uma zona acessível
   na conta do Worker, e o binding de Analytics consulta a conta do Worker. O
   script para se a zona estiver ausente, inacessível, inativa ou em outra conta.
2. Conclua a configuração da organização Zero Trust no plano gratuito. O deploy
   não contrata planos nem cria uma organização com parâmetros presumidos.
3. Configure um token restrito em **GitHub → natharuc/datapyn → Settings → Secrets
   and variables → Actions**, preferencialmente como `CLOUDFLARE_ADMIN_API_TOKEN`.
   O workflow aceita o secret existente `CLOUDFLARE_API_TOKEN` como alternativa;
   se o atualizar, preserve as permissões do coletor em `datapyn.com`.
4. Permissões necessárias: Workers Scripts Edit na conta, Workers Routes Edit e
   DNS Edit na zona `docfis.com`, Zone Read; Access: Apps and Policies Edit;
   Access: Organizations, Identity Providers, and Groups Edit na conta. Inclua
   Account Analytics Read para a inspeção opcional do schema no diagnóstico.
   Consulte os nomes atuais na [lista oficial de permissões](https://developers.cloudflare.com/fundamentals/api/reference/permissions/).
   Nenhum token de consulta é necessário ao Worker com o binding atual.
5. Configure o secret `TELEMETRY_ADMIN_EMAILS` com e-mails separados por vírgula.
   O endereço autorizado pelo usuário foi configurado como secret, sem gravá-lo
   no repositório público. Tokens devem ser inseridos no GitHub ou em um prompt
   local seguro; nunca em mensagens, código, argumentos de comando ou logs.
6. Execute o workflow **DataPyn telemetry admin - Cloudflare** na `main`, com
   `publish` habilitado. Novas mudanças nesse serviço também passam por validação
   e publicação automática na `main`.

```powershell
cd C:\nac\datapyn\services\telemetry-admin
npm ci
npm test
npm run typecheck
npm run check
# Credenciais devem vir do ambiente seguro, nunca de arquivo versionado.
npm run deploy
```

O script verifica a zona exata, DNS, ownership do Worker/domínio e Access antes de
qualquer escrita. O arquivo de produção com audience/issuer descobertos é gerado
em `.wrangler/`, ignorado pelo Git. Depois da publicação, verifica os bloqueios
sem autenticação e o desligamento de `workers.dev`/preview. O login interativo e
a consulta ao dataset real devem ser conferidos com o e-mail autorizado.

Se a criação do Worker funcionar e a associação do Custom Domain falhar, o
próximo deploy recusará adotar um Worker sem domínio apenas pelo nome. Confira
no dashboard a origem e a configuração desse Worker antes de associar o domínio
ou remover somente a publicação incompleta. O script não exclui recursos
automaticamente e não repete escritas de Access depois de uma resposta ambígua.
Falhas temporárias de DNS/TLS na verificação final têm tentativas limitadas;
uma resposta pública com HTTP 200 interrompe a verificação imediatamente.

Os testes do serviço cobrem JWT válido/adulterado/expirado, bloqueio de assets e
cache sem sessão, domínio alternativo, validação de filtros e cálculo dos
indicadores. Os testes do deploy usam uma API simulada para validar colisões,
allowlist e falhas antes de qualquer escrita. A interface também foi conferida
com Playwright isolado em desktop/celular e estados de vazio/erro/sessão expirada.
Nenhum dado fictício é incluído nos arquivos publicados.
O diagnóstico executa as quatro consultas reais pela mesma SQL API com escopo
explícito da conta e valida o contrato resultante. Apenas o resultado da
verificação e as quantidades de linhas são registrados, sem imprimir eventos.

## Limites e situação verificada

Em 28/10/2026, [Workers Free](https://developers.cloudflare.com/workers/platform/pricing/)
inclui 100 mil requisições/dia e 10 ms de CPU por invocação;
[Analytics Engine](https://developers.cloudflare.com/analytics/analytics-engine/pricing/)
anuncia 100 mil pontos/dia e 10 mil consultas/dia. A nova
[SQL API é beta e tem limites próprios de disponibilidade/plano](https://developers.cloudflare.com/analytics/sql-api/limits/);
o funcionamento do binding na conta deve ser validado no primeiro deploy.
Não há contratação automática de plano pago neste serviço. Os limites são
compartilhados pela conta, e o cache reduz consultas repetidas.

O [diagnóstico inicial](https://github.com/natharuc/datapyn/actions/runs/40696733588)
com o secret existente não encontrou a zona `docfis.com` e recebeu HTTP 403 na
organização Access. Isso comprova falta de acesso com essa credencial, sem
concluir se a zona ou a organização existem em outra conta. O domínio não foi
substituído por `datapyn.com`.
