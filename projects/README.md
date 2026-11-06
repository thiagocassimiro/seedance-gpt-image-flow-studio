# Projetos de filmes

Cada filme criado por `studio new <nome>` fica nesta pasta e **não é versionado por padrão**.

Isso evita publicar acidentalmente:

- referências, personagens e materiais de clientes;
- frames, clipes originais, masters e entregas;
- manifestos, task IDs e URLs assinadas temporárias;
- aprovações, estimativas, custos e dados de faturas;
- logs e históricos de produção.

Somente `.gitkeep` e este `README.md` são incluídos no repositório. Não use `git add -f` para contornar essa regra. Se quiser compartilhar um exemplo, crie uma cópia revisada e sanitizada em `docs/validation/`, sem credenciais, URLs assinadas, paths locais ou dados do cliente.

O projeto `studio-selfcheck` existente em algumas máquinas é apenas uma fixture local e também permanece fora do Git.
