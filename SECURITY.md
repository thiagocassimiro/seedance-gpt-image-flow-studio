# Política de segurança

## Credenciais e materiais sensíveis

Nunca envie `ARK_API_KEY`, `OPENAI_API_KEY`, cookies, tokens, URLs assinadas, arquivos `.env`, chaves privadas, manifestos de produção ou dados de clientes para issues, pull requests, commits, GitHub Actions ou logs públicos.

Projetos em `projects/` são ignorados por padrão porque podem conter URLs assinadas e materiais privados. Não use `git add -f` para publicá-los.

## Antes de publicar

Execute:

```powershell
python scripts/check_publication.py
python -m unittest discover -s tests -t . -v
```

O verificador informa somente nomes de arquivos e categorias de problema; nunca imprime o valor suspeito. Revise também `git status --ignored` e o diff staged.

## Relato de vulnerabilidades

Use o canal privado de Security Advisories do repositório, se disponível. Não abra issue pública com segredos ou exploits contendo dados reais. Inclua apenas o mínimo necessário para reproduzir o problema com credenciais fictícias.

## Se uma credencial foi publicada

1. Revogue ou rotacione imediatamente a credencial no provedor correspondente.
2. Considere qualquer URL assinada exposta como comprometida e emita substitutas somente pelo método oficial.
3. Remova o dado do histórico do Git usando o procedimento apropriado do repositório, sem repetir o valor em comandos ou mensagens.
4. Revise logs, forks, caches, releases e artefatos de CI.
5. Registre a lição aprendida sem persistir o segredo.

A remoção do Git não desfaz uma exposição já ocorrida; a rotação é indispensável.
