# Relatório de validação da primeira etapa

Data da execução: 2026-11-06.

## Escopo efetivamente executado

- Leitura integral do guia de referência (499 linhas) e dos três exemplos Seedance (44 linhas cada).
- Criação do projeto reutilizável, CLI, prompts, configurações, documentação, testes e selfcheck.
- Verificações locais, transportes/subprocessos simulados e dry-runs.
- Revisões independentes somente leitura das proteções financeiras, de recuperação e de mídia.
- Nenhuma imagem por IA, vídeo, chamada paga, instalação global, interface web ou servidor.

## Ferramentas encontradas

| Ferramenta | Resultado |
|---|---|
| Python do runtime DSH | **OK**, CPython 3.12.14 |
| `python` no PATH | Alias da Microsoft Store encontrado, mas não utilizável; o runtime explícito foi usado |
| `gpt-image` | **OK**, `C:\Users\user\.local\bin\gpt-image.exe`; `--help` retornou 0 |
| FFmpeg | **Não encontrado** no PATH |
| ffprobe | **Não encontrado** no PATH |
| `ARK_API_KEY` | **Não definida no processo do preflight**; somente presença verificada |
| Configuração local | Válida para dry-run; modelos `unverified_account`, submissões desabilitadas |

Nenhuma dependência foi instalada e nenhuma configuração global foi alterada. O diagnóstico de permissões do Windows não encontrou o problema de ACL que poderia reparar e não mudou permissões; os testes foram executados com autorização pontual fora do sandbox devido ao bloqueio dos diretórios temporários.

## Testes offline finais

Comando:

```powershell
$env:PYTHONPATH = "src"
$env:PYTHONIOENCODING = "utf-8"
python scripts/check_publication.py
python -m unittest discover -s tests -t . -v
```

A verificação `check_publication.py` analisou os arquivos publicáveis sem imprimir valores sensíveis e terminou com `PUBLICACAO_OK`.

Resultado final: **57 testes executados, 57 aprovados, 0 falhas, 0 erros**.

Cobertura incluída:

- verificação de publicação sem exposição de valores sensíveis;
- paths e nomes reservados do Windows, histórico sem sobrescrita;
- payloads Seedance, modelos sem fallback, assets oficiais e redação;
- dimensões/proporção e comandos de frames sem `-y`;
- custos desconhecidos, tentativas, imagens e reconciliação de faturas;
- revisões/aprovações vinculadas a payload, estimativa e arquivos;
- idempotência, timeout, HTTP ambíguo e falha local pós-aceite;
- associação exclusiva de task/idempotency key e recuperação sem novo POST;
- downloads idempotentes e redirects com revalidação;
- ledger single-use de imagem e reconciliação humana sem reexecução;
- bloqueio compartilhado entre imagem e vídeo ativos/ambíguos;
- montagem, silêncio, normalização, aspect ratio, Lanczos e master registrado;
- QC agregado e limitações explícitas de movimento/áudio.

## Evidências do selfcheck

O projeto `projects/studio-selfcheck/` é somente uma fixture operacional, não um filme nem o piloto pago. Seus dois PNGs 1280×720 foram criados programaticamente, sem IA. Os links abaixo são resumos públicos sanitizados; os relatórios originais e o diretório `projects/` permanecem fora do Git.

- [Preflight local](./preflight-summary.json): `network_checks_executed: false`, `paid_calls_executed: false`.
- [Dry-run Seedance](./dry-run-summary.json): Mini, 5 s, 720p, 16:9, `network_request_sent: false`, frames válidos, pagamento desabilitado.
- [Dry-run de imagem](./image-dry-run-summary.json): Flare, `low`, uma imagem, `executed: false`.
- [Estimativa](./estimate-summary.json): `known: false`, `total_amount: null`, preço ausente não tratado como gratuito.
- [QC sem clipes](./qc-summary.json): `pending_no_clips`, `motion_reviewed: false`, `audio_reviewed: false`, `network_used: false`.

## O que não foi validado

- Disponibilidade real dos modelos/IDs na conta BytePlus e todos os parâmetros aceitos.
- Preço atual, moeda, saldo e condições de cobrança.
- Método oficial BytePlus para disponibilizar URLs dos assets locais.
- Chamadas reais à API ModelArk ou à CLI de imagem.
- Execução real de FFmpeg/ffprobe, montagem e decodificação de mídia.
- Qualidade visual, continuidade de movimento, atuação, som e sincronia por revisão humana.

Essas pendências permanecem bloqueadas por configuração e pelas barreiras de aprovação. O piloto de `docs/piloto-5s.md` não foi executado e não possui custo estimado conhecido.
