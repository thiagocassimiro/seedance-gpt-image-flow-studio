# Proposta de piloto — um único plano de 5 segundos

**Status: somente proposta. Não executar sem autorização explícita do usuário, revisão de frames e custo conhecido.**

## Objetivo

Validar o menor fluxo completo possível: texto revisado → frames consistentes → prompt revisado → estimativa → aprovação humana → uma tarefa → download → QC → lições aprendidas.

## Plano técnico

| Campo | Proposta |
|---|---|
| Quantidade | 1 plano, 1 clipe, 1 tentativa |
| Duração | 5 segundos |
| Resolução | 720p |
| Proporção | 16:9 |
| Modelo preferido | `dreamina-seedance-2-0-mini-260615` |
| Disponibilidade | Ainda não verificada na conta; se indisponível, parar |
| Fallback | Nenhum. Fast ou 2.5 exige nova escolha, estimativa e aprovação |
| Áudio gerado | `false` neste piloto, para reduzir variáveis; trilha/efeitos seriam avaliados depois |
| Watermark | `false`, somente se confirmado como suportado |
| Tentativas paralelas | Nenhuma |

## Plano criativo simples

Uma xícara de cerâmica sobre uma mesa de madeira, em um ambiente fixo e sem pessoas, mãos, texto ou reflexos. A câmera permanece estável enquanto uma leve coluna de vapor sobe pela bebida. O primeiro e o último frames preservam câmera, posição da xícara, fundo, luz e paleta.

**Movimento principal:** somente o vapor.

**Por que este plano:** reduz interações, mudanças de identidade, manipulação de objetos, texto e continuidade. O vapor oferece movimento observável sem exigir uma ação complexa.

## Antes de qualquer cobrança

1. Confirmar história de uma frase e decupagem de uma linha.
2. Definir paleta e contraste P&B.
3. Criar primeiro/último frame com 1280×720 e registrar referências.
4. Conferir contato visual, sobreposição e dimensões.
5. Revisar prompt e imagens com `prompts/frame_reviewer.md`.
6. Confirmar que Mini existe e está disponível na conta, com parâmetros aceitos.
7. Confirmar método oficial BytePlus para URLs dos assets.
8. Preencher preço oficial com fonte/data/moeda e reconciliar qualquer custo de imagem.
9. Apresentar ao usuário modelo, 5 s, 720p, quantidade 1 e o custo total estimado.
10. Obter aprovação explícita vinculada ao hash da estimativa e do payload.

## Estimativa atual

**Desconhecida.** Nenhum preço oficial foi confirmado nesta execução.

```text
vídeo = 5 segundos × 1 tentativa × preço_oficial_do_Mini_720p_por_segundo
total = vídeo + custos_de_imagem_efetivamente_planejados/reconciliados
```

Não usar os valores históricos do guia. Não tratar imagens como gratuitas. Não autorizar o piloto enquanto qualquer parcela for desconhecida.

## Se a conta estiver sem saldo ou o modelo estiver indisponível

Parar. Não trocar de modelo, não comprar créditos, não recarregar e não repetir a submissão. Preservar roteiro, frames, revisões, estimativa e demais arquivos existentes.

## Critério de revisão, sem execução agora

Depois de uma futura autorização e geração, verificar integridade do download, duração/resolução, consistência da xícara e do fundo, qualidade do vapor e cortes. Frames estáticos não bastam para avaliar a sensação do movimento; áudio, se adicionado posteriormente, exige escuta humana.
